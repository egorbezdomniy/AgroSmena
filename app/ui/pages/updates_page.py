from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QProgressBar, QScrollArea, QTabWidget, QTextEdit, QVBoxLayout, QWidget

from app.services.update_service import UpdateService
from app.ui.widgets import ForestPanel, make_button, page_heading, panel_layout


class UpdateWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation(self.progress.emit))
        except Exception as error:
            self.failed.emit(str(error))


class UpdatesPage(QWidget):
    install_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = UpdateService()
        self.worker = None
        self.chain = []
        self.staged = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(page_heading('Настройки', 'Обновления, подключение и оформление'))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        panel, fields = panel_layout()
        self.current = QLabel(f'Текущая версия: {self.service.current_version}')
        self.latest = QLabel('Последняя версия: ещё не проверена')
        self.endpoint = QLineEdit(self.service.endpoint())
        self.endpoint.setPlaceholderText('https://ваш-сервер/api/app/update/')
        self.endpoint.setAccessibleName('HTTPS адрес каталога обновлений')
        self.check_button = make_button('Проверить обновления')
        self.update_button = make_button('Обновить и перезапустить', 'primaryButton')
        self.update_button.setEnabled(False)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText('Здесь появится описание изменений')
        self.progress = QProgressBar()
        self.progress.setObjectName('updateProgress')
        self.progress.setRange(0, 100)
        self.status = QLabel('Укажите HTTPS адрес сервера обновлений.')
        self.status.setWordWrap(True)
        for widget in (self.current, self.latest, QLabel('Сервер обновлений'), self.endpoint, self.check_button,
                       self.notes, self.progress, self.status, self.update_button):
            if isinstance(widget, QLabel):
                widget.setObjectName('detailValue')
            fields.addWidget(widget)
        updates_scroll = QScrollArea()
        updates_scroll.setWidgetResizable(True)
        updates_scroll.setWidget(panel)
        tabs.addTab(updates_scroll, 'Обновления')
        connection_panel, self.connection_layout = panel_layout()
        connection_title = QLabel('Состояние подключения')
        connection_title.setObjectName('sectionTitle')
        self.connection_layout.addWidget(connection_title)
        tabs.addTab(connection_panel, 'Подключение')
        appearance_panel, appearance_layout = panel_layout()
        appearance_title = QLabel('Фоновая анимация')
        appearance_title.setObjectName('sectionTitle')
        appearance_layout.addWidget(appearance_title)
        self.motion_button = make_button('Приостановить фон')
        self.motion_button.setCheckable(True)
        self.motion_button.setChecked(not ForestPanel.motion_enabled)
        self.motion_button.setText('Приостановить фон' if ForestPanel.motion_enabled else 'Включить фон')
        self.motion_button.toggled.connect(self._toggle_motion)
        appearance_layout.addWidget(self.motion_button)
        appearance_layout.addStretch()
        tabs.addTab(appearance_panel, 'Оформление')
        self.check_button.clicked.connect(self.check)
        self.update_button.clicked.connect(self.install)
        result = self.service.last_result()
        if result:
            self.status.setText(('Обновление установлено.' if result['status'] == 'installed' else 'Выполнен откат обновления.')
                                + ('\n' + result['error'] if result.get('error') else ''))

    def _toggle_motion(self, paused):
        ForestPanel.set_motion_enabled(not paused)
        self.motion_button.setText('Включить фон' if paused else 'Приостановить фон')

    def refresh(self):
        pass

    def _run(self, operation, success):
        if self.worker:
            return
        self.check_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.endpoint.setEnabled(False)
        self.worker = UpdateWorker(operation, self)
        self.worker.progress.connect(self._progress)
        self.worker.succeeded.connect(success)
        self.worker.failed.connect(self._error)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _progress(self, value, message):
        self.progress.setValue(value)
        self.status.setText(message)

    def _error(self, message):
        self.status.setText('Ошибка обновления: ' + message)

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.check_button.setEnabled(True)
        self.endpoint.setEnabled(True)
        self.update_button.setEnabled(bool(self.chain))
        if self.staged:
            staged, self.staged = self.staged, None
            self.install_requested.emit(staged)

    def check(self):
        endpoint = self.endpoint.text().strip()
        self.chain = []
        self.progress.setValue(0)
        self.status.setText('Проверка обновлений…')
        self._run(lambda progress: self.service.check(endpoint), self._checked)

    def _checked(self, result):
        self.chain = result['chain']
        catalog = result['catalog']
        self.latest.setText('Последняя версия: ' + catalog['latest_version'])
        notes = [catalog.get('release_notes', '')]
        notes.extend(p['to_version'] + '\n' + p.get('release_notes', '') for p in self.chain)
        self.notes.setPlainText('\n\n'.join(n for n in notes if n))
        mandatory = catalog.get('mandatory') or any(p.get('mandatory') for p in self.chain)
        self.status.setText(('Обязательное обновление доступно.' if mandatory else 'Обновление доступно.')
                            if self.chain else 'У вас актуальная версия.')

    def install(self):
        chain = list(self.chain)
        self.status.setText('Загрузка патчей… После проверки приложение перезапустится.')
        self._run(lambda progress: self.service.stage_updater(self.service.download(chain, progress)),
                  lambda staged: setattr(self, 'staged', staged))
