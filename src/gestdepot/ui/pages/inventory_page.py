"""Inventaires physiques : théorique, comptage, écart, validation (§5.13)."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QSpinBox

from ..widgets import DataTable, Page, confirm, info, money, refresh_after


class InventoryPage(Page):
    title = "Inventaires"
    subtitle = ("Le stock théorique est figé au démarrage ; la validation génère des "
                "mouvements de régularisation tracés.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Nouvel inventaire", self.start, primary=True)
        self.add_action("Valider l'inventaire", self.validate)
        self.add_stretch()

        filter_row = QHBoxLayout()
        self.session_label = QLabel("")
        self.session_label.setStyleSheet("font-weight: 600;")
        filter_row.addWidget(self.session_label, 1)
        filter_row.addWidget(QLabel("Compté :"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 1_000_000)
        filter_row.addWidget(self.count_spin)
        self.body.addLayout(filter_row)

        self.table = DataTable(["Produit", "Théorique", "Compté", "Écart",
                                "Coût unitaire", "Valeur de l'écart"])
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.body.addWidget(self.table, 2)

        self.body.addWidget(QLabel("Sessions d'inventaire"))
        self.sessions = DataTable(["N°", "Date", "Statut", "Commentaire"])
        self.sessions.itemSelectionChanged.connect(self._session_selected)
        self.body.addWidget(self.sessions, 1)
        self._current = None
        self._lines = []

    def refresh(self) -> None:
        sessions = self.services["inventory"].list_sessions()
        self._sessions = sessions
        self.sessions.load([[s.number, s.at.strftime("%d/%m/%Y %H:%M"),
                             "Validé" if s.status == "validated" else "Brouillon",
                             s.comment or ""] for s in sessions],
                           colors={2: {"Validé": "#1B7F3B",
                                       "Brouillon": "#B26A00"}})
        if self._current is None and sessions:
            self._current = sessions[0]
        if self._current is not None:
            self._load_lines(self._current)

    def _session_selected(self) -> None:
        row = self.sessions.selected_row()
        if row is not None and row < len(self._sessions):
            self._current = self._sessions[row]
            self._load_lines(self._current)

    def _load_lines(self, session) -> None:
        self._current = session
        self._lines = self.services["inventory"].lines(session.id)
        summary = self.services["inventory"].summary(session.id)
        self.session_label.setText(
            f"{session.number} — {summary['lines']} lignes, "
            f"{summary['gaps']} écart(s), valeur de l'écart "
            f"{money(summary['gap_value'])}")
        self.table.load([[self._product_name(line.product_id), line.theoretical_qty,
                          line.counted_qty,
                          line.counted_qty - line.theoretical_qty,
                          money(line.cost),
                          money((line.counted_qty - line.theoretical_qty) * line.cost)]
                         for line in self._lines], numeric_columns={1, 2, 3, 4, 5})

    def _product_name(self, product_id: int) -> str:
        try:
            return self.services["catalog"].get(product_id).name
        except Exception:
            return f"#{product_id}"

    def _selection_changed(self) -> None:
        row = self.table.selected_row()
        if row is None or row >= len(self._lines):
            return
        self.count_spin.setValue(self._lines[row].counted_qty)

    @refresh_after
    def start(self):
        if not confirm(self, "Démarrer un nouvel inventaire de tous les produits ?"):
            return
        self._current = self.services["inventory"].start_session()
        return True

    @refresh_after
    def validate(self):
        if self._current is None:
            QMessageBox.information(self, "Inventaire",
                                    "Aucun inventaire sélectionné.")
            return
        row = self.table.selected_row()
        if row is not None and row < len(self._lines):
            line = self._lines[row]
            self.services["inventory"].set_counted(
                self._current.id, line.product_id, self.count_spin.value())
        if self._current.status == "validated":
            QMessageBox.information(self, "Inventaire", "Inventaire déjà validé.")
            return
        if not confirm(self, "Valider cet inventaire ?\n\nDes mouvements de "
                             "correction seront enregistrés pour chaque écart."):
            return
        summary = self.services["inventory"].validate(self._current.id)
        info(self, f"Inventaire validé : {summary['adjusted_lines']} ligne(s) "
                   f"régularisée(s), écart de valeur {money(summary['gap_value'])}.",
             "Inventaire validé")
        return True
