"""Application entry point for the local desktop CRM."""

from __future__ import annotations

import sys
import tempfile
import json
import logging
import os
import subprocess
from pathlib import Path
from updatekit.locking import AppLock


def main() -> int:
    # Recovery gate runs before importing possibly patched Qt/SQLAlchemy modules.
    from app.core.config import USER_ROOT, DATABASE_PATH, PROJECT_ROOT

    smoke_test = "--smoke-test" in sys.argv
    probe = '--update-verify' in sys.argv
    smoke_directory = tempfile.TemporaryDirectory(prefix="agrosmena-smoke-") if smoke_test else None
    user_root = Path(smoke_directory.name) if smoke_directory else USER_ROOT
    (user_root / 'logs').mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=user_root / 'logs' / 'crm.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    journal_path = user_root / 'updates' / 'transaction.json'
    lock = None
    try:
        if probe:
            journal = json.loads(journal_path.read_text(encoding='utf-8'))
            if journal['phase'] != 'verifying' or journal['probe_token'] != os.environ.get('AGROSMENA_UPDATE_PROBE'):
                raise RuntimeError('Invalid update startup probe')
        else:
            lock = AppLock(user_root)
            lock.__enter__()
            if journal_path.exists():
                recovery = json.loads((user_root / 'updates' / 'recovery.json').read_text(encoding='utf-8'))
                subprocess.Popen([recovery['runner'], '--plan', recovery['plan'], '--recover',
                                  '--parent-pid', str(os.getpid())], close_fds=True)
                return 0
        return run_gui(smoke_test, probe, smoke_directory)
    except Exception:
        logging.exception('CRM startup failed')
        if sys.stderr:
            import traceback
            traceback.print_exc()
        if not smoke_test and not probe and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 'Не удалось запустить CRM. Другой экземпляр может быть открыт.\n'
                f'Подробности: {user_root / "logs" / "crm.log"}', 'АгроСмена CRM', 0x10)
        return 1
    finally:
        if lock:
            lock.__exit__()
        if smoke_directory:
            logging.shutdown()
            smoke_directory.cleanup()


def run_gui(smoke_test, probe, smoke_directory):
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.core.config import DATABASE_PATH, PROJECT_ROOT
    from app.core.database import Database
    from app.core.migrations import import_legacy_database
    from app.ui.main_window import LOGO_PATH, MainWindow
    from app.ui.styles import APP_STYLESHEET

    if sys.platform == "win32":
        import ctypes

        # Give the running CRM its own taskbar identity instead of Python's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AgroSmena.CRM.Desktop")
    app = QApplication(sys.argv)
    app.setApplicationName("АгроСмена CRM")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    try:
        if not smoke_test and not probe:
            import_legacy_database(DATABASE_PATH, PROJECT_ROOT / 'data' / 'crm.db')
        database = Database(Path(smoke_directory.name) / "crm.db") if smoke_directory else Database()
        database.create_tables()
        window = MainWindow(database.session_factory)
        if smoke_test or probe:
            from PySide6.QtWidgets import QLabel

            logo = window.findChild(QLabel, "brandLogo")
            if window.windowIcon().isNull() or logo is None or logo.pixmap().isNull():
                raise RuntimeError("Application logo was not bundled")
            if logo.pixmap().deviceIndependentSize().width() != 38:
                raise RuntimeError("Unexpected sidebar logo size")
            for index in range(len(window.pages)):
                window.navigate(index)
                app.processEvents()
            window.close()
            return 0
        window.show()
        logging.info('CRM ready; pid=%s', os.getpid())
        return app.exec()
    except Exception as error:  # pragma: no cover - last-resort GUI error handler
        logging.exception('Database migration or GUI initialization failed')
        if smoke_test or probe:
            if sys.stderr is not None:
                import traceback

                traceback.print_exc()
            return 1
        QMessageBox.critical(
            None,
            "Ошибка запуска",
            f"Не удалось запустить приложение:\n{error}",
        )
        return 1
    finally:
        if "database" in locals():
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
