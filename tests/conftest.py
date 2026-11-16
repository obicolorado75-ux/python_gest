"""Fixtures partagées : base isolée par test + utilisateur administrateur connecté."""
import pytest
from sqlalchemy import select

from gestdepot.database.models import Role, User
from gestdepot.database.session import reset_for_tests, session_scope
from gestdepot.security import auth, hash_password


@pytest.fixture()
def db(tmp_path):
    """Base SQLite neuve par test : aucune fuite d'état entre les scénarios."""
    engine = reset_for_tests(f"sqlite:///{tmp_path}/test.db")
    with session_scope() as session:
        role = session.scalar(select(Role).where(Role.name == "Administrateur"))
        session.add(User(username="admin", password_hash=hash_password("secret"),
                         role_id=role.id, full_name="Admin Test"))
    auth.Session.logout()
    yield engine
    auth.Session.logout()


@pytest.fixture()
def admin(db):
    return auth.login("admin", "secret").user


@pytest.fixture()
def catalog():
    from gestdepot.services.catalog_service import CatalogService
    return CatalogService()


@pytest.fixture()
def stock():
    from gestdepot.services.stock_service import StockService
    return StockService()


@pytest.fixture()
def sales():
    from gestdepot.services.sales_service import SalesService
    return SalesService()


@pytest.fixture()
def cash():
    from gestdepot.services.cash_service import CashService
    return CashService()


@pytest.fixture()
def deposit():
    from gestdepot.services.deposit_service import DepositService
    return DepositService()


@pytest.fixture()
def inventory():
    from gestdepot.services.inventory_service import InventoryService
    return InventoryService()


@pytest.fixture()
def reporting():
    from gestdepot.services.reporting_service import ReportingService
    return ReportingService()


@pytest.fixture()
def supplier(stock):
    return stock.create_supplier("FOU-1", "Brasserie Ivoire")


@pytest.fixture()
def product_with_casier(admin, catalog):
    """T01 : 1 casier = 24 bouteilles, avec prix détail (bouteille et casier)."""
    product = catalog.create_product(reference="SOD-33CL", name="Soda 33cl",
                                    base_unit_id=catalog.list_units()[0].id,
                                    initial_cost=100)
    packaging = catalog.add_packaging(product.id, "Casier", factor=24,
                                      is_default=True)
    price_list = catalog.list_price_lists()[0]
    catalog.set_price(product.id, price_list.id, unit_price=150)
    catalog.set_price(product.id, price_list.id, unit_price=3600,
                      packaging_id=packaging.id)
    return product, packaging


@pytest.fixture()
def stocked_product(stock, product_with_casier):
    """Produit avec 240 bouteilles en stock (coût 100)."""
    product, packaging = product_with_casier
    stock.initial_stock(product.id, 240, unit_cost=100)
    return product, packaging


@pytest.fixture()
def order_with_lines(stock, supplier, product_with_casier):
    """Commande d'achat de 240 bouteilles + identifiant de ligne."""
    product, _ = product_with_casier
    order = stock.create_purchase_order(supplier.id, [{
        "product_id": product.id, "packaging_id": None,
        "designation": product.name, "quantity": 240,
        "quantity_display": 10, "unit_cost": 100}])
    from gestdepot.database.models import PurchaseOrderLine
    with session_scope() as session:
        line_id = session.scalar(select(PurchaseOrderLine.id).where(
            PurchaseOrderLine.order_id == order.id))
    return order, line_id
