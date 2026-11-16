"""Feuille de style commune : lisibilité, couleurs d'état cohérentes (§5.1)."""
from __future__ import annotations

STYLESHEET = """
QMainWindow, QDialog { background: #f7f9fc; }
QWidget { font-size: 13px; color: #1f2a35; }

QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit {
    background: #ffffff; border: 1px solid #c9d3de; border-radius: 5px;
    padding: 5px 7px; min-height: 20px;
}
QSpinBox, QDateEdit { padding-right: 20px; }
QSpinBox::up-button, QDateEdit::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border-left: 1px solid #dde3ea; border-top-right-radius: 5px;
    background: #f2f5f8;
}
QSpinBox::down-button, QDateEdit::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border-left: 1px solid #dde3ea; border-bottom-right-radius: 5px;
    background: #f2f5f8;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDateEdit::up-button:hover, QDateEdit::down-button:hover { background: #e2e9f1; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
    border: 1px solid #2f6f9f;
}

QPushButton {
    background: #ffffff; border: 1px solid #c9d3de; border-radius: 5px;
    padding: 6px 12px; color: #1f2a35;
}
QPushButton:hover { background: #eef3f8; border-color: #a9bccd; }
QPushButton:pressed { background: #e2e9f1; }
QPushButton:disabled { color: #9aa7b4; background: #f2f5f8; }

QPushButton#PrimaryButton {
    background: #1d6a3f; border: 1px solid #14512f; color: #ffffff;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #247f4c; }
QPushButton#PrimaryButton:disabled { background: #a9c6b6; border-color: #a9c6b6; }

QTableWidget {
    background: #ffffff; border: 1px solid #dde3ea; border-radius: 6px;
    gridline-color: #eef2f6; selection-background-color: #dcebf7;
    selection-color: #12324f; alternate-background-color: #fafbfd;
}
QHeaderView::section {
    background: #eef3f8; color: #33475b; border: none;
    border-right: 1px solid #dde3ea; border-bottom: 1px solid #dde3ea;
    padding: 6px 8px; font-weight: 600;
}
QTabWidget::pane { border: 1px solid #dde3ea; border-radius: 6px;
                   background: #ffffff; top: -1px; }
QTabBar::tab { background: #eef3f8; border: 1px solid #dde3ea;
               border-bottom: none; padding: 7px 14px;
               border-top-left-radius: 6px; border-top-right-radius: 6px;
               margin-right: 2px; color: #46586b; }
QTabBar::tab:selected { background: #ffffff; color: #12324f; font-weight: 600; }
QListWidget { background: #ffffff; border: 1px solid #dde3ea;
              border-radius: 6px; }
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: #dcebf7; color: #12324f; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #c3cfdb; border-radius: 5px;
                              min-height: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QCheckBox { spacing: 6px; }
QLabel { background: transparent; }
"""


def apply_theme(application) -> None:
    """Applique la feuille de style globale à l'application Qt."""
    try:
        application.setStyle("Fusion")
    except Exception:  # pragma: no cover - plateforme sans styles Qt
        pass
    application.setStyleSheet(STYLESHEET)
