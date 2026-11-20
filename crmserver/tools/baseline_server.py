"""Bounded local WSGI experiment, never a production server."""
import argparse
import json
import logging
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer


class Sink:
    def __init__(self, path):
        self.file = path.open('w', encoding='utf-8', buffering=1)
        self.lock = threading.Lock()

    def write(self, value):
        with self.lock:
            if self.file.tell() > 50_000_000:
                raise RuntimeError('Experiment log limit exceeded')
            self.file.write(value)

    def flush(self):
        with self.lock:
            self.file.flush()

    def event(self, **values):
        self.write(json.dumps(values, separators=(',', ':')) + '\n')


class Profile:
    """Only enabled for separate, explicitly marked synthetic profiling requests."""
    def __init__(self):
        self.groups = {}

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            duration = (time.perf_counter() - start) * 1000
            if sql in self.groups:
                group = self.groups[sql]
            elif len(self.groups) < 150:
                stack = [f'{Path(frame.filename).parent.name}/{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                         for frame in traceback.extract_stack(limit=30)
                         if 'site-packages' not in frame.filename and 'baseline_' not in frame.filename]
                group = self.groups[sql] = {'count': 0, 'duration_ms': 0, 'params': params, 'stack': stack}
            else:
                group = None
            if group is not None:
                group['count'] += 1
                group['duration_ms'] += duration

    def save(self, path):
        from django.db import connection, transaction
        ordered = sorted(self.groups.items(), key=lambda item: item[1]['count'], reverse=True)
        hot = ordered[:3] + sorted(self.groups.items(), key=lambda item: item[1]['duration_ms'], reverse=True)[:3]
        plans = []
        seen = set()
        for sql, group in hot:
            if sql in seen or not sql.lstrip().upper().startswith('SELECT') or 'FOR UPDATE' in sql.upper() or ';' in sql:
                continue
            seen.add(sql)
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION READ ONLY')
                        cursor.execute("SET LOCAL statement_timeout = '5s'")
                        cursor.execute("SET LOCAL lock_timeout = '500ms'")
                        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, group['params'])
                        plan = cursor.fetchone()[0]
                plans.append({'sql': sql, 'plan': plan})
            except Exception as exc:
                plans.append({'sql': sql, 'error_type': type(exc).__name__})
        path.write_text(json.dumps({
            'synthetic_only': True,
            'groups': [{'sql': sql, **{key: value for key, value in group.items() if key != 'params'}}
                       for sql, group in ordered], 'plans': plans,
        }, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--mode', choices=['off', 'http', 'sql'], required=True)
    args = parser.parse_args()
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'crmserver.baseline_settings':
        raise RuntimeError('Only isolated baseline_settings allowed')
    os.environ['BASELINE_DIAGNOSTICS'] = args.mode
    import django
    django.setup()
    from baseline_data import assert_disposable
    root = assert_disposable()
    from django.core.wsgi import get_wsgi_application
    from django.db import connections
    from crmserver.observability import EventFormatter, logger
    # get_wsgi_application() calls django.setup() again, including logging setup.
    # Install the experiment sink AFTER that final setup call.
    app = get_wsgi_application()
    sink = Sink(root / f'events-{args.mode}-{args.port}.jsonl')
    handler = logging.StreamHandler(sink)
    handler.setFormatter(EventFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    local = threading.local()
    profiles = root / 'profiles'
    profiles.mkdir(exist_ok=True)

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    class BoundedServer(WSGIServer):
        request_queue_size = 16
        def __init__(self, *values, **kwargs):
            self.pool = ThreadPoolExecutor(max_workers=5)
            super().__init__(*values, **kwargs)

        def process_request(self, request, client_address):
            request.settimeout(45)
            accepted = time.perf_counter()
            self.pool.submit(self.work, request, client_address, accepted)

        def work(self, request, address, accepted):
            local.accepted = accepted
            local.started = time.perf_counter()
            try:
                self.finish_request(request, address)
            except Exception:
                self.handle_error(request, address)
            finally:
                self.shutdown_request(request)
                connections.close_all()

    def measured(environ, start_response):
        entered = time.perf_counter()
        environ['wsgi.multithread'] = True
        ident = environ.get('HTTP_X_REQUEST_ID', '')
        profile = Profile() if environ.get('HTTP_X_BASELINE_PROFILE') == '1' else None
        with connections['default'].execute_wrapper(profile) if profile else nullcontext():
            result = app(environ, start_response)
        ready = time.perf_counter()
        if profile:
            profile.save(profiles / f'{ident}.json')
        sink.event(event='baseline_transport', request_id=ident,
                   executor_queue_ms=(local.started - local.accepted) * 1000,
                   accepted_to_wsgi_ms=(entered - local.accepted) * 1000,
                   wsgi_response_ready_ms=(ready - entered) * 1000,
                   profile=profile is not None)
        return result

    with BoundedServer(('127.0.0.1', args.port), QuietHandler) as server:
        server.set_app(measured)
        (root / f'server-ready-{args.port}').write_text(str(os.getpid()), encoding='ascii')
        server.serve_forever(poll_interval=0.2)


if __name__ == '__main__':
    main()
