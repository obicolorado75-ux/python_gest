"""Tests d'interface (offscreen) : démarrage, navigation, écrans clés (§10).

Qt exige des bibliothèques système (libGL, libxkbcommon…). Si elles sont absentes,
les tests sont ignorés plutôt que signalés en échec.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")

try:  # les bibliothèques graphiques système peuvent manquer (CI, conteneur)
    import PySide6.QtWidgets  # noqa: F401
except Exception as exc:  # pragma: no cover - dépend de l'environnement
    pytest.skip(f"PySide6 ne peut pas être chargé : {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        pytest.skip(f"Qt ne peut pas démarrer ici : {exc}")
    return app


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """Aucune boîte de dialogue modale ne doit bloquer les tests."""
    from PySide6.QtWidgets import QMessageBox
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))


@pytest.fixture()
def window(qapp, admin):

    from gestdepot.ui.main_window import MainWindow
    window = MainWindow(mode="test")
    window._run_daily_backup = lambda: None  # pas de sauvegarde en test
    yield window
    window.blockSignals(True)
    window._run_daily_backup = lambda: None
    window.close()


class TestFenetrePrincipale:
    def test_navigation_complete(self, window):
        """Chaque entrée du menu latéral doit s'ouvrir sans erreur (§5.2)."""
        from gestdepot.ui.main_window import NAVIGATION
        for _label, key, _tooltip in NAVIGATION:
            window._select(key)
            assert window.stack.currentWidget() is window.pages[key]
            assert window.nav_buttons[key].isChecked()

    def test_ecrans_vides_geres(self, window):
        """Les états vides ne doivent pas lever d'exception."""
        for key in ("dashboard", "sales", "products", "stock", "deposits",
                    "customers", "purchases", "cash", "inventory", "reports",
                    "settings"):
            window._select(key)
            window.pages[key].refresh()

    def test_dashboard_affiche_indicateurs(self, window, stocked_product):
        """Les 6 cartes existent et sont mises à jour sans se dupliquer (§5.4)."""
        window._select("dashboard")
        page = window.pages["dashboard"]
        assert page.cards_grid.count() == 6
        page.refresh()
        page.refresh()
        assert page.cards_grid.count() == 6          # aucune carte recréée
        assert page.cards["net_sales"].value_label.text().endswith("FCFA")

    def test_dashboard_avec_ventes_et_depenses(self, window, sales, cash,
                                               stocked_product, catalog):
        product, _ = stocked_product
        cash_session = cash.open_session(opening_fund=20_000)
        cash.add_expense(5_000, cash.list_expense_categories()[0].id)
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 20}],
            payment_method="especes", paid_amount=3_000,
            price_list_id=catalog.list_price_lists()[0].id)
        window._select("dashboard")
        page = window.pages["dashboard"]
        page.refresh()
        assert "15 000" in page.cards["gross_margin"].hint_label.text() or \
               "3 000" in page.cards["net_sales"].value_label.text()
        assert cash.theoretical_amount(cash_session.id) == 18_000

    def test_pos_ajout_au_panier(self, window, stocked_product):
        from gestdepot.ui.pages.sales_page import SalesPage
        window._select("sales")
        page: SalesPage = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.qty_spin.setValue(2)
        page.add_selected_product()
        assert len(page.lines) == 1
        assert page.lines[0]["quantity_display"] == 2
        page.reset()
        assert page.lines == []

    def test_pos_refuse_quantite_superieure_au_stock(self, window, stocked_product):
        window._select("sales")
        page = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.packaging_box.setCurrentIndex(0)  # unité de base
        page.qty_spin.setValue(9999)
        page.add_selected_product()
        assert page.lines == []  # ajout refusé, message affiché


