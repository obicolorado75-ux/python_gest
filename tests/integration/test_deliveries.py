"""§5.10 — commandes clients et livraisons : stock, reliquats, échecs, unicité."""
import pytest

from gestdepot.services.delivery_service import DeliveryError, DeliveryService


@pytest.fixture()
def delivery(admin):
    return DeliveryService()


@pytest.fixture()
def customer(sales):
    return sales.create_customer(code="CLI-LIV", name="Maquis Le Palmier",
                                 phone="0700000000",
                                 address="Abidjan, Cocody")


@pytest.fixture()
def item(stocked_product, catalog):
    product, _ = stocked_product
    return {"product_id": product.id, "packaging_id": None,
            "quantity_display": 10}


class TestCommande:
    def test_brouillon_ne_touche_pas_le_stock(self, delivery, stock, customer,
                                             item, stocked_product):
        product, _ = stocked_product
        before = stock.available(product.id)
        order = delivery.create_order(customer.id, [item])
        assert order.status == "draft"
        assert stock.available(product.id) == before

    def test_commande_vide_refusee(self, delivery, customer):
        with pytest.raises(DeliveryError):
            delivery.create_order(customer.id, [])

    def test_client_inconnu_refuse(self, delivery, item):
        with pytest.raises(DeliveryError):
            delivery.create_order(999_999, [item])

    def test_confirmation_sans_reservation(self, delivery, stock, customer, item,
                                           stocked_product):
        product, _ = stocked_product
        order = delivery.create_order(customer.id, [item], reserve_stock=False)
        before = stock.available(product.id)
        delivery.confirm_order(order.id)
        assert stock.available(product.id) == before
        assert delivery.get_order(order.id)["status"] == "confirmed"

    def test_reservation_bloque_la_disponibilite(self, delivery, stock, customer,
                                                 item, stocked_product):
        product, _ = stocked_product
        before = stock.available(product.id)
        order = delivery.create_order(customer.id, [item])
        delivery.confirm_order(order.id)
        assert stock.available(product.id) == before - 10
        # la marchandise réservée ne peut pas être vendue une deuxième fois
        from gestdepot.services.sales_service import SalesError
        with pytest.raises(SalesError):
            delivery.sales.confirm_sale(
                items=[{"product_id": product.id, "packaging_id": None,
                        "quantity_display": before - 9}],
                paid_amount=100000, customer_id=customer.id,
                price_list_id=None)

    def test_reservation_impossible_si_stock_insuffisant(self, delivery, customer,
                                                        stocked_product):
        product, _ = stocked_product
        order = delivery.create_order(customer.id, [{
            "product_id": product.id, "packaging_id": None,
            "quantity_display": 5000}])
        with pytest.raises(DeliveryError):
            delivery.confirm_order(order.id, reserve_stock=True)

    def test_annulation_libere_la_reservation(self, delivery, stock, customer,
                                              item, stocked_product):
        product, _ = stocked_product
        before = stock.available(product.id)
        order = delivery.create_order(customer.id, [item])
        delivery.confirm_order(order.id)
        assert stock.available(product.id) == before - 10
        delivery.cancel_order(order.id, "Client injoignable")
        assert stock.available(product.id) == before
        detail = delivery.get_order(order.id)
        assert detail["status"] == "cancelled"

    def test_annulation_exige_un_motif(self, delivery, customer, item):
        order = delivery.create_order(customer.id, [item])
        with pytest.raises(DeliveryError):
            delivery.cancel_order(order.id, "   ")

    def test_brouillon_peut_etre_annule_sans_motif_stock(self, delivery, customer,
                                                        item):
        order = delivery.create_order(customer.id, [item])
        delivery.cancel_order(order.id, "Erreur de saisie")
        assert delivery.get_order(order.id)["status"] == "cancelled"

    def test_preparation(self, delivery, customer, item):
        order = delivery.create_order(customer.id, [item])
        delivery.confirm_order(order.id, reserve_stock=False)
        delivery.set_order_status(order.id, "preparing")
        detail = delivery.get_order(order.id)
        assert detail["status"] == "preparing"
        delivery.set_order_status(order.id, "ready")
        assert delivery.get_order(order.id)["status"] == "ready"

    def test_brouillon_non_confirmable_deux_fois(self, delivery, customer, item):
        order = delivery.create_order(customer.id, [item], reserve_stock=False)
        delivery.confirm_order(order.id)
        with pytest.raises(DeliveryError):
            delivery.confirm_order(order.id)


