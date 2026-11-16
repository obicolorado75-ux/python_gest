"""Consignes et emballages : types, mouvements, comptes par client (§5.8)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...domain.rules import PAYMENT_METHODS, label_payment
from ..widgets import DataTable, Page, info, money, refresh_after

REASON_LABELS = {
    "remis_client": "Remis au client",
    "retourne_client": "Retourné par le client",
    "recu_fournisseur": "Reçu du fournisseur",
    "rendu_fournisseur": "Rendu au fournisseur",
    "casse": "Cassé / perdu",
    "ajuste": "Ajustement",
}


class PackagingDialog(QDialog):
    """Fiche d'un type d'emballage : code, libellé, capacité, consigne (§5.8)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouveau type d'emballage")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit()
        self.label = QLineEdit()
        self.capacity = QSpinBox()
        self.capacity.setRange(0, 10_000)
        self.value = QSpinBox()
        self.value.setRange(0, 1_000_000)
        self.value.setSingleStep(100)
        self.supplier = QComboBox()
        self.supplier.addItem("Aucun fournisseur", None)
        for supplier in services["stock"].list_suppliers():
            self.supplier.addItem(supplier.name, supplier.id)
        form.addRow("Code *", self.code)
        form.addRow("Libellé *", self.label)
        form.addRow("Capacité (bouteilles)", self.capacity)
        form.addRow("Consigne unitaire", self.value)
        form.addRow("Fournisseur", self.supplier)
        layout.addLayout(form)
        hint = QLabel("La consigne est suivie séparément du chiffre d'affaires : "
                      "elle reste due au client ou au fournisseur.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.services["deposit"].create_packaging(
                self.code.text().strip(), self.label.text().strip(),
                self.value.value(), capacity=self.capacity.value() or None,
                supplier_id=self.supplier.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "Emballage", str(exc))
            return
        self.accept()


class MovementDialog(QDialog):
    """Mouvement d'emballage : remise, retour, casse, fournisseur (§5.8)."""

    def __init__(self, services, packaging=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Mouvement d'emballage")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.packaging = QComboBox()
        for item in services["deposit"].list_packagings():
            self.packaging.addItem(
                f"{item.label} — consigne {money(item.deposit_value)}", item.id)
        if packaging is not None:
            index = self.packaging.findData(packaging.id)
            if index >= 0:
                self.packaging.setCurrentIndex(index)
        self.reason = QComboBox()
        for code, label in REASON_LABELS.items():
            self.reason.addItem(label, code)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 100_000)
        self.party = QComboBox()
        self.reason.currentIndexChanged.connect(self._load_parties)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Commentaire (facultatif)")
        form.addRow("Emballage", self.packaging)
        form.addRow("Opération", self.reason)
        form.addRow("Quantité", self.quantity)
        form.addRow("Client / fournisseur", self.party)
        form.addRow("Commentaire", self.comment)
        layout.addLayout(form)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(self.hint)
        self._load_parties()  # après création de l'aide affichée
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _is_supplier(self) -> bool:
        return self.reason.currentData() in ("recu_fournisseur", "rendu_fournisseur")

    def _load_parties(self):
        self.party.clear()
        if self._is_supplier():
            for supplier in self.services["stock"].list_suppliers():
                self.party.addItem(supplier.name, supplier.id)
        else:
            for customer in self.services["sales"].list_customers():
                self.party.addItem(f"{customer.name}", customer.id)
        self._update_hint()

    def _update_hint(self):
        label = REASON_LABELS.get(self.reason.currentData(), "")
        self.hint.setText(
            f"« {label} » : la quantité augmente ou diminue le compte de "
            "consigne de la partie choisie, sans toucher au stock de boissons.")

    def _save(self):
        if self.packaging.currentData() is None or self.party.currentData() is None:
            QMessageBox.information(self, "Consigne",
                                    "Choisissez un emballage et une partie.")
            return
        reason = self.reason.currentData()
        quantity = self.quantity.value()
        # sens du mouvement : entrée de consigne (+) ou retour (-)
        if reason in ("remis_client", "recu_fournisseur"):
            quantity = abs(quantity)
        else:
            quantity = -abs(quantity)
        payload = {"packaging_id": self.packaging.currentData(),
                   "quantity": quantity, "reason": reason,
                   "comment": self.comment.text().strip() or None}
        if self._is_supplier():
            payload["supplier_id"] = self.party.currentData()
        else:
            payload["customer_id"] = self.party.currentData()
        try:
            self.services["deposit"].move(**payload)
        except Exception as exc:
            QMessageBox.warning(self, "Consigne", str(exc))
            return
        self.accept()


