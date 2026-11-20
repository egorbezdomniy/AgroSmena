"""Run only with crmserver.verification_settings and collected temporary static files."""
import gzip
import json
import os
import re
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import ProxyHandler, Request, build_opener
from wsgiref.simple_server import WSGIRequestHandler, make_server

import django


def main():
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'crmserver.verification_settings':
        raise RuntimeError('Only synthetic verification_settings are allowed')
    django.setup()
    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.storage import staticfiles_storage

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server('127.0.0.1', 0, get_wsgi_application(), handler_class=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with opener.open(Request(origin + '/healthz/', headers={'X-Request-ID': 'untrusted'}), timeout=10) as response:
            assert response.status == 200 and json.load(response) == {'status': 'ok'}
            assert re.fullmatch('[a-f0-9]{32}', response.headers['X-Request-ID'])
        try:
            opener.open(Request(origin + '/healthz/', headers={'Host': 'outsider.invalid'}), timeout=10)
        except HTTPError as error:
            assert error.code == 400
        else:
            raise AssertionError('Foreign host accepted')
        with opener.open(origin + '/', timeout=10) as response:
            html = response.read().decode('utf-8')
            assert response.status == 200
        assets = re.findall(r'(?:href|src)="([^\"]+\.(?:css|js)(?:\?[^\"]*)?)"', html)
        assert assets
        for asset in assets:
            with opener.open(urljoin(origin, asset), timeout=10) as response:
                assert response.status == 200 and response.read()
                assert 'immutable' in response.headers['Cache-Control']
        css = staticfiles_storage.url('web/landing.css')
        with opener.open(Request(urljoin(origin, css), headers={'Accept-Encoding': 'gzip'}), timeout=10) as response:
            assert response.headers['Content-Encoding'] == 'gzip'
            assert gzip.decompress(response.read())
        print(json.dumps({'health': 200, 'foreign_host': 400, 'landing': 200,
                          'css_js_assets': len(assets), 'gzip_static': True,
                          'request_id': True, 'real_https_proxy_verified': False}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
