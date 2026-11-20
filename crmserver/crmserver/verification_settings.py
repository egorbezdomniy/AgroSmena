"""Synthetic stage-1 verification only. Never import the developer's .env.

Requires a temporary artifact directory, and an explicit loopback PostgreSQL port
only when running DB tests. No values are read from a deployed configuration.
"""
import os
from pathlib import Path

_root = Path(os.environ['STAGE1_VERIFY_ROOT']).resolve()
_port = int(os.environ.get('STAGE1_VERIFY_PGPORT', '1'))
if not 1 <= _port <= 65535:
    raise ValueError('Invalid STAGE1_VERIFY_PGPORT')

# Clear inherited application/database configuration before importing base settings.
for _key in list(os.environ):
    if _key != 'DJANGO_SETTINGS_MODULE' and _key.startswith(
            ('DJANGO_', 'POSTGRES_', 'OBSERVABILITY_', 'APP_UPDATE_', 'APP_INSTALLER_', 'PG')):
        del os.environ[_key]
os.environ.update({
    'DJANGO_LOAD_DOTENV': 'false',
    'DJANGO_SECRET_KEY': 'stage1-artificial-test-key-0123456789-abcdefghijklmnopqrstuvwxyz',
    'DJANGO_DEBUG': 'false',
    'DJANGO_ALLOWED_HOSTS': 'testserver,localhost,127.0.0.1',
    'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': str(_port),
    'POSTGRES_USER': 'stage1_test', 'POSTGRES_PASSWORD': 'stage1-artificial-only',
    'POSTGRES_DB': 'postgres', 'POSTGRES_SSLMODE': 'disable',
})

from .settings import *  # noqa: F403,E402

STATIC_ROOT = _root / 'static'
MEDIA_ROOT = _root / 'media'
APP_UPDATE_CATALOG = str(_root / 'absent-catalog.json')
APP_INSTALLER_DIR = str(_root / 'installers')
DATABASES['default']['TEST'] = {'NAME': 'test_stage1_disposable'}  # noqa: F405
# Tests that deliberately use cleartext HTTP override secure cookies explicitly.
# Production defaults stay in force for the rest of the suite.
os.environ['AGROSMENA_DATA_ROOT'] = str(_root / 'desktop-test-profile')
