"""Strict environment parsing; errors name the setting, never its value."""
import math
import os

from django.core.exceptions import ImproperlyConfigured


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {'true', '1', 'yes', 'on'}:
        return True
    if value in {'false', '0', 'no', 'off'}:
        return False
    raise ImproperlyConfigured(f'{name} must be a boolean')


def env_list(name, default=''):
    return [value.strip() for value in os.environ.get(name, default).split(',') if value.strip()]


def env_int(name, default, minimum=0):
    try:
        value = int(os.environ.get(name, str(default)))
        if value >= minimum:
            return value
    except ValueError:
        pass
    raise ImproperlyConfigured(f'{name} must be an integer >= {minimum}')


def env_rate(name, default=1.0):
    try:
        value = float(os.environ.get(name, str(default)))
        if math.isfinite(value) and 0 <= value <= 1:
            return value
    except ValueError:
        pass
    raise ImproperlyConfigured(f'{name} must be a number between 0 and 1')
