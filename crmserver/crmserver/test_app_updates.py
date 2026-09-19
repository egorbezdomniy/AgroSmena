import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class UpdateEndpointTests(SimpleTestCase):
    def test_anonymous_catalog_is_independent_of_organization_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.json'
            path.write_text(json.dumps({'latest_version': '0.2.0', 'mandatory': True, 'release_notes': 'Fixes',
                'patches': [{'from_version': '0.1.0', 'to_version': '0.2.0', 'url': 'https://example.com/a.zip',
                             'sha256': 'a' * 64}]}))
            with override_settings(APP_UPDATE_CATALOG=path):
                response = self.client.get('/api/app/update/')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['mandatory'])
            self.assertEqual(response.json()['patches'][0]['release_notes'], '')

    def test_invalid_or_unpublished_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.json'
            with override_settings(APP_UPDATE_CATALOG=path):
                self.assertEqual(self.client.get('/api/app/update/').status_code, 503)
                path.write_text('{bad json')
                self.assertEqual(self.client.get('/api/app/update/').status_code, 503)

    def test_http_patch_rejected(self):
        from crmserver.app_updates import PatchSerializer
        data = {'from_version': '1.0.0', 'to_version': '1.1.0', 'url': 'http://example.com/a.zip', 'sha256': 'a' * 64}
        self.assertFalse(PatchSerializer(data=data).is_valid())
