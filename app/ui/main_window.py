from __future__ import annotations

from datetime import timezone
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QDialog,
    QMessageBox,
)
from sqlalchemy.orm import sessionmaker

from app.services import CustomerService, DashboardService, DealService, TaskService
from app.ui.pages import CustomersPage, DashboardPage, DealsPage, TasksPage
from app.services.sync_service import SyncService
from app.ui.dialogs.sync_login_dialog import SyncLoginDialog
from app.ui.sync_worker import SyncWorker
from app.ui.pages.updates_page import UpdatesPage
from app.ui.widgets import ForestPanel, brand_pixmap

LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "crm-logo.png"


class MainWindow(QMainWindow):
    def __init__(self, session_factory: sessionmaker) -> None:
        super().__init__()
        self.setWindowTitle("АгроСмена CRM")
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.setMinimumSize(QSize(1120, 700))
        self.resize(1380, 820)
        self.sync_service = SyncService(session_factory)
        self.sync_worker = None

        customer_service = CustomerService(session_factory)
        deal_service = DealService(session_factory)
        task_service = TaskService(session_factory)

        self.dashboard_page = DashboardPage(DashboardService(session_factory))
        self.customers_page = CustomersPage(customer_service)
        self.deals_page = DealsPage(deal_service, customer_service)
        self.dashboard_page.stage_change_requested.connect(self.deals_page.change_stage)
        self.tasks_page = TasksPage(task_service, customer_service, deal_service)
        self.updates_page = UpdatesPage()
        self.updates_page.install_requested.connect(self._install_update)
        self.pages = [
            self.dashboard_page,
            self.customers_page,
            self.deals_page,
            self.tasks_page,
            self.updates_page,
        ]

        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)

        sidebar = self._build_sidebar()
        content = QWidget()
        content.setObjectName("contentRoot")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 8, 16)
        content_layout.setSpacing(4)
        content_layout.addWidget(sidebar)
        content_layout.addWidget(self.stack, 1)
        self.setCentralWidget(content)

        for page in (self.customers_page, self.deals_page, self.tasks_page):
            page.data_changed.connect(self._refresh_after_change)

        self.navigate(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = ForestPanel()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 26, 18, 20)
        layout.setSpacing(7)

        brand = QLabel()
        brand.setObjectName("brandLogo")
        brand.setAccessibleName("Логотип АгроСмена CRM")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_image = brand_pixmap(76, '#ffffff')
        brand_image.setDevicePixelRatio(2)
        brand.setPixmap(brand_image)
        brand.setFixedSize(38, 38)
        brand_name = QLabel('АгроСмена')
        brand_name.setObjectName('brand')
        brand_sub = QLabel("Рабочее пространство")
        brand_sub.setObjectName("brandSub")
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(3)
        brand_copy.addWidget(brand_name)
        brand_copy.addWidget(brand_sub)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_row.addWidget(brand)
        brand_row.addLayout(brand_copy, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(20)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, text in enumerate(("Главная", "Клиенты", "Сделки", "Задачи", "Настройки")):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, page=index: self.navigate(page))
            self.nav_group.addButton(button, index)
            layout.addWidget(button)

        self.login_button = QPushButton('Войти на сервер')
        self.login_button.setObjectName('navButton')
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._server_login)
        self.sync_button = QPushButton('Синхронизировать')
        self.sync_button.setObjectName('navButton')
        self.sync_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_button.clicked.connect(self._synchronize)
        self.logout_button = QPushButton('Выйти с сервера')
        self.logout_button.setObjectName('navButton')
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.clicked.connect(self._server_logout)
        self.sync_status = QLabel('Офлайн · вход не выполнен')
        self.sync_status.setObjectName('detailValue')
        self.sync_status.setWordWrap(True)
        state = self.sync_service.state()
        if self.sync_service.client:
            identity = self.sync_service.client.identity
            self.sync_status.setText(f"{identity['username']}\n{identity['organization_name']}\nТокен восстановлен")
        if state and state['last_sync_at']:
            if self.sync_service.client:
                self.sync_status.setText(self.sync_status.text() + '\nПоследний обмен: ' + self._sync_time(state['last_sync_at']))
            else:
                self.sync_status.setText('Последний обмен:\n' + self._sync_time(state['last_sync_at']))
        self._update_server_buttons()
        layout.addStretch()
        self.updates_page.connection_layout.addWidget(self.sync_status)
        layout.addWidget(self.login_button)
        layout.addWidget(self.sync_button)
        layout.addWidget(self.logout_button)
        storage = QLabel("Работает без интернета\nРучной обмен с сервером")
        storage.setObjectName("detailValue")
        self.updates_page.connection_layout.addWidget(storage)
        self.updates_page.connection_layout.addStretch()
        return sidebar

    def navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button:
            button.setChecked(True)
        self.pages[index].refresh()

    def _refresh_after_change(self) -> None:
        self.dashboard_page.refresh()
        current = self.stack.currentWidget()
        if current is not None and current is not self.dashboard_page:
            current.refresh()

    @staticmethod
    def _sync_time(stamp):
        return stamp.replace(tzinfo=timezone.utc).astimezone().strftime('%d.%m.%Y %H:%M:%S')

    def _run_sync_operation(self, operation, success):
        if self.sync_worker is not None:
            return
        self.centralWidget().setEnabled(False)
        worker = SyncWorker(operation, self)
        self.sync_worker = worker
        worker.succeeded.connect(success)
        worker.failed.connect(self._sync_error)
        worker.finished.connect(self._sync_finished)
        worker.start()

    def _sync_finished(self):
        worker = self.sync_worker
        self.sync_worker = None
        self.centralWidget().setEnabled(True)
        self._update_server_buttons()
        if worker:
            worker.deleteLater()

    def _sync_error(self, message):
        self.sync_status.setText('Ошибка синхронизации')
        self.sync_status.setToolTip(message)
        QMessageBox.warning(self, 'Синхронизация', message)

    def _server_login(self):
        state = self.sync_service.state()
        dialog = SyncLoginDialog(state['server_url'] if state else 'http://127.0.0.1:8000', self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        credentials = dialog.credentials()
        dialog.password.clear()
        self.sync_status.setText('Вход на сервер…')
        self._run_sync_operation(lambda: self.sync_service.login(*credentials), self._login_succeeded)

    def _login_succeeded(self, identity):
        self.sync_status.setText(f"{identity['username']}\n{identity['organization_name']}\nГотово к синхронизации")
        self.sync_status.setToolTip('')
        self._update_server_buttons()

    def _server_logout(self):
        self.sync_service.logout(forget=True)
        self.sync_status.setText('Офлайн · вход не выполнен')
        self._update_server_buttons()

    def _update_server_buttons(self):
        logged_in = bool(self.sync_service.client and self.sync_service.client.token)
        self.login_button.setVisible(not logged_in)
        self.sync_button.setVisible(logged_in)
        self.logout_button.setVisible(logged_in)
        self.logout_button.setEnabled(logged_in)

    def _synchronize(self):
        if not self.sync_service.client or not self.sync_service.client.token:
            self._server_login()
            return
        first = self.sync_service.state() is None
        if first:
            organization = self.sync_service.client.identity['organization_name']
            answer = QMessageBox.question(self, 'Привязка локальной базы',
                f'Привязать эту базу SQLite к организации «{organization}»?\n\n'
                'Все локальные записи и отметки удаления будут отправлены на сервер. '
                'Данные сервера будут загружены сюда. Переключение этой базы на другую организацию будет запрещено.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.sync_status.setText('Синхронизация…')
        self._run_sync_operation(lambda: self.sync_service.synchronize(confirm_binding=first), self._sync_succeeded)

    def _sync_succeeded(self, stamp):
        self.sync_status.setText('Синхронизировано\n' + self._sync_time(stamp))
        self.sync_status.setToolTip('')
        for page in self.pages:
            page.refresh()

    def closeEvent(self, event):
        if self.sync_worker is not None or self.updates_page.worker is not None:
            event.ignore()
            self.statusBar().showMessage('Дождитесь завершения синхронизации или загрузки обновления.')
            return
        self.sync_service.logout()
        super().closeEvent(event)

    def _install_update(self, staged):
        if self.sync_worker is not None:
            self.updates_page.status.setText('Дождитесь завершения синхронизации и нажмите «Обновить» ещё раз.')
            return
        try:
            self.updates_page.service.launch(staged)
        except Exception as error:
            QMessageBox.critical(self, 'Обновление', str(error))
            return
        self.close()
