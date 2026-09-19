from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout, QLabel
from app.ui.widgets import page_heading


class SyncLoginDialog(QDialog):
    def __init__(self, server_url='http://127.0.0.1:8000', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Вход на сервер CRM')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        layout.addWidget(page_heading('С возвращением', 'Войдите в рабочее пространство вашей команды'))
        form = QFormLayout()
        form.setSpacing(14)
        self.server = QLineEdit(server_url)
        self.username = QLineEdit()
        self.username.setPlaceholderText('Введите ваш логин')
        self.password = QLineEdit()
        self.password.setPlaceholderText('Введите пароль')
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Сервер', self.server)
        form.addRow('Логин', self.username)
        form.addRow('Пароль', self.password)
        layout.addLayout(form)
        hint = QLabel('Пароль не сохраняется. Токен входа сохраняется в SQLite\nв зашифрованном виде и доступен только этому пользователю Windows.')
        hint.setWordWrap(True)
        hint.setObjectName('pageSubtitle')
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Войти')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName('primaryButton')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def credentials(self):
        return self.server.text().strip(), self.username.text().strip(), self.password.text()
