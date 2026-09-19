from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

from app.core.constants import DEAL_STAGES
from app.services.dto import CustomerDTO, DealDTO
from app.ui.widgets import page_heading


class DealDialog(QDialog):
    def __init__(
        self, customers: list[CustomerDTO], deal: DealDTO | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редактирование сделки" if deal else "Новая сделка")
        self.setMinimumWidth(520)

        self.title = QLineEdit()
        self.customer = QComboBox()
        for item in customers:
            label = item.name + (f" — {item.company_name}" if item.company_name else "")
            self.customer.addItem(label, item.id)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Сумма в ₽")
        self.stage = QComboBox()
        self.stage.addItems(DEAL_STAGES)
        self.has_close_date = QCheckBox("Указать дату")
        self.close_date = QDateEdit(QDate.currentDate())
        self.close_date.setCalendarPopup(True)
        self.close_date.setDisplayFormat("dd.MM.yyyy")
        self.close_date.setEnabled(False)
        self.has_close_date.toggled.connect(self.close_date.setEnabled)
        self.description = QTextEdit()
        self.description.setMaximumHeight(110)

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Название *", self.title)
        form.addRow("Клиент *", self.customer)
        form.addRow("Сумма", self.amount)
        form.addRow("Стадия", self.stage)
        form.addRow(self.has_close_date, self.close_date)
        form.addRow("Описание", self.description)

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
        layout.addWidget(page_heading(self.windowTitle(), 'Клиент, сумма и этап работы'))
        layout.addLayout(form)
        layout.addWidget(buttons)

        if deal:
            self.title.setText(deal.title)
            self.customer.setCurrentIndex(self.customer.findData(deal.customer_id))
            self.amount.setText(str(deal.amount))
            self.stage.setCurrentText(deal.stage)
            self.description.setPlainText(deal.description)
            if deal.expected_close_date:
                value = deal.expected_close_date
                self.has_close_date.setChecked(True)
                self.close_date.setDate(QDate(value.year, value.month, value.day))

    def values(self) -> dict:
        return {
            "title": self.title.text(),
            "customer_id": self.customer.currentData(),
            "amount": self.amount.text().strip().replace(",", ".") or "0",
            "stage": self.stage.currentText(),
            "expected_close_date": (
                self.close_date.date().toPython() if self.has_close_date.isChecked() else None
            ),
            "description": self.description.toPlainText(),
        }
