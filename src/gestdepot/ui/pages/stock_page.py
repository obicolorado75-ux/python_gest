"""Stocks et mouvements : niveaux, journal immuable, ajustements (§5.7)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ...services.stock_service import MOVEMENT_REASONS
from ..widgets import DataTable, Page, money, refresh_after

ADJUSTMENT_REASONS = [reason for reason in sorted(MOVEMENT_REASONS)
                      if reason not in ("mouvement_initial", "reception",
                                        "sortie_vente", "correction_inventaire")]

REASON_LABELS = {
    "mouvement_initial": "Stock initial",
    "reception": "Réception d'achat",
    "sortie_vente": "Sortie de vente",
    "retour_client": "Retour client",
    "retour_fournisseur": "Retour fournisseur",
    "casse": "Casse",
    "perte": "Perte",
    "peremption": "Péremption",
    "correction_inventaire": "Correction d'inventaire",
}


class AdjustmentDialog(QDialog):
    def __init__(self, services, products, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Mouvement de stock manuel")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.product = QComboBox()
        for product in products:
            self.product.addItem(f"{product.name} ({product.reference})", product.id)
        self.reason = QComboBox()
        for reason in ADJUSTMENT_REASONS:
            self.reason.addItem(REASON_LABELS.get(reason, reason), reason)
        self.initial = QCheckBox("Entrée de stock initial (valorisation)")
        self.quantity = QSpinBox()
        self.quantity.setRange(-1_000_000, 1_000_000)
        self.quantity.setValue(1)
        self.cost = QSpinBox()
        self.cost.setRange(0, 100_000_000)
        self.comment = QLineEdit()
        form.addRow("Produit", self.product)
        form.addRow("Motif", self.reason)
        form.addRow("", self.initial)
        form.addRow("Quantité signée", self.quantity)
        form.addRow("Coût unitaire (entrée)", self.cost)
        form.addRow("Commentaire", self.comment)
        layout.addLayout(form)
        hint = QLabel("Une opération validée n'est jamais effacée : le mouvement "
                      "reste dans le journal.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        stock = self.services["stock"]
        try:
            if self.initial.isChecked():
                stock.initial_stock(self.product.currentData(),
                                    self.quantity.value(),
                                    self.cost.value(),
                                    self.comment.text() or "Stock initial")
            else:
                stock.adjust(self.product.currentData(), self.quantity.value(),
                             self.reason.currentData(), self.comment.text() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Mouvement refusé", str(exc))
            return
        self.accept()


class StockPage(Page):
    title = "Stocks et mouvements"
    subtitle = ("Journal immuable : chaque quantité vient d'un mouvement tracé et "
                "le solde est rapprochable.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un produit…")
        self.search.textChanged.connect(self.refresh)
        self.only_alerts = QCheckBox("Alertes uniquement (seuil, rupture)")
        self.only_alerts.toggled.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.only_alerts)
        self.body.addLayout(bar)

        self.add_action("Mouvement manuel", self.new_movement, primary=True)
        self.add_action("Vérifier les soldes", self.check_balances)
        self.add_stretch()

        self.table = DataTable(["Référence", "Produit", "Physique", "Réservé",
                                "Disponible", "Coût moyen", "Valeur", "Seuil",
                                "Statut"])
        self.table.itemSelectionChanged.connect(self._show_movements)
        self.body.addWidget(self.table, 3)

        journal_title = QLabel("Journal des mouvements du produit sélectionné")
        journal_title.setStyleSheet("font-weight: 600; margin-top: 6px;")
        self.body.addWidget(journal_title)
        self.movements = DataTable(["Date", "Motif", "Quantité", "Document",
                                    "Coût unitaire", "Commentaire"])
        self.body.addWidget(self.movements, 2)

    def refresh(self) -> None:
        self._levels = self.services["stock"].stock_levels(
            self.search.text().strip() or None, self.only_alerts.isChecked())
        rows = [[row["reference"], row["name"], row["quantity"], row["reserved"],
                 row["available"], money(row["unit_cost"]), money(row["value"]),
                 row["min_threshold"],
                 {"ok": "OK", "sous_seuil": "Sous seuil", "rupture": "Rupture"}[
                     row["status"]]] for row in self._levels]
        self.table.load(rows, numeric_columns={2, 3, 4, 5, 6, 7},
                        colors={8: {"OK": "#1B7F3B", "Sous seuil": "#B26A00",
                                    "Rupture": "#B3261E"}})
        self._show_movements()

    def _show_movements(self) -> None:
        row = self.table.selected_row()
        if row is None or row >= len(self._levels):
            self.movements.load([])
            return
        product_id = self._levels[row]["product_id"]
        movements = self.services["stock"].movements(product_id, limit=100)
        self.movements.load([
            [m.at.strftime("%d/%m/%Y %H:%M"),
             REASON_LABELS.get(m.reason, m.reason), m.quantity,
             f"{m.document_type or '—'} #{m.document_id}" if m.document_id else "—",
             money(m.unit_cost) if m.unit_cost is not None else "",
             m.comment or ""] for m in movements], numeric_columns={2})

    @refresh_after
    def new_movement(self):
        products = self.services["catalog"].list_products()
        if not products:
            QMessageBox.information(self, "Stock",
                                    "Créez d'abord un produit dans le catalogue.")
            return
        if AdjustmentDialog(self.services, products, self).exec():
            return True

    @refresh_after
    def check_balances(self):
        mismatches = self.services["stock"].reconcile()
        if not mismatches:
            QMessageBox.information(self, "Rapprochement",
                                    "Tous les soldes correspondent au journal.")
        else:
            detail = "\n".join(f"Produit #{p} : solde {b}, journal {j}"
                               for p, b, j in mismatches[:20])
            QMessageBox.warning(self, "Écarts détectés",
                                "Des écarts existent entre soldes et journal :\n\n"
                                + detail
                                + "\n\nCorrigez-les par un inventaire (§7.7).")
        return True
