"""Synthetic performance harness only. Reuses the stage-1 .env exclusion."""
import json
import os
from pathlib import Path

_root = Path(os.environ['STAGE1_VERIFY_ROOT']).resolve()
_owner = json.loads((_root / 'baseline-owner.json').read_text(encoding='utf-8'))
if _owner['purpose'] != 'agrosmena-synthetic-baseline-v1':
    raise RuntimeError('Missing baseline ownership marker')
os.environ['STAGE1_VERIFY_PGPORT'] = str(_owner['port'])
from .verification_settings import *  # noqa: F403,E402

DATABASES['default']['NAME'] = 'baseline_synthetic'  # noqa: F405
DATABASES['default']['OPTIONS']['options'] = (  # noqa: F405
    '-c statement_timeout=25000 -c lock_timeout=15000 -c idle_in_transaction_session_timeout=30000'
)
OBSERVABILITY_ENABLED = os.environ.get('BASELINE_DIAGNOSTICS', 'sql') != 'off'
OBSERVABILITY_SQL_ENABLED = os.environ.get('BASELINE_DIAGNOSTICS', 'sql') == 'sql'
OBSERVABILITY_SQL_SAMPLE_RATE = 1
OBSERVABILITY_HTTP_SAMPLE_RATE = 1
