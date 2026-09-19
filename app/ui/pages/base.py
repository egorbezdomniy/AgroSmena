from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from app.services.exceptions import ServiceError


class CrudPage(QWidget):
    def save_from_dialog(self, dialog: QDialog, action: Callable[[dict], object]) -> bool:
        """Keep a form open when the service rejects its values."""
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                action(dialog.values())
                return True
            except ServiceError as error:
                QMessageBox.warning(self, "Проверьте данные", str(error))
            except Exception as error:  # pragma: no cover - defensive GUI boundary
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить данные:\n{error}")
        return False

    def confirm_delete(
        self, entity_name: str, action: Callable[[], None], warning: str = ""
    ) -> bool:
        answer = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить {entity_name}?\n"
            + (f"{warning}\n" if warning else "")
            + "Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        try:
            action()
            return True
        except ServiceError as error:
            QMessageBox.warning(self, "Удаление невозможно", str(error))
        except Exception as error:  # pragma: no cover - defensive GUI boundary
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить запись:\n{error}")
        return False
