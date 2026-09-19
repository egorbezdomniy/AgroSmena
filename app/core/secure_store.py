"""Encrypt small desktop secrets for the current Windows user with DPAPI."""
import base64
import ctypes
import sys
from ctypes import wintypes


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt(value, decrypt=False):
    if sys.platform != 'win32':
        raise RuntimeError('Безопасное сохранение токена поддерживается только в Windows.')
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    source, source_buffer = _blob(raw)
    entropy, entropy_buffer = _blob(b'AgroSmena.CRM.Sync.Token.v1')
    result = DATA_BLOB()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    args = ((ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(result))
            if decrypt else (ctypes.byref(source), 'AgroSmena CRM', ctypes.byref(entropy), None, None, 0, ctypes.byref(result)))
    if not function(*args):
        raise ctypes.WinError()
    try:
        output = ctypes.string_at(result.pbData, result.cbData)
        return output.decode('utf-8') if decrypt else base64.b64encode(output).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def protect(value):
    return _crypt(value)


def unprotect(value):
    return _crypt(value, decrypt=True)
