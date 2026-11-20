"""Reproducible, bounded synthetic benchmark. Creates and destroys its OWN PG cluster.

Run from crmserver with the project Python; --output must not exist. No .env access.
"""
import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
PURPOSE = 'agrosmena-synthetic-baseline-v1'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def resources(pid):
    """Server CPU seconds and working set on Windows; no dependency, no unrelated PIDs."""
    if os.name != 'nt':
        return {'available': False, 'reason': 'This sampler implements Windows process counters only'}
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak_ws', 'ws', 'peak_paged', 'paged',
                                                'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    memory_api = ctypes.WinDLL('psapi', use_last_error=True)
    memory_api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        return {'available': False, 'reason': 'OpenProcess denied'}
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        memory = Memory()
        memory.cb = ctypes.sizeof(memory)
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in values]):
            return {'available': False, 'reason': 'GetProcessTimes failed'}
        if not memory_api.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            return {'available': False, 'reason': 'GetProcessMemoryInfo failed'}
        seconds = sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in values[2:]) / 10_000_000
        return {'available': True, 'cpu_seconds': seconds, 'rss_bytes': memory.ws,
                'process_lifetime_peak_rss_bytes': memory.peak_ws}
    finally:
        kernel.CloseHandle(handle)


def summarize(samples):
    result = {'n': len(samples), 'errors': sum(row['status'] != 200 for row in samples)}
    keys = ['client_ms', 'response_bytes', 'server_ms', 'sql_count', 'sql_duration_ms',
            'executor_queue_ms', 'input_validation_ms', 'exchange_service_ms', 'organization_lock_acquire_ms',
            'organization_lock_observed_hold_ms', 'apply_ms', 'response_prepare_ms']
    for key in keys:
        values = sorted(row[key] for row in samples if row.get(key) is not None and row['status'] == 200)
        if values:
            result[key] = {'n': len(values), 'median': statistics.median(values),
                           'p95': values[math.ceil(len(values) * 0.95) - 1] if len(values) >= 20 else None,
                           'min': values[0], 'max': values[-1]}
    return result