class RefundDialog(QDialog):
    """Remboursement d'une consigne rendue par le client (§5.8)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Rembourser une consigne")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.customer = QComboBox()
        for customer in services["sales"].list_customers():
            self.customer.addItem(customer.name, customer.id)
        self.packaging = QComboBox()
        for item in services["deposit"].list_packagings():
            self.packaging.addItem(f"{item.label} ({money(item.deposit_value)})",
                                   item.id)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 100_000)
        self.method = QComboBox()
        for method in PAYMENT_METHODS:
            self.method.addItem(label_payment(method), method)
        form.addRow("Client", self.customer)
        form.addRow("Emballage", self.packaging)
        form.addRow("Quantité rendue", self.quantity)
        form.addRow("Moyen de remboursement", self.method)
        layout.addLayout(form)
        hint = QLabel("Pensez à enregistrer d'abord le retour d'emballage : le "
                      "remboursement ne modifie que la caisse, jamais le chiffre "
                      "d'affaires.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Rembourser")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        if self.customer.currentData() is None or self.packaging.currentData() is None:
            QMessageBox.information(self, "Consigne", "Choisissez client et emballage.")
            return
        try:
            amount = self.services["deposit"].refund_customer(
                self.customer.currentData(), self.packaging.currentData(),
                self.quantity.value(), payment_method=self.method.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "Remboursement refusé", str(exc))
            return
        info(self, f"Consigne remboursée : {money(amount)}.", "Consigne")
        self.accept()


class DepositsPage(Page):
    title = "Consignes et emballages"
    subtitle = ("Emballages remis, retournés, cassés ou rendus au fournisseur : "
                "suivi séparé du chiffre d'affaires.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Nouvel emballage", self.new_packaging)
        self.add_action("Mouvement", self.new_movement, primary=True)
        self.add_action("Rembourser une consigne", self.refund)
        self.add_stretch()

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)

        types_tab = QWidget()
        types_layout = QVBoxLayout(types_tab)
        self.types = DataTable(["Code", "Libellé", "Capacité", "Consigne",
                                "Fournisseur", "Solde dû au fournisseur (qté)",
                                "Valeur"])
        types_layout.addWidget(self.types)
        self.tabs.addTab(types_tab, "Types d'emballages")

        accounts_tab = QWidget()
        accounts_layout = QVBoxLayout(accounts_tab)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un client…")
        self.search.textChanged.connect(self.refresh)
        accounts_layout.addWidget(self.search)
        self.accounts = DataTable(["Client", "Code", "Emballage", "Quantité due",
                                   "Valeur"])
        accounts_layout.addWidget(self.accounts)
        self.tabs.addTab(accounts_tab, "Comptes clients")

        movements_tab = QWidget()
        movements_layout = QVBoxLayout(movements_tab)
        self.movements = DataTable(["Date", "Emballage", "Opération", "Quantité",
                                    "Client", "Fournisseur", "Valeur", "Commentaire"])
        movements_layout.addWidget(self.movements)
        self.tabs.addTab(movements_tab, "Mouvements")

    def refresh(self) -> None:
        deposit = self.services["deposit"]
        suppliers = {sup.id: sup.name for sup in self.services["stock"].list_suppliers()}
        packagings = deposit.list_packagings()
        self._packagings = packagings
        rows = []
        for item in packagings:
            # solde dû AU fournisseur pour ce type d'emballage (§5.8, §6.4)
            owed = (deposit.supplier_balance(item.supplier_id).get(item.id, 0)
                    if item.supplier_id else 0)
            rows.append([item.code, item.label, item.capacity or "—",
                         money(item.deposit_value),
                         suppliers.get(item.supplier_id, "—"),
                         owed, money(abs(owed) * item.deposit_value)])
        self.types.load(rows, numeric_columns={2, 3, 5, 6})

        rows = deposit.balances_overview()
        needle = self.search.text().strip().lower()
        if needle:
            rows = [row for row in rows if needle in row["customer"].lower()]
        self.accounts.load([[row["customer"], row["code"], row["label"],
                             row["quantity"], money(row["value"])] for row in rows],
                           numeric_columns={3, 4})

        customers = {c.id: c.name for c in self.services["sales"].list_customers()}
        movements = deposit.movements(limit=300)
        self.movements.load([[m.at.strftime("%d/%m/%Y %H:%M") if m.at else "",
                              m.packaging.label if m.packaging else "—",
                              REASON_LABELS.get(m.reason, m.reason),
                              m.quantity,
                              customers.get(m.customer_id, "—"),
                              suppliers.get(m.supplier_id, "—"),
                              money(abs(m.quantity) * (m.deposit_value or 0)),
                              m.comment or ""] for m in movements],
                            numeric_columns={3, 6})

    @refresh_after
    def new_packaging(self):
        if PackagingDialog(self.services, self).exec():
            return True

    @refresh_after
    def new_movement(self):
        if not self.services["deposit"].list_packagings():
            QMessageBox.information(self, "Consigne",
                                    "Créez d'abord un type d'emballage.")
            return
        if MovementDialog(self.services, parent=self).exec():
            return True

    @refresh_after
    def refund(self):
        if not self.services["deposit"].list_packagings():
            QMessageBox.information(self, "Consigne",
                                    "Aucun type d'emballage configuré.")
            return
        if not self.services["sales"].list_customers():
            QMessageBox.information(self, "Consigne", "Aucun client enregistré.")
            return
        if RefundDialog(self.services, self).exec():
            return True


__all__ = ["DepositsPage", "MovementDialog", "PackagingDialog", "RefundDialog"]