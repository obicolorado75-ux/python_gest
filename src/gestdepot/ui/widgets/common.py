"""Composants réutilisables de l'interface (§5.1)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...domain.rules import format_xof

STATUS_COLORS = {
    "ok": "#1B7F3B",
    "sous_seuil": "#B26A00",
    "rupture": "#B3261E",
}


def money(amount: int | float | None) -> str:
    return format_xof(int(round(amount or 0)))


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageTitle")
    label.setStyleSheet("font-size: 20px; font-weight: 600;")
    return label


def subtitle_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageSubtitle")
    label.setStyleSheet("color: #5f6b7a;")
    label.setWordWrap(True)
    return label


def card(title: str, value: str = "", hint: str = "") -> QFrame:
    """Petite carte d'indicateur du tableau de bord.

    Les libellés sont exposés via les propriétés ``value_label`` et ``hint_label``
    afin d'être mis à jour sans reconstruire le widget.
    """
    frame = QFrame()
    frame.setObjectName("Card")
    frame.setFrameShape(QFrame.StyledPanel)
    frame.setStyleSheet(
        "#Card {background: #ffffff; border: 1px solid #dde3ea; border-radius: 8px;}")
    frame.setMinimumHeight(86)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    heading = QLabel(title.upper())
    heading.setStyleSheet("color: #5f6b7a; font-size: 11px; letter-spacing: 1px;")
    amount = QLabel(value)
    amount.setObjectName("CardValue")
    amount.setStyleSheet("font-size: 18px; font-weight: 700; color: #12324f;")
    layout.addWidget(heading)
    layout.addWidget(amount)
    note = QLabel(hint)
    note.setStyleSheet("color: #7a8794; font-size: 11px;")
    note.setWordWrap(True)
    layout.addWidget(note)
    frame.value_label = amount
    frame.hint_label = note
    return frame


class DataTable(QTableWidget):
    """Tableau en lecture seule : tri, sélection par ligne, colonnes nommées."""

    def __init__(self, headers: list[str], parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setDefaultSectionSize(130)
        self.setShowGrid(False)
        self.setMinimumHeight(120)

    def load(self, rows: list[list], numeric_columns: set[int] | None = None,
             colors: dict[int, dict[str, str]] | None = None) -> None:
        numeric_columns = numeric_columns or set()
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if isinstance(value, int) and c in numeric_columns:
                    item = QTableWidgetItem()
                    item.setData(Qt.DisplayRole, value)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item = QTableWidgetItem("" if value is None else str(value))
                self.setItem(r, c, item)
            if colors:
                for column, mapping in colors.items():
                    text = str(row[column]) if column < len(row) else ""
                    color = mapping.get(text)
                    if color and column < len(row):
                        self.item(r, column).setForeground(QColor(color))
        self.setSortingEnabled(True)
        self.resizeColumnsToContents()

    def selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        return rows[0].row() if rows else None

    def value(self, row: int, column: int):
        item = self.item(row, column)
        if item is None:
            return None
        data = item.data(Qt.DisplayRole)
        return data if data is not None else item.text()


class Page(QWidget):
    """Base des pages : titre, sous-titre, zone d'actions et zone de contenu."""

    title = ""
    subtitle = ""

    def __init__(self, services: dict, parent=None):
        super().__init__(parent)
        self.services = services
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(18, 16, 18, 16)
        self.root.setSpacing(10)
        if self.title:
            self.root.addWidget(title_label(self.title))
        if self.subtitle:
            self.root.addWidget(subtitle_label(self.subtitle))
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.root.addLayout(self.actions)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.root.addLayout(self.body, 1)

    def add_action(self, text: str, slot, primary: bool = False,
                   enabled: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setEnabled(enabled)
        if primary:
            button.setObjectName("PrimaryButton")
            button.setDefault(True)
        self.actions.addWidget(button)
        return button

    def add_stretch(self) -> None:
        self.actions.addStretch(1)

    def refresh(self) -> None:  # surchargée par les pages
        pass


def refresh_after(func):
    """Décorateur : rafraîchit la page et affiche les erreurs métier en dialogue."""

    def wrapper(self, *args, **kwargs):
        try:
            result = func(self, *args, **kwargs)
        except Exception as exc:  # messages compréhensibles (§5.1)
            QMessageBox.warning(self, "Opération impossible", str(exc))
            return None
        self.refresh()
        return result

    return wrapper


def info(parent, message: str, title: str = "Information") -> None:
    QMessageBox.information(parent, title, message)


def confirm(parent, message: str, title: str = "Confirmation") -> bool:
    answer = QMessageBox.question(parent, title, message,
                                  QMessageBox.Yes | QMessageBox.No,
                                  QMessageBox.No)
    return answer == QMessageBox.Yes
