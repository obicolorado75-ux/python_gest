"""§5.11 / §5.8 — achats (remise, frais, paiements, réouverture) et consignes."""
import pytest
from sqlalchemy import select

from gestdepot.database.models import (
    CashMovement,
    PurchaseOrderLine,
    StockMovement,
    SupplierPayment,
)
from gestdepot.database.session import session_scope
from gestdepot.services.deposit_service import DepositError
from gestdepot.services.stock_service import StockError


def _order(stock, supplier, product, quantity=10, cost=100, **kwargs):
    return stock.create_purchase_order(
        supplier.id,
        [{"product_id": product.id, "designation": product.name,
          "quantity": quantity, "quantity_display": quantity, "unit_cost": cost}],
        **kwargs)


class TestAchats:
    def test_commande_ne_touche_pas_au_stock(self, admin, stock, supplier,
                                              product_with_casier):
        """§5.11 : une commande d'achat seule n'augmente pas le stock."""
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=24)
        assert order.total_amount == 2_400
        assert stock.available(product.id) == 0
        with session_scope() as session:
            assert session.scalars(select(StockMovement)).all() == []

    def test_remise_et_frais_dans_le_total(self, admin, stock, supplier,
                                           product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10, cost=100,
                       discount=200, freight_fees=500, other_fees=100)
        # lignes 1 000 − remise 200 + frais 600
        assert order.discount_amount == 200
        assert order.total_amount == 1_400
        line = order.lines[0]
        # 1 000 − 200 + 600 = 1 400 répartis sur 1 000 de marchandise → ×1,4
        assert line.landed_cost == 140
        assert line.landed_cost * line.quantity == order.total_amount

    def test_frais_repartis_sur_plusieurs_lignes(self, admin, stock, supplier,
                                                 catalog, product_with_casier):
        product, _ = product_with_casier
        second = catalog.create_product(reference="EAU-1", name="Eau 1L",
                                       base_unit_id=catalog.list_units()[0].id,
                                       initial_cost=50)
        order = stock.create_purchase_order(
            supplier.id,
            [{"product_id": product.id, "designation": product.name,
              "quantity": 10, "unit_cost": 100},
             {"product_id": second.id, "designation": second.name,
              "quantity": 10, "unit_cost": 100}],
            freight_fees=200)
        # 200 de frais sur 2 000 de marchandise → +10 % par ligne
        assert [line.landed_cost for line in order.lines] == [110, 110]

    def test_reception_utilise_le_cout_landed(self, admin, stock, supplier,
                                              catalog, product_with_casier):
        """Le CMP intègre les frais d'approche (§5.11)."""
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10, cost=100,
                       freight_fees=100)
        line_id = order.lines[0].id
        receipt = stock.receive(order.id, [{"order_line_id": line_id,
                                           "quantity": 10}])
        assert receipt.total_amount == 1_100
        assert stock.balance(product.id).weighted_avg_cost == 110
        assert stock.available(product.id) == 10
        assert stock.get_supplier(supplier.id).balance == 1_100

    def test_reception_partielle_conserve_reliquat(self, admin, stock, supplier,
                                                   product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 4}])
        refreshed = stock.get_purchase_order(order.id)
        assert refreshed.status == "partially_received"
        assert stock.available(product.id) == 4

    def test_reception_superieure_au_reliquat_refusee(self, admin, stock,
                                                      supplier,
                                                      product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=5)
        with pytest.raises(StockError):
            stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                      "quantity": 6}])
        assert stock.available(product.id) == 0

    def test_paiement_fournisseur(self, admin, stock, cash, supplier,
                                  product_with_casier):
        """Paiement : solde dû réduit, espèces sorties de caisse (§5.12)."""
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10, cost=100)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 10}])
        cash_session = cash.open_session(opening_fund=5_000)
        payment = stock.pay_supplier(supplier.id, 400, comment="Acompte")
        assert payment.amount == 400
        assert stock.get_supplier(supplier.id).balance == 600
        assert cash.theoretical_amount(cash_session.id) == 4_600
        with session_scope() as session:
            movements = session.scalars(select(CashMovement)).all()
        assert any(m.reason == "paiement_fournisseur" and m.direction == "out"
                   for m in movements)

    def test_paiement_superieur_au_solde_refuse(self, admin, stock, supplier,
                                                product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 10}])
        with pytest.raises(StockError):
            stock.pay_supplier(supplier.id, 5_000)

    def test_paiement_moyen_inconnu_refuse(self, admin, stock, supplier,
                                           product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 10}])
        with pytest.raises(StockError):
            stock.pay_supplier(supplier.id, 100, payment_method="bitcoin")

    def test_paiement_sur_facture(self, admin, stock, supplier,
                                  product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 10}])
        invoice = stock.supplier_invoices(supplier.id, only_due=True)[0]
        stock.pay_supplier(supplier.id, 300, invoice_id=invoice.id)
        refreshed = stock.supplier_invoices(supplier.id, only_due=True)[0]
        assert refreshed.paid_amount == 300
        assert refreshed.total_amount - refreshed.paid_amount == 700
        with session_scope() as session:
            payment = session.scalars(select(SupplierPayment)).one()
        assert payment.invoice_id == invoice.id

    def test_annulation_et_reeouverture(self, admin, stock, supplier,
                                        product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10)
        with pytest.raises(StockError):
            stock.cancel_order(order.id, "  ")
        stock.cancel_order(order.id, "Fournisseur indisponible")
        assert stock.get_purchase_order(order.id).status == "cancelled"
        stock.reopen_order(order.id, "Erreur de saisie")
        assert stock.get_purchase_order(order.id).status == "confirmed"
        assert stock.available(product.id) == 0

    def test_reeouverture_commande_recue(self, admin, stock, supplier,
                                         product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=6)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 6}])
        assert stock.get_purchase_order(order.id).status == "received"
        stock.reopen_order(order.id, "Reliquat à réceptionner")
        assert stock.get_purchase_order(order.id).status == "partially_received"
        with session_scope() as session:
            line = session.scalars(select(PurchaseOrderLine)).one()
        assert line.received_qty == 6

    def test_historique_achats_par_fournisseur(self, admin, stock, supplier,
                                               product_with_casier):
        product, _ = product_with_casier
        order = _order(stock, supplier, product, quantity=10, cost=100)
        stock.receive(order.id, [{"order_line_id": order.lines[0].id,
                                  "quantity": 10}])
        assert stock.purchased_by_supplier() == {supplier.id: 1_000}
        assert len(stock.list_purchase_orders()) == 1


