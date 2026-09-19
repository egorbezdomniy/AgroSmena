from __future__ import annotations

from decimal import Decimal
from math import sin

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ForestPanel(QFrame):
    """Lightweight contour background; only visible, active windows animate."""

    motion_enabled = True

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)
        QApplication.instance().applicationStateChanged.connect(self._sync_animation)

    @classmethod
    def set_motion_enabled(cls, enabled: bool) -> None:
        cls.motion_enabled = enabled
        for widget in QApplication.allWidgets():
            if isinstance(widget, cls):
                widget._sync_animation()

    def _sync_animation(self, *_args) -> None:
        active = (self.motion_enabled and self.isVisible() and not self.window().isMinimized()
                  and QApplication.applicationState() == Qt.ApplicationState.ApplicationActive)
        if active and not self._timer.isActive():
            self._timer.start()
        elif not active:
            self._timer.stop()

    def _advance(self) -> None:
        self._phase = (self._phase + .027) % (2 * 3.141592653589793)
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(bounds, 22, 22)
        painter.setClipPath(clip)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor('#0c3329'))
        gradient.setColorAt(1, QColor('#204e39'))
        painter.fillPath(clip, gradient)
        width, height = self.width(), self.height()
        sidebar = self.objectName() == 'sidebar'
        painter.setPen(QPen(QColor(196, 220, 184, 15 if sidebar else 23), .8))
        for index in range(30):
            p = index / 29
            wave = sin(self._phase + p * 2.4)
            line = QPainterPath()
            line.moveTo(-width * .12, height * (.62 + p * .58))
            line.cubicTo(width * .32, height * (1.2 + wave * .025),
                         width * (.58 + wave * .025), height * (-.3 + p * .8),
                         width * 1.12, height * (.20 + p * .8))
            painter.drawPath(line)


def brand_pixmap(size: int = 40, color: str = '#103c2f') -> QPixmap:
    """The same four-part mark as the website, with no external asset dependency."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 40, size / 40)
    petal = QPainterPath()
    petal.moveTo(3, 3)
    petal.lineTo(14, 3)
    petal.quadTo(20, 3, 20, 9)
    petal.lineTo(20, 20)
    petal.lineTo(9, 20)
    petal.quadTo(3, 20, 3, 14)
    petal.closeSubpath()
    for index in range(4):
        painter.setOpacity(.64 if index % 2 else 1)
        painter.fillPath(petal, QColor(color))
        painter.translate(20, 20)
        painter.rotate(90)
        painter.translate(-20, -20)
    painter.end()
    return pixmap


class RoundedOutline(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QPainterPath()
        outer.addRect(QRectF(self.rect()))
        rounded = QPainterPath()
        rounded.addRoundedRect(QRectF(self.rect().adjusted(1, 1, -1, -1)), 14, 14)
        table_parent = self.parentWidget().parentWidget()
        background = '#ffffff' if table_parent and table_parent.objectName() == 'panel' else '#f6f8f5'
        painter.fillPath(outer.subtracted(rounded), QColor(background))
        painter.setPen(QPen(QColor('#e2e9e1'), 1))
        painter.drawPath(rounded)


class RoundedTableWidget(QTableWidget):
    """Draw one smooth outline above headers and the internal viewport."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rounded_outline = RoundedOutline(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rounded_outline.setGeometry(self.rect())
        self._rounded_outline.raise_()


def page_heading(title: str, subtitle: str = '') -> QWidget:
    widget = ForestPanel()
    widget.setObjectName('pageHero')
    widget.setMinimumHeight(106 if subtitle else 80)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(26, 22, 26, 22)
    layout.setSpacing(7)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    title_label.setWordWrap(True)
    title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return widget


def make_button(text: str, object_name: str = "secondaryButton") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def make_table(columns: list[str]) -> QTableWidget:
    table = RoundedTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(56)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setShowGrid(False)
    return table


def table_item(value: object, alignment: Qt.AlignmentFlag | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem("" if value is None else str(value))
    if alignment is not None:
        item.setTextAlignment(alignment)
    return item


def action_buttons(on_edit, on_delete) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(6)
    edit = make_button("Изменить")
    delete = make_button("Удалить", "dangerButton")
    edit.setMinimumSize(108, 38)
    delete.setMinimumSize(92, 38)
    widget.setMinimumHeight(48)
    edit.clicked.connect(on_edit)
    delete.clicked.connect(on_delete)
    layout.addStretch()
    layout.addWidget(edit)
    layout.addWidget(delete)
    layout.addStretch()
    return widget


def deal_stage_button(stage: str, on_change) -> QWidget:
    from app.core.constants import DEAL_STAGES

    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(8, 7, 8, 7)
    button = make_button(stage, 'stageButton')

    button.setToolTip('Нажмите, чтобы изменить стадию сделки')
    button.setAccessibleName(f'Изменить стадию сделки: {stage}')
    menu = QMenu(button)
    for value in DEAL_STAGES:
        action = menu.addAction(value)
        action.setCheckable(True)
        action.setChecked(value == stage)
        action.setEnabled(value != stage)
        action.triggered.connect(lambda _checked=False, selected=value: on_change(selected))
    button.setMenu(menu)
    button.ensurePolished()
    text_width = max(button.fontMetrics().horizontalAdvance(value) for value in DEAL_STAGES)
    button.setFixedSize(max(152, text_width + 56), max(36, button.sizeHint().height()))
    holder.setMinimumSize(button.width() + 16, button.height() + 14)
    layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return holder


def set_deal_stage_cell(table: QTableWidget, row: int, stage: str, on_change) -> None:
    holder = deal_stage_button(stage, on_change)
    cell = table.item(row, 2)
    if cell is None:
        cell = table_item('')
        table.setItem(row, 2, cell)
    cell.setText('')
    cell.setSizeHint(holder.minimumSize())
    table.setRowHeight(row, max(table.rowHeight(row), holder.minimumHeight() + 2))
    table.setCellWidget(row, 2, holder)


def panel_layout() -> tuple[QFrame, QVBoxLayout]:
    panel = QFrame()
    panel.setObjectName("panel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)
    return panel, layout


def filter_bar() -> tuple[QFrame, QHBoxLayout]:
    panel = QFrame()
    panel.setObjectName('filterPanel')
    layout = QHBoxLayout(panel)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(12)
    return panel, layout


def format_money(amount: Decimal | float) -> str:
    return f"{amount:,.2f} ₽".replace(",", " ")
