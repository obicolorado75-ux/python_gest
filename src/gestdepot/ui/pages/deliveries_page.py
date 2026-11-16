"""Commandes clients et livraisons : cycle complet (§5.10).

Deux onglets : **Commandes** (brouillon → confirmée → préparation → prête) et
**Livraisons** (planifiée → en route → livrée / partielle / échouée). La sortie
de stock n'a lieu qu'à la confirmation de la livraison, une seule fois.
"""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...services import payment_methods
from ...services.delivery_service import DELIVERY_STATUSES, ORDER_STATUSES
from ..widgets import DataTable, Page, info, money, refresh_after


class OrderDialog(QDialog):
    """Nouvelle commande client : client, lignes, date souhaitée, réservation."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouvelle commande client")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.customer = QComboBox()
        for customer in services["sales"].list_customers():
            self.customer.addItem(customer.name, customer.id)
        self.customer.currentIndexChanged.connect(self._load_catalog)
        self.product = QComboBox()
        self.packaging = QComboBox()
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 100_000)
        self.price_list = QComboBox()
        self.price_list.addItem("Tarif du client", None)
        for price_list in services["catalog"].list_price_lists():
            self.price_list.addItem(price_list.name, price_list.id)
        self.expected = QDateEdit(QDate.currentDate().addDays(1))
        self.expected.setCalendarPopup(True)
        self.expected.setDisplayFormat("dd/MM/yyyy")
        self.address = QLineEdit()
        self.fee = QSpinBox()
        self.fee.setRange(0, 1_000_000)
        self.fee.setSingleStep(500)
        self.reserve = QCheckBox("Réserver le stock à la confirmation")
        self.reserve.setChecked(True)
        self.note = QLineEdit()
        form.addRow("Client *", self.customer)
        form.addRow("Produit", self.product)
        form.addRow("Conditionnement", self.packaging)
        form.addRow("Quantité (conditionnements)", self.quantity)
        form.addRow("Tarif", self.price_list)
        form.addRow("Date souhaitée", self.expected)
        form.addRow("Adresse de livraison", self.address)
        form.addRow("Frais de livraison", self.fee)
        form.addRow("", self.reserve)
        form.addRow("Notes", self.note)
        layout.addLayout(form)
        self.hint = QLabel("Les lignes sont ajoutées une à une : la commande "
                           "enregistrée reste en brouillon et ne touche pas le "
                           "stock.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(self.hint)
        self.lines_table = DataTable(["Produit", "Cond.", "Qté", "Montant"])
        layout.addWidget(self.lines_table, 1)
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Ajouter la ligne au panier"))
        add_row.addStretch(1)
        from PySide6.QtWidgets import QPushButton
        add_row.addWidget(QPushButton("Ajouter", clicked=self.add_line))
        add_row.addWidget(QPushButton("Vider", clicked=self.clear_lines))
        layout.addLayout(add_row)
        self.total_label = QLabel("Total : 0 FCFA")
        self.total_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.total_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer le brouillon")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._lines: list[dict] = []
        self._load_catalog()

    # --- lignes ------------------------------------------------------------
    def _load_catalog(self):
        self.product.clear()
        for product in self.services["catalog"].list_products():
            if getattr(product, "archived", False):
                continue
            self.product.addItem(product.name, product.id)
        self._load_packagings()
        customer = self._current_customer()
        self.address.setText(getattr(customer, "address", "") or "")

    def _load_packagings(self):
        self.packaging.clear()
        self.packaging.addItem("À l'unité", None)
        product_id = self.product.currentData()
        if product_id is None:
            return
        for item in self.services["catalog"].list_packagings(product_id):
            self.packaging.addItem(f"{item.name} (×{item.factor})", item.id)

    def _current_customer(self):
        customer_id = self.customer.currentData()
        if customer_id is None:
            return None
        try:
            return self.services["sales"].get_customer(customer_id)
        except Exception:
            return None

    def add_line(self):
        if self.product.currentData() is None:
            QMessageBox.information(self, "Commande", "Choisissez un produit.")
            return
        self._lines.append({
            "product_id": self.product.currentData(),
            "packaging_id": self.packaging.currentData(),
            "quantity_display": self.quantity.value(),
        })
        self._refresh_lines()

    def clear_lines(self):
        self._lines = []
        self._refresh_lines()

    def _refresh_lines(self):
        if not self._lines:
            self.lines_table.load([])
            self.total_label.setText("Total : 0 FCFA")
            return
        try:
            draft = self.services["sales"].draft_lines(
                self._lines, self.price_list.currentData(), check_stock=False)
        except Exception as exc:
            QMessageBox.warning(self, "Commande", str(exc))
            self._lines.pop()
            return
        self.lines_table.load([[ln["designation"], ln["unit_label"],
                                ln["quantity"], money(ln["total"])]
                               for ln in draft["lines"]],
                              numeric_columns={2, 3})
        self.total_label.setText(f"Total : {money(draft['total'])}")

    # --- enregistrement ----------------------------------------------------
    def _save(self):
        if not self._lines:
            QMessageBox.information(self, "Commande",
                                    "Ajoutez au moins une ligne à la commande.")
            return
        try:
            self.order = self.services["delivery"].create_order(
                self.customer.currentData(), self._lines,
                expected_date=self.expected.date().toPython(),
                price_list_id=self.price_list.currentData(),
                delivery_fee=self.fee.value(),
                address=self.address.text().strip() or None,
                note=self.note.text().strip() or None,
                reserve_stock=self.reserve.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "Commande", str(exc))
            return
        self.accept()


class DeliveryDialog(QDialog):
    """Planifier une livraison à partir d'une commande (quantités préparées)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Planifier une livraison")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.order = QComboBox()
        for order in services["delivery"].orders(limit=200):
            if order.status in ("confirmed", "preparing", "ready",
                                "partially_delivered"):
                self.order.addItem(
                    f"{order.number} — {order.customer.name}"
                    f" ({ORDER_STATUSES.get(order.status, order.status)})",
                    order.id)
        self.order.currentIndexChanged.connect(self._load_order)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.driver = QLineEdit()
        self.driver.setPlaceholderText("Nom du livreur")
        self.vehicle = QLineEdit()
        self.vehicle.setPlaceholderText("Immatriculation (facultatif)")
        self.address = QLineEdit()
        self.fee = QSpinBox()
        self.fee.setRange(0, 1_000_000)
        self.fee.setSingleStep(500)
        form.addRow("Commande *", self.order)
        form.addRow("Date prévue", self.date)
        form.addRow("Chauffeur", self.driver)
        form.addRow("Véhicule", self.vehicle)
        form.addRow("Adresse", self.address)
        form.addRow("Frais de livraison", self.fee)
        layout.addLayout(form)
        layout.addWidget(QLabel("Quantités préparées"))
        self.lines_table = DataTable(["Produit", "Reliquat", "Préparé"])
        layout.addWidget(self.lines_table, 1)
        self.hint = QLabel("La préparation ne sort pas la marchandise du stock : "
                           "la sortie a lieu à la confirmation de la livraison.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Planifier")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._detail = None
        self._load_order()

    def _load_order(self):
        order_id = self.order.currentData()
        if order_id is None:
            self._detail = None
            self.lines_table.load([])
            return
        self._detail = self.services["delivery"].get_order(order_id)
        self.address.setText(self._detail.get("address") or "")
        self.fee.setValue(self._detail.get("delivery_fee") or 0)
        self.lines_table.load([[line["designation"], line["remaining"],
                                line["remaining"]]
                               for line in self._detail["lines"]],
                              numeric_columns={1, 2})

    def _save(self):
        if self.order.currentData() is None:
            QMessageBox.information(self, "Livraison",
                                    "Choisissez une commande confirmée.")
            return
        try:
            self.delivery = self.services["delivery"].plan_delivery(
                self.order.currentData(),
                scheduled_date=self.date.date().toPython(),
                driver=self.driver.text().strip() or None,
                vehicle=self.vehicle.text().strip() or None,
                address=self.address.text().strip() or None,
                fee=self.fee.value())
        except Exception as exc:
            QMessageBox.warning(self, "Livraison", str(exc))
            return
        self.accept()


