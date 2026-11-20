"""Synthetic endpoints used only by stage-1 verification tests."""
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie

from crmserver.health import healthz


def detail(request, pk):
    return JsonResponse({'private': 'stage1-private-response'})


def failing(request):
    raise ValueError('stage1-private-exception')


def sql_view(request, fail=False, count=1):
    with connection.cursor() as cursor:
        for _ in range(count):
            cursor.execute('SELECT 1 / 0' if fail else 'SELECT %s, pg_sleep(0.02)',
                           ['stage1-private-sql'] if not fail else None)
            cursor.fetchall()
    return HttpResponse()


@ensure_csrf_cookie
def cookies(request):
    request.session['marker'] = 'stage1-private-session'
    return HttpResponse()


urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('diagnostic/<int:pk>/', detail, name='diagnostic-detail'),
    path('failure/', failing, name='diagnostic-failure'),
    path('sql/', sql_view, name='diagnostic-sql'),
    path('sql/<int:count>/', sql_view, name='diagnostic-sql-count'),
    path('sql-error/', sql_view, {'fail': True}, name='diagnostic-db-error'),
    path('cookies/', cookies, name='diagnostic-cookies'),
]
