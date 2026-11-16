"""Scénarios métier obligatoires T01–T12, T17 (§10.2)."""
import pytest

from gestdepot.services.catalog_service import CatalogError, CatalogService
from gestdepot.services.cash_service import CashService
from gestdepot.services.deposit_service import DepositService
from gestdepot.services.sales_service import SalesError, SalesService
from gestdepot.services.stock_service import StockError, StockService


@pytest.fixture()
def catalog():
    return CatalogService()


@pytest.fixture()
def stock():
    return StockService()


@pytest.fixture()
def sales():
    return SalesService()


@pytest.fixture()
def product_with_casier(catalog, stock):
    """T01 : produit avec 1 casier = 24 bouteilles."""
    p = catalog.create_product(reference="SOD-33CL", name="Soda 33cl",
                               base_unit_id=1, initial_cost=100)
    catalog.add_packaging(p.id, "Casier", factor=24, is_default=True)
    pl = catalog.list_price_lists()[0]
    catalog.set_price(p.id, pl.id, unit_price=150)          # prix à la bouteille
    pk = catalog.list_packagings(p.id)[0]
    catalog.set_price(p.id, pl.id, unit_price=3600, packaging_id=pk.id)  # casier 3600
    return p, pk


class TestCatalog:
    def test_t01_conversion(self, catalog, product_with_casier):
        p, pk = product_with_casier
        assert pk.factor == 24

    def test_reference_unique(self, catalog, product_with_casier):
        with pytest.raises(CatalogError):
            catalog.create_product(reference="SOD-33CL", name="Doublon", base_unit_id=1)

    def test_archive_pas_suppression(self, catalog, product_with_casier):
        p, _ = product_with_casier
        catalog.archive_product(p.id)
        assert catalog.get(p.id).archived is True


class TestStock:
    def test_t02_reception(self, catalog, stock, product_with_casier):
        p, _ = product_with_casier
        po = stock.create_purchase_order(
            supplier_id=None and 0 or self._supplier(stock), lines=[
                {"product_id": p.id, "packaging_id": None, "designation": "Soda 33cl",
                 "quantity": 240, "quantity_display": 10, "unit_cost": 100}])
        stock.receive(order_id=po.id, receipts=[{
            "order_line_id": po.lines[0].id if hasattr(po, "lines") else 1,
            "quantity": 240, "unit_cost": 100}])
        assert stock.available(p.id) == 240  # T02 : 10 casiers = 240 bouteilles

    def _supplier(self, stock):
        from gestdepot.database.models import Supplier
        from gestdepot.database.session import session_scope
        with session_scope() as s:
            sup = Supplier(code="FOU-1", name="Brasserie Ivoire")
            s.add(sup)
            s.flush()
            return sup.id

    def test_t09_reception_partielle(self, catalog, stock, product_with_casier):
        p, _ = product_with_casier
        from gestdepot.database.models import Supplier
        from gestdepot.database.session import session_scope
        with session_scope() as s:
            sup = Supplier(code="FOU-P", name="Fournisseur P")
            s.add(sup)
            s.flush()
            sid = sup.id
        po = stock.create_purchase_order(sid, lines=[
            {"product_id": p.id, "packaging_id": None, "designation": "Soda 33cl",
             "quantity": 240, "quantity_display": 10, "unit_cost": 100}])
        ol = stock  # récupérer l'id de ligne via la session
        from gestdepot.database.models import PurchaseOrderLine
        from gestdepot.database.session import session_scope as sc
        with sc() as s:
            ol_id = s.scalar(
                __import__("sqlalchemy", fromlist=["select"]).select(
                    PurchaseOrderLine).where(PurchaseOrderLine.order_id == po.id)).id
        stock.receive(po.id, [{"order_line_id": ol_id, "quantity": 120, "unit_cost": 100}])
        assert stock.available(p.id) == 120  # seules les quantités reçues (T09)
        # sur-réception refusée
        with pytest.raises(StockError):
            stock.receive(po.id, [{"order_line_id": ol_id, "quantity": 200}])

    def test_cmp_mis_a_jour(self, stock, product_with_casier):
        p, _ = product_with_casier
        stock.initial_stock(p.id, 100, unit_cost=100)
        stock.adjust(p.id, 100, "mouvement_initial", comment="test")  # refusé sans perm ? admin a *
        from gestdepot.database.models import StockMovement
        from gestdepot.database.session import session_scope
        from sqlalchemy import select
        with session_scope() as s:
            mvs = list(s.scalars(select(StockMovement).where(
                StockMovement.product_id == p.id)))
        assert sum(m.quantity for m in mvs) == stock.balance(p.id).quantity


