"""Focused diagnostics tests. No live server or database required by this module."""
import asyncio
import importlib.util
import json
import logging
import os
import runpy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asgiref.sync import ThreadSensitiveContext, async_to_sync, sync_to_async
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connections
from django.db.backends.utils import CursorWrapper
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError

from crmserver.env import env_bool, env_int, env_rate
from crmserver.observability import (
    Diagnostics, EventFormatter, RequestObservabilityMiddleware, SQLCounter, observe_exchange,
    declared_request_bytes, sync_lock_acquired, sync_phase, sync_record_counts,
)


class EnvironmentTests(SimpleTestCase):
    def test_integer_bounds_and_gunicorn_config_values(self):
        for name in ('WEB_CONCURRENCY', 'GUNICORN_TIMEOUT'):
            for value in ('0', '-1', 'not-an-integer'):
                with patch.dict(os.environ, {name: value}, clear=True):
                    with self.assertRaises(ImproperlyConfigured):
                        env_int(name, 1, minimum=1)
        with patch.dict(os.environ, {}, clear=True):
            config = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gunicorn.conf.py'))
        self.assertEqual(config['workers'], 1)
        self.assertEqual(config['timeout'], 30)
        self.assertEqual(config['worker_class'], 'sync')
        self.assertEqual(config['forwarded_allow_ips'], '')
        self.assertIsNone(config['accesslog'])

    def test_boolean_values_and_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(env_bool('FLAG'))
            self.assertTrue(env_bool('FLAG', True))
            for value in ('false', 'False', '0', 'no', 'OFF', ' false '):
                os.environ['FLAG'] = value
                self.assertFalse(env_bool('FLAG', True))
            for value in ('true', 'TRUE', '1', 'yes', 'on'):
                os.environ['FLAG'] = value
                self.assertTrue(env_bool('FLAG'))
            for value in ('', 'perhaps', 'secret-value'):
                os.environ['FLAG'] = value
                with self.assertRaises(ImproperlyConfigured) as error:
                    env_bool('FLAG')
                self.assertNotIn(value or 'secret-value', str(error.exception))

    def test_sampling_rejects_invalid_and_nonfinite_values(self):
        for value in ('NaN', 'inf', '-0.1', '1.1', 'bad'):
            with patch.dict(os.environ, {'RATE': value}):
                with self.assertRaises(ImproperlyConfigured):
                    env_rate('RATE')

    def load_settings(self, **environment):
        # Never load a developer's .env while testing configuration parsing.
        source = Path(__file__).with_name('settings.py')
        spec = importlib.util.spec_from_file_location('crmserver._isolated_settings', source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, environment, clear=True), patch('dotenv.load_dotenv'):
            spec.loader.exec_module(module)
        return module

    def test_production_defaults_and_no_implicit_host(self):
        configured = self.load_settings(
            DJANGO_SECRET_KEY='test-only-strong-key-0123456789-abcdefghijklmnopqrstuvwxyz',
            DJANGO_ALLOWED_HOSTS='crm.example.test')
        self.assertFalse(configured.DEBUG)
        self.assertTrue(configured.SESSION_COOKIE_SECURE)
        self.assertTrue(configured.CSRF_COOKIE_SECURE)
        self.assertEqual(configured.ALLOWED_HOSTS, ['crm.example.test'])
        self.assertIsNone(configured.SECURE_PROXY_SSL_HEADER)
        self.assertFalse(configured.SECURE_SSL_REDIRECT)
        self.assertEqual(configured.SECURE_HSTS_SECONDS, 0)

    def test_production_requires_key_and_hosts(self):
        for environment in ({}, {'DJANGO_SECRET_KEY': 'short'}, {
            'DJANGO_SECRET_KEY': 'test-only-strong-key-0123456789-abcdefghijklmnopqrstuvwxyz',
        }, {
            'DJANGO_SECRET_KEY': 'test-only-strong-key-0123456789-abcdefghijklmnopqrstuvwxyz',
            'DJANGO_ALLOWED_HOSTS': '*',
        }):
            with self.assertRaises(ImproperlyConfigured):
                self.load_settings(**environment)

    def test_local_debug_requires_explicit_true(self):
        configured = self.load_settings(DJANGO_DEBUG='true', DJANGO_SECRET_KEY='local-only')
        self.assertTrue(configured.DEBUG)
        self.assertFalse(configured.SESSION_COOKIE_SECURE)
        self.assertEqual(configured.ALLOWED_HOSTS, ['127.0.0.1', 'localhost'])

    def test_dotenv_can_be_excluded_before_loading(self):
        source = Path(__file__).with_name('settings.py')
        spec = importlib.util.spec_from_file_location('crmserver._isolated_no_dotenv', source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'DJANGO_LOAD_DOTENV': 'false', 'DJANGO_DEBUG': 'true',
                                     'DJANGO_SECRET_KEY': 'test-only'}, clear=True), patch(
                                         'dotenv.load_dotenv', side_effect=AssertionError('Must never read .env')) as loader:
            spec.loader.exec_module(module)
        loader.assert_not_called()


