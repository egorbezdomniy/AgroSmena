"""Request-local diagnostics. Never retain SQL, payloads or exception details."""
import json
import logging
import random
import re
import time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError, connections, transaction


logger = logging.getLogger('crm.diagnostics')
METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT'}


class EventFormatter(logging.Formatter):
    def format(self, record):
        # Deliberately ignore record.msg, args, exc_info and arbitrary extra fields.
        return json.dumps(record.diagnostic_event, ensure_ascii=True, separators=(',', ':'))


def emit(event):
    try:
        logger.info('', extra={'diagnostic_event': event})
    except Exception:
        # Broken handlers must not change the result of an operation.
        pass


def now():
    try:
        return time.perf_counter()
    except Exception:
        return None


def elapsed(start):
    end = now()
    return round((end - start) * 1000, 3) if start is not None and end is not None else None


def request_id(request):
    value = request.META.get('HTTP_X_REQUEST_ID', '')
    # Only UUID-shaped identifiers; no free text, control characters or unbounded strings.
    if isinstance(value, str) and len(value) in (32, 36) and re.fullmatch(
            r'(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})', value):
        return uuid.UUID(value).hex
    return uuid.uuid4().hex


def route_name(request):
    match = getattr(request, 'resolver_match', None)
    if match is None:
        prefix = '/' + urlsplit(settings.STATIC_URL).path.lstrip('/')
        if prefix != '/' and request.path_info.startswith(prefix):
            return 'static'
        return 'unresolved'
    return match.view_name or match.route or 'unnamed'


def declared_request_bytes(request):
    value = request.META.get('CONTENT_LENGTH', '')
    if isinstance(value, str) and len(value) <= 20 and re.fullmatch(r'[0-9]+', value):
        return int(value)
    return None


def outcome_for_status(status):
    if status < 400:
        return 'success'
    return {400: 'validation_error', 401: 'authentication_error', 403: 'permission_denied',
            409: 'conflict', 429: 'throttled'}.get(status, 'server_error' if status >= 500 else 'client_error')


def exception_outcome(exc):
    # Import lazily: the formatter is constructed during Django logging setup.
    from rest_framework.exceptions import APIException, ParseError, ValidationError
    if isinstance(exc, DatabaseError):
        return 'database_error'
    if isinstance(exc, (ValidationError, ParseError)):
        return 'validation_error'
    if isinstance(exc, APIException):
        return outcome_for_status(exc.status_code)
    return 'other_error'


class SQLCounter:
    def __init__(self):
        self.count = 0
        self.many_count = 0
        self.error_count = 0
        self.duration_ms = 0.0
        self.complete = True

    def __call__(self, execute, sql, params, many, context):
        start = now()
        failed = True
        try:
            result = execute(sql, params, many, context)
            failed = False
            return result
        finally:
            try:
                end = now()
                duration = (end - start) * 1000 if start is not None and end is not None else None
                self.count += 1
                self.many_count += int(many)
                self.error_count += int(failed)
                if duration is None:
                    self.complete = False
                else:
                    self.duration_ms += duration
            except Exception:
                self.complete = False


class Diagnostics:
    def __init__(self, request):
        self.request_id = request_id(request)
        self.started = now()
        self.sql = None
        self.http_sampled = random.random() < settings.OBSERVABILITY_HTTP_SAMPLE_RATE
        self.sync = None
        self.lock_acquired = None

    @contextmanager
    def phase(self, name):
        start = now()
        try:
            yield
        finally:
            try:
                if self.sync is not None:
                    self.sync[name] = elapsed(start)
            except Exception:
                pass


def diagnostics_for(request):
    try:
        return getattr(request, '_crm_diagnostics', None)
    except Exception:
        return None


@contextmanager
def sync_phase(request, name):
    diagnostic = diagnostics_for(request)
    if diagnostic is None or diagnostic.sync is None:
        yield
    else:
        with diagnostic.phase(name):
            yield


def sync_values(request, **values):
    try:
        diagnostic = diagnostics_for(request)
        if diagnostic is not None and diagnostic.sync is not None:
            diagnostic.sync.update(values)
    except Exception:
        pass


def sync_record_counts(request, direction, records):
    try:
        diagnostic = diagnostics_for(request)
        if diagnostic is not None and diagnostic.sync is not None and direction in {'incoming', 'outgoing'}:
            diagnostic.sync.update({
                f'{direction}_records': len(records),
                f'{direction}_deletions': sum(record['deleted'] for record in records),
            })
    except Exception:
        pass


def sync_exception(request, exc):
    try:
        sync_values(request, outcome=exception_outcome(exc))
    except Exception:
        pass


