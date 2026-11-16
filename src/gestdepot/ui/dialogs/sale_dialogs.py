"""Dialogues de l'écran de caisse (§5.5) : paiement mixte, suspension,
reprise d'une vente suspendue, retour et annulation.

Chaque dialogue ne fait aucune écriture métier : il collecte une saisie et la
transmet au service, qui applique les règles (permissions, atomicité, traçabilité).
"""
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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...domain.rules import label_payment
from ...services import payment_methods
from ..widgets import DataTable, money

REFUND_MODES = [("Espèces", "especes"), ("Avoir", "avoir"), ("Autre", "autre")]


class SplitPaymentDialog(QDialog):
    """Saisie d'un règlement en plusieurs moyens de paiement (§5.5)."""

    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self.total = int(total)
        self.setWindowTitle("Paiement mixte")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        header = QLabel(f"Total à payer : {money(self.total)}")
        header.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(header)

        form = QFormLayout()
        self.method_boxes: list[QComboBox] = []
        self.amount_spins: list[QSpinBox] = []
        for index in range(3):
            method = QComboBox()
            labels = payment_methods.labels()
            for code in payment_methods.codes():
                method.addItem(labels[code], code)
            amount = QSpinBox()
            amount.setRange(0, 1_000_000_000)
            amount.setSingleStep(500)
            amount.valueChanged.connect(self._update)
            row = QHBoxLayout()
            row.addWidget(method, 1)
            row.addWidget(amount, 1)
            self.method_boxes.append(method)
            self.amount_spins.append(amount)
            form.addRow(f"Encaissement {index + 1}", self._wrap(row))
        layout.addLayout(form)

        quick = QHBoxLayout()
        quick.addWidget(QPushButton("Répartir en 2", clicked=self._split_two))
        quick.addWidget(QPushButton("Tout en espèces", clicked=self._all_cash))
        quick.addStretch(1)
        layout.addLayout(quick)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Encaisser")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update()

    @staticmethod
    def _wrap(row_layout: QHBoxLayout):
        from PySide6.QtWidgets import QWidget
        widget = QWidget()
        row_layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(row_layout)
        return widget

    def _split_two(self) -> None:
        half = self.total // 2
        self.amount_spins[0].setValue(half)
        self.method_boxes[0].setCurrentIndex(0)
        self.amount_spins[1].setValue(self.total - half)
        index = 1 if self.method_boxes[1].count() > 1 else 0
        if self.method_boxes[1].itemData(index) == "especes":
            index = min(1, self.method_boxes[1].count() - 1)
        self.method_boxes[1].setCurrentIndex(index)

    def _all_cash(self) -> None:
        for index, spin in enumerate(self.amount_spins):
            spin.setValue(self.total if index == 0 else 0)
        self.method_boxes[0].setCurrentIndex(0)
        self._update()

    def payments(self) -> list[dict]:
        return [{"method": method.currentData(), "amount": spin.value()}
                for method, spin in zip(self.method_boxes, self.amount_spins)
                if spin.value() > 0]

    def _total_entered(self) -> int:
        return sum(spin.value() for spin in self.amount_spins)

    def _update(self) -> None:
        entered = self._total_entered()
        remaining = self.total - entered
        if remaining > 0:
            self.summary.setText(f"Reste à encaisser : {money(remaining)}")
            self.summary.setStyleSheet("color: #B3261E; font-weight: 600;")
        elif remaining < 0:
            self.summary.setText(f"Excédent : {money(-remaining)} "
                                 "(non encaissé, rendu au client)")
            self.summary.setStyleSheet("color: #B26A00; font-weight: 600;")
        else:
            self.summary.setText("Montant exact.")
            self.summary.setStyleSheet("color: #1B7F3B; font-weight: 600;")

    def _accept_if_valid(self) -> None:
        methods = [method.currentData() for method, spin
                   in zip(self.method_boxes, self.amount_spins) if spin.value() > 0]
        if not methods:
            QMessageBox.information(self, "Paiement mixte",
                                    "Saisissez au moins un encaissement.")
            return
        if self._total_entered() > self.total:
            QMessageBox.information(
                self, "Paiement mixte",
                "Le total des encaissements dépasse le montant à payer.")
            return
        if len(set(methods)) != len(methods):
            QMessageBox.information(
                self, "Paiement mixte",
                "Chaque moyen de paiement ne peut apparaître qu'une fois.")
            return
        self.accept()


