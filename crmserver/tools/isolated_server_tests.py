"""Run selected server tests in a NEW owned PostgreSQL cluster; no benchmark seed."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from scaling_baseline import Experiment, PROJECT, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=600, choices=range(120, 901))
    parser.add_argument('labels', nargs='+')
    args = parser.parse_args()
    run = Experiment(args)  # Refuses existing output; inherited config is sanitized.
    try:
        run.watchdog.start()
        run.pg('initdb', '-D', run.root / 'pgdata', '-U', 'stage1_test', '--auth=trust',
               '--encoding=UTF8', '--locale=C').check_returncode()
        run.pg('pg_ctl', '-D', run.root / 'pgdata', '-l', run.root / 'postgres.log', '-o',
               f'-h 127.0.0.1 -p {run.pgport} -c max_connections=20', '-w', 'start').check_returncode()
        run.pg_started = True
        for key in list(os.environ):
            if key.startswith('PG'):
                del os.environ[key]
        import psycopg
        with psycopg.connect(host='127.0.0.1', port=run.pgport, dbname='postgres', user='stage1_test',
                password='stage1-artificial-only', passfile=str(run.root / 'no-pgpass'),
                sslmode='disable', connect_timeout=5) as conn:
            directory = conn.execute('SHOW data_directory').fetchone()[0]
            if Path(directory).resolve() != (run.root / 'pgdata').resolve():
                raise RuntimeError('Unexpected PostgreSQL owner')
        env = {**run.env, 'DJANGO_SETTINGS_MODULE': 'crmserver.verification_settings',
               'STAGE1_VERIFY_PGPORT': str(run.pgport)}
        write_json(run.root / 'test-config.json', {'labels': args.labels, 'settings': env['DJANGO_SETTINGS_MODULE'],
                   'port': run.pgport, 'test_database': 'test_stage1_disposable', 'dotenv': False})
        for name, command, limit in [
            ('collectstatic', ['collectstatic', '--noinput', '--verbosity', '0'], 60),
            ('tests', ['test', *args.labels, '--noinput', '--verbosity', '2'], 240),
        ]:
            run.guard()
            with (run.root / f'{name}.log').open('w', encoding='utf-8') as output:
                completed = subprocess.run([sys.executable, str(PROJECT / 'manage.py'), *command],
                    cwd=PROJECT, env=env, stdout=output, stderr=subprocess.STDOUT,
                    timeout=limit, creationflags=run.creationflags)
            print(f'{name}: exit={completed.returncode}; {run.root / (name + ".log")}', flush=True)
            completed.check_returncode()
    except BaseException as exc:
        run.unfinished.append({'error_type': type(exc).__name__, 'reason': str(exc)})
        raise
    finally:
        run.finish()


if __name__ == '__main__':
    main()