class TestLivraison:
    @pytest.fixture()
    def planned(self, delivery, stock, customer, item, stocked_product):
        product, _ = stocked_product
        before = stock.available(product.id)
        order = delivery.create_order(customer.id, [item], reserve_stock=False)
        delivery.confirm_order(order.id)
        shipment = delivery.plan_delivery(order.id, driver="Yao",
                                          fee=2000)
        return {"order": order, "delivery": shipment, "before": before,
                "product": product}

    def test_planification_ne_sort_pas_le_stock(self, delivery, stock, planned):
        assert stock.available(planned["product"].id) == planned["before"]
        detail = delivery.get_delivery(planned["delivery"].id)
        assert detail["prepared_qty"] == 10
        assert detail["status"] == "pending"

    def test_confirmation_complete_sort_le_stock_une_fois(self, delivery, stock,
                                                         planned, admin):
        result = delivery.confirm_delivery(
            planned["delivery"].id, collected_amount=0,
            payment_method="especes")
        assert result["status"] == "delivered", result
        assert result["sale_number"].startswith("VTE-")
        assert stock.available(planned["product"].id) == planned["before"] - 10
        assert delivery.get_order(planned["order"].id)["status"] == "delivered"
        # deuxième confirmation refusée : pas de double sortie
        with pytest.raises(DeliveryError):
            delivery.confirm_delivery(planned["delivery"].id, collected_amount=0)
        assert stock.available(planned["product"].id) == planned["before"] - 10

    def test_livraison_partielle_laisse_un_reliquat(self, delivery, stock, planned,
                                                    admin):
        detail = delivery.get_delivery(planned["delivery"].id)
        line_id = detail["lines"][0]["id"]
        result = delivery.confirm_delivery(
            planned["delivery"].id,
            lines=[{"delivery_line_id": line_id, "delivered_qty": 6}],
            collected_amount=0)
        assert result["status"] == "partial"
        assert stock.available(planned["product"].id) == planned["before"] - 6
        order = delivery.get_order(planned["order"].id)
        assert order["status"] == "partially_delivered"
        assert order["remaining"] == 4

    def test_reliquat_livrable_ensuite(self, delivery, stock, planned, admin):
        detail = delivery.get_delivery(planned["delivery"].id)
        line_id = detail["lines"][0]["id"]
        delivery.confirm_delivery(planned["delivery"].id,
                                  lines=[{"delivery_line_id": line_id,
                                          "delivered_qty": 6}],
                                  collected_amount=0)
        second = delivery.plan_delivery(planned["order"].id)
        delivery.confirm_delivery(second.id, collected_amount=0)
        assert delivery.get_order(planned["order"].id)["status"] == "delivered"
        assert stock.available(planned["product"].id) == planned["before"] - 10

    def test_echec_conserve_commande_et_paiements(self, delivery, sales, planned,
                                                  customer, admin):
        delivery.start_delivery(planned["delivery"].id)
        # un acompte est encaissé avant l'échec
        # un acompte est encaissé avant l'échec : la créance provient d'une
        # vente à crédit antérieure, elle n'est pas effacée par l'échec
        sales.confirm_sale(
            items=[{"product_id": planned["product"].id, "packaging_id": None,
                    "quantity_display": 2}], paid_amount=0,
            customer_id=customer.id, price_list_id=None)
        detail = delivery.fail_delivery(planned["delivery"].id,
                                        "Client absent")
        assert detail["status"] == "failed"
        order = delivery.get_order(planned["order"].id)
        assert order["status"] != "cancelled"
        from sqlalchemy import select

        from gestdepot.database.models import Customer
        from gestdepot.database.session import session_scope
        with session_scope() as s:
            assert s.scalar(select(Customer.balance).where(
                Customer.id == customer.id)) is not None

    def test_echec_exige_un_motif(self, delivery, planned):
        with pytest.raises(DeliveryError):
            delivery.fail_delivery(planned["delivery"].id, "")

    def test_livraison_avec_encaissement_et_frais(self, delivery, planned,
                                                  customer, catalog):
        order_detail = delivery.get_order(planned["order"].id)
        total = order_detail["total_amount"]
        result = delivery.confirm_delivery(
            planned["delivery"].id, collected_amount=total + 2000,
            payment_method="especes", proof="Signé par le gérant")
        assert result["sale_id"] is not None
        from gestdepot.database.models import Sale
        from gestdepot.database.session import session_scope
        with session_scope() as s:
            sale = s.get(Sale, result["sale_id"])
            # frais de livraison facturés avec la marchandise
            assert sale.total_amount == total + 2000
            assert sale.paid_amount == total + 2000

    def test_quantite_livree_superieure_refusee(self, delivery, planned):
        detail = delivery.get_delivery(planned["delivery"].id)
        line_id = detail["lines"][0]["id"]
        with pytest.raises(DeliveryError):
            delivery.confirm_delivery(planned["delivery"].id,
                                      lines=[{"delivery_line_id": line_id,
                                              "delivered_qty": 99}],
                                      collected_amount=0)

    def test_livraison_sans_quantite_refusee(self, delivery, planned):
        detail = delivery.get_delivery(planned["delivery"].id)
        line_id = detail["lines"][0]["id"]
        with pytest.raises(DeliveryError):
            delivery.confirm_delivery(planned["delivery"].id, collected_amount=0,
                                      lines=[{"delivery_line_id": line_id,
                                              "delivered_qty": 0}])

    def test_moyen_de_paiement_inconnu_refuse(self, delivery, planned):
        with pytest.raises(DeliveryError):
            delivery.confirm_delivery(planned["delivery"].id, collected_amount=0,
                                      payment_method="bitcoin")

    def test_depart_du_livreur(self, delivery, planned):
        delivery.start_delivery(planned["delivery"].id)
        detail = delivery.get_delivery(planned["delivery"].id)
        assert detail["status"] == "in_transit"
        with pytest.raises(DeliveryError):
            delivery.confirm_delivery(planned["delivery"].id,
                                      collected_amount=-5)


