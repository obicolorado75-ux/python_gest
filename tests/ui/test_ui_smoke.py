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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit  # noqa: E402


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


class TestCaisseEcran:
    """§5.12 : écran caisse — mouvements, dépenses, corrections, catégories."""

    def test_mouvement_retrait_et_apport(self, window, cash):
        from gestdepot.ui.pages.cash_page import MovementDialog
        cash_session = cash.open_session(opening_fund=10_000)
        dialog = MovementDialog(window.services)
        dialog.kind.setCurrentIndex(0)          # retrait
        dialog.amount.setValue(2_000)
        dialog._save()
        assert cash.theoretical_amount(cash_session.id) == 8_000
        dialog = MovementDialog(window.services)
        dialog.kind.setCurrentIndex(1)          # apport
        dialog.amount.setValue(1_000)
        dialog._save()
        assert cash.theoretical_amount(cash_session.id) == 9_000

    def test_ecran_caisse_affiche_sessions_et_depenses(self, window, cash):
        cash_session = cash.open_session(opening_fund=5_000)
        cash.add_expense(1_000, cash.list_expense_categories()[0].id)
        cash.close_session(cash_session.id, 4_000, "RAS")
        window._select("cash")
        page = window.pages["cash"]
        page.refresh()
        assert page.sessions.rowCount() == 1
        assert page.expenses.rowCount() == 1
        assert page.state_label.text().startswith("Aucune session")

    def test_annulation_depense_depuis_ecran(self, window, cash, monkeypatch):
        from PySide6.QtWidgets import QInputDialog
        cash.open_session(opening_fund=5_000)
        cash.add_expense(1_000, cash.list_expense_categories()[0].id)
        window._select("cash")
        page = window.pages["cash"]
        page.refresh()
        page.tabs.setCurrentIndex(1)
        page.expenses.selectRow(0)
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Erreur", True)))
        page.cancel_expense()
        assert "[Annulée]" not in page.expenses.value(0, 7)
        assert page.expenses.value(0, 7) == "Annulée"

    def test_categorie_dialog_ajout(self, window, cash):
        from gestdepot.ui.pages.cash_page import CategoryDialog
        dialog = CategoryDialog(window.services)
        before = dialog.table.rowCount()
        dialog.name.setText("Carburant")
        dialog._add()
        assert dialog.table.rowCount() == before + 1
        assert "Carburant" in [c.name for c in cash.list_expense_categories()]

    def test_dialogue_correction(self, window, cash):
        from gestdepot.ui.pages.cash_page import CorrectionDialog
        cash_session = cash.open_session(opening_fund=2_000)
        closed = cash.close_session(cash_session.id, 1_500)
        dialog = CorrectionDialog(window.services, closed)
        dialog.direction.setCurrentIndex(0)
        dialog.amount.setValue(500)
        dialog.reason.setText("Billet retrouvé")
        dialog._save()
        assert cash.get_session(closed.id).difference == 0


