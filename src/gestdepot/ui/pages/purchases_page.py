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

from ..widgets import DataTable, Page, info, money, refresh_after


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
        self.total_label.setText(f"Total : {money(total)}")

    def _save(self):
        if not self.lines:
            QMessageBox.information(self, "Commande", "Ajoutez au moins une ligne.")
            return
        if self.supplier.currentData() is None:
            QMessageBox.information(self, "Commande", "Choisissez un fournisseur.")
            return
        try:
            self.services["stock"].create_purchase_order(
                self.supplier.currentData(), self.lines)
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
        layout.addWidget(QLabel("Saisissez les quantités réellement reçues "
                                "(unités de base)."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Produit", "Commandé", "Déjà reçu",
                                              "Reçu maintenant"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.spins = []
        for line in order.lines:
            row = self.table.rowCount()
            self.table.insertRow(row)
            remaining = line.quantity - line.received_qty
            values = [line.designation, line.quantity, line.received_qty, ""]
            for column, value in enumerate(values[:3]):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~2)
                self.table.setItem(row, column, item)
            spin = QSpinBox()
            spin.setRange(0, max(remaining, 0))
            spin.setValue(0)
            self.table.setCellWidget(row, 3, spin)
            self.spins.append((line, spin))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Valider la réception")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        receipts = [{"order_line_id": line.id, "quantity": spin.value(),
                     "unit_cost": line.unit_cost}
                    for line, spin in self.spins if spin.value() > 0]
        if not receipts:
            QMessageBox.information(self, "Réception",
                                    "Aucune quantité reçue à enregistrer.")
            return
        try:
            receipt = self.services["stock"].receive(self.order.id, receipts)
        except Exception as exc:
            QMessageBox.warning(self, "Réception refusée", str(exc))
            return
        info(self, f"Réception {receipt.number} validée : "
                   f"{money(receipt.total_amount)}.\nLe stock et le solde "
                   "fournisseur ont été mis à jour.", "Réception enregistrée")
        self.accept()


class PurchasesPage(Page):
    title = "Achats et réapprovisionnement"
    subtitle = ("Une commande ne modifie pas le stock : seule une réception validée "
                "fait entrer les marchandises.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Nouveau fournisseur", self.new_supplier)
        self.add_action("Nouvelle commande", self.new_order, primary=True)
        self.add_action("Réceptionner", self.receive)
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
        self.suppliers = DataTable(["Code", "Fournisseur", "Téléphone",
                                    "Délai (j)", "Solde dû"])
        suppliers_layout.addWidget(self.suppliers)
        self.tabs.addTab(suppliers_tab, "Fournisseurs")

        stock_tab = QWidget()
        stock_layout = QVBoxLayout(stock_tab)
        self.alerts = DataTable(["Produit", "Disponible", "Stock de sécurité",
                                 "Fournisseur", "Qté suggérée"])
        stock_layout.addWidget(self.alerts)
        self.tabs.addTab(stock_tab, "À réapprovisionner")

    STATUS_LABELS = {"draft": "Brouillon", "confirmed": "Confirmée",
                     "partially_received": "Partiellement reçue",
                     "received": "Reçue", "cancelled": "Annulée"}

    def refresh(self) -> None:
        stock = self.services["stock"]
        self._orders = stock.pending_purchase_orders()
        self.orders.load([[order.number,
                           self._supplier_name(order.supplier_id),
                           order.ordered_at.strftime("%d/%m/%Y"),
                           self.STATUS_LABELS.get(order.status, order.status),
                           money(order.total_amount), order.comment or ""]
                          for order in self._orders], numeric_columns={4})

        suppliers = stock.list_suppliers()
        self.suppliers.load([[sup.code, sup.name, sup.phone or "—",
                              sup.lead_time_days, money(sup.balance)]
                             for sup in suppliers], numeric_columns={3, 4})

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
    def suggestions(self):
        if not self._suggestions:
            QMessageBox.information(self, "Réapprovisionnement",
                                    "Aucun produit sous seuil actuellement.")
            return
        self.tabs.setCurrentIndex(2)
        return True
