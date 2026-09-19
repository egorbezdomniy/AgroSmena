import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.core.database import Database
from app.ui.main_window import MainWindow
from app.ui.sync_worker import SyncWorker
from app.models.sync import SavedSyncLogin


class SyncUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sync_button_status_refresh_and_logout(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'crm.db')
            db.create_tables()
            window = MainWindow(db.session_factory)
            try:
                self.assertEqual(window.sync_button.text(), 'Синхронизировать')
                window._login_succeeded({'username': 'user', 'organization_name': 'Организация'})
                self.assertIn('Организация', window.sync_status.text())
                window._sync_succeeded(datetime(2026, 9, 4, 12))
                self.assertIn('Синхронизировано', window.sync_status.text())
                with patch('app.ui.main_window.QMessageBox.warning') as message:
                    window._sync_error('Нет сети')
                    message.assert_called_once()
                    self.assertEqual(window.sync_status.toolTip(), 'Нет сети')
                window._server_logout()
                self.assertIsNone(window.sync_service.client)
                self.assertFalse(window.logout_button.isEnabled())
            finally:
                window.close()
                db.dispose()

    def test_worker_success_and_error(self):
        for fail in (False, True):
            def operation():
                if fail:
                    raise ValueError('Нет сети')
                return 'OK'
            worker = SyncWorker(operation)
            values, errors = [], []
            worker.succeeded.connect(values.append)
            worker.failed.connect(errors.append)
            loop = QEventLoop()
            worker.finished.connect(loop.quit)
            QTimer.singleShot(3000, loop.quit)
            worker.start()
            loop.exec()
            worker.wait(3000)
            self.assertFalse(worker.isRunning())
            self.assertEqual(errors if fail else values, ['Нет сети'] if fail else ['OK'])
            self.assertIsNone(worker.operation)
