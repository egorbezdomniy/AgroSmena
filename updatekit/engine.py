"""Crash-recoverable file transaction. Only imported by the external updater."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

from updatekit.protocol import atomic_json, inspect_patch, read_version, sha256, target_path


def copy_atomic(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.update-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as output, open(source, 'rb') as stream:
            shutil.copyfileobj(stream, output, length=1024**2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def snapshot_database(source, destination):
    with closing(sqlite3.connect(source)) as old, closing(sqlite3.connect(destination)) as backup:
        old.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RuntimeError('SQLite backup integrity check failed')


class UpdateTransaction:
    def __init__(self, install_root, data_root):
        self.root = Path(install_root).resolve()
        self.data = Path(data_root).resolve()
        if self.root == self.data or self.data.is_relative_to(self.root) or self.root.is_relative_to(self.data):
            raise ValueError('Installation and user data must be separate directories')
        self.state_dir = self.data / 'updates'
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.state_dir / 'transaction.json'
        self.db = self.data / 'data' / 'crm.db'

    def pending(self):
        return self.journal_path.exists()

    def _save(self, journal):
        atomic_json(self.journal_path, journal)

    def _finish(self, journal, status, error=''):
        atomic_json(self.state_dir / 'last-result.json', {
            'status': status, 'version': read_version(self.root), 'error': error,
            'backup': journal['backup'],
        })
        self.journal_path.unlink()

    def rollback(self, error='Interrupted update recovered'):
        journal = json.loads(self.journal_path.read_text(encoding='utf-8'))
        if journal['root'] != str(self.root):
            raise RuntimeError('Journal belongs to a different installation')
        backup = Path(journal['backup']).resolve()
        if not backup.is_relative_to(self.state_dir / 'backups'):
            raise RuntimeError('Unsafe backup location')
        # Verify every backup before restoring anything. A failed rollback keeps its journal.
        for relative, entry in journal['originals'].items():
            target_path(self.root, relative)
            if entry is not None and sha256(backup / 'files' / relative) != entry:
                raise RuntimeError(f'Corrupted rollback backup: {relative}')
        if sha256(backup / 'version.json') != journal['version_hash']:
            raise RuntimeError('Corrupted version backup')
        if journal['db_existed'] and sha256(backup / 'crm.db') != journal['db_hash']:
            raise RuntimeError('Corrupted database backup')
        for relative, entry in journal['originals'].items():
            target = target_path(self.root, relative)
            if entry is None:
                target.unlink(missing_ok=True)
            elif not target.exists() or sha256(target) != entry:
                copy_atomic(backup / 'files' / relative, target)
        # No CRM process can write while the updater owns AppLock.
        if journal['db_existed']:
            copy_atomic(backup / 'crm.db', self.db)
        else:
            self.db.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(self.db) + suffix).unlink(missing_ok=True)
        copy_atomic(backup / 'version.json', self.root / 'version.json')
        self._finish(journal, 'rolled_back', error)

    def apply(self, patches, verify):
        if self.pending():
            raise RuntimeError('Unfinished transaction requires recovery')
        if not patches:
            raise ValueError('Empty patch chain')
        current = read_version(self.root)
        manifests, virtual = [], {}
        for patch in patches:
            if patch['from_version'] != current:
                raise ValueError('Patch chain does not match installed version')
            manifest = inspect_patch(patch['path'], patch)
            for entry in manifest['files']:
                relative = entry['path']
                target = target_path(self.root, relative)
                if target.exists() and not target.is_file():
                    raise ValueError(f'File expected: {relative}')
                if relative not in virtual:
                    virtual[relative] = sha256(target) if target.exists() else None
                before = virtual[relative]
                if entry['action'] == 'add':
                    if before is not None:
                        raise ValueError(f'Added file already exists: {relative}')
                elif before != entry['old_sha256']:
                    raise ValueError(f'Installed file differs from base build: {relative}')
                virtual[relative] = None if entry['action'] == 'delete' else entry['sha256']
            manifests.append(manifest)
            current = patch['to_version']
        # Use UNCOMPRESSED sizes, including temporary copies and rollback space.
        payload_bytes, largest = 0, 0
        for patch in patches:
            with zipfile.ZipFile(patch['path']) as archive:
                sizes = [info.file_size for info in archive.infolist()]
                payload_bytes += sum(sizes)
                largest = max(largest, max(sizes, default=0))
        originals_bytes = sum(target_path(self.root, p).stat().st_size for p in virtual
                              if target_path(self.root, p).exists())
        db_bytes = self.db.stat().st_size if self.db.exists() else 0
        state_needed = originals_bytes + db_bytes * 2 + largest + 64 * 1024**2
        install_needed = payload_bytes + largest + 64 * 1024**2
        if self.root.anchor.casefold() == self.data.anchor.casefold():
            enough = shutil.disk_usage(self.state_dir).free >= state_needed + install_needed
        else:
            enough = (shutil.disk_usage(self.state_dir).free >= state_needed and
                      shutil.disk_usage(self.root).free >= install_needed)
        if not enough:
            raise RuntimeError('Недостаточно места для распаковки, резервной копии и отката.')
        backup = self.state_dir / 'backups' / uuid.uuid4().hex
        backup.mkdir(parents=True)
        originals = {}
        for relative in virtual:
            target = target_path(self.root, relative)
            originals[relative] = sha256(target) if target.exists() else None
            if target.exists():
                copy_atomic(target, backup / 'files' / relative)
        copy_atomic(self.root / 'version.json', backup / 'version.json')
        db_existed = self.db.exists()
        if db_existed:
            snapshot_database(self.db, backup / 'crm.db')
        journal = {'root': str(self.root), 'backup': str(backup), 'originals': originals,
                   'probe_token': uuid.uuid4().hex,
                   'version_hash': sha256(backup / 'version.json'), 'db_existed': db_existed,
                   'db_hash': sha256(backup / 'crm.db') if db_existed else None,
                   'target_version': current, 'phase': 'applying'}
        self._save(journal)  # Durable backup/journal precede every installation mutation.
        try:
            for patch, manifest in zip(patches, manifests):
                with zipfile.ZipFile(patch['path']) as archive:
                    for entry in manifest['files']:
                        target = target_path(self.root, entry['path'])
                        if entry['action'] == 'delete':
                            target.unlink()
                        else:
                            with tempfile.TemporaryDirectory(dir=self.state_dir) as staging:
                                payload = Path(staging) / 'payload'
                                with archive.open(entry['path']) as stream, payload.open('wb') as output:
                                    shutil.copyfileobj(stream, output, length=1024**2)
                                if sha256(payload) != entry['sha256']:
                                    raise ValueError('Payload changed after validation')
                                copy_atomic(payload, target)
                atomic_json(self.root / 'version.json', {'version': patch['to_version']})
            for relative, expected in virtual.items():
                target = target_path(self.root, relative)
                if (sha256(target) if target.exists() else None) != expected:
                    raise RuntimeError(f'Final file verification failed: {relative}')
            journal['phase'] = 'verifying'
            self._save(journal)
            verify()  # Separate new-version process: Alembic upgrade + UI startup probe.
        except Exception as error:
            self.rollback(str(error))
            raise
        self._finish(journal, 'installed')
