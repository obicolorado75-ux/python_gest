"""§5.5 — encaissements multiples, ventes suspendues et retours depuis la caisse."""
import pytest
from sqlalchemy import select

from gestdepot.database.models import CustomerPayment, SalePayment, StockMovement
from gestdepot.database.session import session_scope
from gestdepot.services.sales_service import SalesError


class TestPaiementMixte:
    def test_deux_moyens_de_paiement(self, admin, sales, stocked_product, catalog):
        """10 000 en espèces + le reste en Wave sur une même vente."""
        product, packaging = stocked_product
        detail = catalog.list_price_lists()[0].id
        total = 2 * 3600  # 7 200
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": packaging.id,
                    "quantity_display": 2}],
            payments=[{"method": "especes", "amount": 5_000},
                      {"method": "wave", "amount": total - 5_000}],
            price_list_id=detail)
        assert sale.total_amount == total
        assert sale.paid_amount == total
        # le moyen principal est celui qui porte le plus gros montant
        assert sale.payment_method == "especes"
        with session_scope() as session:
            details = session.scalars(
                select(SalePayment).where(SalePayment.sale_id == sale.id)).all()
            assert {d.payment_method for d in details} == {"especes", "wave"}
            assert sum(d.amount for d in details) == total
            payments = session.scalars(
                select(CustomerPayment)
                .where(CustomerPayment.sale_id == sale.id)).all()
            assert len(payments) == 2
            numbers = {p.number for p in payments}
            assert len(numbers) == 2  # un numéro PAY-… par encaissement

    def test_total_encaissements_coherent(self, admin, sales, stocked_product,
                                          catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": 2}],
                payments=[{"method": "especes", "amount": 100}],
                price_list_id=detail)

    def test_moyen_inconnu_refuse(self, admin, sales, stocked_product, catalog):
        product, _ = stocked_product
        with pytest.raises(SalesError):
            sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": 2}],
                payments=[{"method": "bitcoin", "amount": 300}],
                price_list_id=catalog.list_price_lists()[0].id)

    def test_credit_avec_paiement_mixte(self, admin, sales, stocked_product,
                                        catalog):
        """Paiement partiel multi-moyens : la créance suit le reste à payer."""
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        customer = sales.create_customer(code="CLI-MIX", name="Maquis Mixte",
                                        credit_limit=100_000)
        total = 150 * 100
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 100}],
            payments=[{"method": "especes", "amount": 5_000},
                      {"method": "orange_money", "amount": 5_000}],
            customer_id=customer.id, price_list_id=detail)
        assert sale.total_amount == total
        assert sale.paid_amount == 10_000
        assert sales.customer_balance(customer.id) == total - 10_000


class TestVenteSuspendue:
    def test_suspendre_ne_touche_a_rien(self, admin, sales, stock,
                                        stocked_product, catalog):
        """F8 : suspendre ne crée ni mouvement de stock, ni vente, ni caisse."""
        product, packaging = stocked_product
        items = [{"product_id": product.id, "packaging_id": packaging.id,
                  "quantity_display": 1, "base_qty": 0}]
        held = sales.hold_sale(items, price_list_id=catalog.list_price_lists()[0].id,
                               label="Table 2")
        assert held.id is not None
        assert stock.available(product.id) == 240
        assert sales.recent_sales() == []
        with session_scope() as session:
            movements = session.scalars(select(StockMovement)).all()
        # seul le mouvement initial du produit existe (aucune sortie de vente)
        assert [m.reason for m in movements] == ["mouvement_initial"]
        listed = sales.held_sales()
        assert [h.label for h in listed] == ["Table 2"]
        restored = sales.get_held_sale(held.id)
        assert restored["items"][0]["product_id"] == product.id
        assert restored["price_list_id"] == catalog.list_price_lists()[0].id

    def test_reprendre_valide_la_vente(self, admin, sales, stock,
                                       stocked_product, catalog):
        product, packaging = stocked_product
        detail = catalog.list_price_lists()[0].id
        held = sales.hold_sale(
            [{"product_id": product.id, "packaging_id": packaging.id,
              "quantity_display": 2, "base_qty": 0}], price_list_id=detail)
        sale = sales.resume_held_sale(held.id, payment_method="especes",
                                      paid_amount=7_200)
        assert sale.total_amount == 7_200
        assert stock.available(product.id) == 240 - 48
        assert sales.held_sales() == []  # le panier a été consommé

    def test_abandon_trace(self, admin, sales, stocked_product, catalog):
        from gestdepot.database.models import AuditLog
        product, _ = stocked_product
        held = sales.hold_sale(
            [{"product_id": product.id, "packaging_id": None,
              "quantity_display": 1, "base_qty": 0}], label="Panier oublié",
            price_list_id=catalog.list_price_lists()[0].id)
        sales.discard_held_sale(held.id)
        assert sales.held_sales() == []
        with session_scope() as session:
            actions = [log.action for log in session.scalars(select(AuditLog)).all()]
        assert "sale_hold_discard" in actions

    def test_panier_vide_refuse(self, admin, sales):
        with pytest.raises(SalesError):
            sales.hold_sale([])

    def test_reprise_avec_remise(self, admin, sales, stocked_product, catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        held = sales.hold_sale(
            [{"product_id": product.id, "packaging_id": None,
              "quantity_display": 10, "base_qty": 0}],
            price_list_id=detail, manual_discount=200)
        sale = sales.resume_held_sale(held.id, payment_method="especes",
                                      paid_amount=1_300)
        assert sale.total_amount == 10 * 150 - 200


class TestRetoursEtAnnulation:
    def test_lignes_retournables(self, admin, sales, stocked_product, catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1_500, price_list_id=detail)
        lines = sales.returnable_lines(sale.id)
        assert len(lines) == 1
        assert lines[0]["remaining"] == 10
        assert lines[0]["unit_refund"] == 150
        sales.return_sale(sale.id, [{"sale_line_id": lines[0]["sale_line_id"],
                                     "quantity": 4}], reason="Casse client")
        remaining = sales.returnable_lines(sale.id)[0]
        assert remaining["already_returned"] == 4
        assert remaining["remaining"] == 6

    def test_retour_complet_retire_la_ligne(self, admin, sales, stocked_product,
                                            catalog):
        product, _ = stocked_product
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 5}],
            payment_method="especes", paid_amount=750,
            price_list_id=catalog.list_price_lists()[0].id)
        line = sales.returnable_lines(sale.id)[0]
        sales.return_sale(sale.id, [{"sale_line_id": line["sale_line_id"],
                                     "quantity": 5}], reason="Erreur")
        assert sales.returnable_lines(sale.id) == []
