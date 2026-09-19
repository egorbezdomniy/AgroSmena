from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.ui.widgets import format_money, page_heading


def display(value):
    if value in (None, ''):
        return '—'
    if isinstance(value, datetime):
        return value.strftime('%d.%m.%Y %H:%M:%S')
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    if isinstance(value, Decimal):
        return format_money(value)
    return str(value)


class DetailDialog(QDialog):
    def __init__(self, title, subtitle, fields, *, links=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)
        root.addWidget(page_heading(title, subtitle))
        panel = QFrame()
        panel.setObjectName('detailPanel')
        grid = QGridLayout(panel)
        grid.setContentsMargins(22, 20, 22, 20)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(13)
        for row, (label, value) in enumerate(fields):
            name = QLabel(label)
            name.setObjectName('detailLabel')
            name.setAlignment(Qt.AlignmentFlag.AlignTop)
            content = QLabel(display(value))
            content.setObjectName('detailValue')
            content.setWordWrap(True)
            content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(content, row, 1)
        grid.setColumnStretch(1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        root.addWidget(scroll, 1)
        if links:
            holder = QWidget()
            link_layout = QVBoxLayout(holder)
            link_layout.setContentsMargins(0, 0, 0, 0)
            for label, callback in links:
                button = QPushButton(label)
                button.setObjectName('secondaryButton')
                button.clicked.connect(callback)
                link_layout.addWidget(button)
            root.addWidget(holder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Закрыть')
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
