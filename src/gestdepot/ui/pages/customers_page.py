"""Clients et crédits : fiche, plafond, règlements, relevé (§5.9)."""
from __future__ import annotations

from PySide6.QtWidgets import (
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

from ...services import payment_methods
from ..widgets import DataTable, Page, confirm, money, refresh_after


class CustomerDialog(QDialog):
    def __init__(self, services, customer=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.customer = customer
        self.setWindowTitle("Modifier le client" if customer else "Nouveau client")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit(customer.code if customer else "")
        self.code.setEnabled(customer is None)
        self.name = QLineEdit(customer.name if customer else "")
        self.phone = QLineEdit(customer.phone or "" if customer else "")
        self.address = QLineEdit(customer.address or "" if customer else "")
        self.type = QComboBox()
        for value, label in (("detail", "Détail"), ("gros", "Gros"),
                             ("revendeur", "Revendeur")):
            self.type.addItem(label, value)
        self.price_list = QComboBox()
        self.price_list.addItem("Tarif standard", None)
        for price_list in services["catalog"].list_price_lists():
            self.price_list.addItem(price_list.name, price_list.id)
        self.credit = QSpinBox()
        self.credit.setRange(0, 1_000_000_000)
        self.credit.setSingleStep(5000)
        if customer:
            index = self.type.findData(customer.customer_type)
            if index >= 0:
                self.type.setCurrentIndex(index)
            index = self.price_list.findData(customer.price_list_id)
            if index >= 0:
                self.price_list.setCurrentIndex(index)
            self.credit.setValue(customer.credit_limit)
        form.addRow("Code *", self.code)
        form.addRow("Nom *", self.name)
        form.addRow("Téléphone", self.phone)
        form.addRow("Adresse", self.address)
        form.addRow("Type", self.type)
        form.addRow("Tarif", self.price_list)
        form.addRow("Plafond de crédit", self.credit)
        layout.addLayout(form)
        hint = QLabel("Plafond 0 = aucune vente à crédit autorisée.")
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
            sales = self.services["sales"]
            if self.customer is None:
                sales.create_customer(
                    code=self.code.text().strip(), name=self.name.text().strip(),
                    phone=self.phone.text().strip() or None,
                    address=self.address.text().strip() or None,
                    customer_type=self.type.currentData(),
                    price_list_id=self.price_list.currentData(),
                    credit_limit=self.credit.value())
            else:
                sales.update_customer(
                    self.customer.id, name=self.name.text().strip(),
                    phone=self.phone.text().strip() or None,
                    address=self.address.text().strip() or None,
                    customer_type=self.type.currentData(),
                    price_list_id=self.price_list.currentData(),
                    credit_limit=self.credit.value())
        except Exception as exc:
            QMessageBox.warning(self, "Client", str(exc))
            return
        self.accept()


class PaymentDialog(QDialog):
    def __init__(self, services, customer, parent=None):
        super().__init__(parent)
        self.services = services
        self.customer = customer
        self.setWindowTitle(f"Encaisser — {customer.name}")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        due = QLabel(f"Solde dû : {money(customer.balance)}")
        due.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(due)
        form = QFormLayout()
        self.amount = QSpinBox()
        self.amount.setRange(1, 1_000_000_000)
        self.amount.setSingleStep(500)
        self.amount.setValue(max(customer.balance, 1))
        self.method = QComboBox()
        labels = payment_methods.labels()
        for method in payment_methods.codes():
            self.method.addItem(labels[method], method)
        form.addRow("Montant", self.amount)
        form.addRow("Moyen de paiement", self.method)
        layout.addLayout(form)
        hint = QLabel("Le paiement réduit la créance sans modifier le chiffre "
                      "d'affaires déjà enregistré.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Encaisser")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.services["sales"].pay_credit(self.customer.id, self.amount.value(),
                                              self.method.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "Règlement", str(exc))
            return
        self.accept()


class CustomersPage(Page):
    title = "Clients et crédits"
    subtitle = "Créances, plafonds et règlements partiels ; le CA reste inchangé."

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un client…")
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        self.body.addLayout(bar)

        self.add_action("Nouveau client", self.new_customer, primary=True)
        self.add_action("Modifier", self.edit_customer)
        self.add_action("Encaisser un règlement", self.pay)
        self.add_action("Relevé de compte", self.statement)
        self.add_action("Désactiver", self.archive)
        self.add_stretch()

        self.table = DataTable(["Code", "Nom", "Téléphone", "Type", "Tarif",
                                "Plafond", "Solde dû", "Statut"])
        self.table.doubleClicked.connect(lambda _: self.edit_customer())
        self.body.addWidget(self.table, 1)

    def _selected(self):
        row = self.table.selected_row()
        if row is None or row >= len(self._customers):
            return None
        return self._customers[row]

    def refresh(self) -> None:
        self._customers = self.services["sales"].list_customers(
            self.search.text().strip() or None)
        rows = [[c.code, c.name, c.phone or "—", c.customer_type,
                 c.price_list.name if c.price_list else "Standard",
                 money(c.credit_limit), money(c.balance),
                 "Crédit" if c.balance > 0 else "À jour"] for c in self._customers]
        self.table.load(rows, numeric_columns={5, 6},
                        colors={7: {"Crédit": "#B26A00", "À jour": "#1B7F3B"}})

    @refresh_after
    def new_customer(self):
        if CustomerDialog(self.services, None, self).exec():
            return True

    @refresh_after
    def edit_customer(self):
        customer = self._selected()
        if customer is None:
            QMessageBox.information(self, "Client", "Sélectionnez un client.")
            return
        if CustomerDialog(self.services, customer, self).exec():
            return True

    @refresh_after
    def pay(self):
        customer = self._selected()
        if customer is None:
            QMessageBox.information(self, "Client", "Sélectionnez un client.")
            return
        if customer.balance <= 0:
            QMessageBox.information(self, "Règlement",
                                    "Ce client n'a aucune créance ouverte.")
            return
        if PaymentDialog(self.services, customer, self).exec():
            return True

    @refresh_after
    def statement(self):
        customer = self._selected()
        if customer is None:
            QMessageBox.information(self, "Client", "Sélectionnez un client.")
            return
        data = self.services["sales"].customer_statement(customer.id)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Relevé — {customer.name}")
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        header = QLabel(f"Solde dû actuel : {money(data['balance'])}")
        header.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(header)
        table = DataTable(["Date", "Opération", "Montant"])
        rows = []
        for sale in data["sales"]:
            rows.append((sale.at, f"Vente {sale.number}", sale.total_amount))
        for payment in data["payments"]:
            rows.append((payment.at, f"Paiement {payment.number}", -payment.amount))
        for ret in data["returns"]:
            rows.append((ret.at, f"Retour {ret.number}", -ret.total_amount))
        rows.sort(key=lambda item: item[0])
        table.load([[when.strftime("%d/%m/%Y"), label, money(amount)]
                    for when, label, amount in rows], numeric_columns={2})
        layout.addWidget(table)
        close = QPushButton("Fermer")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        return True

    @refresh_after
    def archive(self):
        customer = self._selected()
        if customer is None:
            QMessageBox.information(self, "Client", "Sélectionnez un client.")
            return
        if not confirm(self, f"Désactiver « {customer.name} » ?\n\n"
                             "L'historique et les créances restent consultables."):
            return
        self.services["sales"].archive_customer(customer.id)
        return True
