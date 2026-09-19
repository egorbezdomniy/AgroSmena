"""Real HTTP smoke test; all data stays in Django's disposable test database."""
import json
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from django.contrib.staticfiles.testing import StaticLiveServerTestCase


class AuthenticatedHTTPTests(StaticLiveServerTestCase):
    def test_registration_crud_and_logout_over_http(self):
        cookies = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookies))

        def request(method, path, payload=None, *, form=False):
            headers = {}
            body = None
            if payload is not None:
                body = (urlencode(payload) if form else json.dumps(payload)).encode()
                headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
            token = next((cookie.value for cookie in cookies if cookie.name == 'csrftoken'), None)
            if token:
                headers['X-CSRFToken'] = token
            with opener.open(Request(self.live_server_url + path, data=body, method=method, headers=headers), timeout=5) as response:
                content = response.read()
                return response.status, (json.loads(content) if content and 'application/json' in response.headers.get('Content-Type', '') else content)

        self.assertEqual(request('GET', '/register/')[0], 200)
        self.assertEqual(request('POST', '/register/', {'username': 'http-owner',
            'organization_name': 'HTTP isolated organization', 'password1': 'HTTP-Strong-Pass!712',
            'password2': 'HTTP-Strong-Pass!712'}, form=True)[0], 200)
        self.assertEqual(request('GET', '/dashboard/')[0], 200)
        ids = {}
        for resource in ['customers', 'deals', 'tasks']:
            payload = {'name': 'HTTP customer'} if resource == 'customers' else {'title': 'HTTP record'}
            if resource == 'deals':
                payload.update(customer_id=ids['customers'], amount='123.45')
            elif resource == 'tasks':
                payload.update(customer_id=ids['customers'], deal_id=ids['deals'])
            url = f'/api/{resource}/'
            status, record = request('POST', url, payload)
            self.assertEqual(status, 201)
            ids[resource] = record['id']
            detail = f"{url}{record['id']}/"
            self.assertEqual(request('GET', url)[0], 200)
            self.assertEqual(request('GET', detail)[0], 200)
            self.assertEqual(request('PUT', detail, payload)[0], 200)
            update = {'notes': 'Updated'} if resource == 'customers' else {'description': 'Updated'}
            self.assertEqual(request('PATCH', detail, update)[0], 200)
        for resource in ['tasks', 'deals', 'customers']:
            self.assertEqual(request('DELETE', f'/api/{resource}/{ids[resource]}/')[0], 204)
        self.assertEqual(request('POST', '/logout/', {}, form=True)[0], 200)
        with self.assertRaises(HTTPError) as error:
            request('GET', '/api/customers/')
        self.assertEqual(error.exception.code, 403)
