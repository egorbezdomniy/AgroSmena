import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.dialogs.deal_dialog import DealDialog
from app.ui.pages.base import CrudPage


class DeleteAndAmountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_enter_confirms_delete_and_shows_warning(self):
        page = CrudPage()
        action = Mock()
        observed = []

        def press_enter():
            box = self.app.activeModalWidget()
            if isinstance(box, QMessageBox):
                observed.append(box.text())
                QTest.keyClick(box, Qt.Key.Key_Return)

        QTimer.singleShot(50, press_enter)
        warning = "Удаление клиента также удалит все сделки, связанные с ним."
        self.assertTrue(page.confirm_delete("клиента", action, warning))
        action.assert_called_once()
        self.assertIn(warning, observed[0])
        page.close()

    def test_amount_starts_empty_and_accepts_decimal_comma(self):
        dialog = DealDialog([])
        self.assertEqual(dialog.amount.text(), "")
        self.assertEqual(dialog.values()["amount"], "0")
        dialog.amount.setText("1250,50")
        self.assertEqual(dialog.values()["amount"], "1250.50")
        dialog.close()
