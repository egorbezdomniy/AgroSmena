from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

from app.services.dto import CustomerDTO
from app.ui.widgets import page_heading


class CustomerDialog(QDialog):
    def __init__(self, customer: CustomerDTO | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редактирование клиента" if customer else "Новый клиент")
        self.setMinimumWidth(500)

        self.name = QLineEdit()
        self.company = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.telegram = QLineEdit()
        self.position = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(110)

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Имя *", self.name)
        form.addRow("Компания", self.company)
        form.addRow("Телефон", self.phone)
        form.addRow("Email", self.email)
        form.addRow("Telegram", self.telegram)
        form.addRow("Должность", self.position)
        form.addRow("Заметки", self.notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primaryButton')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(18)
        layout.addWidget(page_heading(self.windowTitle(), 'Контактная информация и заметки'))
        layout.addLayout(form)
        layout.addWidget(buttons)

        if customer:
            self.name.setText(customer.name)
            self.company.setText(customer.company_name)
            self.phone.setText(customer.phone)
            self.email.setText(customer.email)
            self.telegram.setText(customer.telegram)
            self.position.setText(customer.position)
            self.notes.setPlainText(customer.notes)

    def values(self) -> dict:
        return {
            "name": self.name.text(),
            "company_name": self.company.text(),
            "phone": self.phone.text(),
            "email": self.email.text(),
            "telegram": self.telegram.text(),
            "position": self.position.text(),
            "notes": self.notes.toPlainText(),
        }
