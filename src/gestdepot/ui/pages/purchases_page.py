"""Achats et réapprovisionnement : commandes, réceptions, suggestions (§5.11)."""
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...domain.rules import PAYMENT_METHODS, label_payment
from ..widgets import DataTable, Page, info, money, refresh_after

ORDER_STATUS_LABELS = {"draft": "Brouillon", "confirmed": "Confirmée",
                       "partially_received": "Partiellement reçue",
                       "received": "Reçue", "cancelled": "Annulée"}


class SupplierDialog(QDialog):
    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouveau fournisseur")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit()
        self.name = QLineEdit()
        self.contact = QLineEdit()
        self.phone = QLineEdit()
        self.address = QLineEdit()
        self.terms = QLineEdit()
        self.lead_time = QSpinBox()
        self.lead_time.setRange(0, 365)
        form.addRow("Code *", self.code)
        form.addRow("Raison sociale *", self.name)
        form.addRow("Contact", self.contact)
        form.addRow("Téléphone", self.phone)
        form.addRow("Adresse", self.address)
        form.addRow("Conditions", self.terms)
        form.addRow("Délai habituel (jours)", self.lead_time)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.services["stock"].create_supplier(
                self.code.text().strip(), self.name.text().strip(),
                contact=self.contact.text().strip() or None,
                phone=self.phone.text().strip() or None,
                address=self.address.text().strip() or None,
                terms=self.terms.text().strip() or None,
                lead_time_days=self.lead_time.value())
        except Exception as exc:
            QMessageBox.warning(self, "Fournisseur", str(exc))
            return
        self.accept()


