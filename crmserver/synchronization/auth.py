from django.contrib.auth import get_user_model
from django.core import signing
from django.utils.crypto import constant_time_compare
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from accounts.access import membership_for

SALT = 'crm-desktop-sync-v1'
TOKEN_LIFETIME = 12 * 60 * 60


def issue_token(user, membership):
    return signing.dumps({'user': user.pk, 'organization': str(membership.organization.uuid),
                          'auth': user.get_session_auth_hash()}, salt=SALT)


class SyncAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header:
            return None
        if len(header) != 2 or header[0].lower() != b'bearer':
            raise AuthenticationFailed('Войдите на сервер заново.')
        try:
            data = signing.loads(header[1].decode(), salt=SALT, max_age=TOKEN_LIFETIME)
            user = get_user_model().objects.get(pk=data['user'], is_active=True)
            membership = membership_for(user)
            if (not membership or str(membership.organization.uuid) != data['organization']
                    or not constant_time_compare(user.get_session_auth_hash(), data['auth'])):
                raise ValueError
        except (signing.BadSignature, ValueError, KeyError, UnicodeError, get_user_model().DoesNotExist):
            raise AuthenticationFailed('Сессия истекла или доступ изменён. Войдите заново.') from None
        return user, data
