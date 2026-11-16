"""Catalogue produits : liste, création, conditionnements, tarifs (§5.6)."""
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
    QTextEdit,
    QVBoxLayout,
)

from ..widgets import DataTable, Page, confirm, money, refresh_after


class ProductDialog(QDialog):
    def __init__(self, services, product=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.product = product
        self.setWindowTitle("Modifier le produit" if product else "Nouveau produit")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.reference = QLineEdit(product.reference if product else "")
        self.name = QLineEdit(product.name if product else "")
        self.barcode = QLineEdit(product.barcode or "" if product else "")
        self.description = QTextEdit(product.description or "" if product else "")
        self.description.setMaximumHeight(60)
        self.category = QComboBox()
        self.brand = QComboBox()
        self.unit = QComboBox()
        self.supplier = QComboBox()
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 1_000_000)
        self.safety = QSpinBox()
        self.safety.setRange(0, 1_000_000)
        self.cost = QSpinBox()
        self.cost.setRange(0, 100_000_000)
        self.cost.setSingleStep(25)

        catalog = services["catalog"]
        self.category.addItem("—", None)
        for item in catalog.list_categories():
            self.category.addItem(item.name, item.id)
        self.brand.addItem("—", None)
        for item in catalog.list_brands():
            self.brand.addItem(item.name, item.id)
        for item in catalog.list_units():
            self.unit.addItem(item.name, item.id)
        self.supplier.addItem("—", None)
        for item in services["stock"].list_suppliers():
            self.supplier.addItem(item.name, item.id)

        if product:
            for box, value in ((self.category, product.category_id),
                               (self.brand, product.brand_id),
                               (self.unit, product.base_unit_id),
                               (self.supplier, product.primary_supplier_id)):
                index = box.findData(value)
                if index >= 0:
                    box.setCurrentIndex(index)
            self.threshold.setValue(product.min_threshold)
            self.safety.setValue(product.safety_stock)
            self.cost.setValue(product.current_cost)

        form.addRow("Référence *", self.reference)
        form.addRow("Désignation *", self.name)
        form.addRow("Catégorie", self.category)
        form.addRow("Marque", self.brand)
        form.addRow("Unité de base", self.unit)
        form.addRow("Code-barres", self.barcode)
        form.addRow("Fournisseur principal", self.supplier)
        form.addRow("Seuil minimum", self.threshold)
        form.addRow("Stock de sécurité", self.safety)
        form.addRow("Prix d'achat courant", self.cost)
        form.addRow("Description", self.description)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        payload = {
            "reference": self.reference.text().strip(),
            "name": self.name.text().strip(),
            "base_unit_id": self.unit.currentData(),
            "category_id": self.category.currentData(),
            "brand_id": self.brand.currentData(),
            "barcode": self.barcode.text().strip() or None,
            "description": self.description.toPlainText().strip() or None,
            "primary_supplier_id": self.supplier.currentData(),
            "min_threshold": self.threshold.value(),
            "safety_stock": self.safety.value(),
        }
        try:
            if self.product is None:
                payload.pop("description")
                self.services["catalog"].create_product(
                    initial_cost=self.cost.value(), description=self.description
                    .toPlainText().strip() or None, **payload)
            else:
                catalog = self.services["catalog"]
                catalog.update_product(self.product.id, **{
                    key: value for key, value in payload.items()
                    if key not in ("reference", "base_unit_id")})
                if self.cost.value() != self.product.current_cost:
                    catalog.set_cost(self.product.id, self.cost.value())
        except Exception as exc:
            QMessageBox.warning(self, "Enregistrement impossible", str(exc))
            return
        self.accept()


class PackagingDialog(QDialog):
    """Conditionnements : 1 casier = N unités de base (§7.4)."""

    def __init__(self, services, product, parent=None):
        super().__init__(parent)
        self.services = services
        self.product = product
        self.setWindowTitle(f"Conditionnements — {product.name}")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        self.table = DataTable(["Conditionnement", "Facteur", "Par défaut"])
        layout.addWidget(self.table)

        form = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("ex. Casier")
        self.factor = QSpinBox()
        self.factor.setRange(2, 10000)
        self.factor.setValue(24)
        self.is_default = QCheckBox("Par défaut")
        form.addWidget(self.name, 1)
        form.addWidget(QLabel("×"))
        form.addWidget(self.factor)
        form.addWidget(self.is_default)
        add = QPushButton("Ajouter")
        add.clicked.connect(self._add)
        form.addWidget(add)
        layout.addLayout(form)
        layout.addWidget(QLabel("Note : 1 casier = 24 bouteilles retire 24 unités de "
                                "base du stock par casier vendu."))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Fermer")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._reload()

    def _reload(self):
        packagings = self.services["catalog"].list_packagings(self.product.id)
        self.table.load([[p.name, p.factor, "oui" if p.is_default else ""]
                         for p in packagings], numeric_columns={1})

    def _add(self):
        try:
            self.services["catalog"].add_packaging(
                self.product.id, self.name.text().strip(), self.factor.value(),
                self.is_default.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "Conditionnement", str(exc))
            return
        self.name.clear()
        self._reload()