class TestConsignes:
    def test_comptes_client_et_valeur(self, admin, deposit, sales):
        customer = sales.create_customer(code="CLI-C1", name="Bar Consigne")
        packaging = deposit.create_packaging("CAS-BIE", "Casier bière", 500,
                                             capacity=24)
        deposit.move(packaging.id, 5, "remis_client", customer_id=customer.id)
        deposit.move(packaging.id, -2, "retourne_client", customer_id=customer.id)
        overview = deposit.balances_overview()
        assert overview[0]["quantity"] == 3
        assert overview[0]["value"] == 1_500
        assert deposit.customer_balance_value(customer.id) == 1_500

    def test_retour_superieur_au_solde_refuse(self, admin, deposit, sales):
        customer = sales.create_customer(code="CLI-C2", name="Client 2")
        packaging = deposit.create_packaging("CAS-2", "Casier 2", 300)
        deposit.move(packaging.id, 2, "remis_client", customer_id=customer.id)
        with pytest.raises(DepositError):
            deposit.move(packaging.id, -5, "retourne_client",
                         customer_id=customer.id)

    def test_compte_fournisseur(self, admin, deposit, supplier):
        packaging = deposit.create_packaging("FUT-1", "Fût", 2_000,
                                             supplier_id=supplier.id)
        deposit.move(packaging.id, 4, "recu_fournisseur",
                     supplier_id=supplier.id)
        assert deposit.supplier_balance(supplier.id) == {packaging.id: 4}
        assert deposit.supplier_balance_value(supplier.id) == 8_000
        deposit.move(packaging.id, -1, "rendu_fournisseur",
                     supplier_id=supplier.id)
        assert deposit.supplier_balance(supplier.id) == {packaging.id: 3}
        with pytest.raises(DepositError):
            deposit.move(packaging.id, -10, "rendu_fournisseur",
                         supplier_id=supplier.id)

    def test_mouvement_sans_partie_refuse(self, admin, deposit):
        packaging = deposit.create_packaging("CAS-3", "Casier 3", 100)
        with pytest.raises(DepositError):
            deposit.move(packaging.id, 1, "remis_client")
        with pytest.raises(DepositError):
            deposit.move(packaging.id, 1, "recu_fournisseur")

    def test_remboursement_consigne_hors_chiffre_affaires(self, admin, deposit,
                                                          sales, cash):
        customer = sales.create_customer(code="CLI-C3", name="Client 3")
        packaging = deposit.create_packaging("CAS-R", "Casier remboursable", 400)
        cash_session = cash.open_session(opening_fund=10_000)
        deposit.move(packaging.id, 3, "remis_client", customer_id=customer.id)
        deposit.move(packaging.id, -3, "retourne_client", customer_id=customer.id)
        amount = deposit.refund_customer(customer.id, packaging.id, 3)
        assert amount == 1_200
        assert cash.theoretical_amount(cash_session.id) == 8_800
        with session_scope() as session:
            movements = session.scalars(select(CashMovement)).all()
        assert any(m.reason == "remboursement_consigne" for m in movements)
        # aucune vente créée : la consigne reste hors CA
        assert sales.recent_sales() == []

    def test_code_emballage_unique(self, admin, deposit):
        deposit.create_packaging("CAS-X", "Casier X", 100)
        with pytest.raises(DepositError):
            deposit.create_packaging("CAS-X", "Doublon", 100)
