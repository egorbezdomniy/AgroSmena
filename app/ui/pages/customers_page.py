from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QVBoxLayout

from app.services import CustomerService
from app.ui.dialogs import CustomerDialog
from app.ui.pages.base import CrudPage
from app.ui.dialogs.detail_dialog import DetailDialog
from app.ui.widgets import action_buttons, filter_bar, make_button, make_table, page_heading, table_item


class CustomersPage(CrudPage):
    data_changed = Signal()

    def __init__(self, service: CustomerService, parent=None) -> None:
        super().__init__(parent)
        self.service = service

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по имени, компании, телефону, email…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        add_button = make_button("+  Добавить клиента", "primaryButton")
        add_button.clicked.connect(self.add_customer)

        toolbar_panel, toolbar = filter_bar()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(add_button)

        self.table = make_table(
            ["Имя", "Компания", "Телефон", "Email", "Telegram", "Должность", "Действия"]
        )
        self.table.itemClicked.connect(self._open_from_item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(page_heading("Клиенты", "Контакты и компании вашей клиентской базы"))
        layout.addWidget(toolbar_panel)
        layout.addWidget(self.table, 1)

    def refresh(self, *_args) -> None:
        customers = self.service.list(self.search.text())
        self.table.setRowCount(len(customers))
        for row, item in enumerate(customers):
            values = [
                item.name,
                item.company_name,
                item.phone,
                item.email,
                item.telegram,
                item.position,
            ]
            for column, value in enumerate(values):
                cell = table_item(value)
                cell.setData(Qt.ItemDataRole.UserRole, item.id)
                self.table.setItem(row, column, cell)
            self.table.setCellWidget(
                row,
                6,
                action_buttons(
                    lambda _checked=False, record_id=item.id: self.edit_customer(record_id),
                    lambda _checked=False, record_id=item.id, name=item.name: self.delete_customer(
                        record_id, name
                    ),
                ),
            )

    def add_customer(self) -> None:
        dialog = CustomerDialog(parent=self)
        if self.save_from_dialog(dialog, lambda values: self.service.create(**values)):
            self.refresh()
            self.data_changed.emit()

    def _open_from_item(self, cell) -> None:
        customer_id = cell.data(Qt.ItemDataRole.UserRole)
        if customer_id:
            self.show_customer(customer_id)

    def show_customer(self, customer_id: int) -> None:
        item = self.service.get(customer_id)
        DetailDialog(item.name, '', [
            ('Компания', item.company_name), ('Должность', item.position),
            ('Телефон', item.phone), ('Email', item.email), ('Telegram', item.telegram),
            ('Заметки', item.notes), ('UUID', item.uuid),
            ('Создан', item.created_at), ('Изменён', item.updated_at),
        ], parent=self).exec()

    def edit_customer(self, customer_id: int) -> None:
        dialog = CustomerDialog(self.service.get(customer_id), self)
        if self.save_from_dialog(
            dialog, lambda values: self.service.update(customer_id, **values)
        ):
            self.refresh()
            self.data_changed.emit()

    def delete_customer(self, customer_id: int, name: str) -> None:
        if self.confirm_delete(
            f"клиента «{name}»",
            lambda: self.service.delete(customer_id),
            warning="Удаление клиента также удалит все сделки, связанные с ним.",
        ):
            self.refresh()
            self.data_changed.emit()