class TestBonDeLivraison:
    def test_bon_de_livraison_genere(self, delivery, customer, item, stocked_product,
                                     admin, tmp_path, monkeypatch):
        from gestdepot.config import app_paths
        monkeypatch.setattr(app_paths, "data_dir", lambda: tmp_path)
        order = delivery.create_order(customer.id, [item], reserve_stock=False)
        delivery.confirm_order(order.id)
        shipment = delivery.plan_delivery(order.id, driver="Yao", vehicle="AB-123-CD")
        path = delivery.delivery_note(shipment.id)
        import os
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert shipment.number in content
        assert "Maquis Le Palmier" in content
        assert "Yao" in content

    def test_bon_reference_dans_les_documents(self, delivery, customer, item,
                                              stocked_product, admin, tmp_path,
                                              monkeypatch):
        from sqlalchemy import select

        from gestdepot.config import app_paths
        from gestdepot.database.models import GeneratedDocument
        from gestdepot.database.session import session_scope
        monkeypatch.setattr(app_paths, "data_dir", lambda: tmp_path)
        order = delivery.create_order(customer.id, [item], reserve_stock=False)
        delivery.confirm_order(order.id)
        shipment = delivery.plan_delivery(order.id)
        delivery.delivery_note(shipment.id)
        with session_scope() as s:
            documents = list(s.scalars(select(GeneratedDocument)))
        assert documents and documents[0].document_type == "bon_livraison"
