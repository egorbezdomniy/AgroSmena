"""Opt-in end-to-end test against real Windows builds; never uses the user profile."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from tools.create_patch import create_patch
from updatekit.protocol import atomic_json, read_version
from updater import wait_for_process


@unittest.skipUnless(os.name == 'nt' and os.environ.get('AGROSMENA_TEST_BUILD'), 'Set AGROSMENA_TEST_BUILD to the onedir build')
class BuiltUpdateTests(unittest.TestCase):
    def test_real_updater_migration_restart_and_rollback(self):
        build = Path(os.environ['AGROSMENA_TEST_BUILD']).resolve()
        with tempfile.TemporaryDirectory(prefix='agrosmena-update-e2e-') as folder:
            base = Path(folder)
            old = base / 'old'
            shutil.copytree(build, old)
            new = base / 'new'
            shutil.copytree(old, new)
            version = read_version(old)
            atomic_json(new / 'version.json', {'version': '0.2.0'})
            (new / 'release-marker.txt').write_text('version 2')
            migration = new / '_internal/migrations/versions/0002_update_probe.py'
            migration.write_text("from alembic import op\nimport sqlalchemy as sa\nrevision='0002_probe'\ndown_revision='0001_baseline'\nbranch_labels=None\ndepends_on=None\ndef upgrade():\n    op.create_table('update_probe', sa.Column('id', sa.Integer, primary_key=True))\ndef downgrade():\n    op.drop_table('update_probe')\n")
            zip1 = base / 'one.zip'
            p1 = create_patch(old, new, version, '0.2.0', zip1)
            newer = base / 'newer'
            shutil.copytree(new, newer)
            atomic_json(newer / 'version.json', {'version': '0.3.0'})
            (newer / 'release-marker.txt').write_text('version 3')
            zip2 = base / 'two.zip'
            p2 = create_patch(new, newer, '0.2.0', '0.3.0', zip2)
            broken = base / 'broken'
            shutil.copytree(newer, broken)
            atomic_json(broken / 'version.json', {'version': '0.4.0'})
            (broken / '_internal/migrations/versions/0003_broken.py').write_text(
                "from alembic import op\nrevision='0003_broken'\ndown_revision='0002_probe'\nbranch_labels=None\ndepends_on=None\ndef upgrade():\n    op.execute('DROP TABLE update_probe')\n    raise RuntimeError('Deliberate migration failure')\ndef downgrade():\n    pass\n")
            zip3 = base / 'broken.zip'
            p3 = create_patch(newer, broken, '0.3.0', '0.4.0', zip3)
            for name, chain in [('single', [(p1, zip1)]), ('multi', [(p1, zip1), (p2, zip2)])]:
                with self.subTest(name=name):
                    install, data = base / name, base / (name + '-data')
                    shutil.copytree(old, install)
                    from app.core.database import Database
                    from app.models import Customer
                    database = Database(data / 'data/crm.db')
                    database.create_tables()
                    with database.session_factory.begin() as session:
                        session.add(Customer(name='Preserved update fixture', notes='Must survive migration and rollback'))
                    database.dispose()
                    code = self.run_updater(build, install, data, chain)
                    self.assertEqual(code, 0, self.logs(data))
                    self.assertEqual(read_version(install), chain[-1][0]['to_version'])
                    with closing(sqlite3.connect(data / 'data/crm.db')) as conn:
                        self.assertEqual(conn.execute('SELECT version_num FROM alembic_version').fetchone()[0], '0002_probe')
                        self.assertEqual(conn.execute('SELECT count(*) FROM update_probe').fetchone(), (0,))
                        self.assertEqual(conn.execute('SELECT name FROM customers').fetchall(), [('Preserved update fixture',)])
                    if name == 'multi':
                        code = self.run_updater(build, install, data, [(p3, zip3)])
                        self.assertEqual(code, 1)
                        self.assertEqual(read_version(install), '0.3.0')
                        self.assertFalse((install / '_internal/migrations/versions/0003_broken.py').exists())
                        with closing(sqlite3.connect(data / 'data/crm.db')) as conn:
                            self.assertEqual(conn.execute('SELECT count(*) FROM update_probe').fetchone(), (0,))
                            self.assertEqual(conn.execute('SELECT name FROM customers').fetchall(), [('Preserved update fixture',)])
                        result = json.loads((data / 'updates/last-result.json').read_text())
                        self.assertEqual(result['status'], 'rolled_back')

    def logs(self, data):
        return '\n'.join(p.read_text(errors='replace') for p in (data / 'logs').glob('*.log'))

    def run_updater(self, build, install, data, chain):
        cache = data / 'updates/downloads'
        cache.mkdir(parents=True, exist_ok=True)
        patches = []
        for meta, archive in chain:
            local = cache / archive.name
            shutil.copy2(archive, local)
            patches.append({**meta, 'path': str(local)})
        runner = data / 'updates/updater.exe'
        shutil.copy2(build / 'updater.exe', runner)
        plan = data / 'updates/test-plan.json'
        atomic_json(plan, {'install_root': str(install), 'data_root': str(data), 'patches': patches})
        env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'AGROSMENA_DATA_ROOT': str(data)}
        result = subprocess.run([str(runner), '--plan', str(plan)], env=env, timeout=180)
        if result.returncode == 0:
            updater_log = (data / 'logs/updater.log').read_text()
            pid = int(re.findall(r'CRM restart requested; pid=(\d+)', updater_log)[-1])
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    crm_log = data / 'logs/crm.log'
                    if crm_log.exists() and f'CRM ready; pid={pid}' in crm_log.read_text():
                        break
                    time.sleep(.1)
                else:
                    self.fail('Restarted CRM failed to become ready: ' + self.logs(data))
            finally:
                # Stop only the test CRM process whose PID was returned by this updater.
                stopped = subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=10)
                self.assertEqual(stopped.returncode, 0, stopped.stderr.decode(errors='replace'))
                wait_for_process(pid, timeout=10)
        return result.returncode
