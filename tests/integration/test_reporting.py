"""Tests des rapports, exports et du tableau de bord (§5.15, T14)."""
import os
from datetime import datetime, timedelta

import pytest

from gestdepot.database.session import session_scope
from gestdepot.services.reporting_service import Period


class TestPeriodes:
    def test_periodes_predefinies(self):
        assert Period.today().label == "Aujourd'hui"
        assert Period.current_month().label == "Mois en cours"
        period = Period.last_days(7)
        assert (period.end.date() - period.start.date()).days == 6

    def test_periode_invalide_refusee(self):
        with pytest.raises(ValueError):
            Period(datetime(2026, 1, 10), datetime(2026, 1, 1))


class TestTableauDeBord:
    def test_indicateurs_coherents(self, admin, stock, sales, cash,
                                   stocked_product, catalog):
        """Les chiffres viennent des opérations sources (§5.4)."""
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        cash.open_session(opening_fund=0)
        customer = sales.create_customer(code="CLI-DB", name="Client Dashboard",
                                         credit_limit=100_000)
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 100}],   # 15 000
            payment_method="especes", paid_amount=10_000,
            customer_id=customer.id, price_list_id=detail)
        from gestdepot.services.reporting_service import ReportingService
        report = ReportingService().dashboard(Period.today())
        assert report["sales_count"] == 1
        assert report["gross_sales"] == 15_000
        assert report["net_sales"] == 15_000
        assert report["cogs"] == 100 * 100
        assert report["gross_margin"] == 15_000 - 10_000
        assert report["receivables"] == 5_000  # créance du client

    def test_retour_reduit_le_chiffre_affaires(self, admin, sales, stocked_product,
                                               catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1500, price_list_id=detail)
        sales.return_sale(sale.id, [{"sale_line_id": sale.lines[0].id,
                                     "quantity": 4}], reason="Retour partiel")
        summary = sales.sales_summary(datetime.now() - timedelta(hours=1),
                                      datetime.now() + timedelta(hours=1))
        assert summary["returns"] == 600
        assert summary["net_sales"] == 900
        assert summary["cogs"] == 600          # coût des 6 unités restantes
        assert summary["gross_margin"] == 300  # 900 - 600

    def test_marges_par_produit(self, admin, sales, stocked_product, catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1500, price_list_id=detail)
        from gestdepot.services.reporting_service import ReportingService
        top = ReportingService().top_products(Period.today(), by="margin")
        assert top[0]["designation"] == "Soda 33cl"
        assert top[0]["margin"] == 10 * (150 - 100)


class TestExports:
    def test_t14_exports_concordent(self, admin, sales, stocked_product, catalog,
                                    tmp_path, monkeypatch):
        """T14 : les totaux exportés correspondent aux données sources."""
        from gestdepot.config import app_paths
        monkeypatch.setattr(app_paths, "exports_dir", lambda: tmp_path)
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1500, price_list_id=detail)

        from gestdepot.reports.exports import export_excel, export_pdf
        xlsx = export_excel("Ventes", ["N°", "Total"],
                            [[sale.number, sale.total_amount]],
                            {"Total": sale.total_amount})
        pdf = export_pdf("Ventes", ["N°", "Total"],
                         [[sale.number, sale.total_amount]],
                         company={"name": "Dépôt Test"},
                         totals={"Total": sale.total_amount})
        assert os.path.exists(xlsx) and os.path.getsize(xlsx) > 0
        assert os.path.exists(pdf) and os.path.getsize(pdf) > 0

        from openpyxl import load_workbook
        sheet = load_workbook(xlsx).active
        values = [[cell for cell in row]
                  for row in sheet.iter_rows(values_only=True)]
        assert any(row[0] == sale.number and row[1] == sale.total_amount
                   for row in values)
        # l'export ne modifie pas la base
        assert sales.get_sale(sale.id).total_amount == 1500

    def test_export_vide(self, admin, tmp_path, monkeypatch):
        from gestdepot.config import app_paths
        from gestdepot.reports.exports import export_excel, export_pdf
        monkeypatch.setattr(app_paths, "exports_dir", lambda: tmp_path)
        assert os.path.exists(export_excel("Vide", ["A"], []))
        assert os.path.exists(export_pdf("Vide", ["A"], []))


class TestRapprochements:
    def test_rapprochement_stock_apres_operations(self, admin, stock, sales,
                                                  stocked_product, catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1500, price_list_id=detail)
        assert stock.reconcile() == []
        assert stock.journal_total(product.id) == stock.available(product.id)

    def test_solde_client_egale_ventes_moins_paiements(self, admin, sales,
                                                      stocked_product, catalog):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        customer = sales.create_customer(code="CLI-X", name="Client X",
                                        credit_limit=100_000)
        sale = sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 20}],   # 3000
            payment_method="especes", paid_amount=1000,
            customer_id=customer.id, price_list_id=detail)
        sales.pay_credit(customer.id, 500)
        with session_scope() as session:
            refreshed = session.get(type(customer), customer.id)
            assert refreshed.balance == sale.total_amount - 1000 - 500
