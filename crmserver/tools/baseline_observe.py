"""Low-frequency DB wait sampling, exclusively inside an owned baseline cluster."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=700, choices=range(1, 1201))
    parser.add_argument('--after-catalog', action='store_true', help='Wait at most 300s for sequential measurements to finish')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.after_catalog:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                results = json.loads((root / 'results.json').read_text(encoding='utf-8'))
                if any(row['scenario'] == 'catalog_filter' for row in results['results']):
                    break
                if (root / 'cleanup.json').exists():
                    return
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        else:
            raise TimeoutError('Sequential phase did not complete within observer wait budget')
    marker = json.loads((root / 'baseline-owner.json').read_text(encoding='utf-8'))
    if marker['purpose'] != 'agrosmena-synthetic-baseline-v1' or not (root / 'pgdata').is_dir():
        raise RuntimeError('Not a live owned synthetic cluster')
    for name in list(os.environ):
        if name.startswith('PG'):
            del os.environ[name]
    import psycopg
    with psycopg.connect(host='127.0.0.1', port=marker['port'], dbname='baseline_synthetic', user='stage1_test',
                         password='stage1-artificial-only', passfile=str(root / 'no-pgpass'),
                         connect_timeout=5, autocommit=True, options='-c statement_timeout=1000') as conn:
        directory = conn.execute('SHOW data_directory').fetchone()[0]
        if Path(directory).resolve() != (root / 'pgdata').resolve():
            raise RuntimeError('Cluster ownership check failed')
        start = time.monotonic()
        count = 0
        max_lock = 0
        with (root / 'db-observations.jsonl').open('w', encoding='utf-8', buffering=1) as output:
            while time.monotonic() - start < args.max_seconds:
                try:
                    row = conn.execute("""SELECT count(*) FILTER (WHERE wait_event_type='Lock'),
                        count(*) FILTER (WHERE state='active'), count(*)
                        FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()""").fetchone()
                except psycopg.Error:
                    break  # Owner stopped the disposable cluster; never reconnect elsewhere.
                count += 1
                max_lock = max(max_lock, row[0])
                output.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
                                         'lock_waiters': row[0], 'active': row[1], 'connections': row[2]}) + '\n')
                if count % 50 == 0:
                    try:
                        size = conn.execute('SELECT pg_database_size(current_database())').fetchone()[0]
                        wal = conn.execute('SELECT wal_bytes FROM pg_stat_wal').fetchone()[0]
                        (root / 'db-resource-latest.json').write_text(json.dumps({
                            'database_bytes': size, 'cluster_wal_generated_bytes': int(wal),
                            'sampled_lock_waiters_max': max_lock, 'samples': count,
                        }), encoding='utf-8')
                    except psycopg.Error:
                        break
                time.sleep(0.1)
        print(json.dumps({'db_samples': count, 'max_lock_waiters': max_lock}))


if __name__ == '__main__':
    main()
