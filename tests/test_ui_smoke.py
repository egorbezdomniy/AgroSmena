from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.database import Database  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


class MainWindowSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_all_pages_can_be_opened_and_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "ui.db")
            database.create_tables()
            try:
                window = MainWindow(database.session_factory)
                for index in range(4):
                    window.navigate(index)
                    self.app.processEvents()
                    self.assertEqual(window.stack.currentIndex(), index)
                window.close()
            finally:
                database.dispose()


if __name__ == "__main__":
    unittest.main()

