import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.services.update_service import UpdateService
from app.ui.pages.updates_page import UpdatesPage
from updatekit.protocol import atomic_json


class UpdatesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_background_check_progress_and_ready_to_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            atomic_json(root / 'version.json', {'version': '0.1.0'})
            service = UpdateService(root, root / 'profile')
            with patch('app.ui.pages.updates_page.UpdateService', return_value=service):
                page = UpdatesPage()
            try:
                page.endpoint.setText('https://example.org/api/app/update/')
                release = {'from_version': '0.1.0', 'to_version': '0.2.0', 'release_notes': 'Notes', 'mandatory': True}
                ticks = []
                timer = QTimer()
                timer.setInterval(5)
                timer.timeout.connect(lambda: ticks.append(1))
                timer.start()

                def check(endpoint):
                    time.sleep(.1)
                    return {'catalog': {'latest_version': '0.2.0', 'release_notes': 'Fix'}, 'chain': [release]}

                with patch.object(service, 'check', side_effect=check):
                    page.check()
                    self.assertFalse(page.check_button.isEnabled())
                    self.wait(page)
                timer.stop()
                self.assertGreater(len(ticks), 2, 'Qt event loop must remain responsive')
                self.assertTrue(page.update_button.isEnabled())
                self.assertIn('Обязательное', page.status.text())
                self.assertIn('Notes', page.notes.toPlainText())
                received = []
                page.install_requested.connect(received.append)
                def download(chain, progress):
                    progress(35, 'Downloading')
                    time.sleep(.03)
                    progress(100, 'Verified')
                    return ['patch']
                with patch.object(service, 'download', side_effect=download), patch.object(service, 'stage_updater', return_value=('runner', 'plan')):
                    page.install()
                    self.wait(page)
                self.assertEqual(page.progress.value(), 100)
                self.assertEqual(received, [('runner', 'plan')])
            finally:
                page.close()
                page.deleteLater()
                self.app.processEvents()

    def wait(self, page):
        loop = QEventLoop()
        worker = page.worker
        worker.finished.connect(loop.quit)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.app.processEvents()
        if page.worker is not None:
            worker.wait(1000)
            self.app.processEvents()
        self.assertIsNone(page.worker)