@override_settings(
    DEBUG=False, OBSERVABILITY_ENABLED=True, OBSERVABILITY_HTTP_SAMPLE_RATE=1,
    OBSERVABILITY_SQL_ENABLED=True, OBSERVABILITY_SQL_SAMPLE_RATE=1,
    OBSERVABILITY_SYNC_ENABLED=True, OBSERVABILITY_EXCLUDE_ROUTES=['healthz'],
)
class ObservabilityTests(SimpleTestCase):
    def request(self, route='customers-detail', method='GET', **headers):
        request = RequestFactory().generic(method, '/customers/987/?search=private', **headers)
        request.resolver_match = SimpleNamespace(view_name=route)
        return request

    def capture(self, request, view):
        middleware = RequestObservabilityMiddleware(None)

        def handler(req):
            middleware.process_view(req, view, (), {})
            return view(req)

        middleware.get_response = handler
        with patch('crmserver.observability.emit') as output:
            response = middleware(request)
        return response, [call.args[0] for call in output.call_args_list]

    def execute_fake_sql(self, many=False, fail=False):
        raw = Mock()
        if fail:
            raw.execute.side_effect = DatabaseError('private SQL parameters')
        cursor = CursorWrapper(raw, connections['default'])
        if many:
            cursor.executemany('private SQL text', iter([('private parameter',)]))
        else:
            cursor.execute('private SQL text', ['private parameter'])
        return raw

    def test_request_id_routes_and_no_sensitive_data(self):
        request = self.request(HTTP_AUTHORIZATION='Bearer private-token', HTTP_COOKIE='private-cookie')

        def view(req):
            self.execute_fake_sql()
            return HttpResponse('private response data')

        response, events = self.capture(request, view)
        event = events[0]
        self.assertRegex(response['X-Request-ID'], r'^[0-9a-f]{32}$')
        self.assertEqual(event['request_id'], response['X-Request-ID'])
        self.assertEqual(event['route'], 'customers-detail')
        self.assertEqual(event['sql_count'], 1)
        self.assertTrue(event['sql_collection_complete'])
        encoded = json.dumps(events)
        for secret in ('/customers/987/', 'private', 'Authorization', 'Cookie', 'search='):
            self.assertNotIn(secret, encoded)
        self.assertEqual(connections['default'].execute_wrappers, [])

    def test_incoming_id_validation(self):
        valid = '12345678-1234-1234-1234-123456789abc'
        response, _ = self.capture(self.request(HTTP_X_REQUEST_ID=valid), lambda req: HttpResponse())
        self.assertEqual(response['X-Request-ID'], valid.replace('-', ''))
        for invalid in ('untrusted\nvalue', 'x' * 10000, 'not-a-uuid'):
            response, _ = self.capture(self.request(HTTP_X_REQUEST_ID=invalid), lambda req: HttpResponse())
            self.assertRegex(response['X-Request-ID'], r'^[0-9a-f]{32}$')

    def test_executemany_and_sql_errors_are_counted_without_consuming_parameters(self):
        counter = SQLCounter()
        params = iter([('private',)])
        execute = Mock(side_effect=DatabaseError('private'))
        with self.assertRaises(DatabaseError):
            counter(execute, 'private SQL', params, True, {})
        execute.assert_called_once_with('private SQL', params, True, {})
        self.assertEqual(next(params), ('private',))
        self.assertEqual((counter.count, counter.many_count, counter.error_count), (1, 1, 1))
        self.assertGreaterEqual(counter.duration_ms, 0)

    def test_counters_are_isolated_in_concurrent_request_threads(self):
        barrier = Barrier(2)

        def run(count):
            request = self.request()
            middleware = RequestObservabilityMiddleware(None)

            def view(req):
                barrier.wait(timeout=10)
                for _ in range(count):
                    self.execute_fake_sql()
                return HttpResponse()

            middleware.get_response = view
            middleware(request)
            return request._crm_diagnostics.sql.count, len(connections['default'].execute_wrappers)

        with patch('crmserver.observability.emit'), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, [2, 5]))
        self.assertEqual(results, [(2, 0), (5, 0)])

    def test_all_aliases_including_lazy_connections_are_wrapped(self):
        # Connection copies are not connected to PostgreSQL.
        first = connections['default'].copy(alias='first')
        second = connections['default'].copy(alias='second')

        def view(req):
            CursorWrapper(Mock(), first).execute('private')
            CursorWrapper(Mock(), second).executemany('private', [])
            return HttpResponse()

        with patch('crmserver.observability.connections.all', return_value=[first, second]):
            _, events = self.capture(self.request(), view)
        self.assertEqual(events[0]['sql_count'], 2)
        self.assertEqual(events[0]['sql_executemany_count'], 1)
        self.assertEqual(first.execute_wrappers, [])
        self.assertEqual(second.execute_wrappers, [])

    def test_sync_success_bytes_phases_and_stream_scope(self):
        request = self.request('sync-exchange', 'POST', CONTENT_LENGTH='123')

        def view(req):
            with sync_phase(req, 'input_validation_ms'):
                pass
            records = [{'deleted': False, 'fields': {'name': 'private'}},
                       {'deleted': True, 'uuid': 'private-record-id'}]
            sync_record_counts(req, 'incoming', records)
            sync_record_counts(req, 'outgoing', records)
            return HttpResponse(b'{}', content_type='application/json')

        _, events = self.capture(request, view)
        event = events[1]
        self.assertEqual(event['event'], 'sync_exchange')
        self.assertEqual(event['outcome'], 'success')
        self.assertEqual(event['request_declared_bytes'], 123)
        self.assertEqual(event['response_body_bytes'], 2)
        self.assertIn('input_validation_ms', event)
        self.assertEqual(event['incoming_records'], 2)
        self.assertEqual(event['outgoing_deletions'], 1)
        self.assertNotIn('private', json.dumps(events))
        # Iteration must remain the server's responsibility, outside request timing.
        def stream():
            raise AssertionError('Streaming body must not be consumed by diagnostics')
            yield b''
        _, events = self.capture(self.request(), lambda req: StreamingHttpResponse(stream()))
        self.assertEqual(events[0]['duration_scope'], 'stream_response_ready')

    def test_request_size_is_only_declared_and_disabled_counts_do_not_inspect_records(self):
        for value in ('', '-1', 'not-a-size', '1' * 21):
            self.assertIsNone(declared_request_bytes(self.request(CONTENT_LENGTH=value)))
        request = self.request()
        request._crm_diagnostics = Diagnostics(request)
        records = Mock()  # No sync enabled: the collection must not be touched.
        sync_record_counts(request, 'incoming', records)
        self.assertEqual(records.mock_calls, [])

    def test_business_exception_propagates_and_wrappers_are_removed(self):
        error = DatabaseError('sensitive database details')

        def view(req):
            self.execute_fake_sql()
            raise error

        middleware = RequestObservabilityMiddleware(None)
        def handler(req):
            middleware.process_view(req, view, (), {})
            return view(req)
        middleware.get_response = handler
        with patch('crmserver.observability.emit') as output:
            with self.assertRaises(DatabaseError) as caught:
                middleware(self.request('sync-exchange'))
        self.assertIs(caught.exception, error)
        event = output.call_args.args[0]
        self.assertEqual(event['outcome'], 'database_error')
        self.assertNotIn('sensitive', json.dumps(event))
        self.assertEqual(connections['default'].execute_wrappers, [])

    def test_atomic_exit_is_included_in_observed_hold_and_errors_propagate(self):
        request = self.request('sync-exchange')
        request._crm_diagnostics = Diagnostics(request)
        request._crm_diagnostics.sync = {}
        clock = [0.0]

        @observe_exchange
        def fake_atomic(req):
            clock[0] = 1.0
            sync_lock_acquired(req)
            try:
                clock[0] = 2.0
                raise ValidationError('private entity information')
            finally:
                # Simulate the atomic decorator finishing rollback after the body.
                clock[0] = 5.0

        for outer_atomic in (False, True):
            clock[0] = 0.0
            with patch('crmserver.observability.transaction.get_connection',
                       return_value=SimpleNamespace(in_atomic_block=outer_atomic)), patch(
                           'crmserver.observability.now', side_effect=lambda: clock[0]):
                with self.assertRaises(ValidationError):
                    fake_atomic(request)
            event = request._crm_diagnostics.sync
            self.assertEqual(event['outcome'], 'validation_error')
            self.assertEqual(event['lock_release_at_service_exit'], not outer_atomic)
            self.assertEqual(event['organization_lock_observed_hold_ms'], 4000.0)
            self.assertEqual(event['exchange_service_ms'], 5000.0)

    def test_diagnostic_failures_do_not_change_business_response(self):
        with patch('crmserver.observability.logger.info', side_effect=RuntimeError('broken sink')):
            middleware = RequestObservabilityMiddleware(lambda req: HttpResponse(status=201))
            self.assertEqual(middleware(self.request()).status_code, 201)
        with patch('crmserver.observability.connections.all', side_effect=RuntimeError('broken collector')):
            response, events = self.capture(self.request(), lambda req: HttpResponse(status=201))
        self.assertEqual(response.status_code, 201)
        self.assertFalse(events[0]['sql_collection_complete'])

    def test_sampling_exclusions_and_disable_switch(self):
        _, events = self.capture(self.request('healthz'), lambda req: HttpResponse())
        self.assertEqual(events, [])
        _, events = self.capture(self.request('healthz'), lambda req: HttpResponse(status=503))
        self.assertEqual(len(events), 1)
        with override_settings(OBSERVABILITY_HTTP_SAMPLE_RATE=0):
            _, events = self.capture(self.request('sync-exchange'), lambda req: HttpResponse())
        self.assertEqual([event['event'] for event in events], ['sync_exchange'])
        with override_settings(OBSERVABILITY_ENABLED=False):
            response, events = self.capture(self.request(), lambda req: HttpResponse())
        self.assertEqual(events, [])
        self.assertIn('X-Request-ID', response)

    def test_fractional_http_and_sql_sampling_are_independent(self):
        with override_settings(OBSERVABILITY_HTTP_SAMPLE_RATE=0.5, OBSERVABILITY_SQL_SAMPLE_RATE=0.5):
            with patch('crmserver.observability.random.random', side_effect=[0.4, 0.6]):
                _, events = self.capture(self.request(), lambda req: HttpResponse())
            self.assertFalse(events[0]['sql_sampled'])
            self.assertNotIn('sql_count', events[0])
            with patch('crmserver.observability.random.random', side_effect=[0.6, 0.4]):
                request = self.request()
                _, events = self.capture(request, lambda req: HttpResponse())
            self.assertEqual(events, [])
            self.assertIsNotNone(request._crm_diagnostics.sql)
            self.assertEqual(connections['default'].execute_wrappers, [])

    def test_sync_chain_adapted_to_async_keeps_thread_local_sql_scope(self):
        barrier = Barrier(2)

        async def run(count):
            # Model Django ASGI: sync middleware -> async handler -> sync ORM view,
            # with a separate thread-sensitive context for each request.
            async with ThreadSensitiveContext():
                request = self.request()

                def view():
                    barrier.wait(timeout=10)
                    for _ in range(count):
                        self.execute_fake_sql()
                    return HttpResponse()

                async def handler(req):
                    return await sync_to_async(view, thread_sensitive=True)()

                middleware = RequestObservabilityMiddleware(async_to_sync(handler))
                await sync_to_async(middleware, thread_sensitive=True)(request)
                return request._crm_diagnostics.sql.count

        async def scenario():
            return await asyncio.gather(run(2), run(5))

        with patch('crmserver.observability.emit'):
            # A real ASGI request starts in an event loop, not under a parent
            # AsyncToSync executor (which would serialize the two barrier participants).
            results = asyncio.run(scenario())
        self.assertEqual(results, [2, 5])

    def test_formatter_ignores_exception_message_and_arbitrary_log_fields(self):
        record = logging.LogRecord('crm.diagnostics', logging.INFO, '', 0, 'private', (), None)
        record.diagnostic_event = {'event': 'http_request', 'status_code': 200}
        record.authorization = 'private token'
        self.assertEqual(json.loads(EventFormatter().format(record)), record.diagnostic_event)
