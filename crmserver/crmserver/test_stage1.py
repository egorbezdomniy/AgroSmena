"""Behavioral checks through Django's real middleware and real PostgreSQL when required."""
import asyncio
import json
import logging
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import AsyncClient, Client, RequestFactory, SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Membership, Organization
from customers.models import Customer
from synchronization.services import exchange, serialize_record
from tasks.models import Task
from crmserver.observability import Diagnostics, EventFormatter, logger


@contextmanager
def captured_events():
    events = []
    class Capture(logging.Handler):
        def emit(self, record):
            events.append(json.loads(EventFormatter().format(record)))
    with patch.object(logger, 'handlers', [Capture()]), patch.object(logger, 'level', logging.INFO):
        yield events


@override_settings(
    DEBUG=False, ROOT_URLCONF='crmserver.test_stage1_urls',
    OBSERVABILITY_ENABLED=True, OBSERVABILITY_HTTP_SAMPLE_RATE=1,
    OBSERVABILITY_SQL_ENABLED=False, OBSERVABILITY_EXCLUDE_ROUTES=[],
    SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies',
)
class MiddlewareHTTPTests(SimpleTestCase):
    def test_login_throttle_ignores_untrusted_forwarded_for(self):
        with override_settings(ROOT_URLCONF='crmserver.urls', CACHES={'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'stage1-throttle-only',
        }}, REST_FRAMEWORK={**settings.REST_FRAMEWORK, 'NUM_PROXIES': 0}), captured_events():
            client = APIClient()
            statuses = [client.post('/api/sync/login/', {}, format='json',
                                    HTTP_X_FORWARDED_FOR=f'192.0.2.{i}').status_code for i in range(11)]
        self.assertEqual(statuses, [400] * 10 + [429])

    def test_sequential_requests_normalize_route_and_do_not_share_state(self):
        with captured_events() as events:
            first = self.client.get('/diagnostic/31/?search=stage1-private-query',
                                    HTTP_AUTHORIZATION='Bearer stage1-private-auth')
            second = self.client.get('/diagnostic/72/')
        self.assertEqual([event['route'] for event in events], ['diagnostic-detail'] * 2)
        self.assertNotEqual(first['X-Request-ID'], second['X-Request-ID'])
        self.assertTrue(all(event['sql_sampled'] is False for event in events))
        self.assertTrue(all('sql_count' not in event and 'sql_duration_ms' not in event for event in events))
        self.assertNotIn('stage1-private', json.dumps(events))
        self.assertNotIn('/diagnostic/31/', json.dumps(events))

    def test_converted_view_exception_has_status_and_id_without_details(self):
        with captured_events() as events, self.assertLogs('django.request', level='ERROR'):
            response = Client(raise_request_exception=False).get('/failure/')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(events[0]['status_code'], 500)
        self.assertEqual(events[0]['request_id'], response['X-Request-ID'])
        self.assertNotIn('stage1-private-exception', json.dumps(events))

    def test_health_hosts_and_untrusted_id(self):
        with captured_events() as events:
            response = self.client.get('/healthz/', HTTP_X_REQUEST_ID='bad-input')
            head = self.client.head('/healthz/')
            with self.assertLogs('django.security.DisallowedHost', level='ERROR'):
                forbidden = self.client.get('/healthz/', HTTP_HOST='outsider.invalid')
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertRegex(response['X-Request-ID'], r'^[a-f0-9]{32}$')
        self.assertEqual(head.content, b'')
        self.assertEqual(forbidden.status_code, 400)
        self.assertEqual(events[-1]['route'], 'unresolved')

    def test_secure_cookies_and_explicit_proxy_trust(self):
        response = self.client.get('/cookies/')
        self.assertTrue(response.cookies['sessionid']['secure'])
        self.assertTrue(response.cookies['csrftoken']['secure'])
        self.assertTrue(response.cookies['sessionid']['httponly'])
        request = RequestFactory().get('/', HTTP_X_FORWARDED_PROTO='https')
        self.assertFalse(request.is_secure())
        with override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https')):
            self.assertTrue(request.is_secure())
            with override_settings(SECURE_SSL_REDIRECT=True):
                # SecurityMiddleware caches its settings when its chain is created.
                trusted = Client().get('/healthz/', HTTP_X_FORWARDED_PROTO='https')
                cleartext = Client().get('/healthz/')
            self.assertEqual(trusted.status_code, 200)
            self.assertEqual(cleartext.status_code, 301)
        with override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False):
            local = Client().get('/cookies/')
            self.assertFalse(local.cookies['sessionid']['secure'])
            self.assertFalse(local.cookies['csrftoken']['secure'])

    def test_logger_refusal_and_collection_off(self):
        with patch('crmserver.observability.logger.info', side_effect=OSError('test sink failure')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        with override_settings(OBSERVABILITY_ENABLED=False), captured_events() as events:
            response = self.client.get('/diagnostic/1/')
        self.assertEqual(events, [])
        self.assertIn('X-Request-ID', response)

    def test_sql_sample_miss_omits_fields(self):
        with override_settings(OBSERVABILITY_SQL_ENABLED=True, OBSERVABILITY_SQL_SAMPLE_RATE=0), captured_events() as events:
            self.client.get('/healthz/')
        self.assertFalse(events[0]['sql_sampled'])
        self.assertNotIn('sql_count', events[0])
        self.assertEqual(connections['default'].execute_wrappers, [])

    def test_static_has_fixed_route_and_can_be_silenced_without_hiding_errors(self):
        from django.contrib.staticfiles.storage import staticfiles_storage
        asset = staticfiles_storage.url('web/landing.css')
        with override_settings(OBSERVABILITY_EXCLUDE_ROUTES=['static']), captured_events() as events:
            response = self.client.get(asset)
            response.close()
            self.assertEqual(events, [])
            missing = self.client.get('/static/stage1-absent.css')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(events[0]['route'], 'static')

    def test_actual_asgi_chain_returns_id_and_events(self):
        async def scenario():
            return await asyncio.gather(AsyncClient().get('/diagnostic/1/'), AsyncClient().get('/diagnostic/2/'))
        with captured_events() as events:
            responses = asyncio.run(scenario())
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertNotEqual(responses[0]['X-Request-ID'], responses[1]['X-Request-ID'])
        self.assertEqual([event['route'] for event in events], ['diagnostic-detail'] * 2)

    def test_manifest_contains_used_template_assets(self):
        # collectstatic must have run against the same isolated STATIC_ROOT first.
        from django.contrib.staticfiles.storage import staticfiles_storage
        import re
        assets = set()
        root = settings.BASE_DIR
        for app in ('web', 'accounts', 'catalog'):
            for source in (root / app / 'templates').rglob('*.html'):
                assets.update(re.findall(r"\{%\s*static\s+['\"]([^'\"]+)['\"]", source.read_text(encoding='utf-8')))
        self.assertTrue(assets)
        for asset in assets:
            with self.subTest(asset=asset):
                hashed = staticfiles_storage.stored_name(asset)
                self.assertTrue((Path(settings.STATIC_ROOT) / hashed).is_file())
                self.assertIn(hashed, staticfiles_storage.url(asset))


@override_settings(DEBUG=False, OBSERVABILITY_SQL_ENABLED=True, OBSERVABILITY_SQL_SAMPLE_RATE=1,
                   OBSERVABILITY_HTTP_SAMPLE_RATE=1, OBSERVABILITY_EXCLUDE_ROUTES=[])
class PostgreSQLDiagnosticsTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='stage1-private-organization')
        self.user = get_user_model().objects.create_user('stage1-private-user', password='stage1-fake-only-834!')
        self.membership = Membership.objects.create(user=self.user, organization=self.org, role='admin')

    def request(self):
        request = SimpleNamespace(user=self.user, crm_membership=self.membership)
        request._crm_diagnostics = Diagnostics(RequestFactory().get('/'))
        request._crm_diagnostics.sync = {}
        return request

    def test_real_sql_exception_cleanup_and_next_request(self):
        with override_settings(ROOT_URLCONF='crmserver.test_stage1_urls'), captured_events() as events:
            client = Client(raise_request_exception=False)
            first = client.get('/sql/')
            with self.assertLogs('django.request', level='ERROR'):
                failed = client.get('/sql-error/')
            again = client.get('/sql/')
        self.assertEqual([first.status_code, failed.status_code, again.status_code], [200, 500, 200])
        self.assertEqual([event['sql_count'] for event in events], [1, 1, 1])
        self.assertEqual([event['sql_error_count'] for event in events], [0, 1, 0])
        self.assertTrue(all(event['sql_collection_complete'] for event in events))
        self.assertEqual(connection.execute_wrappers, [])
        self.assertNotIn('stage1-private', json.dumps(events))

    def test_real_concurrent_http_sql_counts_are_isolated(self):
        barrier = Barrier(2)
        def run(count):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = Client().get(f'/sql/{count}/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(connection.execute_wrappers, [])
                return response['X-Request-ID']
            finally:
                connection.close()
        with override_settings(ROOT_URLCONF='crmserver.test_stage1_urls'), captured_events() as events:
            with ThreadPoolExecutor(max_workers=2) as pool:
                ids = list(pool.map(run, [1, 3]))
        by_id = {event['request_id']: event for event in events}
        self.assertEqual([by_id[key]['sql_count'] for key in ids], [1, 3])
        self.assertTrue(all(event['sql_collection_complete'] for event in events))
        self.assertEqual({event['route'] for event in events}, {'diagnostic-sql-count'})

    def test_sync_http_format_counts_and_rollback(self):
        from synchronization.auth import issue_token
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_token(self.user, self.membership))
        customer = Customer.objects.create(organization=self.org, name='stage1-private-customer')
        payload = {'organization': str(self.org.uuid), 'changes': []}
        with captured_events() as events:
            response = client.post('/api/sync/exchange/', payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'organization', 'synced_at', 'members', 'changes'})
        self.assertEqual(set(response.data['changes'][0]), {'entity', 'uuid', 'created_at', 'updated_at', 'deleted', 'fields'})
        sync = [event for event in events if event['event'] == 'sync_exchange'][0]
        self.assertEqual(sync['outgoing_records'], 1)
        self.assertEqual(sync['incoming_records'], 0)
        self.assertEqual(sync['response_body_bytes'], len(response.content))
        self.assertTrue(sync['lock_release_at_service_exit'])
        self.assertLessEqual(sync['organization_lock_observed_hold_ms'], sync['exchange_service_ms'])
        self.assertNotIn('stage1-private', json.dumps(events))
        self.assertNotIn(str(customer.uuid), json.dumps(events))
        row = serialize_record('customers', customer)
        row['updated_at'] = (timezone.now() + timedelta(seconds=1)).isoformat()
        row['fields']['name'] = 'stage1-must-rollback'
        bad = {'entity': 'deals', 'uuid': str(uuid4()), 'created_at': row['created_at'],
               'updated_at': row['updated_at'], 'deleted': False,
               'fields': {'title': 'invalid parent', 'customer_uuid': str(uuid4())}}
        with captured_events() as events:
            rejected = client.post('/api/sync/exchange/', {**payload, 'changes': [row, bad]}, format='json')
        self.assertEqual(rejected.status_code, 400)
        customer.refresh_from_db()
        self.assertEqual(customer.name, 'stage1-private-customer')
        sync = [event for event in events if event['event'] == 'sync_exchange'][0]
        self.assertEqual(sync['outcome'], 'validation_error')
        self.assertNotIn('stage1-must-rollback', json.dumps(events))

    def test_assigned_common_and_other_organization_tasks_stay_isolated(self):
        colleague = get_user_model().objects.create_user('stage1-colleague')
        colleague_membership = Membership.objects.create(user=colleague, organization=self.org, role='manager')
        common = Task.objects.create(organization=self.org, title='stage1-common')
        mine = Task.objects.create(organization=self.org, title='stage1-mine')
        mine.assignees.add(self.membership)
        theirs = Task.objects.create(organization=self.org, title='stage1-theirs')
        theirs.assignees.add(colleague_membership)
        foreign_org = Organization.objects.create(name='stage1-foreign')
        foreign = Task.objects.create(organization=foreign_org, title='stage1-foreign-task')
        client = APIClient()
        client.force_login(self.user)
        response = client.get('/api/tasks/')
        self.assertEqual({row['id'] for row in response.data['results']}, {common.pk, mine.pk})
        self.assertEqual(client.get(f'/api/tasks/{theirs.pk}/').status_code, 404)
        self.assertEqual(client.get(f'/api/tasks/{foreign.pk}/').status_code, 404)
        webpage = client.get('/tasks/')
        self.assertContains(webpage, 'stage1-common')
        self.assertContains(webpage, 'stage1-mine')
        self.assertNotContains(webpage, 'stage1-theirs')
        self.assertNotContains(webpage, 'stage1-foreign-task')
        result = exchange(self.request(), {'organization': self.org.uuid, 'changes': []})
        self.assertEqual({row['uuid'] for row in result['changes']}, {str(common.uuid), str(mine.uuid)})

    def test_concurrent_exchanges_and_outer_atomic_lock_lifetime(self):
        # Confirm actual PostgreSQL contention via pg_stat_activity, not a sleep-based guess.
        attempted = Event()
        holder_ready = Event()
        release_holder = Event()
        waiter_pid = []

        def waiter():
            close_old_connections()
            try:
                req = self.request()
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    waiter_pid.append(cursor.fetchone()[0])
                attempted.set()
                result = exchange(req, {'organization': self.org.uuid, 'changes': []})
                return req._crm_diagnostics.sync, result
            finally:
                connection.close()

        def holder():
            close_old_connections()
            try:
                req = self.request()
                with transaction.atomic():
                    exchange(req, {'organization': self.org.uuid, 'changes': []})
                    holder_ready.set()
                    if not release_holder.wait(15):
                        raise AssertionError('Test did not release outer transaction')
                return req._crm_diagnostics.sync
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            holding = pool.submit(holder)
            waiting = None
            try:
                self.assertTrue(holder_ready.wait(10))
                waiting = pool.submit(waiter)
                self.assertTrue(attempted.wait(10))
                deadline = time.monotonic() + 10
                blocked = False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', waiter_pid)
                        row = cursor.fetchone()
                    if row and row[0] == 'Lock':
                        blocked = True
                        break
                    time.sleep(0.01)
                self.assertTrue(blocked, 'Second exchange was not observed waiting on a real DB lock')
                self.assertFalse(waiting.done())
            finally:
                release_holder.set()
            holder_metrics = holding.result(timeout=10)
            waiter_metrics, result = waiting.result(timeout=10)
        self.assertFalse(holder_metrics['lock_release_at_service_exit'])
        self.assertTrue(waiter_metrics['lock_release_at_service_exit'])
        self.assertGreater(waiter_metrics['organization_lock_acquire_ms'], 0)
        self.assertGreaterEqual(waiter_metrics['exchange_service_ms'], waiter_metrics['organization_lock_observed_hold_ms'])
        self.assertEqual(set(result), {'organization', 'synced_at', 'members', 'changes'})
