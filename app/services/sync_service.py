import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import text

from app.core.secure_store import protect, unprotect
from app.models.sync import SavedSyncLogin, SyncState
from app.repositories.sync_repository import SyncRepository, parse_time


class SyncError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or tokens to a redirect target.


class SyncClient:
    def __init__(self, server_url):
        url = urlsplit(server_url.strip().rstrip('/'))
        if (url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {'', '/'}):
            raise SyncError('Введите адрес сервера, например http://127.0.0.1:8000')
        if url.scheme != 'https' and url.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise SyncError('Для удалённого сервера требуется HTTPS.')
        self.server_url = f'{url.scheme}://{url.netloc}'.lower()
        self.token = None
        self.identity = None

    def request(self, path, payload):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        try:
            request = Request(self.server_url + '/api/sync/' + path + '/',
                              data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
            with build_opener(NoRedirects).open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code in (401, 403):
                self.token = None
                raise SyncError('Нет доступа. Проверьте логин, пароль и организацию; войдите заново.') from None
            try:
                detail = json.loads(error.read(8192))
                message = json.dumps(detail, ensure_ascii=False)[:1000]
            except (ValueError, UnicodeError):
                message = 'Проверьте адрес и версию сервера.'
            raise SyncError(f'Ошибка сервера {error.code}: {message}') from None
        except (URLError, TimeoutError, OSError):
            raise SyncError('Сервер недоступен или время ожидания истекло. Локальные данные сохранены.') from None
        except (ValueError, UnicodeError):
            raise SyncError('Сервер вернул некорректный ответ. Локальные данные сохранены.') from None

    def login(self, username, password):
        identity = self.request('login', {'username': username, 'password': password})
        self.token = identity['token']
        self.identity = {key: value for key, value in identity.items() if key != 'token'}
        return self.identity


class SyncService:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.client = None
        self._restore_login()

    def _restore_login(self):
        with self.session_factory.begin() as session:
            saved = session.get(SavedSyncLogin, 1)
            if saved is None:
                return
            try:
                client = SyncClient(saved.server_url)
                client.token = unprotect(saved.protected_token)
            except Exception:
                session.delete(saved)
                return
            client.identity = {'organization': saved.organization_uuid,
                'organization_name': saved.organization_name, 'username': saved.username}
            state = SyncRepository(session).state()
            if state and (state.server_url != client.server_url or state.organization_uuid != saved.organization_uuid):
                session.delete(saved)
                return
            self.client = client

    def state(self):
        with self.session_factory() as session:
            state = SyncRepository(session).state()
            return None if state is None else {'server_url': state.server_url, 'organization': state.organization_uuid,
                'organization_name': state.organization_name, 'last_sync_at': state.last_sync_at}

    def login(self, server_url, username, password):
        self.logout()
        client = SyncClient(server_url)
        identity = client.login(username, password)
        state = self.state()
        if state and (state['server_url'] != client.server_url or state['organization'] != identity['organization']):
            raise SyncError('Эта SQLite-база привязана к другому серверу или организации. Обмен запрещён. Используйте отдельную локальную базу.')
        try:
            encrypted = protect(client.token)
        except Exception as error:
            raise SyncError(f'Не удалось безопасно сохранить токен Windows: {error}') from None
        with self.session_factory.begin() as session:
            session.merge(SavedSyncLogin(id=1, server_url=client.server_url,
                organization_uuid=identity['organization'], organization_name=identity['organization_name'],
                username=identity['username'], protected_token=encrypted))
        self.client = client
        return identity

    def logout(self, *, forget=False):
        if self.client:
            self.client.token = None
        self.client = None
        if forget:
            with self.session_factory.begin() as session:
                saved = session.get(SavedSyncLogin, 1)
                if saved:
                    session.delete(saved)

    def synchronize(self, *, confirm_binding=False):
        client = self.client
        if client is None or not client.token:
            raise SyncError('Сначала войдите на сервер.')
        # Persist the approved organization BEFORE sending anything. A lost response must
        # never allow the same SQLite database to be rebound and uploaded elsewhere.
        with self.session_factory() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            state = SyncRepository(session).state()
            if state is None:
                if not confirm_binding:
                    raise SyncError('Подтвердите привязку локальной базы к организации.')
                session.add(SyncState(id=1, server_url=client.server_url,
                    organization_uuid=client.identity['organization'], organization_name=client.identity['organization_name']))
            elif state.server_url != client.server_url or state.organization_uuid != client.identity['organization']:
                raise SyncError('Организация локальной базы не совпадает с аккаунтом.')
            session.commit()
        with self.session_factory() as session:
            try:
                # Block writers in other desktop instances until this snapshot is committed.
                session.execute(text('BEGIN IMMEDIATE'))
                repository = SyncRepository(session)
                state = repository.state()
                if state.server_url != client.server_url or state.organization_uuid != client.identity['organization']:
                    raise SyncError('Организация локальной базы не совпадает с аккаунтом.')
                changes = repository.export()
                response = client.request('exchange', {'organization': state.organization_uuid, 'changes': changes})
                if response['organization'] != state.organization_uuid:
                    raise SyncError('Сервер вернул другую организацию. Данные не изменены.')
                repository.apply_snapshot(response['changes'])
                state.last_sync_at = parse_time(response['synced_at'])
                session.commit()
                return state.last_sync_at
            except Exception:
                session.rollback()
                if client.token is None:
                    self.logout(forget=True)
                raise
