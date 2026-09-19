from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.services import DashboardService
from app.ui.widgets import set_deal_stage_cell, format_money, make_table, page_heading, panel_layout, table_item


class MetricCard(QFrame):
    def __init__(self, label: str, variant: str = 'default', parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty('variant', variant)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("cardValue")
        self.value_label.setWordWrap(True)
        self.value_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label_widget = QLabel(label)
        label_widget.setObjectName("cardLabel")
        label_widget.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(label_widget)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class DashboardPage(QWidget):
    stage_change_requested = Signal(int, str)

    def __init__(self, service: DashboardService, parent=None) -> None:
        super().__init__(parent)
        self.service = service

        self.cards = [
            MetricCard("Клиенты"),
            MetricCard("Активные сделки"),
            MetricCard("Сумма активных сделок", "accent"),
            MetricCard("Задачи на сегодня"),
            MetricCard("Просрочено", "warning"),
        ]
        card_layout = QGridLayout()
        card_layout.setSpacing(12)
        for index, card in enumerate(self.cards):
            card_layout.addWidget(card, 0, index)
            card_layout.setColumnStretch(index, 1)

        deals_panel, deals_layout = panel_layout()
        title = QLabel("Последние сделки")
        title.setObjectName("sectionTitle")
        self.deals_table = make_table(["Название", "Клиент", "Стадия", "Сумма"])
        self.deals_table.horizontalHeader().setStretchLastSection(False)
        self.deals_table.setMinimumHeight(245)
        deals_layout.addWidget(title)
        deals_layout.addWidget(self.deals_table)

        tasks_panel, tasks_layout = panel_layout()
        title = QLabel("Ближайшие задачи")
        title.setObjectName("sectionTitle")
        self.tasks_table = make_table(["Задача", "Срок", "Приоритет", "Статус"])
        self.tasks_table.setMinimumHeight(245)
        tasks_layout.addWidget(title)
        tasks_layout.addWidget(self.tasks_table)

        lower = QHBoxLayout()
        lower.setSpacing(14)
        lower.addWidget(deals_panel, 1)
        lower.addWidget(tasks_panel, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(page_heading("Главная", "Краткая сводка по CRM на сегодня"))
        layout.addLayout(card_layout)
        layout.addLayout(lower, 1)

    def refresh(self) -> None:
        summary = self.service.get_summary()
        values = [
            str(summary.customer_count),
            str(summary.active_deal_count),
            format_money(summary.active_deal_amount),
            str(summary.tasks_today),
            str(summary.overdue_tasks),
        ]
        for card, value in zip(self.cards, values, strict=True):
            card.set_value(value)

        self.deals_table.setRowCount(len(summary.latest_deals))
        for row, item in enumerate(summary.latest_deals):
            # Stage is displayed by the cell's menu button, not the table item.
            values = [item.title, item.customer_name, "", format_money(item.amount)]
            for column, value in enumerate(values):
                alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter if column == 3 else None
                self.deals_table.setItem(row, column, table_item(value, alignment))
            set_deal_stage_cell(
                self.deals_table, row, item.stage,
                lambda stage, record_id=item.id: self.stage_change_requested.emit(record_id, stage),
            )
        self.deals_table.resizeColumnToContents(2)

        self.tasks_table.setRowCount(len(summary.upcoming_tasks))
        for row, item in enumerate(summary.upcoming_tasks):
            values = [
                item.title,
                item.due_date.strftime("%d.%m.%Y") if item.due_date else "—",
                item.priority,
                item.status,
            ]
            for column, value in enumerate(values):
                self.tasks_table.setItem(row, column, table_item(value))
