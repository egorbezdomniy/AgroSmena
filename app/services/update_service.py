"""HTTPS catalog/download service. Never changes installed application files."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.config import INSTALL_ROOT, USER_ROOT
from updatekit.protocol import (MAX_ARCHIVE, atomic_json, https_url, inspect_patch,
                                patch_chain, read_version, sha256, validate_catalog)


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)  # Reject HTTPS -> HTTP before sending the redirected request.
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UpdateService:
    def __init__(self, install_root=INSTALL_ROOT, data_root=USER_ROOT):
        self.root, self.data = Path(install_root).resolve(), Path(data_root).resolve()
        self.settings_file = self.data / 'settings' / 'updates.json'
        self.opener = build_opener(HTTPSRedirects())

    @property
    def current_version(self):
        return read_version(self.root)

    def endpoint(self):
        if os.environ.get('AGROSMENA_UPDATE_URL'):
            return os.environ['AGROSMENA_UPDATE_URL']
        if self.settings_file.exists():
            return json.loads(self.settings_file.read_text(encoding='utf-8')).get('endpoint', '')
        return ''

    def save_endpoint(self, endpoint):
        atomic_json(self.settings_file, {'endpoint': https_url(endpoint.strip())})

    def _open(self, url):
        response = self.opener.open(Request(https_url(url), headers={
            'User-Agent': 'AgroSmena-Updater/1', 'Accept-Encoding': 'identity'}), timeout=30)
        https_url(response.geturl())
        return response

    def check(self, endpoint):
        self.save_endpoint(endpoint)
        with self._open(endpoint) as response:
            payload = response.read(2 * 1024**2 + 1)
        if len(payload) > 2 * 1024**2:
            raise ValueError('Каталог обновлений слишком большой.')
        catalog = validate_catalog(json.loads(payload))
        return {'catalog': catalog, 'chain': patch_chain(self.current_version, catalog)}

    def download(self, chain, progress=lambda value, message: None):
        cache = self.data / 'updates' / 'downloads'
        cache.mkdir(parents=True, exist_ok=True)
        completed = []
        for index, patch in enumerate(chain):
            destination = cache / (patch['sha256'] + '.zip')
            if not destination.exists() or sha256(destination) != patch['sha256']:
                temporary = cache / (uuid.uuid4().hex + '.part')
                try:
                    with self._open(patch['url']) as response, temporary.open('xb') as output:
                        total = int(response.headers.get('Content-Length', 0))
                        if total > MAX_ARCHIVE:
                            raise ValueError('Патч слишком большой.')
                        downloaded = 0
                        while chunk := response.read(256 * 1024):
                            downloaded += len(chunk)
                            if downloaded > MAX_ARCHIVE:
                                raise ValueError('Патч превышает допустимый размер.')
                            output.write(chunk)
                            fraction = min(downloaded / total, 1) if total > 0 else 0
                            progress(int(100 * (index + fraction) / len(chain)),
                                     f'Патч {index + 1}/{len(chain)}: {downloaded / 1024**2:.1f} МБ')
                    inspect_patch(temporary, patch)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            inspect_patch(destination, patch)
            completed.append({**patch, 'path': str(destination)})
            progress(int(100 * (index + 1) / len(chain)), f'Патч {index + 1}/{len(chain)} проверен')
        return completed

    def stage_updater(self, patches, recover=False):
        if not getattr(sys, 'frozen', False):
            raise RuntimeError('Установка патчей доступна в установленной Windows-сборке. Исходный проект не обновляется.')
        source = self.root / 'updater.exe'
        if recover:
            saved = self.data / 'updates' / 'recovery.json'
            if saved.exists():
                source = Path(json.loads(saved.read_text(encoding='utf-8'))['runner'])
        if not source.is_file():
            raise RuntimeError('updater.exe отсутствует. Установите сборку с поддержкой обновлений.')
        runner_dir = self.data / 'updates' / 'runners' / uuid.uuid4().hex
        runner_dir.mkdir(parents=True)
        runner = runner_dir / 'updater.exe'
        shutil.copy2(source, runner)
        if sha256(source) != sha256(runner):
            raise RuntimeError('Не удалось подготовить updater.exe')
        plan = runner_dir / 'plan.json'
        atomic_json(plan, {'install_root': str(self.root), 'data_root': str(self.data), 'patches': patches})
        atomic_json(self.data / 'updates' / 'recovery.json', {'runner': str(runner), 'plan': str(plan)})
        return runner, plan

    def launch(self, staged, recover=False):
        runner, plan = staged
        command = [str(runner), '--plan', str(plan), '--parent-pid', str(os.getpid())]
        if recover:
            command.append('--recover')
        return subprocess.Popen(command, cwd=runner.parent, close_fds=True)

    def last_result(self):
        path = self.data / 'updates' / 'last-result.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
