"""Run real authenticated HTTP CRUD against an isolated PostgreSQL test database."""
from pathlib import Path
import subprocess
import sys


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    raise SystemExit(subprocess.call(
        [sys.executable, 'manage.py', 'test', 'accounts.test_http', '--noinput', '-v', '2'], cwd=root))