class ConfirmDeliveryDialog(QDialog):
    """Confirmation de livraison : quantités réellement livrées, preuve, encaissement."""

    def __init__(self, services, delivery, parent=None):
        super().__init__(parent)
        self.services = services
        self.delivery = delivery
        self.setWindowTitle(f"Confirmer la livraison {delivery['number']}")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        head = QLabel(f"{delivery['customer']} — commande "
                      f"{delivery['order_number'] or '—'}")
        head.setStyleSheet("font-weight: 600;")
        layout.addWidget(head)
        layout.addWidget(QLabel("Quantités livrées (unités de base)"))
        self.lines_table = DataTable(["Produit", "Préparé", "Déjà livré", "Livré"])
        layout.addWidget(self.lines_table, 1)
        self.spins: dict[int, QSpinBox] = {}
        rows = []
        for line in delivery["lines"]:
            rows.append([line["designation"], line["prepared_qty"],
                         line["delivered_qty"], 0])
        self.lines_table.load(rows, numeric_columns={1, 2, 3})
        # un champ de saisie par ligne, aligné sur la colonne « Livré »
        for index, line in enumerate(delivery["lines"]):
            spin = QSpinBox()
            spin.setRange(0, max(line["remaining"], 0))
            spin.setValue(max(line["remaining"], 0))
            self.spins[line["id"]] = spin
            self.lines_table.setCellWidget(index, 3, spin)
        form = QFormLayout()
        self.method = QComboBox()
        labels = payment_methods.labels()
        for code in payment_methods.codes():
            self.method.addItem(labels[code], code)
        self.collected = QSpinBox()
        self.collected.setRange(0, 1_000_000_000)
        self.collected.setSingleStep(500)
        self.collected.setValue(delivery.get("collected_amount") or 0)
        self.proof = QPlainTextEdit()
        self.proof.setPlaceholderText("Preuve / commentaire (nom du réceptionnaire…)")
        self.proof.setMaximumHeight(70)
        form.addRow("Moyen de paiement", self.method)
        form.addRow("Montant encaissé", self.collected)
        form.addRow("Preuve", self.proof)
        layout.addLayout(form)
        self.hint = QLabel("La vente est créée à la confirmation : la sortie de "
                           "stock n'a lieu qu'une seule fois. Un montant inférieur "
                           "au total laisse une créance au client.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Confirmer la livraison")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        lines = [{"delivery_line_id": line_id, "delivered_qty": spin.value()}
                 for line_id, spin in self.spins.items()]
        try:
            self.result = self.services["delivery"].confirm_delivery(
                self.delivery["id"], lines=lines,
                proof=self.proof.toPlainText().strip() or None,
                collected_amount=self.collected.value(),
                payment_method=self.method.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "Livraison", str(exc))
            return
        self.accept()


