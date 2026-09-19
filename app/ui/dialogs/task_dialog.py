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

from app.core.constants import TASK_PRIORITIES, TASK_STATUSES
from app.services.dto import CustomerDTO, DealDTO, TaskDTO
from app.ui.widgets import page_heading


class TaskDialog(QDialog):
    def __init__(
        self,
        customers: list[CustomerDTO],
        deals: list[DealDTO],
        task: TaskDTO | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редактирование задачи" if task else "Новая задача")
        self.setMinimumWidth(520)
        self._deals = deals

        self.title = QLineEdit()
        self.description = QTextEdit()
        self.description.setMaximumHeight(100)
        self.customer = QComboBox()
        self.customer.addItem("Не выбран", None)
        for item in customers:
            self.customer.addItem(item.name, item.id)
        self.deal = QComboBox()
        self.has_due_date = QCheckBox("Указать срок")
        self.due_date = QDateEdit(QDate.currentDate())
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("dd.MM.yyyy")
        self.due_date.setEnabled(False)
        self.has_due_date.toggled.connect(self.due_date.setEnabled)
        self.priority = QComboBox()
        self.priority.addItems(TASK_PRIORITIES)
        self.priority.setCurrentText("Обычный")
        self.status = QComboBox()
        self.status.addItems(TASK_STATUSES)

        self.customer.currentIndexChanged.connect(self._on_customer_changed)
        self._fill_deals()

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Название *", self.title)
        form.addRow("Описание", self.description)
        form.addRow("Клиент", self.customer)
        form.addRow("Сделка", self.deal)
        form.addRow(self.has_due_date, self.due_date)
        form.addRow("Приоритет", self.priority)
        form.addRow("Статус", self.status)

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
        layout.addWidget(page_heading(self.windowTitle(), 'Планы, сроки и приоритеты'))
        layout.addLayout(form)
        layout.addWidget(buttons)

        if task:
            self.title.setText(task.title)
            self.description.setPlainText(task.description)
            self.customer.setCurrentIndex(self.customer.findData(task.customer_id))
            self._fill_deals(task.deal_id)
            if task.due_date:
                value = task.due_date
                self.has_due_date.setChecked(True)
                self.due_date.setDate(QDate(value.year, value.month, value.day))
            self.priority.setCurrentText(task.priority)
            self.status.setCurrentText(task.status)

    def _fill_deals(self, selected_id: int | None = None) -> None:
        previous = selected_id if selected_id is not None else self.deal.currentData()
        customer_id = self.customer.currentData()
        self.deal.blockSignals(True)
        self.deal.clear()
        self.deal.addItem("Не выбрана", None)
        for item in self._deals:
            if customer_id is None or item.customer_id == customer_id:
                self.deal.addItem(item.title, item.id)
        index = self.deal.findData(previous)
        self.deal.setCurrentIndex(max(0, index))
        self.deal.blockSignals(False)

    def _on_customer_changed(self, _index: int) -> None:
        self._fill_deals()

    def values(self) -> dict:
        return {
            "title": self.title.text(),
            "description": self.description.toPlainText(),
            "customer_id": self.customer.currentData(),
            "deal_id": self.deal.currentData(),
            "due_date": self.due_date.date().toPython() if self.has_due_date.isChecked() else None,
            "priority": self.priority.currentText(),
            "status": self.status.currentText(),
        }
