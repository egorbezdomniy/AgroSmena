import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.services.update_service import HTTPSRedirects, UpdateService
from tools.create_patch import create_patch
from updatekit.engine import UpdateTransaction, copy_atomic
from updatekit.locking import AppLock
from updatekit.protocol import (atomic_json, https_url, inspect_patch, patch_chain, read_version,
                                safe_path, sha256, version_key)
from updater import wait_for_process


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'installed'
        self.data = self.base / 'profile'
        self.root.mkdir()
        self.data.mkdir()
        self.build(self.root, '0.1.0', {'app.txt': b'old', 'remove.txt': b'delete me'})
        db = self.data / 'data' / 'crm.db'
        db.parent.mkdir()
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('CREATE TABLE personal (name TEXT)')
            conn.execute("INSERT INTO personal VALUES ('keep me')")
        self.tx = UpdateTransaction(self.root, self.data)

    def build(self, root, version, files):
        root.mkdir(exist_ok=True)
        atomic_json(root / 'version.json', {'version': version})
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def make_patch(self, old=None, version='0.2.0', files=None):
        old = old or self.root
        new = self.base / version
        self.build(new, version, files or {'app.txt': b'new', 'sub/added.txt': b'added'})
        output = self.base / f'{read_version(old)}-{version}.zip'
        meta = create_patch(old, new, read_version(old), version, output)
        return {**meta, 'url': 'https://updates.example.test/' + output.name, 'path': str(output)}, new

    def assert_original(self):
        self.assertEqual(read_version(self.root), '0.1.0')
        self.assertEqual((self.root / 'app.txt').read_bytes(), b'old')
        self.assertTrue((self.root / 'remove.txt').exists())
        self.assertFalse((self.root / 'sub' / 'added.txt').exists())
        with closing(sqlite3.connect(self.tx.db)) as conn:
            self.assertEqual(conn.execute('SELECT name FROM personal').fetchall(), [('keep me',)])

    def test_single_patch_add_replace_delete_and_data(self):
        info, _ = self.make_patch()
        self.tx.apply([info], lambda: None)
        self.assertEqual(read_version(self.root), '0.2.0')
        self.assertEqual((self.root / 'app.txt').read_bytes(), b'new')
        self.assertFalse((self.root / 'remove.txt').exists())
        self.assertEqual((self.root / 'sub/added.txt').read_bytes(), b'added')
        self.assertFalse(self.tx.pending())
        self.assertEqual(json.loads((self.data / 'updates/last-result.json').read_text())['status'], 'installed')

    def test_multiple_patches(self):
        first, new = self.make_patch()
        second, _ = self.make_patch(new, '0.3.0', {'app.txt': b'third', 'other.txt': b'other'})
        catalog = {'latest_version': '0.3.0', 'patches': [second, first]}
        self.assertEqual(patch_chain('0.1.0', catalog), [first, second])
        self.tx.apply(patch_chain('0.1.0', catalog), lambda: None)
        self.assertEqual(read_version(self.root), '0.3.0')
        self.assertEqual((self.root / 'app.txt').read_bytes(), b'third')
        self.assertFalse((self.root / 'sub/added.txt').exists())

    def test_corrupt_archive(self):
        info, _ = self.make_patch()
        Path(info['path']).write_bytes(b'not a zip')
        info['sha256'] = sha256(info['path'])
        with self.assertRaises(zipfile.BadZipFile):
            self.tx.apply([info], lambda: None)
        self.assert_original()

    def test_wrong_archive_hash(self):
        info, _ = self.make_patch()
        info['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.tx.apply([info], lambda: None)
        self.assert_original()

    def test_payload_hash_and_manifest_tampering(self):
        info, _ = self.make_patch()
        with zipfile.ZipFile(info['path']) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        for mode in ['payload', 'traversal', 'duplicate', 'version']:
            with self.subTest(mode=mode):
                contents = dict(original)
                manifest = json.loads(contents['manifest.json'])
                if mode == 'payload':
                    contents['app.txt'] = b'tampered'
                elif mode == 'traversal':
                    manifest['files'].append({'path': '../outside.txt', 'action': 'add', 'sha256': 'a' * 64})
                elif mode == 'duplicate':
                    manifest['files'].append(dict(manifest['files'][0]))
                else:
                    manifest['to_version'] = '0.9.0'
                contents['manifest.json'] = json.dumps(manifest).encode()
                output = self.base / (mode + '.zip')
                with zipfile.ZipFile(output, 'w') as archive:
                    for name, content in contents.items():
                        archive.writestr(name, content)
                bad = {**info, 'path': str(output), 'sha256': sha256(output)}
                with self.assertRaises(ValueError):
                    self.tx.apply([bad], lambda: None)
                self.assert_original()

    def test_file_replace_failure_rolls_back(self):
        info, _ = self.make_patch()
        failed = False

        def fail_once(source, target):
            nonlocal failed
            if Path(target) == self.root / 'sub/added.txt' and not failed:
                failed = True
                raise PermissionError('File locked by another program')
            copy_atomic(source, target)

        with patch('updatekit.engine.copy_atomic', side_effect=fail_once):
            with self.assertRaises(PermissionError):
                self.tx.apply([info], lambda: None)
        self.assert_original()
        self.assertFalse(self.tx.pending())

    def test_failed_migration_restores_database_and_files(self):
        info, _ = self.make_patch()

        def broken_migration():
            with closing(sqlite3.connect(self.tx.db)) as conn, conn:
                conn.execute('DROP TABLE personal')
                conn.execute('CREATE TABLE broken (id INTEGER)')
            raise RuntimeError('Migration failed after committed DDL')

        with self.assertRaises(RuntimeError):
            self.tx.apply([info], broken_migration)
        self.assert_original()
        with closing(sqlite3.connect(self.tx.db)) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='broken'").fetchone())

    @unittest.skipUnless(os.name == 'nt', 'Windows file locking')
    def test_actual_windows_locked_file(self):
        info, _ = self.make_patch()
        with (self.root / 'remove.txt').open('rb'):
            with self.assertRaises(PermissionError):
                self.tx.apply([info], lambda: None)
        self.assert_original()
        self.assertFalse(self.tx.pending())

    def test_interruption_recovered_from_journal(self):
        info, _ = self.make_patch()
        def interrupted():
            raise SystemExit('Simulated updater termination')
        with self.assertRaises(SystemExit):
            self.tx.apply([info], interrupted)
        self.assertTrue(self.tx.pending())
        UpdateTransaction(self.root, self.data).rollback()
        self.assert_original()

    def test_corrupted_backup_fails_closed(self):
        info, _ = self.make_patch()
        with self.assertRaises(SystemExit):
            self.tx.apply([info], lambda: sys.exit(1))
        journal = json.loads(self.tx.journal_path.read_text())
        (Path(journal['backup']) / 'files/app.txt').write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):
            self.tx.rollback()
        self.assertTrue(self.tx.pending())

    def test_original_file_mismatch(self):
        info, _ = self.make_patch()
        (self.root / 'app.txt').write_bytes(b'user edit')
        with self.assertRaises(ValueError):
            self.tx.apply([info], lambda: None)
        self.assertFalse(self.tx.pending())
        self.assertEqual((self.root / 'app.txt').read_bytes(), b'user edit')

    def test_insufficient_disk_space_leaves_installation_intact(self):
        from types import SimpleNamespace
        info, _ = self.make_patch()
        with patch('updatekit.engine.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaises(RuntimeError):
                self.tx.apply([info], lambda: None)
        self.assert_original()
        self.assertFalse(self.tx.pending())

    def test_semver(self):
        versions = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0', '1.2.0', '1.10.0']
        self.assertEqual(sorted(versions, key=version_key), versions)
        self.assertEqual(version_key('1.0.0+abc'), version_key('1.0.0+xyz'))
        for value in ['01.0.0', '1.0', '1.0.0-01', 'v1.0.0']:
            with self.assertRaises(ValueError):
                version_key(value)

    def test_no_route_no_downgrade_and_https_only(self):
        info, _ = self.make_patch()
        with self.assertRaises(ValueError):
            patch_chain('0.0.1', {'latest_version': '0.2.0', 'patches': [info]})
        self.assertEqual(patch_chain('0.3.0', {'latest_version': '0.2.0', 'patches': [info]}), [])
        for url in ['http://localhost/p.zip', 'file:///patch.zip', 'https://user:pass@example.org/a']:
            with self.assertRaises(ValueError):
                https_url(url)
        with self.assertRaises(ValueError):
            HTTPSRedirects().redirect_request(None, None, 302, '', {}, 'http://example.org/patch.zip')

    def test_traversal_and_user_data_paths(self):
        for value in ['../file', '/file', 'C:/file', 'a\\b', 'a/../b', 'data/crm.db', '_internal/data/crm.db',
                      'logs/log.txt', 'version.json', 'NUL', 'foo:bar', 'x./a', 'a//b', 'settings/token.json']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_path(value)

    def test_download_progress_and_cache(self):
        info, _ = self.make_patch()
        body = Path(info['path']).read_bytes()
        service = UpdateService(self.root, self.data)
        response = io.BytesIO(body)
        response.headers = {'Content-Length': str(len(body))}
        progress = []
        with patch.object(service, '_open', return_value=response):
            downloaded = service.download([info], lambda value, text: progress.append(value))
        self.assertEqual(progress[-1], 100)
        self.assertEqual(sha256(downloaded[0]['path']), info['sha256'])
        with patch.object(service, '_open', side_effect=AssertionError('Cache should be used')):
            service.download([info])

    def test_app_lock_and_wait_for_exit(self):
        with AppLock(self.data):
            with self.assertRaises(RuntimeError):
                with AppLock(self.data):
                    pass
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.3)'])
        wait_for_process(process.pid, timeout=5)
        self.assertEqual(process.wait(timeout=2), 0)

    def test_alembic_new_and_legacy_sqlite(self):
        from app.core.database import Database
        from app.models import Base, Customer
        for legacy in (False, True):
            db = Database(self.base / f'migration-{legacy}.db')
            try:
                if legacy:
                    Base.metadata.create_all(db.engine)
                    with db.session_factory.begin() as session:
                        session.add(Customer(name='Existing customer'))
                db.create_tables()
                db.create_tables()
                with db.engine.connect() as conn:
                    self.assertEqual(conn.exec_driver_sql('SELECT version_num FROM alembic_version').scalar(), '0001_baseline')
                    self.assertEqual(conn.exec_driver_sql('PRAGMA integrity_check').scalar(), 'ok')
                if legacy:
                    with db.session_factory() as session:
                        self.assertEqual(session.query(Customer).one().name, 'Existing customer')
            finally:
                db.dispose()


if __name__ == '__main__':
    unittest.main()