class DeliveryPage(Page):
    title = "Commandes et livraisons"
    subtitle = ("Commandes clients, réservation facultative du stock, bons de "
                "livraison, reliquats et échecs de livraison (§5.10).")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Nouvelle commande", self.new_order, primary=True)
        self.add_action("Confirmer la commande", self.confirm_order)
        self.add_action("Prête à livrer", self.mark_ready)
        self.add_action("Annuler la commande", self.cancel_order)
        self.add_action("Planifier une livraison", self.plan_delivery)
        self.add_action("Départ du livreur", self.start_delivery)
        self.add_action("Confirmer la livraison", self.confirm_delivery)
        self.add_action("Échec de livraison", self.fail_delivery)
        self.add_action("Bon de livraison", self.print_note)

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)

        orders_tab = QWidget()
        orders_layout = QVBoxLayout(orders_tab)
        self.filter = QComboBox()
        self.filter.addItem("Toutes les commandes", None)
        for code, label in ORDER_STATUSES.items():
            self.filter.addItem(label, code)
        self.filter.currentIndexChanged.connect(self.refresh)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Statut"))
        filter_row.addWidget(self.filter)
        filter_row.addStretch(1)
        orders_layout.addLayout(filter_row)
        self.orders_table = DataTable(["N°", "Date", "Client", "Statut",
                                       "Attendu", "Total", "Reliquat",
                                       "Réservé"])
        orders_layout.addWidget(self.orders_table, 1)
        self.tabs.addTab(orders_tab, "Commandes")

        deliveries_tab = QWidget()
        deliveries_layout = QVBoxLayout(deliveries_tab)
        self.deliveries_table = DataTable(["N°", "Commande", "Client", "Date",
                                           "Livreur", "Statut", "Préparé",
                                           "Livré", "Encaissé"])
        deliveries_layout.addWidget(self.deliveries_table, 1)
        self.tabs.addTab(deliveries_tab, "Livraisons")
        self._orders: list = []
        self._deliveries: list = []

    # --- chargement --------------------------------------------------------
    def refresh(self):
        service = self.services["delivery"]
        status = self.filter.currentData()
        self._orders = list(service.orders(status=status, limit=300))
        rows = []
        for order in self._orders:
            detail = service.get_order(order.id)
            rows.append([
                order.number,
                order.created_at.strftime("%d/%m/%Y") if order.created_at else "—",
                order.customer.name if order.customer else "—",
                ORDER_STATUSES.get(order.status, order.status),
                order.desired_date.strftime("%d/%m/%Y") if order.desired_date else "—",
                money(order.total_amount),
                detail["remaining"],
                "Oui" if order.reserve_stock else "Non",
            ])
        self.orders_table.load(
            rows, numeric_columns={6},
            colors={3: {"Confirmée": "#12324F", "En préparation": "#B26A00",
                        "Prête": "#1B7F3B", "Livrée": "#1B7F3B",
                        "Partiellement livrée": "#B26A00",
                        "Annulée": "#B3261E"}})

        self._deliveries = list(service.deliveries(limit=300))
        delivery_rows = []
        for delivery in self._deliveries:
            delivery_rows.append([
                delivery.number,
                delivery.order.number if delivery.order else "—",
                delivery.customer.name if delivery.customer else "—",
                delivery.scheduled_date.strftime("%d/%m/%Y")
                if delivery.scheduled_date else "—",
                delivery.driver or "—",
                DELIVERY_STATUSES.get(delivery.status, delivery.status),
                delivery.prepared_qty,
                delivery.delivered_qty,
                money(delivery.collected_amount),
            ])
        self.deliveries_table.load(
            delivery_rows, numeric_columns={6, 7},
            colors={5: {"Livrée": "#1B7F3B", "Livrée partiellement": "#B26A00",
                        "Échec de livraison": "#B3261E"}})

    # --- sélections --------------------------------------------------------
    def _selected_order(self):
        row = self.orders_table.selected_row()
        if row is None or row >= len(self._orders):
            QMessageBox.information(self, "Commandes",
                                    "Sélectionnez d'abord une commande.")
            return None
        return self._orders[row]

    def _selected_delivery(self):
        row = self.deliveries_table.selected_row()
        if row is None or row >= len(self._deliveries):
            QMessageBox.information(self, "Livraisons",
                                    "Sélectionnez d'abord une livraison.")
            return None
        return self._deliveries[row]

    # --- actions commandes -------------------------------------------------
    @refresh_after
    def new_order(self):
        dialog = OrderDialog(self.services, self)
        if not dialog.exec():
            return
        info(self, f"Commande {dialog.order.number} enregistrée en brouillon.",
             "Commandes")
        return True

    @refresh_after
    def confirm_order(self):
        order = self._selected_order()
        if order is None:
            return False
        result = self.services["delivery"].confirm_order(order.id)
        message = f"Commande {result['number']} confirmée."
        if result["reserved"]:
            message += f"\n{result['reserved']} unité(s) réservée(s) en stock."
        info(self, message, "Commandes")
        return True

    @refresh_after
    def mark_ready(self):
        order = self._selected_order()
        if order is None:
            return False
        self.services["delivery"].set_order_status(order.id, "ready")
        info(self, f"Commande {order.number} prête à livrer.", "Commandes")
        return True

    @refresh_after
    def cancel_order(self):
        from PySide6.QtWidgets import QInputDialog
        order = self._selected_order()
        if order is None:
            return False
        reason, ok = QInputDialog.getText(
            self, "Annuler la commande",
            f"Motif d'annulation de {order.number} (obligatoire) :")
        if not ok:
            return
        self.services["delivery"].cancel_order(order.id, reason)
        info(self, "Commande annulée ; la réservation de stock est libérée.",
             "Commandes")
        return True

    # --- actions livraisons ------------------------------------------------
    @refresh_after
    def plan_delivery(self):
        dialog = DeliveryDialog(self.services, self)
        if not dialog.exec():
            return
        info(self, f"Livraison {dialog.delivery.number} planifiée.",
             "Livraisons")
        return True

    @refresh_after
    def start_delivery(self):
        delivery = self._selected_delivery()
        if delivery is None:
            return False
        self.services["delivery"].start_delivery(delivery.id)
        info(self, f"{delivery.number} : le livreur est en route.", "Livraisons")
        return True

    @refresh_after
    def confirm_delivery(self):
        delivery = self._selected_delivery()
        if delivery is None:
            return False
        detail = self.services["delivery"].get_delivery(delivery.id)
        dialog = ConfirmDeliveryDialog(self.services, detail, self)
        if not dialog.exec():
            return
        result = dialog.result
        message = f"Livraison confirmée ({result['delivered_qty']} unité(s))."
        if result["sale_number"]:
            message += f"\nVente {result['sale_number']} enregistrée."
        if result["remaining"]:
            message += f"\nReliquat à livrer : {result['remaining']} unité(s)."
        info(self, message, "Livraisons")
        return True

    @refresh_after
    def fail_delivery(self):
        from PySide6.QtWidgets import QInputDialog
        delivery = self._selected_delivery()
        if delivery is None:
            return False
        reason, ok = QInputDialog.getText(
            self, "Échec de livraison",
            f"Motif de l'échec de {delivery.number} (obligatoire) :")
        if not ok:
            return
        self.services["delivery"].fail_delivery(delivery.id, reason)
        info(self, "Échec enregistré : la commande et les paiements déjà reçus "
                   "sont conservés. Replanifiez la livraison.", "Livraisons")
        return True

    @refresh_after
    def print_note(self):
        delivery = self._selected_delivery()
        if delivery is None:
            return False
        path = self.services["delivery"].delivery_note(delivery.id)
        info(self, f"Bon de livraison généré :\n{path}", "Livraisons")
        return True