class TestCaisseEtendue:
    """§5.5 : paiement mixte, suspension (F8), quantités, retours."""

    def test_paiement_mixte_alimente_les_encaissements(self, window,
                                                       stocked_product):
        window._select("sales")
        page = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.packaging_box.setCurrentIndex(0)
        page.qty_spin.setValue(10)          # 10 × 150 = 1 500
        page.add_selected_product()
        page._split_payments = [{"method": "especes", "amount": 1_000},
                                {"method": "wave", "amount": 400}]
        page.paid_spin.setValue(1_400)
        payments = page._effective_payments()
        assert sum(entry["amount"] for entry in payments) == 1_400
        assert {entry["method"] for entry in payments} == {"especes", "wave"}

    def test_paiement_mixte_plafonne_au_total(self, window, stocked_product):
        window._select("sales")
        page = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.packaging_box.setCurrentIndex(0)
        page.qty_spin.setValue(2)           # 300
        page.add_selected_product()
        page._split_payments = [{"method": "especes", "amount": 500},
                                {"method": "wave", "amount": 500}]
        payments = page._effective_payments()
        assert sum(entry["amount"] for entry in payments) == 300

    def test_dialogue_paiement_mixte_repartition(self, qapp):
        from gestdepot.ui.dialogs.sale_dialogs import SplitPaymentDialog
        dialog = SplitPaymentDialog(10_000)
        dialog._split_two()
        assert sum(entry["amount"] for entry in dialog.payments()) == 10_000
        assert len({entry["method"] for entry in dialog.payments()}) == 2
        dialog._all_cash()
        assert dialog.payments() == [{"method": "especes", "amount": 10_000}]

    def test_suspendre_puis_reprendre(self, window, sales, stocked_product):
        window._select("sales")
        page = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.packaging_box.setCurrentIndex(0)
        page.qty_spin.setValue(3)
        page.add_selected_product()
        state = page._sale_state()
        held = sales.hold_sale(
            items=state["items"], price_list_id=state["price_list_id"],
            label="Table 3")
        page.reset()
        assert page.lines == []
        page.resume_held(held.id)
        assert len(page.lines) == 1
        assert len(sales.held_sales()) == 1

    def test_modifier_quantite_ligne(self, window, stocked_product, monkeypatch):
        from PySide6.QtWidgets import QInputDialog
        window._select("sales")
        page = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.packaging_box.setCurrentIndex(0)
        page.qty_spin.setValue(2)
        page.add_selected_product()
        page.cart.selectRow(0)
        monkeypatch.setattr(QInputDialog, "getInt",
                            staticmethod(lambda *a, **k: (5, True)))
        page.edit_line_quantity()
        assert page.lines[0]["quantity_display"] == 5

    def test_modifier_quantite_zero_retire_la_ligne(self, window, stocked_product,
                                                    monkeypatch):
        from PySide6.QtWidgets import QInputDialog
        window._select("sales")
        page = window.pages["sales"]
        page.product_list.setCurrentRow(0)
        page.packaging_box.setCurrentIndex(0)
        page.qty_spin.setValue(2)
        page.add_selected_product()
        page.cart.selectRow(0)
        monkeypatch.setattr(QInputDialog, "getInt",
                            staticmethod(lambda *a, **k: (0, True)))
        page.edit_line_quantity()
        assert page.lines == []

    def test_retour_depuis_la_caisse(self, window, stocked_product,
                                     catalog, monkeypatch):
        from gestdepot.ui.dialogs.sale_dialogs import ReturnDialog
        services = window.services
        sales = services["sales"]
        product, _ = stocked_product
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 4}],
            payment_method="especes", paid_amount=600,
            price_list_id=catalog.list_price_lists()[0].id)
        dialog = ReturnDialog(services, sales.get_sale(sale.id))
        monkeypatch.setattr(dialog, "exec", lambda: dialog.DialogCode.Accepted)
        dialog.spins[0].setValue(2)
        dialog.reason.setText("Bouteilles cassées")
        dialog._save()
        assert dialog.return_number.startswith("RET-")
        assert sales.returnable_lines(sale.id)[0]["remaining"] == 2


class TestAchatsEtConsignes:
    """§5.11 / §5.8 : écrans achats (paiement, historique) et consignes."""

    def test_ecran_consignes_alimente(self, window, deposit, sales):
        customer = sales.create_customer(code="CLI-UI", name="Bar UI")
        packaging = deposit.create_packaging("CAS-UI", "Casier UI", 500)
        deposit.move(packaging.id, 4, "remis_client", customer_id=customer.id)
        window._select("deposits")
        page = window.pages["deposits"]
        page.refresh()
        assert page.types.rowCount() == 1
        assert page.accounts.rowCount() == 1
        assert page.accounts.value(0, 3) == 4
        assert page.movements.rowCount() == 1

    def test_ecran_consignes_vide(self, window):
        window._select("deposits")
        page = window.pages["deposits"]
        page.refresh()
        assert page.types.rowCount() == 0

    def test_dialogue_mouvement_consigne(self, window, deposit, sales, monkeypatch):
        from gestdepot.ui.pages.deposits_page import MovementDialog
        customer = sales.create_customer(code="CLI-UI2", name="Bar UI 2")
        packaging = deposit.create_packaging("CAS-UI2", "Casier UI 2", 300)
        dialog = MovementDialog(window.services)
        dialog.packaging.setCurrentIndex(dialog.packaging.findData(packaging.id))
        dialog.reason.setCurrentIndex(dialog.reason.findData("remis_client"))
        dialog.party.setCurrentIndex(dialog.party.findData(customer.id))
        dialog.quantity.setValue(6)
        dialog._save()
        assert deposit.customer_balance(customer.id)[packaging.id] == 6

    def test_ecran_achats_paiement_fournisseur(self, window, stock, cash,
                                               supplier, product_with_casier):
        product, _ = product_with_casier
        order = stock.create_purchase_order(
            supplier.id, [{"product_id": product.id, "designation": product.name,
                           "quantity": 10, "unit_cost": 100}])
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 10}])
        window._select("purchases")
        page = window.pages["purchases"]
        page.refresh()
        assert page.suppliers.rowCount() == 1
        payment = stock.pay_supplier(supplier.id, 300)
        assert payment.amount == 300
        assert stock.get_supplier(supplier.id).balance == 700
        page.refresh()
        assert page.suppliers.rowCount() == 1

    def test_historique_achats_affiche_commandes(self, window, stock, supplier,
                                                product_with_casier):
        from gestdepot.ui.pages.purchases_page import PurchaseOrderHistoryDialog
        product, _ = product_with_casier
        stock.create_purchase_order(
            supplier.id, [{"product_id": product.id, "designation": product.name,
                           "quantity": 3, "unit_cost": 100}])
        dialog = PurchaseOrderHistoryDialog(window.services)
        assert dialog.orders.rowCount() == 1
        assert dialog.invoices.rowCount() == 0