def sync_lock_acquired(request):
    try:
        diagnostic = diagnostics_for(request)
        if diagnostic is not None and diagnostic.sync is not None:
            diagnostic.lock_acquired = now()
    except Exception:
        pass


def observe_exchange(function):
    """Wrap OUTSIDE the existing atomic decorator, including commit/rollback time."""
    @wraps(function)
    def observed(request, *args, **kwargs):
        diagnostic = diagnostics_for(request)
        if diagnostic is None or diagnostic.sync is None:
            return function(request, *args, **kwargs)
        try:
            outer_atomic = transaction.get_connection().in_atomic_block
        except Exception:
            outer_atomic = None
        with diagnostic.phase('exchange_service_ms'):
            try:
                return function(request, *args, **kwargs)
            except Exception as exc:
                sync_exception(request, exc)
                raise
            finally:
                try:
                    if diagnostic.lock_acquired is not None:
                        sync_values(request,
                            organization_lock_observed_hold_ms=elapsed(diagnostic.lock_acquired),
                            lock_release_at_service_exit=(not outer_atomic) if outer_atomic is not None else None)
                except Exception:
                    pass
    return observed


class RequestObservabilityMiddleware:
    # All current views are synchronous. Under ASGI Django adapts the whole sync
    # chain into the request's thread-sensitive context, including its ORM calls.
    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        try:
            diagnostic = diagnostics_for(request)
            if (diagnostic is not None and settings.OBSERVABILITY_ENABLED and settings.OBSERVABILITY_SYNC_ENABLED
                    and route_name(request) == 'sync-exchange'):
                diagnostic.sync = {}
        except Exception:
            pass

    def process_exception(self, request, exception):
        sync_exception(request, exception)
        # Let Django handle the business exception normally.
        return None

    def __call__(self, request):
        diagnostic = None
        stack = ExitStack()
        try:
            diagnostic = Diagnostics(request)
            request._crm_diagnostics = diagnostic
            request.request_id = diagnostic.request_id
            if (settings.OBSERVABILITY_ENABLED and settings.OBSERVABILITY_SQL_ENABLED
                    and random.random() < settings.OBSERVABILITY_SQL_SAMPLE_RATE):
                diagnostic.sql = SQLCounter()
                # Every configured alias, including connections first opened by the view.
                for connection in connections.all():
                    stack.enter_context(connection.execute_wrapper(diagnostic.sql))
        except Exception:
            if diagnostic is not None and diagnostic.sql is not None:
                diagnostic.sql.complete = False

        response = None
        try:
            response = self.get_response(request)
            return response
        except Exception as exc:
            sync_exception(request, exc)
            raise
        finally:
            try:
                stack.close()
            except Exception:
                if diagnostic is not None and diagnostic.sql is not None:
                    diagnostic.sql.complete = False
            if diagnostic is not None:
                try:
                    self.finish(request, response, diagnostic)
                except Exception:
                    pass

    def finish(self, request, response, diagnostic):
        if response is not None:
            response['X-Request-ID'] = diagnostic.request_id
        if not settings.OBSERVABILITY_ENABLED:
            return
        status = response.status_code if response is not None else 500
        streaming = bool(response is not None and response.streaming)
        base = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'request_id': diagnostic.request_id,
            'method': request.method if request.method in METHODS else 'OTHER',
            'route': route_name(request), 'status_code': status,
            'duration_ms': elapsed(diagnostic.started),
            'duration_scope': 'stream_response_ready' if streaming else 'response_ready',
            'sql_sampled': diagnostic.sql is not None,
        }
        if diagnostic.sql is not None:
            counter = diagnostic.sql
            base.update(sql_count=counter.count, sql_duration_ms=round(counter.duration_ms, 3),
                        sql_executemany_count=counter.many_count, sql_error_count=counter.error_count,
                        sql_collection_complete=counter.complete,
                        sql_sample_rate=settings.OBSERVABILITY_SQL_SAMPLE_RATE)
        if diagnostic.http_sampled and (status >= 400 or base['route'] not in settings.OBSERVABILITY_EXCLUDE_ROUTES):
            emit({**base, 'event': 'http_request', 'sample_rate': settings.OBSERVABILITY_HTTP_SAMPLE_RATE})
        if diagnostic.sync is not None:
            response_bytes = None
            if response is not None and not streaming:
                # Already rendered bytes, before any outer server/proxy encoding. Never re-render.
                response_bytes = len(response.content)
            emit({**base, 'event': 'sync_exchange',
                  'outcome': outcome_for_status(status), **diagnostic.sync,
                  'request_declared_bytes': declared_request_bytes(request),
                  'response_body_bytes': response_bytes})
