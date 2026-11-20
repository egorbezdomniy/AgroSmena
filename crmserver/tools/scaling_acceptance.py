"""Small final acceptance, reusing the owned baseline harness and its limits.

No profiles, A/B, EXPLAIN, new server mode or timeout changes. Only small org,
1/2 clients, full unchanged packet and 1% customer edits. Fixed 6 samples/group.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import subprocess
import sys
from pathlib import Path

from scaling_baseline import Experiment, PROJECT, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=300, choices=range(120, 601))
    args = parser.parse_args()
    args.anchor_date = '2026-10-16'
    run = Experiment(args)
    try:
        run.setup()  # Existing deterministic fixtures; only small is exercised.
        for name, command, env in (
            ('deploy-check', [str(PROJECT / 'manage.py'), 'check', '--deploy'], run.env),
            ('http-static-smoke', [str(PROJECT / 'tools/verify_stage1_http.py')],
             {**run.env, 'DJANGO_SETTINGS_MODULE': 'crmserver.verification_settings',
              'STAGE1_VERIFY_PGPORT': str(run.pgport)}),
            ('integrity-clean-seed', [str(PROJECT / 'manage.py'), 'check_crm_integrity'], run.env),
        ):
            run.guard()
            with (run.root / f'{name}.log').open('w', encoding='utf-8') as output:
                result = subprocess.run([sys.executable, *command], cwd=PROJECT, env=env,
                    stdout=output, stderr=subprocess.STDOUT, timeout=60, creationflags=run.creationflags)
            result.check_returncode()
        run.start_server('sql')
        org = next(row for row in run.data['organizations'] if row['label'] == 'small')
        for clients in (1, 2):
            initial = run.http(org, '/api/sync/exchange/', {'organization': org['uuid'], 'changes': []}, retain=True)
            if initial['status'] != 200 or len(initial['body']['changes']) != org['admin_snapshot_records']:
                raise RuntimeError('Cannot prepare full acceptance packet')
            snapshot = {'organization': org['uuid'], 'changes': initial['body']['changes']}
            for changed in (False, True):
                def operation(i):
                    packet = deepcopy(snapshot) if changed else snapshot
                    if changed:
                        customers = [row for row in packet['changes']
                                     if row['entity'] == 'customers' and not row['deleted']][:org['live'] // 100]
                        stamp = datetime.now(timezone.utc).isoformat()
                        for row in customers:
                            row['updated_at'] = stamp
                            row['fields']['notes'] = f'Synthetic acceptance {clients}/{i}'
                    row = run.http(org, '/api/sync/exchange/', packet)
                    if i < 0:
                        with (run.root / 'warmups.jsonl').open('a', encoding='utf-8') as target:
                            target.write(json.dumps({'parallel': clients, 'changed': changed, **row}) + '\n')
                        if row['status'] != 200:
                            raise RuntimeError('Acceptance warm-up failed; see warmups.jsonl')
                    return row
                run.group(org, 'sync_changed_1pct' if changed else 'sync_unchanged', operation,
                          repeats=6, parallel=clients, warmup=2, category='acceptance')
        write_json(run.root / 'acceptance-scope.json', {
            'product_capacity_claim': False, 'organization': org, 'measured_attempts': 24,
            'warmups': 8, 'client_timeout_seconds': 45, 'desktop_client_timeout_seconds': 30,
            'diagnostics': 'HTTP + sync + SQL at sample rate 1',
            'concurrent_changes': 'Same 10 customers; timestamp conflict rules still apply',
        })
    except BaseException as exc:
        run.unfinished.append({'error_type': type(exc).__name__, 'reason': str(exc)})
        raise
    finally:
        run.finish()


if __name__ == '__main__':
    main()
