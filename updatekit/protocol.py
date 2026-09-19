from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from collections import deque
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

SEMVER = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')
HASH = re.compile(r'^[a-f0-9]{64}$')
MAX_ARCHIVE = 2 * 1024**3
MAX_EXPANDED = 8 * 1024**3
MAX_FILES = 30000
PROTECTED = {'data', 'logs', 'settings', 'updates', 'backups', '.git', '.venv', '__pycache__'}


def version_key(value):
    match = SEMVER.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError(f'Invalid SemVer: {value!r}')
    major, minor, patch, pre, _ = match.groups()
    parts = []
    for part in pre.split('.') if pre else []:
        if part.isdigit() and len(part) > 1 and part[0] == '0':
            raise ValueError('Leading zero in SemVer prerelease')
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return int(major), int(minor), int(patch), pre is None, tuple(parts)


def https_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Обновления доступны только по HTTPS без пароля в URL.')
    return value


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.update-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_version(root):
    value = json.loads((Path(root) / 'version.json').read_text(encoding='utf-8'))['version']
    version_key(value)
    return value


def safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise ValueError(f'Unsafe patch path: {value!r}')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in parts):
        raise ValueError(f'Unsafe patch path: {value}')
    for part in parts:
        if any(ord(c) < 32 or c in '<>"|?*' for c in part) or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I):
            raise ValueError(f'Unsafe Windows path: {value}')
    lower = value.casefold()
    if any(p.casefold() in PROTECTED for p in parts) or lower.endswith(('.db', '.db-wal', '.db-shm', '.db-journal', '.sqlite', '.sqlite3', '.log')) or lower in {'version.json', 'uninstall.exe', 'manifest.json', '.env'}:
        raise ValueError(f'User data / reserved path in patch: {value}')
    return value


def target_path(root, relative):
    root = Path(root).resolve()
    candidate = root / safe_path(relative)
    for path in [candidate, *candidate.parents]:
        if path == root:
            break
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError(f'Link in patch destination: {relative}')
    if not candidate.resolve().is_relative_to(root):
        raise ValueError('Patch escapes installation directory')
    return candidate


def validate_catalog(catalog):
    latest = version_key(catalog['latest_version'])
    if type(catalog.get('mandatory', False)) is not bool or not isinstance(catalog.get('release_notes', ''), str):
        raise ValueError('Invalid release metadata')
    patches = catalog['patches']
    if not isinstance(patches, list) or len(patches) > 1000:
        raise ValueError('Invalid patch list')
    edges = set()
    for patch in patches:
        a, b = version_key(patch['from_version']), version_key(patch['to_version'])
        if a >= b or b > latest or (a, b) in edges:
            raise ValueError('Duplicate, backwards or future patch')
        edges.add((a, b))
        https_url(patch['url'])
        if not HASH.fullmatch(patch['sha256']):
            raise ValueError('Invalid patch SHA-256')
        if type(patch.get('mandatory', False)) is not bool or not isinstance(patch.get('release_notes', ''), str):
            raise ValueError('Invalid patch metadata')
    return catalog


def patch_chain(current, catalog):
    validate_catalog(catalog)
    start, goal = version_key(current), version_key(catalog['latest_version'])
    if start >= goal:
        return []
    queue, seen = deque([(current, [])]), {start}
    while queue:
        version, chain = queue.popleft()
        for patch in catalog['patches']:
            key = version_key(patch['to_version'])
            if version_key(patch['from_version']) != version_key(version) or key in seen:
                continue
            if key == goal:
                return chain + [patch]
            seen.add(key)
            queue.append((patch['to_version'], chain + [patch]))
    raise ValueError('Нет полной цепочки патчей до последней версии. Нужен новый установщик.')


def inspect_patch(path, expected):
    if Path(path).stat().st_size > MAX_ARCHIVE or sha256(path) != expected['sha256']:
        raise ValueError('SHA-256 архива не совпадает или архив слишком большой.')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_EXPANDED:
            raise ValueError('Patch exceeds extraction limits')
        names = [i.filename for i in infos]
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError('Duplicate ZIP paths')
        if archive.getinfo('manifest.json').file_size > 8 * 1024**2:
            raise ValueError('Manifest too large')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format', 1) != 1:
            raise ValueError('Unsupported patch format')
        if manifest['from_version'] != expected['from_version'] or manifest['to_version'] != expected['to_version']:
            raise ValueError('Manifest versions differ from catalog')
        if version_key(manifest['from_version']) >= version_key(manifest['to_version']):
            raise ValueError('Patch must move forward')
        files = manifest['files']
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise ValueError('Invalid manifest files')
        used, payloads = set(), {'manifest.json'}
        for entry in files:
            name = safe_path(entry['path'])
            key = name.casefold()
            if key in used or any(key.startswith(p + '/') or p.startswith(key + '/') for p in used):
                raise ValueError('Overlapping manifest paths')
            used.add(key)
            if entry['action'] not in {'add', 'replace', 'delete'}:
                raise ValueError('Unsupported patch action')
            if entry['action'] != 'add' and not HASH.fullmatch(entry.get('old_sha256', '')):
                raise ValueError('replace/delete requires old_sha256')
            if entry['action'] != 'delete':
                if not HASH.fullmatch(entry.get('sha256', '')):
                    raise ValueError('Missing file hash')
                info = archive.getinfo(name)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise ValueError('Links, directories and encrypted ZIP entries are unsupported')
                with archive.open(name) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                        raise ValueError(f'Invalid payload hash: {name}')
                payloads.add(name)
        if set(names) != payloads:
            raise ValueError('Unexpected ZIP payloads')
    return manifest
