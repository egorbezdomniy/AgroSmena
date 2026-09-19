"""Optional isolated PostgreSQL cluster for local development, never a Windows service."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.postgres'
ENV = ROOT / '.env'


def run(binary_dir, executable, *args, check=True):
    return subprocess.run(
        [str(binary_dir / (executable + ('.exe' if os.name == 'nt' else ''))), *args],
        check=check,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'start', 'stop', 'status'])
    parser.add_argument('--bin', type=Path, help='PostgreSQL 14+ bin directory')
    parser.add_argument('--port', type=int, default=55432)
    args = parser.parse_args()
    config = dotenv_values(ENV) if ENV.exists() else {}
    binary_dir = args.bin or (Path(config['POSTGRES_BIN']) if config.get('POSTGRES_BIN') else None)
    if binary_dir is None:
        parser.error('Provide --bin with the PostgreSQL bin directory.')
    port = int(config.get('POSTGRES_PORT', args.port))
    if args.action in {'start', 'status'}:
        status = run(binary_dir, 'pg_ctl', '-D', str(DATA), 'status', check=False)
        if args.action == 'status':
            raise SystemExit(status.returncode)
        if status.returncode == 0:
            print(f'CRM PostgreSQL is already running on 127.0.0.1:{port}')
            return
        if status.returncode != 3:
            parser.error('Cannot determine cluster status; start was not attempted.')
    if args.action == 'init':
        if ENV.exists() or DATA.exists():
            parser.error('.env or .postgres already exists; nothing was overwritten.')
        password = secrets.token_urlsafe(32)
        with tempfile.TemporaryDirectory(prefix='crm-pg-init-') as temporary:
            password_file = Path(temporary) / 'password'
            password_file.write_text(password, encoding='utf-8')
            run(binary_dir, 'initdb', '-D', str(DATA), '-U', 'crm_dev',
                '--pwfile', str(password_file), '--auth=scram-sha-256',
                '--encoding=UTF8', '--locale=C')
        # These are newly generated local secrets; never print or commit them.
        ENV.write_text(
            f'DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}\n'
            'DJANGO_DEBUG=True\nDJANGO_ALLOWED_HOSTS=127.0.0.1,localhost\n'
            f'POSTGRES_DB=crmserver\nPOSTGRES_USER=crm_dev\nPOSTGRES_PASSWORD={password}\n'
            f'POSTGRES_HOST=127.0.0.1\nPOSTGRES_PORT={port}\n'
            f"POSTGRES_BIN='{binary_dir.as_posix()}'\n",
            encoding='utf-8',
        )
        config = dotenv_values(ENV)
    if args.action in {'init', 'start'}:
        # Loopback only; do not use an existing service or its data directory.
        run(binary_dir, 'pg_ctl', '-D', str(DATA), '-l', str(DATA / 'server.log'),
            '-o', f'-h 127.0.0.1 -p {port}', '-w', 'start')
        if args.action == 'init':
            with psycopg.connect(host='127.0.0.1', port=port, user='crm_dev',
                                 password=config['POSTGRES_PASSWORD'], dbname='postgres',
                                 autocommit=True) as connection:
                connection.execute('CREATE DATABASE crmserver')
        print(f'CRM PostgreSQL started on 127.0.0.1:{port}')
    else:
        run(binary_dir, 'pg_ctl', '-D', str(DATA), '-m', 'fast', '-w', 'stop')


if __name__ == '__main__':
    main()
