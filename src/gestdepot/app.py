"""Amorçage de l'application GestDepot (Phase 0)."""
from __future__ import annotations

import sys

from .config import app_paths
from .database.session import init_engine
from .security import auth


def bootstrap_database() -> None:
    """Crée/rouvre la base locale au démarrage (aucune connexion requise, §1.2)."""
    app_paths.ensure_dirs()
    init_engine()


def first_user_if_needed():
    """Indique si l'assistant de premier lancement doit créer l'administrateur."""
    from .services.admin_service import AdminService
    return not AdminService().has_any_user()


def seed_demo_data() -> None:
    """Données de démonstration clairement identifiées (§12) — base dédiée."""
    from sqlalchemy import select

    from .database.models import Product, Supplier
    from .database.session import session_scope
    from .services.catalog_service import CatalogService
    from .services.deposit_service import DepositService
    from .services.sales_service import SalesService
    from .services.stock_service import StockService

    catalog = CatalogService()
    stock = StockService()
    sales = SalesService()
    deposit = DepositService()

    # Idempotent : ne recrée pas un jeu de démonstration déjà présent.
    with session_scope() as session:
        already = session.scalar(select(Product.id).where(
            Product.reference == "DEMO-BIERE-33"))
    if already:
        raise RuntimeError("Les données de démonstration existent déjà.")

    unit = catalog.list_units()[0]
    detail = catalog.list_price_lists()[0]
    gros = catalog.list_price_lists()[1] if len(catalog.list_price_lists()) > 1 else detail

    with session_scope() as session:
        supplier_existing = session.scalar(select(Supplier.id).where(
            Supplier.code == "FOU-DEMO"))
    supplier = (stock.get_supplier(supplier_existing) if supplier_existing
                else stock.create_supplier("FOU-DEMO", "Brasserie Démo (exemple)"))
    products = [
        ("DEMO-BIERE-33", "Bière blonde 33cl (démo)", "Bière", 24, 400, 500, 450),
        ("DEMO-SODA-50", "Soda 50cl (démo)", "Sodas", 12, 250, 350, 300),
        ("DEMO-EAU-1L", "Eau minérale 1L (démo)", "Eaux", 6, 150, 250, 200),
    ]
    for reference, name, category, factor, cost, price_detail, price_gros in products:
        try:
            catalog.create_category(category)
        except Exception:
            pass  # catégorie déjà présente
        product = catalog.create_product(reference=reference, name=name,
                                         base_unit_id=unit.id, initial_cost=cost)
        packaging = catalog.add_packaging(product.id, "Casier", factor=factor,
                                          is_default=True)
        catalog.set_price(product.id, detail.id, unit_price=price_detail)
        catalog.set_price(product.id, gros.id, unit_price=price_gros)
        catalog.set_price(product.id, detail.id,
                          unit_price=price_detail * factor, packaging_id=packaging.id)
        # prix au casier par liste (détail plein tarif, gros remisé)
        catalog.set_price(product.id, gros.id,
                          unit_price=int(price_gros * factor * 0.97),
                          packaging_id=packaging.id)
        order = stock.create_purchase_order(
            supplier.id, [{"product_id": product.id, "packaging_id": packaging.id,
                           "designation": name, "quantity": factor * 20,
                           "quantity_display": 20, "unit_cost": cost}])
        from sqlalchemy import select

        from .database.models import PurchaseOrderLine
        from .database.session import session_scope
        with session_scope() as session:
            line_id = session.scalar(select(PurchaseOrderLine.id).where(
                PurchaseOrderLine.order_id == order.id))
        stock.receive(order.id, [{"order_line_id": line_id,
                                  "quantity": factor * 20, "unit_cost": cost}])

    customer = sales.create_customer("CLI-DEMO", "Bar Le Baobab (démo)",
                                     customer_type="gros", credit_limit=200_000)
    sales.create_customer("CLI-DEMO2", "Boutique Démo (démo)",
                          customer_type="detail", credit_limit=0)
    deposit.create_packaging("CAS-DEMO", "Casier consigné (démo)", 500)

    first = catalog.list_products("DEMO-BIERE")[0]
    packaging = catalog.list_packagings(first.id)[0]
    # Vente à crédit partiel (2 casiers + 3 bouteilles au tarif gros)
    items = [{"product_id": first.id, "packaging_id": packaging.id,
              "quantity_display": 2},
             {"product_id": first.id, "packaging_id": None, "quantity_display": 3}]
    total = sales.draft_lines(items, gros.id)["total"]
    sales.confirm_sale(items, payment_method="especes",
                       paid_amount=max(total - 2_000, 0),
                       customer_id=customer.id, price_list_id=gros.id)
    # Vente comptoir payée par Mobile Money
    items = [{"product_id": first.id, "packaging_id": None, "quantity_display": 12}]
    total = sales.draft_lines(items, detail.id)["total"]
    sales.confirm_sale(items, payment_method="orange_money", paid_amount=total,
                       price_list_id=detail.id)


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée : lance l'interface PySide6 (hors ligne)."""
    argv = sys.argv if argv is None else argv
    bootstrap_database()

    from PySide6.QtWidgets import QApplication

    from .ui.dialogs.login_dialog import FirstRunDialog, LoginDialog
    from .ui.main_window import MainWindow

    application = QApplication.instance() or QApplication(argv)
    application.setApplicationName("GestDepot")

    from .ui.styles.theme import apply_theme
    apply_theme(application)

    if first_user_if_needed():
        dialog = FirstRunDialog()
        if not dialog.exec():
            return 0
        auth.login(dialog.username, dialog.password)

    if auth.Session.current() is None:
        login = LoginDialog()
        if not login.exec():
            return 0

    window = MainWindow(mode="desktop")
    window.show()
    return application.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
