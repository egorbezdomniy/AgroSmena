from django.apps import AppConfig


class SynchronizationConfig(AppConfig):
    name = 'synchronization'

    def ready(self):
        from . import signals  # noqa: F401
