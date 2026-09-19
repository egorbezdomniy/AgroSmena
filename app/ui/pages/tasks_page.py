from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QLineEdit, QVBoxLayout

from app.core.constants import TASK_PRIORITIES, TASK_STATUSES
from app.services import CustomerService, DealService, TaskService
from app.ui.dialogs import TaskDialog
from app.ui.pages.base import CrudPage
from app.ui.widgets import action_buttons, filter_bar, make_button, make_table, page_heading, table_item


class TasksPage(CrudPage):
    data_changed = Signal()

    def __init__(
        self,
        service: TaskService,
        customer_service: CustomerService,
        deal_service: DealService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.customer_service = customer_service
        self.deal_service = deal_service

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по задаче, клиенту или сделке…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все статусы", None)
        for status in TASK_STATUSES:
            self.status_filter.addItem(status, status)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.priority_filter = QComboBox()
        self.priority_filter.addItem("Все приоритеты", None)
        for priority in TASK_PRIORITIES:
            self.priority_filter.addItem(priority, priority)
        self.priority_filter.currentIndexChanged.connect(self.refresh)
        add_button = make_button("+  Добавить задачу", "primaryButton")
        add_button.clicked.connect(self.add_task)

        toolbar_panel, toolbar = filter_bar()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.status_filter)
        toolbar.addWidget(self.priority_filter)
        toolbar.addWidget(add_button)

        self.table = make_table(
            ["Название", "Срок", "Приоритет", "Статус", "Клиент", "Сделка", "Действия"]
        )
        self.table.itemClicked.connect(self._open_from_item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(page_heading("Задачи", "Контроль сроков и текущей работы"))
        layout.addWidget(toolbar_panel)
        layout.addWidget(self.table, 1)

    def refresh(self, *_args) -> None:
        tasks = self.service.list(
            self.search.text(), self.status_filter.currentData(), self.priority_filter.currentData()
        )
        self.table.setRowCount(len(tasks))
        for row, item in enumerate(tasks):
            values = [
                item.title,
                item.due_date.strftime("%d.%m.%Y") if item.due_date else "—",
                item.priority,
                item.status,
                item.customer_name or "—",
                item.deal_title or "—",
            ]
            for column, value in enumerate(values):
                cell = table_item(value)
                cell.setData(Qt.ItemDataRole.UserRole, item.id)
                self.table.setItem(row, column, cell)
            self.table.setCellWidget(
                row,
                6,
                action_buttons(
                    lambda _checked=False, record_id=item.id: self.edit_task(record_id),
                    lambda _checked=False, record_id=item.id, title=item.title: self.delete_task(
                        record_id, title
                    ),
                ),
            )

    def _dialog(self, task=None) -> TaskDialog:
        return TaskDialog(
            self.customer_service.list(), self.deal_service.list(), task=task, parent=self
        )

    def add_task(self) -> None:
        dialog = self._dialog()
        if self.save_from_dialog(dialog, lambda values: self.service.create(**values)):
            self.refresh()
            self.data_changed.emit()

    def _open_from_item(self, cell) -> None:
        task_id = cell.data(Qt.ItemDataRole.UserRole)
        if task_id:
            self.show_task(task_id)

    def show_task(self, task_id: int) -> None:
        from app.ui.dialogs.detail_dialog import DetailDialog
        item = self.service.get(task_id)
        links = []
        if item.customer_id:
            links.append((f'Открыть клиента: {item.customer_name}',
                          lambda: self._show_customer(item.customer_id)))
        if item.deal_id:
            links.append((f'Открыть сделку: {item.deal_title}',
                          lambda: self._show_deal(item.deal_id)))
        DetailDialog(item.title, '', [
            ('Описание', item.description), ('Срок', item.due_date), ('Приоритет', item.priority),
            ('Статус', item.status), ('Клиент', item.customer_name), ('Сделка', item.deal_title),
            ('UUID', item.uuid), ('Создана', item.created_at), ('Изменена', item.updated_at),
        ], links=links, parent=self).exec()

    def _show_customer(self, customer_id: int) -> None:
        from app.ui.dialogs.detail_dialog import DetailDialog
        item = self.customer_service.get(customer_id)
        DetailDialog(item.name, '', [
            ('Компания', item.company_name), ('Должность', item.position), ('Телефон', item.phone),
            ('Email', item.email), ('Telegram', item.telegram), ('Заметки', item.notes),
            ('UUID', item.uuid), ('Создан', item.created_at), ('Изменён', item.updated_at),
        ], parent=self).exec()

    def _show_deal(self, deal_id: int) -> None:
        from app.ui.dialogs.detail_dialog import DetailDialog
        item = self.deal_service.get(deal_id)
        DetailDialog(item.title, '', [
            ('Клиент', item.customer_name), ('Сумма', item.amount), ('Стадия', item.stage),
            ('Планируемое закрытие', item.expected_close_date), ('Описание', item.description),
            ('UUID', item.uuid), ('Создана', item.created_at), ('Изменена', item.updated_at),
        ], parent=self).exec()

    def edit_task(self, task_id: int) -> None:
        dialog = self._dialog(self.service.get(task_id))
        if self.save_from_dialog(dialog, lambda values: self.service.update(task_id, **values)):
            self.refresh()
            self.data_changed.emit()

    def delete_task(self, task_id: int, title: str) -> None:
        if self.confirm_delete(f"задачу «{title}»", lambda: self.service.delete(task_id)):
            self.refresh()
            self.data_changed.emit()
