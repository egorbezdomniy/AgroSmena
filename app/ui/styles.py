from pathlib import Path


COMBO_ARROW = (Path(__file__).resolve().parents[2] / 'assets' / 'chevron-down.svg').as_posix()

APP_STYLESHEET = """
QWidget { font-family: "Segoe UI"; font-size: 13px; color: #193b30; }
QLabel { background: transparent; }
QToolTip { background: #ffffff; color: #193b30; border: 1px solid #dce5db; padding: 6px; }
QMainWindow, QWidget#contentRoot {
    background: #f6f8f5; color: #193b30; font-family: "Segoe UI"; font-size: 13px;
}
QFrame#sidebar, QFrame#pageHero { background: transparent; border: none; }
QLabel#brand { color: white; font-size: 21px; font-weight: 600; padding: 0; }
QLabel#brandSub { color: #b4c9b9; font-size: 11px; }
QPushButton#navButton {
    color: #c7d9cb; background: transparent; border: 1px solid transparent; border-radius: 9px;
    padding: 12px 15px; text-align: left; font-size: 14px;
}
QPushButton#navButton:hover { background: #214b39; color: white; }
QPushButton#navButton:checked { background: #2a5744; border-color: #52755b; color: white; font-weight: 600; }
QLabel#pageTitle { font-size: 27px; font-weight: 600; color: #193b30; }
QLabel#pageSubtitle, QLabel#detailLabel { color: #708077; font-size: 12px; }
QLabel#detailTitle { color: #193b30; font-size: 22px; font-weight: 700; }
QLabel#detailValue { color: #344d40; font-size: 13px; }
QFrame#card, QFrame#panel, QFrame#detailPanel, QFrame#filterPanel {
    background: white; border: 1px solid #e2e9e1; border-radius: 20px;
}
QLabel#cardLabel { color: #708077; font-size: 12px; }
QLabel#cardValue { color: #193b30; font-size: 25px; font-weight: 700; }
QLabel#sectionTitle { color: #345742; font-size: 16px; font-weight: 650; }
QPushButton#primaryButton {
    background: #103c2f; color: white; border: 1px solid #103c2f;
    border-radius: 10px; padding: 9px 15px; font-weight: 600;
}
QPushButton#primaryButton:hover { background: #1c5541; border-color: #1c5541; }
QPushButton#primaryButton:disabled { background: #9bb49b; border-color: #9bb49b; }
QPushButton#secondaryButton {
    background: white; color: #344d40; border: 1px solid #dce5db;
    border-radius: 10px; padding: 8px 12px; font-weight: 600;
}
QPushButton#secondaryButton:hover { background: #edf3e9; color: #103c2f; }
QPushButton#dangerButton {
    background: #fff0ec; color: #9f4535; border: 1px solid #f3d7cf;
    border-radius: 10px; padding: 8px 12px; font-weight: 600;
}
QPushButton#dangerButton:hover { background: #fbe4dd; }
QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QTextEdit {
    background: white; color: #284333; border: 1px solid #dce5da;
    border-radius: 10px; padding: 8px 10px; selection-background-color: #103c2f;
    selection-color: white;
}
QComboBox { padding-right: 38px; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 30px; margin: 3px; border: none; border-left: 1px solid #dce5da;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
    background: #f4f8f1;
}
QComboBox::drop-down:hover { background: #edf3e9; }
QComboBox::down-arrow { image: url("__COMBO_ARROW__"); width: 12px; height: 8px; }
QComboBox::down-arrow:on { top: 1px; }
QComboBox QAbstractItemView {
    background-color: white; color: #284333; border: none;
    border-radius: 6px; outline: 0; padding: 4px;
    selection-background-color: #e8f1e2; selection-color: #315b3d;
}
QComboBoxPrivateContainer {
    background-color: white; border: 1px solid #dce5da; border-radius: 7px;
    padding: 0; margin: 0;
}
QComboBox QAbstractItemView::item { min-height: 30px; padding: 4px 8px; border: none; }
QComboBox QAbstractItemView::item:hover { background-color: #f4f8f1; color: #315b3d; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border: 1px solid #103c2f;
}
QTableWidget {
    background: white; color: #284333; selection-background-color: #e8f1e2;
    selection-color: #315b3d; alternate-background-color: #f5f8f2;
    border: none; border-radius: 0; gridline-color: #edf1eb;
}
QTableWidget::item:hover { background: #f4f8f1; }
QHeaderView::section {
    background: #f5f8f2; color: #708077; border: none;
    border-bottom: 1px solid #e2e9e1; padding: 9px; font-weight: 600;
}
QTableCornerButton::section { background: #f5f8f2; border: none; border-bottom: 1px solid #e2e9e1; }
QTableWidget::item { padding: 7px; }
QDialog { background: #f6f8f5; }
QDialog QLabel { color: #344d40; }
QDialog QCheckBox { color: #284333; }
QDialogButtonBox QPushButton {
    color: #344d40; border: 1px solid #dce5db; border-radius: 10px;
    padding: 8px 16px; background: white; font-weight: 600;
}
QDialogButtonBox QPushButton:hover { background: #edf3e9; color: #103c2f; }
QScrollArea { border: none; background: transparent; }
QProgressBar#updateProgress {
    background: white; color: #344d40; border: 1px solid #dce5db;
    border-radius: 10px; min-height: 22px; text-align: center;
}
QProgressBar#updateProgress::chunk { background: #6f9e7a; border-radius: 7px; }

/* Forest headers and brand treatment shared by all desktop pages. */
QFrame#pageHero QLabel#pageTitle { color: white; font-size: 27px; font-weight: 600; }
QFrame#pageHero QLabel#pageSubtitle { color: #c1d0c4; font-size: 12px; }
QFrame#sidebar QLabel#navCaption { color: #b4c9b9; font-size: 10px; padding: 10px 12px; }
QPushButton#navButton:pressed { background: #37654f; color: white; }
QPushButton#navButton:disabled { color: #849b88; }
QPushButton#navButton:focus { border: 1px solid #a8c4ae; }
QPushButton#motionButton {
    background: transparent; color: #b4c9b9; border: 1px solid #41634b;
    border-radius: 7px; font-size: 10px; padding: 5px 9px; text-align: left;
}
QPushButton#motionButton:hover { background: #2a5744; color: white; }
QFrame#card[variant="accent"] { background: #103c2f; border-color: #103c2f; }
QFrame#card[variant="accent"] QLabel#cardLabel { color: #c2d3bd; }
QFrame#card[variant="accent"] QLabel#cardValue { color: white; font-size: 21px; }
QFrame#card[variant="warning"] QLabel#cardValue { color: #a5623e; }
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QDoubleSpinBox:hover, QTextEdit:hover {
    border-color: #afc2b1;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QDoubleSpinBox:disabled {
    background: #f0f3ec; color: #859180; border-color: #e2e9e1;
}
QPushButton#primaryButton:pressed { background: #0c3025; }
QPushButton#secondaryButton:pressed { background: #e1ebdb; }
QPushButton#secondaryButton:disabled, QDialogButtonBox QPushButton:disabled {
    color: #899684; background: #f3f5ef; border-color: #e2e9e1;
}
QPushButton#primaryButton:focus, QPushButton#secondaryButton:focus,
QPushButton#dangerButton:focus { border: 2px solid #719777; }
QDialogButtonBox QPushButton#primaryButton {
    background: #103c2f; color: white; border-color: #103c2f;
}
QDialogButtonBox QPushButton#primaryButton:hover { background: #1c5541; }
QScrollBar:vertical { width: 10px; background: #f0f4ed; margin: 0; border-radius: 5px; }
QScrollBar::handle:vertical { background: #c2d0bd; min-height: 30px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #9cb494; }
QScrollBar:horizontal { height: 10px; background: #f0f4ed; margin: 0; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #c2d0bd; min-width: 30px; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: #f6f8f5; color: #708077; }
QPushButton#stageButton {
    color: #315b3d; background: #edf4e6; border: 1px solid #d4e2c8;
    border-radius: 8px; padding: 6px 26px 6px 18px; text-align: center;
}
QPushButton#stageButton:hover, QPushButton#stageButton:focus { background: #e1eed8; border-color: #91ad81; }
QPushButton#stageButton::menu-indicator { subcontrol-position: right center; right: 10px; }
QMenu { background: white; color: #193b30; border: 1px solid #dce5db; padding: 6px; }
QMenu::item { padding: 8px 28px; border-radius: 5px; }
QMenu::item:selected { background: #e8f1e2; color: #103c2f; }
QMenu::item:disabled { color: #708077; }
QTabWidget::pane { border: none; padding-top: 12px; }
QTabBar::tab {
    color: #607765; background: #edf3e9; border: 1px solid #dce5db;
    border-radius: 8px; padding: 10px 18px; margin-right: 8px;
}
QTabBar::tab:selected { color: white; background: #103c2f; border-color: #103c2f; }
QTabBar::tab:hover:!selected { background: #e1ebdb; }
""".replace('__COMBO_ARROW__', COMBO_ARROW)
