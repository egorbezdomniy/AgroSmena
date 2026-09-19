"""Generate a file-level patch from two complete onedir builds."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updatekit.protocol import atomic_json, read_version, safe_path, sha256, version_key


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError(f'Build contains a link: {path}')
        if not path.is_file() or path == root / 'version.json':
            continue
        name = safe_path(path.relative_to(root).as_posix())
        if name.casefold() in {p.casefold() for p in result}:
            raise ValueError('Case-insensitive path collision')
        result[name] = sha256(path)
    return result


def create_patch(old, new, from_version, to_version, output):
    old, new, output = Path(old).resolve(), Path(new).resolve(), Path(output).resolve()
    if not old.is_dir() or not new.is_dir() or old.is_relative_to(new) or new.is_relative_to(old):
        raise ValueError('Provide two different build directories')
    if output.is_relative_to(old) or output.is_relative_to(new):
        raise ValueError('Output must be outside build directories')
    if version_key(from_version) >= version_key(to_version):
        raise ValueError('Target version must be newer')
    if read_version(old) != from_version or read_version(new) != to_version:
        raise ValueError('Build version.json does not match command arguments')
    before, after = inventory(old), inventory(new)
    old_names = {p.casefold(): p for p in before}
    if any(p.casefold() in old_names and p != old_names[p.casefold()] for p in after):
        raise ValueError('Case-only renames are unsupported on Windows')
    files = []
    for name in sorted(before.keys() | after.keys()):
        if before.get(name) == after.get(name):
            continue
        entry = {'path': name, 'action': 'delete' if name not in after else 'replace' if name in before else 'add'}
        if name in before:
            entry['old_sha256'] = before[name]
        if name in after:
            entry['sha256'] = after[name]
        files.append(entry)
    manifest = {'format': 1, 'from_version': from_version, 'to_version': to_version, 'files': files}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for entry in files:
            if entry['action'] != 'delete':
                archive.write(new / entry['path'], entry['path'])
    atomic_json(output.with_suffix('.manifest.json'), manifest)
    metadata = {'from_version': from_version, 'to_version': to_version, 'url': '',
                'sha256': sha256(output), 'mandatory': False, 'release_notes': ''}
    atomic_json(output.with_suffix('.release.json'), metadata)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old_build', type=Path)
    parser.add_argument('new_build', type=Path)
    parser.add_argument('from_version')
    parser.add_argument('to_version')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path('dist/patches') / f'{args.from_version}-to-{args.to_version}.zip'
    print(json.dumps(create_patch(args.old_build, args.new_build, args.from_version, args.to_version, output), indent=2))
