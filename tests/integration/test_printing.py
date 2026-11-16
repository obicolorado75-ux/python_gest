"""Tests des documents imprimables (ticket de caisse, §5.5 / §9)."""
import os

from gestdepot.domain.rules import format_xof, label_payment, label_status


class TestTicket:
    def test_ticket_contient_les_totaux(self, admin, sales, stocked_product,
                                        catalog, tmp_path, monkeypatch):
        from gestdepot.config import app_paths
        monkeypatch.setattr(app_paths, "data_dir", lambda: tmp_path)
        product, packaging = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": packaging.id,
                    "quantity_display": 2},
                   {"product_id": product.id, "packaging_id": None,
                    "quantity_display": 3}],
            payment_method="especes", paid_amount=7650, price_list_id=detail)

        from gestdepot.printing import write_receipt
        path = write_receipt(sale, {"name": "Dépôt Test",
                                    "address": "Abidjan",
                                    "phone": "+225 07"},
                             list(sale.lines))
        assert os.path.exists(path)
        html = open(path, encoding="utf-8").read()
        assert sale.number in html
        assert "Dépôt Test" in html
        assert format_xof(sale.total_amount) in html
        assert format_xof(0) in html                # reste dû nul
        assert "Merci de votre visite" in html

    def test_ticket_sans_client(self, admin, sales, stocked_product, catalog,
                                tmp_path, monkeypatch):
        from gestdepot.config import app_paths
        monkeypatch.setattr(app_paths, "data_dir", lambda: tmp_path)
        product, _ = stocked_product
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 2}],
            payment_method="especes", paid_amount=300,
            price_list_id=catalog.list_price_lists()[0].id)
        from gestdepot.printing import sale_receipt_html
        html = sale_receipt_html(sale, {"name": "Dépôt"})
        assert "Comptoir" in html

    def test_libelles_francais(self):
        assert label_status("partially_returned") == "Partiellement retournée"
        assert label_status(None) == "—"
        assert label_payment("orange_money") == "Orange Money"
        assert label_payment(None) == "—"