class TestInventaireEcran:
    """§5.13 : écran inventaires — périmètre, comptage, contrôle, validation."""

    def test_dialogue_demarrage_global_et_cible(self, window, stocked_product):
        from gestdepot.ui.pages.inventory_page import StartInventoryDialog
        dialog = StartInventoryDialog(window.services)
        assert dialog.payload()["product_ids"] is None      # global par défaut
        dialog.scope.setCurrentIndex(1)                     # ciblé
        from PySide6.QtCore import Qt
        dialog.products.item(0).setCheckState(Qt.Checked)
        payload = dialog.payload()
        assert payload["product_ids"] == [dialog.products.item(0).data(Qt.UserRole)]
        assert payload["threshold_value"] == 5_000

    def test_ecran_inventaire_comptage_et_validation(self, window, stock,
                                                     inventory, product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 30, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        window._select("inventory")
        page = window.pages["inventory"]
        page.refresh()
        assert page.sessions.rowCount() == 1
        assert page.table.rowCount() == 1
        assert page.table.value(0, 1) == 30
        page._current = session
        page._load_lines(session)
        page.table.selectRow(0)
        inventory.set_counted(session.id, product.id, 29)
        page.refresh()
        page._current = session
        page._load_lines(session)
        assert page.table.value(0, 3) == -1

    def test_dialogue_comptage_controle_obligatoire(self, window, stock,
                                                   inventory, product_with_casier):
        from gestdepot.ui.pages.inventory_page import CountDialog
        product, _ = product_with_casier
        stock.initial_stock(product.id, 100, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        line = inventory.lines(session.id)[0]
        dialog = CountDialog(window.services, inventory.get_session(session.id),
                             line, "Soda")
        dialog.counted.setValue(50)     # écart 5 000 > seuil
        assert "contrôle obligatoire" in dialog.gap.text()
        dialog.comment.setText("Casse importante")

    def test_validation_bloquee_par_le_seuil_dans_l_ecran(self, window, stock,
                                                          inventory,
                                                          product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 100, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        inventory.set_counted(session.id, product.id, 10)
        window._select("inventory")
        page = window.pages["inventory"]
        page.refresh()
        page._current = inventory.get_session(session.id)
        page._load_lines(page._current)
        page.validate()                 # bloqué : message, pas de validation
        assert inventory.get_session(session.id).status != "validated"
        assert page.table.value(0, 6) == "À contrôler"


class TestParametresSauvegarde:
    """§5.16 / §8 : politique de sauvegarde pilotable depuis les paramètres."""

    def test_onglet_sauvegarde_affiche_la_politique(self, window,
                                                    backup_dir_setting):
        window._select("settings")
        page = window.pages["settings"]
        page.refresh()
        assert page.keep_daily.value() == 7
        assert page.keep_weekly.value() == 4
        assert page.auto_close.isChecked() is True
        assert page.backups_table.columnCount() == 5
        assert "Dernière sauvegarde" in page.last_backup_label.text()

    def test_enregistrer_la_politique(self, window, backup_dir_setting):
        window._select("settings")
        page = window.pages["settings"]
        page.refresh()
        page.keep_daily.setValue(15)
        page.keep_weekly.setValue(6)
        page.auto_close.setChecked(False)
        page.save_backup_policy()
        settings = window.services["backup"].settings()
        assert settings["backup.keep_daily"] == "15"
        assert settings["backup.keep_weekly"] == "6"
        assert settings["backup.auto_close"] == "0"

    def test_sauvegarde_manuelle_listee(self, window, backup_dir_setting):
        window._select("settings")
        page = window.pages["settings"]
        page.backup_now()
        page.refresh()
        assert page.backups_table.rowCount() == 1
        assert page.backups_table.value(0, 4) == "OK"


@pytest.fixture()
def backup_dir_setting(window, tmp_path):
    """Redirige les sauvegardes vers un dossier de test."""
    directory = tmp_path / "backups"
    directory.mkdir()
    window.services["backup"].save_settings(directory=str(directory),
                                            keep_daily=7, keep_weekly=4,
                                            auto_close=True)
    return directory


class TestMoyensDePaiementEcran:
    """§5.12 : moyens de paiement configurables depuis les paramètres."""

    def test_onglet_liste_les_moyens(self, window):
        window._select("settings")
        page = window.pages["settings"]
        page.refresh()
        codes = [page.payment_list.item(i).data(Qt.UserRole)
                 for i in range(page.payment_list.count())]
        assert "especes" in codes and "wave" in codes
        # Espèces ne peut pas être décoché
        first = page.payment_list.item(0)
        assert "Espèces" in first.text()

    def test_ajout_d_un_moyen(self, window):
        from gestdepot.services import payment_methods
        window._select("settings")
        page = window.pages["settings"]
        page.new_method_label.setText("Airtel Money")
        page.add_payment_method()
        assert "airtel_money" in payment_methods.codes()
        assert page.new_method_label.text() == ""

    def test_decocher_et_enregistrer(self, window):
        from gestdepot.services import payment_methods
        window._select("settings")
        page = window.pages["settings"]
        page.refresh()
        for index in range(page.payment_list.count()):
            item = page.payment_list.item(index)
            if item.data(Qt.UserRole) == "wave":
                item.setCheckState(Qt.Unchecked)
        page.save_payment_methods()
        assert "wave" not in payment_methods.codes()

    def test_vente_propose_les_moyens_actifs(self, window):
        from gestdepot.services import payment_methods
        payment_methods.save([code for code in payment_methods.codes()
                              if code != "cheque"])
        page = window.pages["sales"] if "sales" in window.pages else None
        window._select("sales")
        page = window.pages["sales"]
        codes = [page.method_box.itemData(i)
                 for i in range(page.method_box.count())]
        assert "cheque" not in codes and "especes" in codes


class TestEcranDeConnexion:
    """§5.3 : logo, nom du dépôt, message neutre, mode hors ligne."""

    def test_ecran_affiche_l_identite_et_le_mode_hors_ligne(self, qapp, tmp_path):
        from sqlalchemy import select

        from gestdepot.database.models import Role, User
        from gestdepot.database.session import reset_for_tests, session_scope
        from gestdepot.security import auth, hash_password
        from gestdepot.ui.dialogs.login_dialog import LoginDialog

        reset_for_tests(f"sqlite:///{tmp_path}/login.db")
        with session_scope() as session:
            role = session.scalar(select(Role).where(Role.name == "Administrateur"))
            session.add(User(username="admin", role_id=role.id,
                             password_hash=hash_password("secret"),
                             full_name="Awa Koné"))
        from gestdepot.services.admin_service import AdminService
        auth.login("admin", "secret")
        AdminService().update_company_settings(name="Dépôt Les Palmiers")
        auth.Session.logout()

        dialog = LoginDialog()
        texts = [child.text() for child in dialog.findChildren(QLabel)
                 if hasattr(child, "text")]
        assert any("Dépôt Les Palmiers" in text for text in texts)
        assert any("hors ligne" in text.lower() for text in texts)
        assert dialog.pass_edit.echoMode() == QLineEdit.Password

        # message neutre affiché dans le dialogue, pas de fuite d'information
        dialog.user_edit.setText("admin")
        dialog.pass_edit.setText("mauvais")
        dialog._login()
        assert "incorrect" in dialog.error.text()
        assert dialog.result() != QDialog.Accepted

    def test_connexion_reussie_ferme_le_dialogue(self, qapp, tmp_path):
        from sqlalchemy import select

        from gestdepot.database.models import Role, User
        from gestdepot.database.session import reset_for_tests, session_scope
        from gestdepot.security import auth, hash_password
        from gestdepot.ui.dialogs.login_dialog import LoginDialog

        auth._failed.clear()
        reset_for_tests(f"sqlite:///{tmp_path}/login2.db")
        with session_scope() as session:
            role = session.scalar(select(Role).where(Role.name == "Administrateur"))
            session.add(User(username="admin", role_id=role.id,
                             password_hash=hash_password("secret")))
        dialog = LoginDialog()
        dialog.user_edit.setText("admin")
        dialog.pass_edit.setText("secret")
        dialog._login()
        assert dialog.result() == QDialog.Accepted
        assert dialog.username == "admin"
