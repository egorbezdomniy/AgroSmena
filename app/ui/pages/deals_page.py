from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QLineEdit, QMessageBox, QVBoxLayout

from app.core.constants import DEAL_STAGES
from app.services import CustomerService, DealService
from app.services.exceptions import ServiceError
from app.ui.dialogs import DealDialog
from app.ui.pages.base import CrudPage
from app.ui.widgets import (
    action_buttons,
    set_deal_stage_cell,
    filter_bar,
    format_money,
    make_button,
    make_table,
    page_heading,
    table_item,
)


class DealsPage(CrudPage):
    data_changed = Signal()

    def __init__(
        self, service: DealService, customer_service: CustomerService, parent=None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.customer_service = customer_service

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по сделке или клиенту…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.stage_filter = QComboBox()
        self.stage_filter.addItem("Все стадии", None)
        for stage in DEAL_STAGES:
            self.stage_filter.addItem(stage, stage)
        self.stage_filter.currentIndexChanged.connect(self.refresh)
        add_button = make_button("+  Добавить сделку", "primaryButton")
        add_button.clicked.connect(self.add_deal)

        toolbar_panel, toolbar = filter_bar()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.stage_filter)
        toolbar.addWidget(add_button)

        self.table = make_table(
            ["Название", "Клиент", "Стадия", "Сумма", "Закрытие", "Действия"]
        )
        self.table.itemClicked.connect(self._open_from_item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(page_heading("Сделки", "Продажи, стадии и планируемые даты закрытия"))
        layout.addWidget(toolbar_panel)
        layout.addWidget(self.table, 1)

    def refresh(self, *_args) -> None:
        deals = self.service.list(self.search.text(), self.stage_filter.currentData())
        self.table.setRowCount(len(deals))
        for row, item in enumerate(deals):
            values = [
                item.title,
                item.customer_name,
                "",  # Stage is displayed by the cell's menu button.
                format_money(item.amount),
                item.expected_close_date.strftime("%d.%m.%Y")
                if item.expected_close_date
                else "—",
            ]
            for column, value in enumerate(values):
                alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter if column == 3 else None
                cell = table_item(value, alignment)
                cell.setData(Qt.ItemDataRole.UserRole, item.id)
                self.table.setItem(row, column, cell)
            set_deal_stage_cell(
                self.table, row, item.stage,
                lambda stage, record_id=item.id: self.change_stage(record_id, stage),
            )
            self.table.setCellWidget(
                row,
                5,
                action_buttons(
                    lambda _checked=False, record_id=item.id: self.edit_deal(record_id),
                    lambda _checked=False, record_id=item.id, title=item.title: self.delete_deal(
                        record_id, title
                    ),
                ),
            )

        self.table.resizeColumnToContents(2)

    def add_deal(self) -> None:
        dialog = DealDialog(self.customer_service.list(), parent=self)
        if self.save_from_dialog(dialog, lambda values: self.service.create(**values)):
            self.refresh()
            self.data_changed.emit()

    def _open_from_item(self, cell) -> None:
        if cell.column() == 2:
            return
        deal_id = cell.data(Qt.ItemDataRole.UserRole)
        if deal_id:
            self.show_deal(deal_id)

    def change_stage(self, deal_id: int, stage: str) -> None:
        try:
            self.service.change_stage(deal_id, stage)
        except ServiceError as error:
            QMessageBox.warning(self, 'Не удалось изменить стадию', str(error))
            return
        except Exception as error:
            QMessageBox.critical(self, 'Ошибка сохранения', f'Стадия не сохранена:\n{error}')
            return
        self.refresh()
        self.data_changed.emit()

    def show_deal(self, deal_id: int) -> None:
        from app.ui.dialogs.detail_dialog import DetailDialog
        item = self.service.get(deal_id)
        DetailDialog(item.title, '', [
            ('Клиент', item.customer_name), ('Сумма', item.amount), ('Стадия', item.stage),
            ('Планируемое закрытие', item.expected_close_date), ('Описание', item.description),
            ('UUID', item.uuid), ('Создана', item.created_at), ('Изменена', item.updated_at),
        ], links=[(f'Открыть клиента: {item.customer_name}',
                   lambda: self._show_customer(item.customer_id))], parent=self).exec()

    def _show_customer(self, customer_id: int) -> None:
        from app.ui.dialogs.detail_dialog import DetailDialog
        item = self.customer_service.get(customer_id)
        DetailDialog(item.name, '', [
            ('Компания', item.company_name), ('Должность', item.position), ('Телефон', item.phone),
            ('Email', item.email), ('Telegram', item.telegram), ('Заметки', item.notes),
            ('UUID', item.uuid), ('Создан', item.created_at), ('Изменён', item.updated_at),
        ], parent=self).exec()

    def edit_deal(self, deal_id: int) -> None:
        dialog = DealDialog(self.customer_service.list(), self.service.get(deal_id), self)
        if self.save_from_dialog(dialog, lambda values: self.service.update(deal_id, **values)):
            self.refresh()
            self.data_changed.emit()

    def delete_deal(self, deal_id: int, title: str) -> None:
        if self.confirm_delete(f"сделку «{title}»", lambda: self.service.delete(deal_id)):
            self.refresh()
            self.data_changed.emit()
