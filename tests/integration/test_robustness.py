"""Tests de robustesse : atomicité des transactions (§10.2, T16) et schéma."""
import pytest
from sqlalchemy import inspect, select

from gestdepot.database.models import Base, StockMovement
from gestdepot.database.session import current_engine, session_scope
from gestdepot.services.sales_service import SalesError


class TestAtomicite:
    def test_t16_echec_en_cours_de_validation(self, admin, stock, sales,
                                              stocked_product, catalog):
        """T16 : un échec pendant la validation n'enregistre aucun état partiel."""
        product, packaging = stocked_product
        detail = catalog.list_price_lists()[0].id
        before = stock.available(product.id)
        # ligne 1 valide + ligne 2 demandant plus que le stock disponible
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": 5},
                       {"product_id": product.id, "packaging_id": None,
                        "quantity_display": 5000}],
                payment_method="especes", paid_amount=1000, price_list_id=detail)
        assert stock.available(product.id) == before
        with session_scope() as session:
            from gestdepot.database.models import Sale
            assert list(session.scalars(select(Sale))) == []
            # seul le mouvement de stock initial existe encore
            movements = list(session.scalars(select(StockMovement)))
            assert len(movements) == 1
            assert movements[0].reason == "mouvement_initial"

    def test_rollback_sur_exception_metier(self, admin, stock, product_with_casier):
        """Une exception dans la transaction annule le mouvement précédent."""
        product, _ = product_with_casier
        with pytest.raises(ValueError):
            with session_scope() as session:
                from gestdepot.database.models import StockBalance
                stock._apply(session, product.id, 10, "mouvement_initial",
                             unit_cost=100)
                raise ValueError("simulation de panne")
        with session_scope() as session:
            balance = session.get(StockBalance, product.id)
            assert balance is None or balance.quantity == 0
            assert list(session.scalars(select(StockMovement))) == []


class TestSchema:
    def test_tables_creees(self, db):
        tables = set(inspect(current_engine()).get_table_names())
        expected = {"products", "product_packagings", "product_prices",
                    "stock_movements", "stock_balances", "sales", "sale_lines",
                    "customers", "customer_payments", "suppliers",
                    "purchase_orders", "goods_receipts", "cash_sessions",
                    "cash_movements", "expenses", "users", "roles",
                    "permissions", "audit_logs", "document_sequences",
                    "backup_history", "inventory_sessions", "deposit_movements"}
        missing = expected - tables
        assert not missing, f"Tables manquantes : {missing}"
        assert set(Base.metadata.tables) <= tables

    def test_cle_etrangere_active(self, db):
        """SQLite doit refuser une référence inexistante (§6.9)."""
        from sqlalchemy.exc import IntegrityError

        from gestdepot.database.models import StockBalance
        from gestdepot.database.session import session_scope
        with pytest.raises(IntegrityError):
            with session_scope() as session:
                session.add(StockBalance(product_id=999999, quantity=1))

    def test_donnees_de_reference(self, db):
        from gestdepot.database.models import DocumentSequence, Permission, PriceList, Role, Unit
        with session_scope() as session:
            assert {r.name for r in session.scalars(select(Role))} >= {
                "Administrateur", "Gérant", "Caissier", "Magasinier", "Livreur"}
            assert session.scalar(select(Permission).limit(1)) is not None
            assert len(list(session.scalars(select(Unit)))) >= 4
            assert {p.name for p in session.scalars(select(PriceList))} >= {
                "Détail", "Gros"}
            keys = set(session.scalars(select(DocumentSequence.key)))
            assert {"VTE", "ACH", "REC", "PAY"} <= keys

    def test_numerotation_unique(self, admin, sales, stocked_product, catalog):
        """Deux ventes successives n'ont jamais le même numéro (§7.1)."""
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        numbers = set()
        for _ in range(3):
            sale = sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": 1}],
                payment_method="especes", paid_amount=150, price_list_id=detail)
            numbers.add(sale.number)
        assert len(numbers) == 3
        assert all(number.startswith("VTE-") for number in numbers)

    def test_seed_idempotent(self, db):
        from gestdepot.database.models import Role
        from gestdepot.database.session import seed_reference_data, session_scope
        with session_scope() as session:
            seed_reference_data(session)
            seed_reference_data(session)
            assert len(list(session.scalars(select(Role)))) == 5
