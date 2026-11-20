"""Liveness only: no DB access and no internal details."""
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def healthz(request):
    response = JsonResponse({'status': 'ok'})
    response['Cache-Control'] = 'no-store'
    return response