class HoldDialog(QDialog):
    """Met le panier de côté (F8) : aucune écriture comptable."""

    def __init__(self, default_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Suspendre la vente")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        hint = QLabel("Le panier est conservé sans toucher au stock ni à la caisse. "
                      "Vous pourrez le reprendre depuis « Ventes suspendues ».")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        form = QFormLayout()
        self.label = QLineEdit(default_label)
        self.label.setPlaceholderText("Nom du panier, ex. « Table 3 »")
        form.addRow("Repère", self.label)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Note (facultatif)")
        form.addRow("Note", self.note)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Suspendre")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class HeldSalesDialog(QDialog):
    """Liste des ventes suspendues : reprendre ou abandonner (§5.5, F8)."""

    HEADERS = ["Repère", "Client", "Lignes", "Note", "Suspendue le"]

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.selected_id: int | None = None
        self.setWindowTitle("Ventes suspendues")
        self.setMinimumSize(620, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sélectionnez un panier à reprendre en caisse."))
        self.table = DataTable(self.HEADERS)
        self.table.doubleClicked.connect(lambda _: self._resume())
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Reprendre", clicked=self._resume))
        buttons.addWidget(QPushButton("Abandonner", clicked=self._discard))
        buttons.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._held: list = []
        self._load()

    def _load(self) -> None:
        self._held = self.services["sales"].held_sales()
        rows = []
        for held in self._held:
            try:
                count = len(self.services["sales"].get_held_sale(held.id)["items"])
            except Exception:
                count = 0
            customer = held.customer.name if held.customer else "Comptoir"
            rows.append([held.label, customer,
                         str(count),
                         held.note or "",
                         held.at.strftime("%d/%m/%Y %H:%M") if held.at else ""])
        self.table.load(rows, numeric_columns={2})
        if rows:
            self.table.selectRow(0)

    def _current(self):
        row = self.table.selected_row()
        if row is None or row >= len(self._held):
            return None
        return self._held[row]

    def _resume(self) -> None:
        held = self._current()
        if held is None:
            QMessageBox.information(self, "Vente suspendue",
                                    "Sélectionnez un panier.")
            return
        self.selected_id = held.id
        self.accept()

    def _discard(self) -> None:
        held = self._current()
        if held is None:
            QMessageBox.information(self, "Vente suspendue",
                                    "Sélectionnez un panier.")
            return
        answer = QMessageBox.question(
            self, "Abandonner",
            f"Abandonner définitivement le panier « {held.label} » ?\n"
            "L'abandon est enregistré dans le journal d'audit.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            self.services["sales"].discard_held_sale(held.id)
        except Exception as exc:
            QMessageBox.warning(self, "Abandon impossible", str(exc))
            return
        self._load()


class ReturnDialog(QDialog):
    """Retour de marchandise sur une vente existante (§7.3, T07)."""

    def __init__(self, services, sale, parent=None):
        super().__init__(parent)
        self.services = services
        self.sale = sale
        self.setWindowTitle(f"Retour — {sale.number}")
        self.setMinimumSize(620, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Vente {sale.number} du {sale.at.strftime('%d/%m/%Y %H:%M')} — "
            f"{money(sale.total_amount)}"))
        self.table = DataTable(["Désignation", "Vendu", "Déjà retourné",
                                "Retournable", "Qté à retourner", "Remboursable"])
        layout.addWidget(self.table, 1)
        self.spins: list[QSpinBox] = []
        self.checkboxes: list[QCheckBox] = []
        try:
            self._lines = self.services["sales"].returnable_lines(sale.id)
        except Exception as exc:
            self._lines = []
            QMessageBox.warning(self, "Retour", str(exc))
        rows = []
        for line in self._lines:
            rows.append([line["designation"], str(line["sold"]),
                         str(line["already_returned"]), str(line["remaining"]),
                         "", ""])
        self.table.load(rows, numeric_columns={1, 2, 3})
        self._install_editors()

        form = QFormLayout()
        self.refund_mode = QComboBox()
        for label, code in REFUND_MODES:
            self.refund_mode.addItem(label, code)
        form.addRow("Remboursement", self.refund_mode)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motif du retour (obligatoire)")
        form.addRow("Motif", self.reason)
        layout.addLayout(form)

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer le retour")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_summary()

    def _install_editors(self) -> None:
        for row, line in enumerate(self._lines):
            spin = QSpinBox()
            spin.setRange(0, line["remaining"])
            spin.valueChanged.connect(self._update_summary)
            check = QCheckBox()
            check.setChecked(True)
            check.setToolTip("Marchandise revendable : elle entre en stock")
            check.stateChanged.connect(lambda _=0: self._update_summary())
            self.table.setCellWidget(row, 4, spin)
            self.table.setCellWidget(row, 5, check)
            self.spins.append(spin)
            self.checkboxes.append(check)

    def _selected_returns(self) -> list[dict]:
        returns = []
        for line, spin, check in zip(self._lines, self.spins, self.checkboxes):
            qty = spin.value()
            if qty > 0:
                returns.append({"sale_line_id": line["sale_line_id"],
                                "quantity": qty,
                                "resellable": bool(check.isChecked())})
        return returns

    def _update_summary(self) -> None:
        amount = 0
        for line, spin in zip(self._lines, self.spins):
            amount += spin.value() * line["unit_refund"]
        self.summary.setText(f"Montant remboursé : {money(amount)}")

    def _save(self) -> None:
        returns = self._selected_returns()
        if not returns:
            QMessageBox.information(self, "Retour", "Aucune quantité saisie.")
            return
        reason = self.reason.text().strip()
        if not reason:
            QMessageBox.information(self, "Retour",
                                    "Le motif du retour est obligatoire.")
            return
        try:
            ret = self.services["sales"].return_sale(
                self.sale.id, returns,
                refund_method=self.refund_mode.currentData(), reason=reason)
        except Exception as exc:
            QMessageBox.warning(self, "Retour refusé", str(exc))
            return
        self.return_number = ret.number
        self.accept()


class CancelSaleDialog(QDialog):
    """Annulation d'une vente : motif obligatoire, contrepassation tracée."""

    def __init__(self, sale, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Annuler la vente {sale.number}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        warning = QLabel(
            f"La vente {sale.number} ({money(sale.total_amount)}) sera annulée : "
            "le stock est réintégré, la créance soldée et l'opération inscrite au "
            "journal d'audit. Le document reste consultable.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motif de l'annulation (obligatoire)")
        layout.addWidget(self.reason)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Annuler la vente")
        buttons.button(QDialogButtonBox.Cancel).setText("Fermer")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        if not self.reason.text().strip():
            QMessageBox.information(self, "Annulation",
                                    "Le motif d'annulation est obligatoire.")
            return
        self.accept()

    def motif(self) -> str:
        return self.reason.text().strip()


class SaleHistoryDialog(QDialog):
    """Historique des ventes : accès aux retours et annulations (§5.5)."""

    HEADERS = ["N°", "Date", "Client", "Total", "Encaissé", "Statut"]

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.chosen_action: str | None = None
        self.chosen_sale = None
        self.setWindowTitle("Historique des ventes")
        self.setMinimumSize(760, 460)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer par numéro ou client…")
        self.search.textChanged.connect(self._load)
        bar.addWidget(self.search, 1)
        layout.addLayout(bar)
        self.table = DataTable(self.HEADERS)
        self.table.doubleClicked.connect(lambda _: self._act("return"))
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Retour de marchandise",
                                      clicked=lambda: self._act("return")))
        buttons.addWidget(QPushButton("Annuler la vente",
                                      clicked=lambda: self._act("cancel")))
        buttons.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._sales = []
        self._load()

    def _load(self) -> None:
        from ...domain.rules import label_status
        recent = self.services["sales"].recent_sales(limit=300)
        needle = self.search.text().strip().lower()
        self._sales = []
        rows = []
        for sale in recent:
            customer = "Comptoir"
            try:
                customer = sale.customer.name if sale.customer else "Comptoir"
            except Exception:
                customer = "Comptoir"
            if needle and needle not in (sale.number or "").lower() \
                    and needle not in customer.lower():
                continue
            self._sales.append(sale)
            rows.append([sale.number,
                         sale.at.strftime("%d/%m/%Y %H:%M") if sale.at else "",
                         customer, money(sale.total_amount),
                         money(sale.paid_amount), label_status(sale.status)])
        self.table.load(rows, numeric_columns={3, 4})
        if rows:
            self.table.selectRow(0)

    def selected_sale(self):
        row = self.table.selected_row()
        if row is None or row >= len(self._sales):
            return None
        return self._sales[row]

    def _act(self, action: str) -> None:
        sale = self.selected_sale()
        if sale is None:
            QMessageBox.information(self, "Ventes",
                                    "Sélectionnez une vente dans la liste.")
            return
        if action == "return" and sale.status in ("cancelled", "returned"):
            QMessageBox.information(self, "Retour",
                                    "Cette vente ne peut plus faire l'objet "
                                    "d'un retour.")
            return
        if action == "cancel" and sale.status == "cancelled":
            QMessageBox.information(self, "Annulation",
                                    "Cette vente est déjà annulée.")
            return
        self.chosen_action = action
        self.chosen_sale = sale
        self.accept()


def _label_method(code: str | None) -> str:
    try:
        return label_payment(code)
    except Exception:
        return code or ""


__all__ = ["CancelSaleDialog", "HeldSalesDialog", "HoldDialog", "ReturnDialog",
           "SaleHistoryDialog", "SplitPaymentDialog", "_label_method"]
