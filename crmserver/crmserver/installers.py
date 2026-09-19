"""Full Windows installers, managed separately from incremental patch catalogs."""
import hashlib
import json
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache


VERSION_PATTERN = r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
MAX_INSTALLER_SIZE = 512 * 1024 * 1024


def installer_directory():
    return Path(settings.APP_INSTALLER_DIR)


def current_release():
    directory = installer_directory()
    try:
        data = json.loads((directory / 'current.json').read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return None
        if not re.fullmatch(VERSION_PATTERN, str(data.get('version', ''))):
            return None
        if not re.fullmatch(r'[a-f0-9]{32}\.exe', str(data.get('file', ''))):
            return None
        if not re.fullmatch(r'[a-f0-9]{64}', str(data.get('sha256', ''))):
            return None
        if not isinstance(data.get('size'), int) or not 0 < data['size'] <= MAX_INSTALLER_SIZE:
            return None
        if not isinstance(data.get('notes', ''), str):
            return None
        path = directory / data['file']
        if not path.is_file() or path.stat().st_size != data['size']:
            return None
        return data
    except (OSError, ValueError):
        return None


class InstallerForm(forms.Form):
    version = forms.RegexField(VERSION_PATTERN, label='Версия', max_length=40,
                               help_text='Например, 0.1.3. Должна совпадать с версией загружаемой сборки.')
    installer = forms.FileField(label='Установщик Windows (.exe)',
                               help_text='Готовый установщик, до 512 МБ.',
                               widget=forms.ClearableFileInput(attrs={'accept': '.exe'}))
    notes = forms.CharField(label='Что нового', required=False, max_length=4000,
                            widget=forms.Textarea(attrs={'rows': 4}))

    def clean_version(self):
        value = self.cleaned_data['version']
        if not re.fullmatch(VERSION_PATTERN, value):
            raise forms.ValidationError('Укажите версию в формате 0.1.3.')
        return value

    def clean_installer(self):
        upload = self.cleaned_data['installer']
        if Path(upload.name).suffix.lower() != '.exe' or not 2 <= upload.size <= MAX_INSTALLER_SIZE:
            raise forms.ValidationError('Нужен установщик .exe размером до 512 МБ.')
        signature = upload.read(2)
        upload.seek(0)
        if signature != b'MZ':
            raise forms.ValidationError('Файл не является исполняемым файлом Windows.')
        return upload


def publish_installer(cleaned):
    directory = installer_directory()
    directory.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + '.exe'
    temporary = None
    manifest_temporary = None
    try:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.upload', delete=False) as target:
            temporary = Path(target.name)
            for chunk in cleaned['installer'].chunks():
                size += len(chunk)
                if size > MAX_INSTALLER_SIZE:
                    raise ValueError('Installer exceeds size limit')
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if size != cleaned['installer'].size:
            raise ValueError('Incomplete installer upload')
        os.replace(temporary, directory / filename)
        release = {
            'version': cleaned['version'], 'file': filename, 'size': size,
            'sha256': digest.hexdigest(), 'notes': cleaned['notes'],
            'published_at': timezone.now().isoformat(),
        }
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.json.tmp', mode='w',
                                         encoding='utf-8', delete=False) as target:
            manifest_temporary = Path(target.name)
            json.dump(release, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        # Readers always see one complete release; existing downloads remain valid.
        os.replace(manifest_temporary, directory / 'current.json')
    finally:
        for path in (temporary, manifest_temporary):
            if path is not None:
                path.unlink(missing_ok=True)


@method_decorator(never_cache, name='dispatch')
class DownloadPageView(View):
    def get(self, request):
        return render(request, 'web/download.html', {'release': current_release()})


@method_decorator(never_cache, name='dispatch')
class InstallerDownloadView(View):
    def get(self, request):
        release = current_release()
        if release is None:
            raise Http404('Установщик пока не опубликован.')
        try:
            stream = (installer_directory() / release['file']).open('rb')
        except OSError as error:
            raise Http404('Установщик временно недоступен.') from error
        return FileResponse(stream, as_attachment=True,
                            filename=f"AgroSmenaCRM-{release['version']}-Setup.exe",
                            content_type='application/octet-stream')


@method_decorator(never_cache, name='dispatch')
class InstallerAdminView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_active and self.request.user.is_superuser

    def get(self, request):
        return self.render_form(request, InstallerForm())

    def post(self, request):
        form = InstallerForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                publish_installer(form.cleaned_data)
            except (OSError, ValueError):
                logging.getLogger(__name__).exception('Failed to publish installer')
                form.add_error(None, 'Не удалось опубликовать файл. Проверьте доступность хранилища и повторите загрузку.')
            else:
                messages.success(request, 'Новая версия опубликована и доступна для скачивания.')
                return redirect('installer-admin')
        return self.render_form(request, form)

    def render_form(self, request, form):
        return render(request, 'web/installer_admin.html', {
            'form': form, 'release': current_release(), 'section': 'installer-admin',
        })
