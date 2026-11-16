"""Écran Ventes / Caisse : saisie rapide, panier, paiement, reçu (§5.5)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...domain.rules import label_status
from ...services import payment_methods
from ...services.sales_service import SalesError
from ..dialogs.sale_dialogs import (
    CancelSaleDialog,
    HeldSalesDialog,
    HoldDialog,
    ReturnDialog,
    SaleHistoryDialog,
    SplitPaymentDialog,
)
from ..widgets import DataTable, Page, confirm, info, money

LINE_HEADERS = ["Désignation", "Conditionnement", "Qté", "Prix unitaire", "Total"]


class SalesPage(Page):
    title = "Ventes / Caisse"
    subtitle = ("Rechercher un produit (F2), choisir le client (F4), "
                "encaisser (F6), valider (F9).")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.lines: list[dict] = []
        self.price_list_id: int | None = None
        self.customers: list = []
        self._split_payments: list[dict] = []
        self._held_id: int | None = None

        splitter = QSplitter(Qt.Horizontal)
        self.body.addWidget(splitter, 1)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([560, 520])

        self._bind_shortcuts()
        self.reload_reference_data()

    # --- panneau gauche : recherche + panier -------------------------------
    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher par nom, référence ou code-barres — F2")
        self.search.textChanged.connect(self._fill_products)
        self.search.returnPressed.connect(self.add_selected_product)
        layout.addWidget(self.search)

        self.product_list = QListWidget()
        self.product_list.setAlternatingRowColors(True)
        self.product_list.itemDoubleClicked.connect(lambda _: self.add_selected_product())
        layout.addWidget(self.product_list, 2)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Conditionnement :"))
        self.packaging_box = QComboBox()
        add_row.addWidget(self.packaging_box, 1)
        add_row.addWidget(QLabel("Qté :"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 9999)
        add_row.addWidget(self.qty_spin)
        self.add_button = QPushButton("Ajouter (F3)")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.clicked.connect(self.add_selected_product)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)

        self.cart = DataTable(LINE_HEADERS)
        self.cart.setMinimumHeight(220)
        layout.addWidget(QLabel("Panier"))
        layout.addWidget(self.cart, 3)

        cart_actions = QHBoxLayout()
        cart_actions.addWidget(QPushButton("Modifier la quantité",
                                          clicked=self.edit_line_quantity))
        cart_actions.addWidget(QPushButton("Retirer la ligne", clicked=self.remove_line))
        cart_actions.addWidget(QPushButton("Vider le panier", clicked=self.clear_cart))
        cart_actions.addStretch(1)
        layout.addLayout(cart_actions)

        hold_row = QHBoxLayout()
        hold_row.addWidget(QPushButton("Suspendre (F8)", clicked=self.hold_current_sale))
        hold_row.addWidget(QPushButton("Ventes suspendues",
                                       clicked=self.open_held_sales))
        hold_row.addWidget(QPushButton("Historique / retours",
                                       clicked=self.open_history))
        hold_row.addStretch(1)
        layout.addLayout(hold_row)
        return panel

    # --- panneau droit : client, totaux, paiement ---------------------------
    def _build_right(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setStyleSheet("#Card {background: #f8fafc; border: 1px solid #dde3ea;"
                            " border-radius: 8px;}")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)

        form = QFormLayout()
        self.customer_box = QComboBox()
        self.customer_box.currentIndexChanged.connect(self._customer_changed)
        form.addRow("Client", self.customer_box)

        self.price_list_box = QComboBox()
        self.price_list_box.currentIndexChanged.connect(self._price_list_changed)
        form.addRow("Tarif", self.price_list_box)

        self.deposit_box = QComboBox()
        self.deposit_qty = QSpinBox()
        self.deposit_qty.setRange(0, 999)
        deposit_row = QHBoxLayout()
        deposit_row.addWidget(self.deposit_box, 1)
        deposit_row.addWidget(self.deposit_qty)
        deposit_widget = QWidget()
        deposit_widget.setLayout(deposit_row)
        deposit_row.setContentsMargins(0, 0, 0, 0)
        form.addRow("Consigne (qté)", deposit_widget)
        layout.addLayout(form)

        self.discount_spin = QSpinBox()
        self.discount_spin.setRange(0, 100_000_000)
        self.discount_spin.setSingleStep(100)
        self.discount_spin.valueChanged.connect(lambda _: self._recompute())
        discount_row = QHBoxLayout()
        discount_row.addWidget(QLabel("Remise (FCFA)"))
        discount_row.addWidget(self.discount_spin, 1)
        layout.addLayout(discount_row)

        totals = QGridLayout()
        self.lbl_total = QLabel("0 FCFA")
        self.lbl_total.setStyleSheet("font-size: 22px; font-weight: 700; color: #12324f;")
        self.lbl_detail = QLabel("")
        self.lbl_detail.setStyleSheet("color: #5f6b7a; font-size: 11px;")
        totals.addWidget(QLabel("Total à payer"), 0, 0)
        totals.addWidget(self.lbl_total, 1, 0)
        totals.addWidget(self.lbl_detail, 2, 0)
        layout.addLayout(totals)

        layout.addWidget(QLabel("Moyen de paiement"))
        self.method_box = QComboBox()
        labels = payment_methods.labels()
        for method in payment_methods.codes():
            self.method_box.addItem(labels[method], method)
        layout.addWidget(self.method_box)

        paid_row = QHBoxLayout()
        paid_row.addWidget(QLabel("Montant encaissé"))
        self.paid_spin = QSpinBox()
        self.paid_spin.setRange(0, 1_000_000_000)
        self.paid_spin.setSingleStep(500)
        self.paid_spin.valueChanged.connect(lambda _: self._update_change())
        paid_row.addWidget(self.paid_spin, 1)
        layout.addLayout(paid_row)

        pay_row = QHBoxLayout()
        self.pay_full = QPushButton("Tout encaisser")
        self.pay_full.clicked.connect(self._pay_full)
        pay_row.addWidget(self.pay_full)
        self.split_button = QPushButton("Paiement mixte…")
        self.split_button.clicked.connect(self.open_split_payment)
        pay_row.addWidget(self.split_button)
        layout.addLayout(pay_row)

        self.change_label = QLabel("")
        self.change_label.setStyleSheet("color: #1B7F3B; font-weight: 600;")
        self.change_label.setWordWrap(True)
        layout.addWidget(self.change_label)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Note (facultatif)")
        layout.addWidget(self.note_edit)

        layout.addStretch(1)
        self.validate_button = QPushButton("Valider la vente (F9)")
        self.validate_button.setObjectName("PrimaryButton")
        self.validate_button.setMinimumHeight(42)
        self.validate_button.clicked.connect(self.confirm_sale)
        layout.addWidget(self.validate_button)

        self.new_button = QPushButton("Nouvelle vente")
        self.new_button.clicked.connect(self.reset)
        layout.addWidget(self.new_button)

        self.print_button = QPushButton("Imprimer le dernier ticket")
        self.print_button.setEnabled(False)
        self.print_button.clicked.connect(self.print_last_receipt)
        layout.addWidget(self.print_button)

        history_title = QLabel("Ventes récentes")
        history_title.setStyleSheet("font-weight: 600; margin-top: 10px;")
        layout.addWidget(history_title)
        self.recent = DataTable(["N°", "Total", "Statut"])
        self.recent.setMaximumHeight(150)
        layout.addWidget(self.recent)
        return panel

    # --- raccourcis (§5.5) ---------------------------------------------------
    def _bind_shortcuts(self) -> None:
        shortcuts = {
            "F2": lambda: self.search.setFocus(),
            "F4": lambda: self.customer_box.setFocus(),
            "F6": lambda: self.method_box.setFocus(),
            "F8": self.hold_current_sale,
            "F9": self.confirm_sale,
            "Escape": self.reset,
        }
        for key, slot in shortcuts.items():
            QShortcut(QKeySequence(key), self, activated=slot)

    # --- chargement -----------------------------------------------------------
    def reload_reference_data(self) -> None:
        catalog = self.services["catalog"]
        self.price_lists = catalog.list_price_lists()
        self.packagings = {}
        self._fill_price_lists()
        self._fill_customers()
        self._fill_deposits()
        self._fill_products()
        self._recompute()

    def _fill_price_lists(self) -> None:
        current = self.price_list_box.currentData()
        self.price_list_box.blockSignals(True)
        self.price_list_box.clear()
        self.price_list_box.addItem("Tarif par défaut", None)
        for price_list in self.price_lists:
            self.price_list_box.addItem(price_list.name, price_list.id)
        index = self.price_list_box.findData(current)
        if index < 0:
            # tarif par défaut = première liste (Détail) : saisie immédiate possible
            index = 1 if self.price_list_box.count() > 1 else 0
        self.price_list_box.setCurrentIndex(index)
        self.price_list_box.blockSignals(False)
        self._price_list_changed()

    def _fill_customers(self) -> None:
        self.customers = self.services["sales"].list_customers()
        current = self.customer_box.currentData()
        self.customer_box.blockSignals(True)
        self.customer_box.clear()
        self.customer_box.addItem("Client comptoir (paiement immédiat)", None)
        for customer in self.customers:
            label = f"{customer.name} — dû {money(customer.balance)}"
            self.customer_box.addItem(label, customer.id)
        index = self.customer_box.findData(current)
        self.customer_box.setCurrentIndex(index if index >= 0 else 0)
        self.customer_box.blockSignals(False)

    def _fill_deposits(self) -> None:
        current = self.deposit_box.currentData()
        self.deposit_box.clear()
        self.deposit_box.addItem("Aucune", None)
        for packaging in self.services["deposit"].list_packagings():
            self.deposit_box.addItem(
                f"{packaging.label} ({money(packaging.deposit_value)})", packaging.id)
        index = self.deposit_box.findData(current)
        self.deposit_box.setCurrentIndex(index if index >= 0 else 0)

    def _fill_products(self) -> None:
        search = self.search.text().strip() or None
        self.products = self.services["catalog"].list_products(search)
        self.product_list.clear()
        for product in self.products:
            available = self.services["stock"].available(product.id)
            item = QListWidgetItem(
                f"{product.name}  ·  {product.reference}  ·  dispo {available}")
            item.setData(Qt.UserRole, product.id)
            if available <= 0:
                item.setForeground(Qt.red)
            self.product_list.addItem(item)
        if self.product_list.count():
            self.product_list.setCurrentRow(0)
        self._fill_packagings()

    def _fill_packagings(self) -> None:
        self.packaging_box.clear()
        product = self._selected_product()
        if product is None:
            return
        self.packaging_box.addItem("Unité de base", None)
        for packaging in self.services["catalog"].list_packagings(product.id):
            self.packaging_box.addItem(f"{packaging.name} (×{packaging.factor})",
                                       packaging.id)

    def _selected_product(self):
        item = self.product_list.currentItem()
        if item is None:
            return None
        product_id = item.data(Qt.UserRole)
        return next((p for p in self.products if p.id == product_id), None)

    # --- interactions ----------------------------------------------------------
    def _customer_changed(self) -> None:
        customer_id = self.customer_box.currentData()
        customer = next((c for c in self.customers if c.id == customer_id), None)
        if customer and customer.price_list_id:
            index = self.price_list_box.findData(customer.price_list_id)
            if index >= 0:
                self.price_list_box.setCurrentIndex(index)
        self._recompute()

    def _price_list_changed(self) -> None:
        self.price_list_id = self.price_list_box.currentData()
        if getattr(self, "lines", None):
            self._render_cart()   # les prix affichés suivent le tarif choisi
        else:
            self._recompute()

    def add_selected_product(self) -> None:
        product = self._selected_product()
        if product is None:
            QMessageBox.information(self, "Produit", "Sélectionnez un produit.")
            return
        packaging_id = self.packaging_box.currentData()
        qty = self.qty_spin.value()
        item = {"product_id": product.id, "packaging_id": packaging_id,
                "quantity_display": qty, "base_qty": 0}
        try:
            prepared = self.services["sales"].draft_lines(
                self.lines + [item], self.price_list_id)
        except SalesError as exc:
            QMessageBox.warning(self, "Ajout impossible", str(exc))
            return
        self.lines = [{key: line[key] for key in
                       ("product_id", "packaging_id", "quantity_display", "base_qty")}
                      for line in prepared["lines"]]
        self.qty_spin.setValue(1)
        self._render_cart()
        self.search.selectAll()
        self.search.setFocus()

    def remove_line(self) -> None:
        row = self.cart.selected_row()
        if row is None:
            return
        del self.lines[row]
        self._render_cart()

    def edit_line_quantity(self) -> None:
        """Modifie la quantité d'une ligne du panier sans la ressaisir (§5.5)."""
        row = self.cart.selected_row()
        if row is None or row >= len(self.lines):
            QMessageBox.information(self, "Panier", "Sélectionnez une ligne.")
            return
        line = dict(self.lines[row])
        from PySide6.QtWidgets import QInputDialog
        qty, ok = QInputDialog.getInt(
            self, "Modifier la quantité",
            f"Nouvelle quantité ({line.get('quantity_display') or 1}) :",
            int(line.get("quantity_display") or 1), 0, 99_999, 1)
        if not ok:
            return
        if qty == 0:
            del self.lines[row]
            self._render_cart()
            return
        line["quantity_display"] = qty
        candidate = list(self.lines)
        candidate[row] = line
        try:
            prepared = self.services["sales"].draft_lines(
                candidate, self.price_list_id, self.discount_spin.value())
        except SalesError as exc:
            QMessageBox.warning(self, "Quantité refusée", str(exc))
            return
        self.lines = [{key: item[key] for key in
                       ("product_id", "packaging_id", "quantity_display", "base_qty")}
                      for item in prepared["lines"]]
        self._render_cart()

    def clear_cart(self) -> None:
        if self.lines and not confirm(self, "Vider le panier ?"):
            return
        self.lines = []
        self._render_cart()

    def _render_cart(self) -> None:
        rows = []
        self._prepared = []
        if self.lines:
            try:
                self._prepared = self.services["sales"].draft_lines(
                    self.lines, self.price_list_id, self.discount_spin.value())["lines"]
            except SalesError as exc:
                QMessageBox.warning(self, "Panier", str(exc))
                self._prepared = []
        for line in self._prepared:
            rows.append([line["designation"], line["unit_label"],
                         f"{line['quantity_display']} × {line['factor']}"
                         if line["factor"] > 1 else str(line["quantity"]),
                         money(line["unit_price"]), money(line["total"])])
        self.cart.load(rows, numeric_columns={3, 4})
        self._recompute()

    def _recompute(self) -> None:
        try:
            prepared = self.services["sales"].draft_lines(
                self.lines, self.price_list_id, self.discount_spin.value()) if self.lines else None
        except SalesError:
            prepared = None
        goods = prepared["total"] if prepared else 0
        deposit_id = self.deposit_box.currentData()
        deposit_amount = 0
        if deposit_id and self.deposit_qty.value():
            packaging = self.services["deposit"].get_packaging(deposit_id)
            deposit_amount = packaging.deposit_value * self.deposit_qty.value()
        total = goods + deposit_amount
        self.lbl_total.setText(money(total))
        parts = []
        if prepared and prepared["discount"]:
            parts.append(f"brut {money(prepared['gross_total'])} "
                         f"− remise {money(prepared['discount'])}")
        if deposit_amount:
            parts.append(f"dont consigne {money(deposit_amount)}")
        self.lbl_detail.setText("  ·  ".join(parts))
        self._total = total
        self._update_change()

    def _update_change(self) -> None:
        total = getattr(self, "_total", 0)
        paid = self.paid_spin.value()
        if paid > total:
            self.change_label.setText(f"Rendre au client : {money(paid - total)}")
            self.change_label.setStyleSheet("color: #1B7F3B; font-weight: 600;")
        elif paid < total:
            remaining = total - paid
            customer_id = self.customer_box.currentData()
            if customer_id is None:
                self.change_label.setText(
                    f"Reste à payer : {money(remaining)} — vente à crédit impossible "
                    "sans client.")
                self.change_label.setStyleSheet("color: #B3261E; font-weight: 600;")
            else:
                self.change_label.setText(f"Créance créée : {money(remaining)}")
                self.change_label.setStyleSheet("color: #B26A00; font-weight: 600;")
        else:
            self.change_label.setText("")
            self.change_label.setStyleSheet("color: #1B7F3B; font-weight: 600;")

    def _pay_full(self) -> None:
        self.paid_spin.setValue(getattr(self, "_total", 0))
        self._split_payments = []

    def open_split_payment(self) -> None:
        """Saisie d'un règlement en plusieurs moyens de paiement (§5.5)."""
        total = getattr(self, "_total", 0)
        if not self.lines:
            QMessageBox.information(self, "Paiement mixte",
                                    "Le panier est vide.")
            return
        dialog = SplitPaymentDialog(total, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        payments = dialog.payments()
        self._split_payments = payments
        collected = sum(entry["amount"] for entry in payments)
        self.paid_spin.blockSignals(True)
        self.paid_spin.setValue(min(collected, total))
        self.paid_spin.blockSignals(False)
        self.method_box.blockSignals(True)
        index = self.method_box.findData(payments[0]["method"])
        if index >= 0:
            self.method_box.setCurrentIndex(index)
        self.method_box.blockSignals(False)
        detail = " + ".join(f"{payment_methods.labels().get(entry['method'], entry['method'])} "
                            f"{money(entry['amount'])}" for entry in payments)
        self.lbl_detail.setText(f"Encaissements : {detail}")
        self._update_change()

    def _effective_payments(self) -> list[dict]:
        """Encaissements à transmettre au service (mixte ou règlement unique)."""
        total = getattr(self, "_total", 0)
        if self._split_payments:
            payments = [dict(entry) for entry in self._split_payments]
            self._split_payments = payments
            # le rendu de monnaie n'est jamais encaissé : on plafonne au dû
            over = sum(entry["amount"] for entry in payments) - total
            for entry in reversed(payments):
                if over <= 0:
                    break
                reduction = min(entry["amount"], over)
                entry["amount"] -= reduction
                over -= reduction
            return [entry for entry in payments if entry["amount"] > 0]
        paid = min(self.paid_spin.value(), total)
        if paid <= 0:
            return []
        return [{"method": self.method_box.currentData(), "amount": paid}]

    # --- validation ------------------------------------------------------------
    def confirm_sale(self) -> None:
        if not self.lines:
            QMessageBox.information(self, "Vente", "Le panier est vide.")
            return
        paid = self.paid_spin.value()
        total = getattr(self, "_total", 0)
        if paid > total:
            # on n'encaisse que le dû : le rendu de monnaie est une information
            paid = total
        if not confirm(self, f"Valider la vente de {money(total)} ?"):
            return
        payments = self._effective_payments()
        paid = sum(entry["amount"] for entry in payments)
        try:
            sale = self.services["sales"].confirm_sale(
                items=self.lines,
                payment_method=self.method_box.currentData(),
                paid_amount=paid,
                customer_id=self.customer_box.currentData(),
                price_list_id=self.price_list_id,
                manual_discount=self.discount_spin.value(),
                deposit_packaging_id=self.deposit_box.currentData(),
                deposit_qty=self.deposit_qty.value(),
                note=self.note_edit.text().strip() or None,
                payments=payments)
        except (SalesError, PermissionError) as exc:
            QMessageBox.warning(self, "Vente refusée", str(exc))
            return
        self._last_sale = sale
        self._last_sale_lines = list(sale.lines)
        self.print_button.setEnabled(True)
        info(self, f"Vente {sale.number} validée : {money(sale.total_amount)}.\n"
                   f"Encaissé : {money(sale.paid_amount)}  ·  "
                   f"Créance : {money(sale.total_amount - sale.paid_amount)}",
             "Vente enregistrée")
        self.reset()
        self.refresh()

    # --- suspension / reprise (F8) -------------------------------------------
    def _sale_label(self) -> str:
        customer_id = self.customer_box.currentData()
        customer = next((c for c in self.customers if c.id == customer_id), None)
        return customer.name if customer else "Comptoir"

    def _sale_state(self) -> dict:
        return {"items": [dict(item) for item in self.lines],
                "customer_id": self.customer_box.currentData(),
                "price_list_id": self.price_list_id,
                "discount": self.discount_spin.value(),
                "deposit_packaging_id": self.deposit_box.currentData(),
                "deposit_qty": self.deposit_qty.value(),
                "label": self._sale_label(),
                "note": self.note_edit.text().strip() or None}

    def hold_current_sale(self) -> None:
        """Suspend la vente en cours sans écriture de stock ni de caisse (F8)."""
        if not self.lines:
            QMessageBox.information(self, "Suspension",
                                    "Le panier est vide.")
            return
        dialog = HoldDialog(self._sale_label(), self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        state = self._sale_state()
        try:
            held = self.services["sales"].hold_sale(
                items=state["items"], customer_id=state["customer_id"],
                price_list_id=state["price_list_id"],
                manual_discount=state["discount"],
                deposit_packaging_id=state["deposit_packaging_id"],
                deposit_qty=state["deposit_qty"],
                label=dialog.label.text().strip() or state["label"],
                note=dialog.note.text().strip() or None)
        except (SalesError, PermissionError) as exc:
            QMessageBox.warning(self, "Suspension impossible", str(exc))
            return
        self._held_id = held.id
        info(self, f"Panier « {held.label} » suspendu.\n"
                   "Il reste disponible dans « Ventes suspendues ».",
             "Vente suspendue")
        self.reset()

    def open_held_sales(self) -> None:
        dialog = HeldSalesDialog(self.services, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_id is None:
            return
        self.resume_held(dialog.selected_id)

    def resume_held(self, held_id: int) -> None:
        """Recharge un panier suspendu dans l'écran de vente (aucune validation)."""
        try:
            data = self.services["sales"].get_held_sale(held_id)
        except (SalesError, PermissionError) as exc:
            QMessageBox.warning(self, "Reprise impossible", str(exc))
            return
        self.lines = [{key: item[key] for key in
                       ("product_id", "packaging_id", "quantity_display", "base_qty")}
                      for item in data["items"]]
        self._held_id = held_id
        self.customer_box.blockSignals(True)
        index = self.customer_box.findData(data["customer_id"])
        self.customer_box.setCurrentIndex(index if index >= 0 else 0)
        self.customer_box.blockSignals(False)
        if data["price_list_id"]:
            self.price_list_box.blockSignals(True)
            index = self.price_list_box.findData(data["price_list_id"])
            if index >= 0:
                self.price_list_box.setCurrentIndex(index)
            self.price_list_box.blockSignals(False)
            self.price_list_id = self.price_list_box.currentData()
        self.discount_spin.setValue(int(data["discount"] or 0))
        self._split_payments = []
        self._render_cart()
        info(self, f"Panier « {data['label']} » repris.\n"
                   "Vérifiez les quantités puis validez la vente (F9).",
             "Vente reprise")

    # --- historique, retours et annulations ----------------------------------
    def open_history(self) -> None:
        dialog = SaleHistoryDialog(self.services, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        sale = dialog.chosen_sale
        if sale is None:
            return
        if dialog.chosen_action == "return":
            self._open_return(sale)
        elif dialog.chosen_action == "cancel":
            self._open_cancel(sale)

    def _open_return(self, sale) -> None:
        dialog = ReturnDialog(self.services, sale, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        number = getattr(dialog, "return_number", "")
        info(self, f"Retour {number} enregistré sur la vente {sale.number}.",
             "Retour de marchandise")
        self.refresh()

    def _open_cancel(self, sale) -> None:
        dialog = CancelSaleDialog(sale, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.services["sales"].cancel_sale(sale.id, dialog.motif())
        except (SalesError, PermissionError) as exc:
            QMessageBox.warning(self, "Annulation refusée", str(exc))
            return
        info(self, f"Vente {sale.number} annulée.", "Annulation")
        self.refresh()

    def print_last_receipt(self) -> None:
        """Ticket 80 mm du dernier ticket (fichier imprimable, §9)."""
        sale = getattr(self, "_last_sale", None)
        if sale is None:
            QMessageBox.information(self, "Ticket", "Aucune vente à imprimer.")
            return
        try:
            from ...printing import write_receipt
            path = write_receipt(sale, self._company(),
                                 getattr(self, "_last_sale_lines", []),
                                 open_after=True)
        except Exception as exc:
            QMessageBox.warning(self, "Impression", str(exc))
            return
        info(self, f"Ticket généré :\n{path}", "Ticket de caisse")

    def _company(self) -> dict:
        settings = self.services["admin"].company_settings()
        return {"name": settings.name, "address": settings.address,
                "phone": settings.phone, "document_footer": settings.document_footer}

    def reset(self) -> None:
        self.lines = []
        self._prepared = []
        self.cart.setRowCount(0)
        self.discount_spin.setValue(0)
        self._split_payments = []
        self._held_id = None
        self.paid_spin.setValue(0)
        self.note_edit.clear()
        self.deposit_qty.setValue(0)
        self.deposit_box.setCurrentIndex(0)
        self.search.clear()
        self.reload_reference_data()
        self.search.setFocus()

    def refresh(self) -> None:
        self._fill_customers()
        self._fill_deposits()
        self._fill_products()
        self._render_cart()
        recent = self.services["sales"].recent_sales(limit=12)
        self.recent.load([[sale.number, money(sale.total_amount),
                           label_status(sale.status)] for sale in recent],
                         numeric_columns={1})
