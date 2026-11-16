"""Inventaires physiques : démarrage ciblé, comptage, contrôle, validation (§5.13)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ..widgets import DataTable, Page, confirm, info, money, refresh_after

STATUS_LABELS = {"draft": "Brouillon", "counting": "Comptage",
                 "reviewed": "Contrôlé", "validated": "Validé",
                 "cancelled": "Abandonné"}


class StartInventoryDialog(QDialog):
    """Inventaire global ou ciblé, avec seuil de contrôle des écarts (§5.13)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouvel inventaire")
        self.setMinimumSize(520, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("Tous les produits (inventaire global)", "all")
        self.scope.addItem("Produits sélectionnés (inventaire ciblé)", "partial")
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 100_000_000)
        self.threshold.setSingleStep(1_000)
        self.threshold.setValue(5_000)
        self.threshold.setToolTip(
            "Au-delà de cet écart de valeur, un contrôle sera exigé avant la "
            "validation. 0 = aucun contrôle obligatoire.")
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Commentaire (facultatif)")
        form.addRow("Périmètre", self.scope)
        form.addRow("Seuil de contrôle (FCFA)", self.threshold)
        form.addRow("Commentaire", self.comment)
        layout.addLayout(form)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les produits…")
        self.filter.textChanged.connect(self._fill_products)
        layout.addWidget(self.filter)
        self.products = QListWidget()
        layout.addWidget(self.products, 1)
        self.selection_hint = QLabel("")
        self.selection_hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(self.selection_hint)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.products.itemChanged.connect(lambda _=0: self._update_hint())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Démarrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._products = services["catalog"].list_products()
        self._fill_products()
        self._scope_changed()

    def _scope_changed(self) -> None:
        partial = self.scope.currentData() == "partial"
        self.products.setEnabled(partial)
        self.filter.setEnabled(partial)
        self._update_hint()

    def _fill_products(self) -> None:
        needle = self.filter.text().strip().lower()
        self.products.blockSignals(True)
        self.products.clear()
        for product in self._products:
            if needle and needle not in product.name.lower() \
                    and needle not in product.reference.lower():
                continue
            item = QListWidgetItem(f"{product.name} — {product.reference}")
            item.setData(Qt.UserRole, product.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.products.addItem(item)
        self.products.blockSignals(False)
        self._update_hint()

    def selected_ids(self) -> list[int]:
        return [self.products.item(index).data(Qt.UserRole)
                for index in range(self.products.count())
                if self.products.item(index).checkState() == Qt.Checked]

    def _update_hint(self) -> None:
        if self.scope.currentData() == "all":
            self.selection_hint.setText(
                f"{len(self._products)} produit(s) seront inventoriés.")
        else:
            self.selection_hint.setText(
                f"{len(self.selected_ids())} produit(s) sélectionné(s).")

    def payload(self) -> dict:
        return {"product_ids": (None if self.scope.currentData() == "all"
                                else self.selected_ids()),
                "comment": self.comment.text().strip() or None,
                "threshold_value": self.threshold.value()}

    def _save(self) -> None:
        if self.scope.currentData() == "partial" and not self.selected_ids():
            QMessageBox.information(self, "Inventaire",
                                    "Cochez au moins un produit à compter.")
            return
        self.accept()


class CountDialog(QDialog):
    """Saisie du comptage d'un produit avec contrôle d'écart (§5.13)."""

    def __init__(self, services, session, line, product_name: str, parent=None):
        super().__init__(parent)
        self.services = services
        self.session = session
        self.line = line
        self.setWindowTitle(f"Comptage — {product_name}")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        theoretical = line.theoretical_qty
        header = QLabel(f"Stock théorique : {theoretical}  ·  coût "
                        f"{money(line.cost)}")
        header.setStyleSheet("font-weight: 600;")
        layout.addWidget(header)
        form = QFormLayout()
        self.counted = QSpinBox()
        self.counted.setRange(0, 1_000_000)
        self.counted.setValue(line.counted_qty)
        self.counted.valueChanged.connect(self._update)
        form.addRow("Quantité comptée", self.counted)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Commentaire de contrôle (si écart)")
        form.addRow("Contrôle", self.comment)
        layout.addLayout(form)
        self.gap = QLabel("")
        self.gap.setWordWrap(True)
        layout.addWidget(self.gap)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer le comptage")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._threshold = session.threshold_value or 0
        self._update()

    def _update(self) -> None:
        gap_qty = self.counted.value() - self.line.theoretical_qty
        gap_value = gap_qty * self.line.cost
        self.gap.setText(f"Écart : {gap_qty} unité(s) — {money(gap_value)}")
        if gap_qty and self._threshold and abs(gap_value) >= self._threshold:
            self.gap.setStyleSheet("color: #B3261E; font-weight: 600;")
            self.gap.setText(self.gap.text() +
                             "   ·   contrôle obligatoire (seuil "
                             f"{money(self._threshold)})")
        else:
            self.gap.setStyleSheet("font-weight: 600;")

    def _save(self) -> None:
        try:
            self.services["inventory"].set_counted(
                self.session.id, self.line.product_id, self.counted.value())
            comment = self.comment.text().strip()
            if comment:
                self.services["inventory"].review_gap(
                    self.session.id, self.line.product_id, comment)
        except Exception as exc:
            QMessageBox.warning(self, "Comptage", str(exc))
            return
        self.accept()


class InventoryPage(Page):
    title = "Inventaires"
    subtitle = ("Le stock théorique est figé au démarrage ; la validation génère des "
                "mouvements de régularisation tracés et reste non destructive.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Nouvel inventaire", self.start, primary=True)
        self.add_action("Saisir le comptage", self.count)
        self.add_action("Contrôler les écarts", self.review_gaps)
        self.add_action("Valider l'inventaire", self.validate)
        self.add_action("Abandonner", self.cancel_session)
        self.add_stretch()

        self.session_label = QLabel("")
        self.session_label.setStyleSheet("font-weight: 600;")
        self.session_label.setWordWrap(True)
        self.body.addWidget(self.session_label)

        self.table = DataTable(["Produit", "Théorique", "Compté", "Écart",
                                "Coût unitaire", "Valeur de l'écart", "Contrôle"])
        self.table.doubleClicked.connect(lambda _: self.count())
        self.body.addWidget(self.table, 2)

        self.body.addWidget(QLabel("Sessions d'inventaire"))
        self.sessions = DataTable(["N°", "Date", "Statut", "Lignes", "Écart (qté)",
                                   "Écart (valeur)", "Seuil", "Commentaire"])
        self.sessions.itemSelectionChanged.connect(self._session_selected)
        self.body.addWidget(self.sessions, 1)
        self._current = None
        self._lines = []

    def refresh(self) -> None:
        inventory = self.services["inventory"]
        sessions = inventory.list_sessions()
        self._sessions = sessions
        rows = []
        for item in sessions:
            summary = inventory.summary(item.id)
            rows.append([item.number, item.at.strftime("%d/%m/%Y %H:%M"),
                         STATUS_LABELS.get(item.status, item.status),
                         summary["lines"], summary["gap_quantity"],
                         money(summary["gap_value"]),
                         money(item.threshold_value or 0),
                         item.comment or ""])
        self.sessions.load(rows, numeric_columns={3, 4, 5, 6},
                           colors={2: {"Validé": "#1B7F3B",
                                       "Abandonné": "#B3261E"}})
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
        inventory = self.services["inventory"]
        self._lines = inventory.lines(session.id)
        summary = inventory.summary(session.id)
        control = inventory.check_control(session.id)
        self.session_label.setText(
            f"{session.number} — {summary['lines']} lignes, "
            f"{summary['gaps']} écart(s), valeur {money(summary['gap_value'])}  ·  "
            f"{control['count']} écart(s) à contrôler  ·  statut "
            f"{STATUS_LABELS.get(session.status, session.status)}")
        self.table.load([[self._product_name(line.product_id), line.theoretical_qty,
                          line.counted_qty,
                          line.counted_qty - line.theoretical_qty,
                          money(line.cost),
                          money((line.counted_qty - line.theoretical_qty) * line.cost),
                          "Contrôlé" if line.reviewed else
                          ("À contrôler" if self._needs_review(session, line)
                           else "—")]
                         for line in self._lines], numeric_columns={1, 2, 3, 4, 5},
                        colors={6: {"À contrôler": "#B3261E", "Contrôlé": "#1B7F3B"}})

    @staticmethod
    def _needs_review(session, line) -> bool:
        gap = line.counted_qty - line.theoretical_qty
        if not gap or line.reviewed:
            return False
        return bool(session.threshold_value
                    and abs(gap * line.cost) >= session.threshold_value)

    def _product_name(self, product_id: int) -> str:
        try:
            return self.services["catalog"].get(product_id).name
        except Exception:
            return f"#{product_id}"

    @refresh_after
    def start(self):
        dialog = StartInventoryDialog(self.services, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._current = self.services["inventory"].start_session(**dialog.payload())
        return True

    @refresh_after
    def count(self):
        if self._current is None:
            QMessageBox.information(self, "Inventaire",
                                    "Aucun inventaire sélectionné.")
            return
        if self._current.status in ("validated", "cancelled"):
            QMessageBox.information(self, "Inventaire",
                                    "Inventaire clôturé : créez une nouvelle "
                                    "régularisation.")
            return
        row = self.table.selected_row()
        if row is None or row >= len(self._lines):
            QMessageBox.information(self, "Inventaire",
                                    "Sélectionnez une ligne à compter.")
            return
        line = self._lines[row]
        session = self.services["inventory"].get_session(self._current.id)
        if CountDialog(self.services, session, line,
                       self._product_name(line.product_id), self).exec():
            return True

    @refresh_after
    def review_gaps(self):
        if self._current is None:
            QMessageBox.information(self, "Inventaire",
                                    "Aucun inventaire sélectionné.")
            return
        control = self.services["inventory"].check_control(self._current.id)
        if not control["pending"]:
            QMessageBox.information(
                self, "Contrôle",
                "Aucun écart au-delà du seuil ne reste à contrôler.")
            return
        names = {line.product_id: self._product_name(line.product_id)
                 for line in self._lines}
        labels = [f"{names.get(item['product_id'], item['product_id'])} — "
                  f"{item['gap']} unité(s), {money(item['value'])}"
                  for item in control["pending"]]
        choice, ok = QInputDialog.getItem(self, "Contrôle des écarts",
                                          "Écart à contrôler :", labels, 0, False)
        if not ok:
            return
        item = control["pending"][labels.index(choice)]
        comment, ok = QInputDialog.getText(
            self, "Contrôle des écarts",
            f"Constat pour {names.get(item['product_id'])} "
            f"(écart {item['gap']}) :")
        if not ok or not comment.strip():
            return
        self.services["inventory"].review_gap(
            self._current.id, item["product_id"], comment.strip())
        return True

    @refresh_after
    def cancel_session(self):
        if self._current is None:
            QMessageBox.information(self, "Inventaire",
                                    "Aucun inventaire sélectionné.")
            return
        if self._current.status == "validated":
            QMessageBox.information(self, "Inventaire",
                                    "Un inventaire validé ne peut pas être abandonné.")
            return
        reason, ok = QInputDialog.getText(
            self, "Abandonner l'inventaire",
            f"Motif de l'abandon de {self._current.number} :")
        if not ok or not reason.strip():
            return
        self.services["inventory"].cancel_session(self._current.id, reason.strip())
        self._current = None
        return True

    @refresh_after
    def validate(self):
        if self._current is None:
            QMessageBox.information(self, "Inventaire",
                                    "Aucun inventaire sélectionné.")
            return
        if self._current.status == "validated":
            QMessageBox.information(self, "Inventaire", "Inventaire déjà validé.")
            return
        control = self.services["inventory"].check_control(self._current.id)
        if control["pending"]:
            QMessageBox.warning(
                self, "Inventaire",
                f"{control['count']} écart(s) dépassent le seuil de "
                f"{money(control['threshold'])} et doivent être contrôlés "
                "avant la validation.")
            return
        if not confirm(self, "Valider cet inventaire ?\n\nDes mouvements de "
                             "régularisation seront enregistrés pour chaque écart."):
            return
        summary = self.services["inventory"].validate(self._current.id)
        info(self, f"Inventaire validé : {summary['adjusted_lines']} ligne(s) "
                   f"régularisée(s), écart de valeur {money(summary['gap_value'])}.",
             "Inventaire validé")
        return True