class OrderDialog(QDialog):
    """Commande d'achat : ne modifie jamais le stock (§5.11)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouvelle commande d'achat")
        self.resize(760, 520)
        layout = QVBoxLayout(self)

        head = QFormLayout()
        self.supplier = QComboBox()
        for supplier in services["stock"].list_suppliers():
            self.supplier.addItem(supplier.name, supplier.id)
        head.addRow("Fournisseur", self.supplier)
        layout.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Produit", "Quantité (unités de base)",
                                              "Prix unitaire", "Total"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        form = QHBoxLayout()
        self.product = QComboBox()
        for product in services["catalog"].list_products():
            self.product.addItem(f"{product.name} ({product.reference})", product.id)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.cost = QSpinBox()
        self.cost.setRange(0, 100_000_000)
        self.cost.setSingleStep(25)
        add = QPushButton("Ajouter la ligne")
        add.clicked.connect(self._add_line)
        form.addWidget(self.product, 2)
        form.addWidget(QLabel("Qté"))
        form.addWidget(self.quantity)
        form.addWidget(QLabel("Prix"))
        form.addWidget(self.cost)
        form.addWidget(add)
        layout.addLayout(form)

        charges = QFormLayout()
        self.discount = QSpinBox()
        self.discount.setRange(0, 100_000_000)
        self.discount.setSingleStep(500)
        self.discount.setToolTip("Remise globale négociée (FCFA)")
        self.freight = QSpinBox()
        self.freight.setRange(0, 100_000_000)
        self.freight.setSingleStep(500)
        self.freight.setToolTip("Transport : réparti dans le coût des articles")
        self.other_fees = QSpinBox()
        self.other_fees.setRange(0, 100_000_000)
        self.other_fees.setSingleStep(500)
        for widget in (self.discount, self.freight, self.other_fees):
            widget.valueChanged.connect(lambda _: self._reload())
        fees_row = QHBoxLayout()
        fees_row.addWidget(QLabel("Remise"))
        fees_row.addWidget(self.discount)
        fees_row.addWidget(QLabel("Transport"))
        fees_row.addWidget(self.freight)
        fees_row.addWidget(QLabel("Autres frais"))
        fees_row.addWidget(self.other_fees)
        fees = QWidget()
        fees.setLayout(fees_row)
        fees_row.setContentsMargins(0, 0, 0, 0)
        charges.addRow("Remise / frais d'approche", fees)
        layout.addLayout(charges)

        self.total_label = QLabel("Total : 0 FCFA")
        self.total_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(self.total_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer la commande")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.lines = []

    def _add_line(self):
        if self.quantity.value() <= 0:
            return
        product_id = self.product.currentData()
        self.lines.append({"product_id": product_id,
                           "designation": self.product.currentText(),
                           "quantity": self.quantity.value(),
                           "quantity_display": self.quantity.value(),
                           "unit_cost": self.cost.value()})
        self._reload()

    def _reload(self):
        self.table.setRowCount(len(self.lines))
        total = 0
        for row, line in enumerate(self.lines):
            amount = line["quantity"] * line["unit_cost"]
            total += amount
            for column, value in enumerate([line["designation"], line["quantity"],
                                            money(line["unit_cost"]), money(amount)]):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~2)  # lecture seule
                self.table.setItem(row, column, item)
        discount = min(self.discount.value(), total)
        fees = self.freight.value() + self.other_fees.value()
        net = total - discount
        self.total_label.setText(
            f"Lignes : {money(total)}   ·   remise : {money(discount)}   ·   "
            f"frais : {money(fees)}   ·   net à payer : {money(net + fees)}")

    def _save(self):
        if not self.lines:
            QMessageBox.information(self, "Commande", "Ajoutez au moins une ligne.")
            return
        if self.supplier.currentData() is None:
            QMessageBox.information(self, "Commande", "Choisissez un fournisseur.")
            return
        try:
            self.services["stock"].create_purchase_order(
                self.supplier.currentData(), self.lines,
                discount=self.discount.value(),
                freight_fees=self.freight.value(),
                other_fees=self.other_fees.value())
        except Exception as exc:
            QMessageBox.warning(self, "Commande", str(exc))
            return
        self.accept()


class ReceiptDialog(QDialog):
    """Réception partielle ou totale : seules les quantités reçues entrent en stock."""

    def __init__(self, services, order, parent=None):
        super().__init__(parent)
        self.services = services
        self.order = order
        self.setWindowTitle(f"Réception — {order.number}")
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Saisissez les quantités réellement reçues, "
                                "refusées et le coût constaté (unités de base). "
                                "Seules les quantités reçues entrent en stock."))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Produit", "Commandé", "Déjà reçu", "Reçu maintenant", "Refusé",
             "Coût unitaire"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.spins = []
        self.refused_spins = []
        self.cost_spins = []
        for line in order.lines:
            row = self.table.rowCount()
            self.table.insertRow(row)
            remaining = line.quantity - line.received_qty
            values = [line.designation, line.quantity, line.received_qty]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~2)
                self.table.setItem(row, column, item)
            spin = QSpinBox()
            spin.setRange(0, max(remaining, 0))
            spin.setValue(0)
            spin.valueChanged.connect(self._update_summary)
            self.table.setCellWidget(row, 3, spin)
            refused = QSpinBox()
            refused.setRange(0, max(remaining, 0))
            self.table.setCellWidget(row, 4, refused)
            cost = QSpinBox()
            cost.setRange(0, 100_000_000)
            cost.setValue(line.landed_cost or line.unit_cost)
            cost.setToolTip("Coût convenu majoré des frais d'approche")
            cost.valueChanged.connect(self._update_summary)
            self.table.setCellWidget(row, 5, cost)
            self.spins.append((line, spin))
            self.refused_spins.append(refused)
            self.cost_spins.append(cost)

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.summary)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Commentaire de réception (facultatif)")
        layout.addWidget(self.comment)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Valider la réception")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_summary()

    def _update_summary(self) -> None:
        total = sum(spin.value() * cost.value() for (_line, spin), cost
                    in zip(self.spins, self.cost_spins))
        received = sum(spin.value() for _line, spin in self.spins)
        refused = sum(spin.value() for spin in self.refused_spins)
        self.summary.setText(f"Reçu : {received} unité(s)   ·   refusé : {refused}   "
                             f"·   montant réceptionné : {money(total)}")

    def _save(self):
        receipts = [{"order_line_id": line.id, "quantity": spin.value(),
                     "unit_cost": cost.value(),
                     "quantity_refused": refused.value()}
                    for (line, spin), cost, refused
                    in zip(self.spins, self.cost_spins, self.refused_spins)
                    if spin.value() > 0]
        if not receipts:
            QMessageBox.information(self, "Réception",
                                    "Aucune quantité reçue à enregistrer.")
            return
        try:
            receipt = self.services["stock"].receive(
                self.order.id, receipts,
                comment=self.comment.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Réception refusée", str(exc))
            return
        info(self, f"Réception {receipt.number} validée : "
                   f"{money(receipt.total_amount)}.\nLe stock et le solde "
                   "fournisseur ont été mis à jour.", "Réception enregistrée")
        self.accept()


class SupplierPaymentDialog(QDialog):
    """Règlement d'un fournisseur, éventuellement rattaché à une facture (§5.11)."""

    def __init__(self, services, supplier, parent=None):
        super().__init__(parent)
        self.services = services
        self.supplier = supplier
        self.setWindowTitle(f"Payer — {supplier.name}")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        due = QLabel(f"Solde dû : {money(supplier.balance)}")
        due.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(due)
        form = QFormLayout()
        self.amount = QSpinBox()
        self.amount.setRange(1, 1_000_000_000)
        self.amount.setSingleStep(500)
        self.amount.setValue(max(supplier.balance, 1))
        self.method = QComboBox()
        for method in PAYMENT_METHODS:
            self.method.addItem(label_payment(method), method)
        self.invoice = QComboBox()
        self.invoice.addItem("Toutes les factures (affectation globale)", None)
        for invoice in services["stock"].supplier_invoices(supplier.id, only_due=True):
            outstanding = invoice.total_amount - invoice.paid_amount
            self.invoice.addItem(f"{invoice.number} — reste {money(outstanding)}",
                                 invoice.id)
        form.addRow("Montant", self.amount)
        form.addRow("Moyen de paiement", self.method)
        form.addRow("Facture", self.invoice)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Référence du règlement (facultatif)")
        form.addRow("Commentaire", self.comment)
        layout.addLayout(form)
        hint = QLabel("Seules les espèces diminuent le solde physique de la caisse "
                      "ouverte. Le stock n'est pas modifié.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer le paiement")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.services["stock"].pay_supplier(
                self.supplier.id, self.amount.value(),
                payment_method=self.method.currentData(),
                invoice_id=self.invoice.currentData(),
                comment=self.comment.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Paiement refusé", str(exc))
            return
        self.accept()


class PurchaseOrderHistoryDialog(QDialog):
    """Historique des achats : commandes, réceptions, paiements (§5.11)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Historique des achats")
        self.setMinimumSize(820, 500)
        layout = QVBoxLayout(self)
        from PySide6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        orders_tab = QWidget()
        orders_layout = QVBoxLayout(orders_tab)
        self.orders = DataTable(["N°", "Fournisseur", "Date", "Statut", "Total"])
        self.orders.doubleClicked.connect(lambda _: self._act("reopen"))
        orders_layout.addWidget(self.orders)
        orders_bar = QHBoxLayout()
        orders_bar.addWidget(QPushButton("Annuler la commande",
                                        clicked=lambda: self._act("cancel")))
        orders_bar.addWidget(QPushButton("Rouvrir la commande",
                                        clicked=lambda: self._act("reopen")))
        orders_bar.addStretch(1)
        orders_layout.addLayout(orders_bar)
        self.tabs.addTab(orders_tab, "Commandes")

        payments_tab = QWidget()
        payments_layout = QVBoxLayout(payments_tab)
        self.payments = DataTable(["Date", "Fournisseur", "Montant", "Moyen",
                                   "Commentaire"])
        payments_layout.addWidget(self.payments)
        self.tabs.addTab(payments_tab, "Paiements")

        invoices_tab = QWidget()
        invoices_layout = QVBoxLayout(invoices_tab)
        self.invoices = DataTable(["N°", "Fournisseur", "Date", "Total", "Payé",
                                   "Reste dû"])
        invoices_layout.addWidget(self.invoices)
        self.tabs.addTab(invoices_tab, "Factures")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._orders = []
        self._load()

    STATUS_LABELS = ORDER_STATUS_LABELS

    def _load(self) -> None:
        stock = self.services["stock"]
        suppliers = {sup.id: sup.name for sup in stock.list_suppliers()}
        orders = stock.list_purchase_orders(limit=300)
        self._orders = orders
        self.orders.load([[order.number, suppliers.get(order.supplier_id, "—"),
                           order.ordered_at.strftime("%d/%m/%Y") if order.ordered_at else "",
                           self.STATUS_LABELS.get(order.status, order.status),
                           money(order.total_amount)] for order in orders],
                         numeric_columns={4})
        if orders:
            self.orders.selectRow(0)
        self.payments.load([[pay.at.strftime("%d/%m/%Y %H:%M") if pay.at else "",
                             suppliers.get(pay.supplier_id, "—"),
                             money(pay.amount), label_payment(pay.payment_method),
                             pay.comment or ""]
                            for pay in stock.list_payments(limit=300)],
                           numeric_columns={2})
        self.invoices.load([[inv.number, suppliers.get(inv.supplier_id, "—"),
                             inv.at.strftime("%d/%m/%Y") if inv.at else "",
                             money(inv.total_amount), money(inv.paid_amount),
                             money(inv.total_amount - inv.paid_amount)]
                            for inv in stock.supplier_invoices()],
                           numeric_columns={3, 4, 5})

    def _selected_order(self):
        row = self.orders.selected_row()
        if row is None or row >= len(self._orders):
            return None
        return self._orders[row]

    def _act(self, action: str) -> None:
        order = self._selected_order()
        if order is None:
            QMessageBox.information(self, "Achats",
                                    "Sélectionnez une commande.")
            return
        from PySide6.QtWidgets import QInputDialog
        if action == "cancel":
            if order.status in ("received", "cancelled"):
                QMessageBox.information(self, "Annulation",
                                        "Commande déjà soldée ou annulée.")
                return
            label = "Motif d'annulation :"
            raison, ok = QInputDialog.getText(self, "Annuler", label)
            if not ok or not raison.strip():
                return
            try:
                self.services["stock"].cancel_order(order.id, raison.strip())
            except Exception as exc:
                QMessageBox.warning(self, "Annulation impossible", str(exc))
                return
        else:
            if order.status not in ("received", "cancelled"):
                QMessageBox.information(self, "Réouverture",
                                        "Seule une commande soldée ou annulée "
                                        "peut être rouverte.")
                return
            raison, ok = QInputDialog.getText(
                self, "Rouvrir", "Motif de réouverture :")
            if not ok or not raison.strip():
                return
            try:
                self.services["stock"].reopen_order(order.id, raison.strip())
            except Exception as exc:
                QMessageBox.warning(self, "Réouverture impossible", str(exc))
                return
        self._load()


class PurchasesPage(Page):
    title = "Achats et réapprovisionnement"
    subtitle = ("Une commande ne modifie pas le stock : seule une réception validée "
                "fait entrer les marchandises.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Nouveau fournisseur", self.new_supplier)
        self.add_action("Nouvelle commande", self.new_order, primary=True)
        self.add_action("Réceptionner", self.receive)
        self.add_action("Payer le fournisseur", self.pay_supplier)
        self.add_action("Historique des achats", self.open_history)
        self.add_action("Suggestions de réappro", self.suggestions)
        self.add_stretch()

        from PySide6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)

        orders_tab = QWidget()
        orders_layout = QVBoxLayout(orders_tab)
        self.orders = DataTable(["N°", "Fournisseur", "Date", "Statut", "Total",
                                 "Commentaire"])
        self.orders.doubleClicked.connect(lambda _: self.receive())
        orders_layout.addWidget(self.orders)
        self.tabs.addTab(orders_tab, "Commandes d'achat")

        suppliers_tab = QWidget()
        suppliers_layout = QVBoxLayout(suppliers_tab)
        self.supplier_search = QLineEdit()
        self.supplier_search.setPlaceholderText("Rechercher un fournisseur…")
        self.supplier_search.textChanged.connect(self.refresh)
        suppliers_layout.addWidget(self.supplier_search)
        self.suppliers = DataTable(["Code", "Fournisseur", "Téléphone", "Contact",
                                    "Conditions", "Délai (j)", "Achats",
                                    "Solde dû"])
        self.suppliers.doubleClicked.connect(lambda _: self.pay_supplier())
        suppliers_layout.addWidget(self.suppliers)
        self.tabs.addTab(suppliers_tab, "Fournisseurs")

        stock_tab = QWidget()
        stock_layout = QVBoxLayout(stock_tab)
        self.alerts = DataTable(["Produit", "Disponible", "Stock de sécurité",
                                 "Fournisseur", "Qté suggérée"])
        stock_layout.addWidget(self.alerts)
        self.tabs.addTab(stock_tab, "À réapprovisionner")

    STATUS_LABELS = ORDER_STATUS_LABELS

    def refresh(self) -> None:
        stock = self.services["stock"]
        self._orders = stock.pending_purchase_orders()
        self.orders.load([[order.number,
                           self._supplier_name(order.supplier_id),
                           order.ordered_at.strftime("%d/%m/%Y"),
                           self.STATUS_LABELS.get(order.status, order.status),
                           money(order.total_amount), order.comment or ""]
                          for order in self._orders], numeric_columns={4})

        suppliers = stock.list_suppliers(self.supplier_search.text().strip() or None)
        self._suppliers = suppliers
        purchased = stock.purchased_by_supplier()
        self.suppliers.load([[sup.code, sup.name, sup.phone or "—",
                              sup.contact or "—", sup.terms or "—",
                              sup.lead_time_days, money(purchased.get(sup.id, 0)),
                              money(sup.balance)]
                             for sup in suppliers], numeric_columns={5, 6, 7})

        suggestions = stock.reorder_suggestions()
        self._suggestions = suggestions
        self.alerts.load([[row["name"], row["available"], row["safety_stock"],
                           row["supplier"] or "—", row["suggested_qty"]]
                          for row in suggestions], numeric_columns={1, 2, 4})

    def _supplier_name(self, supplier_id: int) -> str:
        suppliers = {sup.id: sup.name for sup in self.services["stock"].list_suppliers()}
        return suppliers.get(supplier_id, f"#{supplier_id}")

    @refresh_after
    def new_supplier(self):
        if SupplierDialog(self.services, self).exec():
            return True

    @refresh_after
    def new_order(self):
        if not self.services["stock"].list_suppliers():
            QMessageBox.information(self, "Commande",
                                    "Créez d'abord un fournisseur.")
            return
        if not self.services["catalog"].list_products():
            QMessageBox.information(self, "Commande", "Créez d'abord un produit.")
            return
        if OrderDialog(self.services, self).exec():
            return True

    @refresh_after
    def receive(self):
        row = self.orders.selected_row()
        if row is None or row >= len(self._orders):
            QMessageBox.information(self, "Réception",
                                    "Sélectionnez une commande d'achat.")
            return
        order = self._orders[row]
        if order.status == "received":
            QMessageBox.information(self, "Réception", "Commande déjà soldée.")
            return
        if ReceiptDialog(self.services, order, self).exec():
            return True

    @refresh_after
    def pay_supplier(self):
        """Règlement d'un fournisseur depuis l'onglet Fournisseurs (§5.11)."""
        suppliers = getattr(self, "_suppliers", [])
        if self.tabs.currentIndex() == 0:
            self.tabs.setCurrentIndex(1)
        row = self.suppliers.selected_row()
        if row is None or row >= len(suppliers):
            QMessageBox.information(self, "Paiement fournisseur",
                                    "Sélectionnez un fournisseur dans l'onglet "
                                    "« Fournisseurs ».")
            return
        supplier = suppliers[row]
        if supplier.balance <= 0:
            QMessageBox.information(self, "Paiement fournisseur",
                                    f"Aucun solde dû pour {supplier.name}.")
            return
        if SupplierPaymentDialog(self.services, supplier, self).exec():
            return True

    def open_history(self):
        PurchaseOrderHistoryDialog(self.services, self).exec()
        self.refresh()

    @refresh_after
    def suggestions(self):
        if not self._suggestions:
            QMessageBox.information(self, "Réapprovisionnement",
                                    "Aucun produit sous seuil actuellement.")
            return
        self.tabs.setCurrentIndex(2)
        return True
