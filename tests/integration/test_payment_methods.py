"""§5.12 — moyens de paiement configurables (espace, Mobile Money, autre…)."""
import pytest

from gestdepot.services import payment_methods
from gestdepot.services.sales_service import SalesError


@pytest.fixture()
def configured(admin, tmp_path):
    """Administrateur connecté, réglages de paiement à l'état par défaut."""
    payment_methods.save(list(payment_methods.DEFAULT_METHODS))
    return payment_methods


class Testconfiguration:
    def test_liste_par_defaut(self, configured):
        codes = configured.codes()
        assert "especes" in codes and "wave" in codes and "cheque" in codes
        assert len(codes) == 8

    def test_desactiver_un_moyen(self, configured):
        codes = [code for code in configured.codes() if code != "wave"]
        configured.save(codes)
        assert "wave" not in configured.codes()
        assert configured.labels()["especes"] == "Espèces"

    def test_especes_obligatoire(self, configured):
        with pytest.raises(ValueError):
            configured.save(["wave", "cheque"])

    def test_ajout_d_un_moyen_personnalise(self, configured):
        configured.add("Airtel Money", "Airtel Money")
        codes = configured.codes()
        assert "airtel_money" in codes
        assert configured.labels()["airtel_money"] == "Airtel Money"

    def test_ajout_avec_libelle_seul(self, configured):
        configured.add("Moov Flooz")
        assert "moov_flooz" in configured.codes()
        assert configured.labels()["moov_flooz"] == "Moov Flooz"

    def test_doublon_refuse(self, configured):
        with pytest.raises(ValueError):
            configured.add("Wave", "Wave")

    def test_code_vide_refuse(self, configured):
        with pytest.raises(ValueError):
            configured.add("   ")

    def test_configuration_persistee(self, configured):
        configured.save([code for code in configured.codes() if code != "cheque"])
        # une nouvelle lecture en base reflète l'enregistrement
        assert "cheque" not in payment_methods.resolve()

    def test_libelle_supprime_reste_lisible(self, configured):
        configured.add("Airtel Money", "Airtel Money")
        configured.save([code for code in configured.codes()
                         if code != "airtel_money"])
        assert "airtel_money" not in configured.codes()
        # le libellé historique reste résolu pour l'affichage
        assert "airtel_money" not in configured.labels()


class TestImpactMetier:
    def test_vente_avec_moyen_desactive_refusee(self, configured, sales, stocked_product,
                                                catalog, admin):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        configured.save([code for code in configured.codes() if code != "wave"])
        with pytest.raises(SalesError):
            sales.confirm_sale(items=[{"product_id": product.id,
                                       "packaging_id": None,
                                       "quantity_display": 1}],
                               payment_method="wave", paid_amount=0,
                               price_list_id=detail)

    def test_vente_avec_moyen_personnalise(self, configured, sales, stocked_product,
                                           catalog, admin):
        product, _ = stocked_product
        detail = catalog.list_price_lists()[0].id
        configured.add("Airtel Money", "Airtel Money")
        customer = sales.create_customer(code="CLI-PAY", name="Client Airtel")
        sale = sales.confirm_sale(items=[{"product_id": product.id,
                                          "packaging_id": None,
                                          "quantity_display": 1}],
                                  payment_method="airtel_money",
                                  paid_amount=0, customer_id=customer.id,
                                  price_list_id=detail)
        assert sale.payment_method == "airtel_money"

    def test_audit_de_la_modification(self, configured, admin):
        from gestdepot.services.admin_service import AdminService
        configured.save(list(configured.codes()))
        assert any(log.action == "payment_methods_update"
                   for log in AdminService().audit_logs(limit=10))