class Experiment:
    def __init__(self, args):
        self.args = args
        self.root = args.output.resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.expired = threading.Event()
        self.server = None
        self.pg_started = False
        self.event_offsets = {}
        self.requests = 0
        self.results = []
        self.unfinished = []
        self.pgport = free_port()
        self.marker = {'purpose': PURPOSE, 'port': self.pgport, 'run_id': str(uuid4())}
        write_json(self.root / 'baseline-owner.json', self.marker)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith(
            ('DJANGO_', 'POSTGRES_', 'PG', 'OBSERVABILITY_', 'APP_UPDATE_', 'APP_INSTALLER_', 'BASELINE_'))}
        self.env.update(STAGE1_VERIFY_ROOT=str(self.root), DJANGO_SETTINGS_MODULE='crmserver.baseline_settings',
                        PYTHONPATH=os.pathsep.join([str(PROJECT), str(PROJECT / 'tools')]),
                        PYTHONIOENCODING='utf-8', NO_PROXY='127.0.0.1,localhost')
        self.binary = args.postgres_bin.resolve()
        self.creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.watchdog = threading.Timer(args.max_seconds, self.expire)
        self.watchdog.daemon = True

    def pg(self, program, *args, timeout=60):
        name = program + ('.exe' if os.name == 'nt' else '')
        with (self.root / 'postgres-control.log').open('a', encoding='utf-8') as output:
            return subprocess.run([str(self.binary / name), *map(str, args)], env=self.env,
                                  stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                  creationflags=self.creationflags)

    def expire(self):
        self.expired.set()
        if self.server and self.server.poll() is None:
            self.server.terminate()
        if self.pg_started:
            try:
                self.pg('pg_ctl', '-D', self.root / 'pgdata', '-m', 'immediate', '-w', 'stop', timeout=15)
            except Exception:
                pass

    def guard(self):
        if self.expired.is_set() or time.monotonic() - self.started >= self.args.max_seconds:
            raise TimeoutError('Global experiment budget exhausted')
        if self.requests > 1800:
            raise RuntimeError('Request budget exhausted')
        used = sum(path.stat().st_size for path in self.root.rglob('*') if path.is_file())
        if used > 1_000_000_000:
            raise RuntimeError('Artifact disk budget exceeded (1 GB)')

    def setup(self):
        self.watchdog.start()
        for key in list(os.environ):
            if key.startswith('PG'):
                del os.environ[key]
        self.pg('initdb', '-D', self.root / 'pgdata', '-U', 'stage1_test', '--auth=trust',
                '--encoding=UTF8', '--locale=C').check_returncode()
        self.pg('pg_ctl', '-D', self.root / 'pgdata', '-l', self.root / 'postgres.log', '-o',
                f'-h 127.0.0.1 -p {self.pgport} -c shared_buffers=64MB -c max_connections=20 -c max_wal_size=128MB',
                '-w', 'start').check_returncode()
        self.pg_started = True
        import psycopg
        with psycopg.connect(host='127.0.0.1', port=self.pgport, dbname='postgres', user='stage1_test',
                             password='stage1-artificial-only', passfile=str(self.root / 'no-pgpass'),
                             autocommit=True, connect_timeout=5) as conn:
            conn.execute('CREATE DATABASE baseline_synthetic')
        os.environ.update(self.env)
        sys.path[:0] = [str(PROJECT), str(PROJECT / 'tools')]
        import django
        django.setup()
        from django.core.management import call_command
        from baseline_data import generate
        call_command('migrate', interactive=False, verbosity=0)
        call_command('collectstatic', interactive=False, verbosity=0)
        self.data = generate(anchor=date.fromisoformat(self.args.anchor_date))
        write_json(self.root / 'dataset.json', self.data)
        self.identities = {}
        from django.contrib.auth import get_user_model
        from django.test import Client
        from accounts.models import Membership
        from synchronization.auth import issue_token
        for org in self.data['organizations']:
            user = get_user_model().objects.get(pk=org['user_id'])
            member = Membership.objects.select_related('organization').get(pk=org['member_id'])
            client = Client()
            client.force_login(user)
            self.identities[org['label']] = {'cookie': client.cookies['sessionid'].value,
                                             'token': issue_token(user, member)}
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT version(), pg_database_size(current_database())")
            version, size = cursor.fetchone()
            cursor.execute('SHOW shared_buffers')
            buffers = cursor.fetchone()[0]
        self.environment = {'python': sys.version, 'platform': platform.platform(), 'logical_cpus': os.cpu_count(),
            'postgres': version, 'database_bytes_after_seed': size, 'shared_buffers': buffers,
            'versions': {name: importlib.metadata.version(name) for name in
                         ('Django', 'djangorestframework', 'psycopg', 'whitenoise', 'asgiref')},
            'max_seconds': self.args.max_seconds, 'worker_threads': 5, 'max_connections': 20,
            'max_response_bytes': 16_000_000, 'seed': self.data['seed'], 'anchor': self.data['anchor']}
        self.environment['sync_organizations'] = getattr(self.args, 'sync_org', None)
        self.environment['sync_part'] = getattr(self.args, 'sync_part', 'all')
        self.environment['sync_scenarios'] = getattr(self.args, 'sync_scenario', None)
        source_files = [*PROJECT.glob('web/*.py'), *PROJECT.glob('synchronization/*.py'),
                        *PROJECT.glob('tasks/*.py'), *PROJECT.glob('catalog/*.py'),
                        *PROJECT.glob('web/templates/web/*.html'), PROJECT / 'crmserver/settings.py',
                        PROJECT / 'crmserver/observability.py']
        self.environment['source_sha256'] = {str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                              for path in sorted(source_files)}
        write_json(self.root / 'environment.json', self.environment)

    def stop_server(self):
        if self.server:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
            self.server = None

    def start_server(self, mode):
        self.stop_server()
        self.guard()
        self.mode = mode
        self.port = free_port()
        self.eventfile = self.root / f'events-{mode}-{self.port}.jsonl'
        with (self.root / 'http-server.log').open('a', encoding='utf-8') as output:
            self.server = subprocess.Popen([sys.executable, str(PROJECT / 'tools/baseline_server.py'),
                '--port', str(self.port), '--mode', mode], cwd=PROJECT, env=self.env, stdout=output,
                stderr=subprocess.STDOUT, creationflags=self.creationflags)
        ready = self.root / f'server-ready-{self.port}'
        deadline = time.monotonic() + 20
        while not ready.exists():
            if self.server.poll() is not None:
                raise RuntimeError('HTTP server exited; see http-server.log')
            if time.monotonic() > deadline:
                raise TimeoutError('HTTP server readiness timeout')
            time.sleep(0.05)

    def http(self, org, path, payload=None, retain=False, profile=False):
        self.requests += 1
        identity = self.identities[org['label']]
        ident = uuid4().hex
        headers = {'X-Request-ID': ident}
        if payload is None:
            if not path.startswith('/catalog/'):
                headers['Cookie'] = 'sessionid=' + identity['cookie']
            body = None
        else:
            headers.update(Authorization='Bearer ' + identity['token'], **{'Content-Type': 'application/json'})
            body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if profile:
            headers['X-Baseline-Profile'] = '1'
        request = Request(f'http://127.0.0.1:{self.port}' + path, data=body, headers=headers)
        start = time.perf_counter()
        try:
            opener = build_opener(ProxyHandler({}))
            try:
                response = opener.open(request, timeout=45)
            except HTTPError as error:
                response = error
            with response:
                content = response.read(16_000_001)
                if len(content) > 16_000_000:
                    raise RuntimeError('Response size budget exceeded')
                status = response.status
            record = {'request_id': ident, 'status': status, 'client_ms': (time.perf_counter() - start) * 1000,
                      'response_bytes': len(content), 'request_body_bytes': len(body) if body else 0}
            if retain:
                record['body'] = json.loads(content)
            return record
        except Exception as exc:
            return {'request_id': ident, 'status': 0, 'client_ms': (time.perf_counter() - start) * 1000,
                    'error_type': type(exc).__name__}

    def events(self):
        records = {}
        with self.eventfile.open(encoding='utf-8') as source:
            source.seek(self.event_offsets.get(str(self.eventfile), 0))
            for line in source:
                event = json.loads(line)
                records.setdefault(event['request_id'], []).append(event)
            self.event_offsets[str(self.eventfile)] = source.tell()
        return records

    def enrich(self, rows):
        events = self.events()
        for row in rows:
            for event in events.get(row['request_id'], []):
                kind = event['event']
                if kind == 'baseline_transport':
                    row['executor_queue_ms'] = event['executor_queue_ms']
                    row['accepted_to_wsgi_ms'] = event['accepted_to_wsgi_ms']
                elif kind in ('http_request', 'sync_exchange'):
                    row['server_ms'] = event['duration_ms']
                    row['route'] = event['route']
                    for key, value in event.items():
                        if key.startswith('sql_') or key.endswith('_ms') and key != 'duration_ms' or key in (
                                'outcome', 'incoming_records', 'outgoing_records', 'incoming_deletions', 'outgoing_deletions'):
                            row[key] = value
        return rows

    def group(self, org, name, operation, repeats=20, parallel=1, warmup=2, category='sequential', block=0):
        self.guard()
        for i in range(warmup):
            operation(-i - 1)
        self.events()  # discard warm-up events, retain files for audit
        before = resources(self.server.pid)
        client_before = resources(os.getpid())
        wall = time.perf_counter()
        rows = []
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            for offset in range(0, repeats, parallel):
                self.guard()
                indices = list(range(offset, min(repeats, offset + parallel)))
                barrier = threading.Barrier(len(indices))
                def start_together(i):
                    barrier.wait(timeout=10)
                    return operation(i)
                futures = [pool.submit(start_together, i) for i in indices]
                rows.extend(future.result(timeout=50) for future in futures)
        wall = time.perf_counter() - wall
        after = resources(self.server.pid)
        client_after = resources(os.getpid())
        self.enrich(rows)
        result = {'organization': org['label'], 'live_records': org['live'], 'scenario': name,
                  'mode': self.mode, 'parallel': parallel, 'warmup': warmup, 'category': category,
                  'block': block, 'wall_seconds': wall, 'resources_before': before, 'resources_after': after,
                  'client_resources_before': client_before, 'client_resources_after': client_after,
                  **summarize(rows)}
        if before.get('available') and after.get('available'):
            result['server_cpu_seconds'] = after['cpu_seconds'] - before['cpu_seconds']
            result['server_cpu_core_equivalent'] = result['server_cpu_seconds'] / wall
        self.results.append(result)
        with (self.root / 'samples.jsonl').open('a', encoding='utf-8') as target:
            for row in rows:
                target.write(json.dumps({'scenario': name, 'organization': org['label'], 'mode': self.mode,
                                         'category': category, 'parallel': parallel, 'block': block, **row}) + '\n')
        self.save()
        print(f"{self.mode} {category} {org['label']} {name} c={parallel}: n={result['n']} errors={result['errors']} "
              f"client_median={result.get('client_ms', {}).get('median', 0):.1f}ms", flush=True)
        return result

    def profile(self, org, name, path, payload=None):
        self.guard()
        result = self.http(org, path, payload, profile=True)
        self.events()
        with (self.root / 'profile-index.jsonl').open('a', encoding='utf-8') as target:
            target.write(json.dumps({'organization': org['label'], 'scenario': name, **result}) + '\n')

    def sequential(self, sync_only=False):
        self.start_server('sql')
        self.snapshots = {}
        for org in self.sync_organizations() if sync_only else self.data['organizations'][:3]:
            cases = {
                'dashboard': '/dashboard/', 'customers_list': '/customers/',
                'customers_search': '/customers/?' + urlencode({'q': 'Клиент 000'}),
                'deals_list': '/deals/', 'tasks_list': '/tasks/',
                'tasks_filter': '/tasks/?' + urlencode({'status': 'Новая', 'priority': 'Высокий'}),
                'customer_hot_detail': f"/customers/{org['customer_id']}/", 'deal_detail': f"/deals/{org['deal_id']}/",
                'task_detail': f"/tasks/{org['task_id']}/", 'deal_form': '/deals/new/',
                'task_form': '/tasks/new/', 'task_edit': f"/tasks/{org['task_id']}/edit/",
            }
            for name, path in ({} if sync_only else cases).items():
                self.group(org, name, lambda i, path=path: self.http(org, path))
                if name in ('dashboard', 'task_form', 'customer_hot_detail'):
                    self.profile(org, name, path)
            empty = {'organization': org['uuid'], 'changes': []}
            initial = self.http(org, '/api/sync/exchange/', empty, retain=True)
            if initial['status'] != 200:
                raise RuntimeError('Cannot prepare synthetic snapshot')
            snapshot = {'organization': org['uuid'], 'changes': initial['body']['changes']}
            if len(snapshot['changes']) != org['admin_snapshot_records'] or len(snapshot['changes']) > 10000:
                raise RuntimeError('Fixture snapshot count/limit mismatch')
            if sync_only:
                # Untimed equivalence check between fresh-cluster before/after runs.
                content = {'changes': snapshot['changes'], 'members': initial['body']['members']}
                write_json(self.root / f"snapshot-fingerprint-{org['label']}.json", {
                    'sha256': hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest(),
                    'records': len(snapshot['changes']),
                })
            self.snapshots[org['label']] = snapshot
            selected = getattr(self.args, 'sync_scenario', None) if sync_only else None
            if not selected or 'sync_unchanged' in selected:
                self.group(org, 'sync_unchanged', lambda i: self.http(org, '/api/sync/exchange/', snapshot), repeats=5)
                self.profile(org, 'sync_unchanged', '/api/sync/exchange/', snapshot)
            if not selected or 'sync_first_empty_device' in selected:
                self.group(org, 'sync_first_empty_device', lambda i: self.http(org, '/api/sync/exchange/', empty), repeats=5)
                self.profile(org, 'sync_first_empty_device', '/api/sync/exchange/', empty)
            mutable = [row for row in snapshot['changes'] if row['entity'] == 'customers' and not row['deleted']][:org['live'] // 100]
            from django.utils import timezone
            def changed(i):
                stamp = timezone.now().isoformat()
                for row in mutable:
                    row['updated_at'] = stamp
                    row['fields']['notes'] = f'Synthetic modified round {i}'
                return self.http(org, '/api/sync/exchange/', snapshot)
            if not selected or 'sync_changed_1pct' in selected:
                self.group(org, 'sync_changed_1pct', changed, repeats=5)
                for row in mutable:
                    row['updated_at'] = timezone.now().isoformat()
                    row['fields']['notes'] = 'Synthetic profile modification'
                self.profile(org, 'sync_changed_1pct', '/api/sync/exchange/', snapshot)
        if sync_only:
            return
        org = self.data['organizations'][2]
        kind = self.data['catalog']['types'][0]
        cases = {'catalog_list': '/catalog/baseline-catalog/',
                 'catalog_search': '/catalog/baseline-catalog/?' + urlencode({'q': 'Товар 0'}),
                 'catalog_filter': '/catalog/baseline-catalog/?' + urlencode({
                     'type': kind['id'], 'price_min': '200', 'price_max': '1000', 'in_stock': 'on',
                     'sort': 'price', f"attr_{kind['weight_key']}_min": '5', f"attr_{kind['color_key']}": 'Белый'})}
        for name, path in cases.items():
            self.group(org, name, lambda i, path=path: self.http(org, path))
            self.profile(org, name, path)

    def sync_read(self):
        """Focused comparison: identical sync cases, settings, seed, warm-up and timeouts."""
        part = getattr(self.args, 'sync_part', 'all')
        if part == 'concurrency':
            self.start_server('sql')
            # Recreate the logical state left by the original changed-profile case,
            # outside timing. No DB shortcut or altered sync implementation.
            from django.utils import timezone
            for org in self.sync_organizations():
                initial = self.http(org, '/api/sync/exchange/',
                                    {'organization': org['uuid'], 'changes': []}, retain=True)
                if initial['status'] != 200:
                    raise RuntimeError('Cannot prepare contention fixture snapshot')
                changes = initial['body']['changes']
                mutable = [row for row in changes if row['entity'] == 'customers' and not row['deleted']][:org['live'] // 100]
                # Same eight customer updates as 2 warm-ups + 5 changes + profile.
                # Only preparation omits unchanged input rows; measured pulls stay identical.
                for round_number in (-1, -2, 0, 1, 2, 3, 4, None):
                    stamp = timezone.now().isoformat()
                    for row in mutable:
                        row['updated_at'] = stamp
                        row['fields']['notes'] = ('Synthetic profile modification' if round_number is None
                                                 else f'Synthetic modified round {round_number}')
                    applied = self.http(org, '/api/sync/exchange/',
                                        {'organization': org['uuid'], 'changes': mutable})
                    if applied['status'] != 200:
                        raise RuntimeError('Cannot prepare contention fixture changes')
            self.events()
        else:
            self.sequential(sync_only=True)
        if part == 'sequential':
            return
        for org in self.sync_organizations():
            empty = {'organization': org['uuid'], 'changes': []}
            name = 'same_org_large_sync_pull' if org['label'] == 'large' else 'same_org_sync_pull'
            for parallel in (1, 2, 5):
                self.group(org, name, lambda i: self.http(org, '/api/sync/exchange/', empty),
                           parallel=parallel, repeats=20 if org['label'] == 'small' else 5,
                           category='concurrency')

    def sync_organizations(self):
        labels = getattr(self.args, 'sync_org', None)
        return [org for org in self.data['organizations'][:3] if not labels or org['label'] in labels]

    def verify_tests(self):
        """Use the runner's separate disposable test DB in this OWNED cluster, before timing."""
        self.guard()
        test_env = {**self.env, 'DJANGO_SETTINGS_MODULE': 'crmserver.verification_settings',
                    'STAGE1_VERIFY_PGPORT': str(self.pgport)}
        with (self.root / 'tests.log').open('w', encoding='utf-8') as output:
            for labels in (('accounts', 'web'), ('synchronization',), ('crmserver', 'tools.test_baseline_harness')):
                self.guard()
                output.write(f'\nTest batch: {labels}\n')
                output.flush()
                result = subprocess.run([sys.executable, str(PROJECT / 'manage.py'), 'test',
                    *labels, '--noinput', '--verbosity', '1'], cwd=PROJECT, env=test_env,
                    stdout=output, stderr=subprocess.STDOUT, timeout=180, creationflags=self.creationflags)
                result.check_returncode()

    def competition(self):
        org = self.data['organizations'][0]
        peers = [org] + self.data['organizations'][3:]
        for parallel in (1, 2, 5):
            same = {'organization': org['uuid'], 'changes': []}
            self.group(org, 'same_org_sync_pull', lambda i: self.http(org, '/api/sync/exchange/', same),
                       parallel=parallel, category='concurrency')
            def different(i):
                peer = peers[i % parallel]
                return self.http(peer, '/api/sync/exchange/', {'organization': peer['uuid'], 'changes': []})
            self.group(org, 'different_org_sync_pull', different, parallel=parallel, category='concurrency')
            self.group(org, 'crm_during_sync', lambda i: self.http(org, '/dashboard/') if i % 2 else
                       self.http(org, '/api/sync/exchange/', same), parallel=parallel, category='concurrency')
        large = self.data['organizations'][2]
        for parallel in (1, 2, 5):
            empty = {'organization': large['uuid'], 'changes': []}
            self.group(large, 'same_org_large_sync_pull', lambda i: self.http(large, '/api/sync/exchange/', empty),
                       parallel=parallel, repeats=5, category='concurrency')

    def overhead(self):
        org = self.data['organizations'][0]
        # Balanced order across three blocks. Each mode starts a fresh server and receives equal warm-up.
        for block, order in enumerate((('off', 'http', 'sql'), ('sql', 'off', 'http'), ('http', 'sql', 'off'))):
            for mode in order:
                self.start_server(mode)
                self.group(org, 'dashboard', lambda i: self.http(org, '/dashboard/'), repeats=20,
                           warmup=3, category='overhead', block=block)
                payload = {'organization': org['uuid'], 'changes': []}
                self.group(org, 'sync_pull', lambda i: self.http(org, '/api/sync/exchange/', payload), repeats=20,
                           warmup=3, category='overhead', block=block)

    def save(self):
        write_json(self.root / 'results.json', {'results': self.results, 'unfinished': self.unfinished,
            'elapsed_seconds': time.monotonic() - self.started, 'request_count': self.requests})

    def finish(self):
        self.watchdog.cancel()
        self.stop_server()
        from django.conf import settings
        if settings.configured:
            from django.db import connections
            connections.close_all()
        stopped = False
        if self.pg_started:
            try:
                stopped = self.pg('pg_ctl', '-D', self.root / 'pgdata', '-m', 'fast', '-w', 'stop', timeout=20).returncode == 0
            except Exception:
                stopped = False
        marker = json.loads((self.root / 'baseline-owner.json').read_text(encoding='utf-8'))
        directory = (self.root / 'pgdata').resolve()
        if stopped and marker == self.marker and directory.parent == self.root:
            shutil.rmtree(directory)
        write_json(self.root / 'cleanup.json', {'http_stopped': self.server is None, 'postgres_stopped': stopped,
                                                'cluster_removed': not directory.exists()})
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=1200, choices=range(120, 1801), metavar='120..1800')
    parser.add_argument('--anchor-date', default='2026-10-16')
    parser.add_argument('--phase', choices=['full', 'overhead', 'concurrency', 'sync-read'], default='full',
                        help='A separate bounded fresh-cluster run for a phase if the full time budget is exhausted')
    parser.add_argument('--verify-tests', action='store_true', help='Run server regressions on a separate test DB before measuring')
    parser.add_argument('--sync-org', nargs='+', choices=['small', 'medium', 'large'],
                        help='Resume only selected organizations in a fresh bounded sync-read run')
    parser.add_argument('--sync-part', choices=['all', 'sequential', 'concurrency'], default='all')
    parser.add_argument('--sync-scenario', nargs='+', choices=[
        'sync_unchanged', 'sync_first_empty_device', 'sync_changed_1pct'])
    args = parser.parse_args()
    if (args.sync_org or args.sync_scenario or args.sync_part != 'all') and args.phase != 'sync-read':
        parser.error('--sync-* filters require --phase sync-read')
    if args.sync_scenario and args.sync_part == 'concurrency':
        parser.error('--sync-scenario cannot be used with --sync-part concurrency')
    if args.sync_scenario and args.sync_part == 'all' and 'sync_changed_1pct' not in args.sync_scenario:
        parser.error('Contention after selected cases requires sync_changed_1pct to prepare the same data')
    experiment = Experiment(args)
    try:
        experiment.setup()
        if args.verify_tests:
            experiment.verify_tests()
        if args.phase == 'sync-read':
            experiment.sync_read()
        if args.phase == 'full':
            experiment.sequential()
        if args.phase in ('full', 'concurrency'):
            experiment.competition()
        if args.phase in ('full', 'overhead'):
            experiment.overhead()
    except BaseException as exc:
        experiment.unfinished.append({'error_type': type(exc).__name__, 'reason': str(exc)})
        raise
    finally:
        experiment.finish()


if __name__ == '__main__':
    main()
