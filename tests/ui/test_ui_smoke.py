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
        for key in ("dashboard", "sales", "products", "stock", "customers",
                    "purchases", "cash", "inventory", "reports", "settings"):
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
