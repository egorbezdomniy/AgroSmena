from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class AccountsConfig(AppConfig):
    name = 'accounts'
    verbose_name = 'Организации и пользователи'


class CRMAdminConfig(AdminConfig):
    default_site = 'accounts.admin_site.SystemAdminSite'