class PricesDialog(QDialog):
    """Tarifs par liste et par conditionnement (§7.5)."""

    def __init__(self, services, product, parent=None):
        super().__init__(parent)
        self.services = services
        self.product = product
        self.setWindowTitle(f"Tarifs — {product.name}")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.table = DataTable(["Tarif", "Conditionnement", "Prix"])
        layout.addWidget(self.table)

        form = QHBoxLayout()
        self.price_list = QComboBox()
        for price_list in services["catalog"].list_price_lists():
            self.price_list.addItem(price_list.name, price_list.id)
        self.packaging = QComboBox()
        self.packaging.addItem("Unité de base", None)
        for packaging in services["catalog"].list_packagings(product.id):
            self.packaging.addItem(f"{packaging.name} (×{packaging.factor})",
                                   packaging.id)
        self.price = QSpinBox()
        self.price.setRange(0, 100_000_000)
        self.price.setSingleStep(25)
        save = QPushButton("Enregistrer le prix")
        save.clicked.connect(self._save)
        form.addWidget(self.price_list)
        form.addWidget(self.packaging, 1)
        form.addWidget(self.price, 1)
        form.addWidget(save)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Fermer")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._reload()

    def _reload(self):
        rows = []
        catalog = self.services["catalog"]
        packagings = {None: "Unité de base"}
        packagings.update({p.id: p.name
                           for p in catalog.list_packagings(self.product.id)})
        for price_list in catalog.list_price_lists():
            for packaging_id, label in packagings.items():
                price = catalog.get_price(self.product.id, price_list.id,
                                          packaging_id)
                if price:
                    rows.append([price_list.name, label, money(price)])
        self.table.load(rows)

    def _save(self):
        try:
            self.services["catalog"].set_price(
                self.product.id, self.price_list.currentData(),
                self.price.value(), packaging_id=self.packaging.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "Tarif", str(exc))
            return
        self._reload()


class ProductsPage(Page):
    title = "Produits et catalogue"
    subtitle = "Catalogue configurable : conditionnements et tarifs sans modifier le code."

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un produit…")
        self.search.textChanged.connect(self.refresh)
        self.show_archived = QCheckBox("Afficher les archivés")
        self.show_archived.toggled.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_archived)
        self.body.addLayout(bar)

        self.add_action("Nouveau produit", self.new_product, primary=True)
        self.add_action("Modifier", self.edit_product)
        self.add_action("Conditionnements", self.manage_packagings)
        self.add_action("Tarifs", self.manage_prices)
        self.add_action("Archiver", self.archive_product)
        self.add_stretch()

        self.table = DataTable(["Référence", "Désignation", "Catégorie",
                                "Conditionnement", "Stock", "Coût", "Prix détail",
                                "Seuil", "Statut"])
        self.table.doubleClicked.connect(lambda _: self.edit_product())
        self.body.addWidget(self.table, 1)

    def _selected(self):
        row = self.table.selected_row()
        if row is None:
            return None
        return self._products[row]

    def refresh(self) -> None:
        catalog = self.services["catalog"]
        self._products = catalog.list_products(
            self.search.text().strip() or None,
            include_archived=self.show_archived.isChecked())
        detail_list = catalog.price_list_id_for("Détail")
        rows = []
        for product in self._products:
            packagings = catalog.list_packagings(product.id, include_archived=True)
            packaging = packagings[0] if packagings else None
            stock = self.services["stock"].available(product.id)
            rows.append([
                product.reference, product.name,
                product.category.name if product.category else "—",
                f"{packaging.name} ×{packaging.factor}" if packaging else "Unité",
                stock, money(product.current_cost),
                money(catalog.get_price(product.id, detail_list, None)),
                product.min_threshold,
                "Archivé" if product.archived else "Actif",
            ])
        self.table.load(rows, numeric_columns={4, 5, 6, 7},
                        colors={8: {"Archivé": "#B3261E", "Actif": "#1B7F3B"}})

    @refresh_after
    def new_product(self):
        if ProductDialog(self.services, None, self).exec():
            return True

    @refresh_after
    def edit_product(self):
        product = self._selected()
        if product is None:
            QMessageBox.information(self, "Produit", "Sélectionnez un produit.")
            return
        if ProductDialog(self.services, product, self).exec():
            return True

    @refresh_after
    def manage_packagings(self):
        product = self._selected()
        if product is None:
            QMessageBox.information(self, "Produit", "Sélectionnez un produit.")
            return
        PackagingDialog(self.services, product, self).exec()
        return True

    @refresh_after
    def manage_prices(self):
        product = self._selected()
        if product is None:
            QMessageBox.information(self, "Produit", "Sélectionnez un produit.")
            return
        PricesDialog(self.services, product, self).exec()
        return True

    @refresh_after
    def archive_product(self):
        product = self._selected()
        if product is None:
            QMessageBox.information(self, "Produit", "Sélectionnez un produit.")
            return
        if not confirm(self, f"Archiver « {product.name} » ?\n\n"
                             "Le produit et son historique sont conservés."):
            return
        self.services["catalog"].archive_product(product.id)
        return True