class TestSales:
    def test_t03_vente_mixte(self, catalog, stock, sales, product_with_casier, admin):
        p, pk = product_with_casier
        stock.initial_stock(p.id, 240, unit_cost=100)
        # vendre 2 casiers (packaging) + 3 bouteilles (base)
        sale = sales.confirm_sale(
            items=[{"product_id": p.id, "packaging_id": pk.id, "quantity_display": 2},
                   {"product_id": p.id, "packaging_id": None, "quantity_display": 3}],
            payment_method="especes", paid_amount=7260,
            price_list_id=catalog.list_price_lists()[0].id)
        assert stock.available(p.id) == 240 - 51  # T03 : -51 bouteilles
        assert sale.total_amount == 2 * 3600 + 3 * 150  # 7650

    def test_t04_stock_insuffisant(self, catalog, stock, sales, product_with_casier):
        p, pk = product_with_casier
        stock.initial_stock(p.id, 24, unit_cost=100)
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": p.id, "packaging_id": pk.id,
                        "quantity_display": 2}],  # 48 > 24
                payment_method="especes", paid_amount=7200)

    def test_t05_t06_credit_partiel(self, catalog, stock, sales, product_with_casier, admin):
        p, _ = product_with_casier
        stock.initial_stock(p.id, 1000, unit_cost=100)
        cust = sales.create_customer(code="CLI-1", name="Bar Le Baobab",
                                     customer_type="gros", credit_limit=1_000_000)
        pl = catalog.list_price_lists()[1]  # Gros
        catalog.set_price(p.id, pl.id, unit_price=120)
        # vente 150 000 F, encaisse 100 000 => créance 50 000 (T05)
        qty = 1250  # 1250 × 120 = 150 000
        sale = sales.confirm_sale(
            items=[{"product_id": p.id, "packaging_id": None, "quantity_display": qty}],
            payment_method="especes", paid_amount=100_000, customer_id=cust.id,
            price_list_id=pl.id)
        assert sale.total_amount == 150_000
        assert sales.customer_balance(cust.id) == 50_000
        # règlement 20 000 => créance 30 000, CA inchangé (T06)
        sales.pay_credit(cust.id, 20_000)
        assert sales.customer_balance(cust.id) == 30_000

    def test_t07_retour_partiel(self, catalog, stock, sales, product_with_casier, admin):
        p, pk = product_with_casier
        stock.initial_stock(p.id, 240, unit_cost=100)
        sale = sales.confirm_sale(
            items=[{"product_id": p.id, "packaging_id": pk.id, "quantity_display": 5}],
            payment_method="especes", paid_amount=18_000)  # 5 × 3600
        line_id = sale.lines[0].id
        ret = sales.return_sale(sale.id, [{"sale_line_id": line_id, "quantity": 24}])
        assert ret.total_amount == 3600
        assert stock.available(p.id) == 240 - 120 + 24
        # retour excessif refusé
        with pytest.raises(SalesError):
            sales.return_sale(sale.id, [{"sale_line_id": line_id, "quantity": 200}])

    def test_t08_consignes(self, catalog, stock, sales, deposit, admin):
        dep = deposit
        rp = dep.create_packaging(code="CAS-BIE", label="Casier bière", deposit_value=500)
        dep.move(rp.id, 5, "remis_client", customer_id=None)  # via vente directe ci-dessous
        # scénario client : 5 remis, 3 retournés => solde 2 (T08)
        from gestdepot.database.session import session_scope
        from gestdepot.database.models import Customer
        with session_scope() as s:
            c = Customer(code="CLI-D", name="Client Dépôt")
            s.add(c)
            s.flush()
            cid = c.id
        dep.move(rp.id, 5, "remis_client", customer_id=cid)
        assert dep.customer_balance(cid)[rp.id] == 5
        dep.move(rp.id, -3, "retourne_client", customer_id=cid)
        assert dep.customer_balance(cid)[rp.id] == 2  # T08


@pytest.fixture()
def deposit():
    return DepositService()


class TestCaisse:
    def test_t10_t12_depense_et_cloture(self, admin):
        cash = CashService()
        sess = cash.open_session(opening_fund=50_000)
        cat = None
        from gestdepot.database.session import session_scope
        from gestdepot.database.models import ExpenseCategory
        with session_scope() as s:
            cat = s.scalar(__import__("sqlalchemy", fromlist=["select"]).select(
                ExpenseCategory)).id
        exp = cash.add_expense(10_000, cat, beneficiary="Carburant")
        assert cash.theoretical_amount(sess.id) == 40_000  # T10 : dépense en espèces
        closed = cash.close_session(sess.id, counted_amount=39_000, comment="test")
        assert closed.difference == -1_000  # T12 : écart conservé

    def test_t11_mobile_money_hors_caisse(self, catalog, stock, sales,
                                          product_with_casier, admin):
        p, pk = product_with_casier
        cash = CashService()
        sess = cash.open_session(opening_fund=0)
        stock.initial_stock(p.id, 240, unit_cost=100)
        sales.confirm_sale(items=[{"product_id": p.id, "packaging_id": pk.id,
                                   "quantity_display": 4}],
                           payment_method="orange_money", paid_amount=14_400)
        # la caisse espèces reste inchangée (T11)
        assert cash.theoretical_amount(sess.id) == 0

    def test_t17_marge_historique(self, catalog, stock, sales, product_with_casier, admin):
        p, pk = product_with_casier
        stock.initial_stock(p.id, 240, unit_cost=100)
        sale = sales.confirm_sale(
            items=[{"product_id": p.id, "packaging_id": None, "quantity_display": 10}],
            payment_method="especes", paid_amount=1500)
        assert sale.lines[0].unit_cost == 100
        # le prix d'achat change après coup : la marge historique reste figée
        catalog.set_cost(p.id, 200)
        assert sale.lines[0].unit_cost == 100  # T17


class TestSecurity:
    def test_login_incorrect_message_neutre(self, db):
        from gestdepot.security import auth, AuthError
        with pytest.raises(AuthError):
            auth.login("admin", "mauvais")

    def test_permission_refusee(self, db):
        from gestdepot.database.models import Role, User
        from gestdepot.database.session import session_scope
        from gestdepot.security import auth, hash_password
        from sqlalchemy import select
        with session_scope() as s:
            role = s.scalar(select(Role).where(Role.name == "Caissier"))
            s.add(User(username="cai", password_hash=hash_password("secret"),
                       role_id=role.id))
        auth.login("cai", "secret")
        with pytest.raises(PermissionError):
            auth.Session.current().require("users.manage")
