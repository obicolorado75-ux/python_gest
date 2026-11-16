"""§5.13 — inventaires : périmètre, comptage, contrôle des écarts, validation."""
import pytest
from sqlalchemy import select

from gestdepot.database.models import InventoryLine, StockMovement
from gestdepot.database.session import session_scope
from gestdepot.services.inventory_service import InventoryError


class TestPerimetre:
    def test_inventaire_global(self, admin, inventory, stock, product_with_casier,
                               catalog):
        product, _ = product_with_casier
        second = catalog.create_product(reference="EAU-INV", name="Eau inv",
                                        base_unit_id=catalog.list_units()[0].id,
                                        initial_cost=50)
        stock.initial_stock(product.id, 10, unit_cost=100)
        stock.initial_stock(second.id, 5, unit_cost=50)
        session = inventory.start_session()
        assert len(inventory.lines(session.id)) == 2

    def test_inventaire_cible(self, admin, inventory, stock, product_with_casier,
                              catalog):
        product, _ = product_with_casier
        catalog.create_product(reference="EAU-CIB", name="Eau ciblée",
                               base_unit_id=catalog.list_units()[0].id,
                               initial_cost=50)
        stock.initial_stock(product.id, 10, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        lines = inventory.lines(session.id)
        assert [line.product_id for line in lines] == [product.id]
        assert lines[0].theoretical_qty == 10
        assert lines[0].cost == 100

    def test_inventaire_vide_refuse(self, admin, inventory, catalog):
        catalog.archive_product(catalog.create_product(
            reference="ARCH-1", name="Archivé",
            base_unit_id=catalog.list_units()[0].id).id)
        with pytest.raises(InventoryError):
            inventory.start_session()

    def test_seuil_negatif_refuse(self, admin, inventory, product_with_casier):
        with pytest.raises(InventoryError):
            inventory.start_session(threshold_value=-1)


class TestComptage:
    def test_comptage_horodate_et_statut(self, admin, inventory, stock,
                                         product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 20, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        assert inventory.get_session(session.id).status == "draft"
        inventory.set_counted(session.id, product.id, 18)
        refreshed = inventory.get_session(session.id)
        assert refreshed.status == "counting"
        line = inventory.lines(session.id)[0]
        assert line.counted_qty == 18
        assert line.counted_at is not None

    def test_comptage_negatif_refuse(self, admin, inventory, stock,
                                     product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 5, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        with pytest.raises(InventoryError):
            inventory.set_counted(session.id, product.id, -1)

    def test_produit_hors_inventaire_refuse(self, admin, inventory, stock,
                                            product_with_casier, catalog):
        product, _ = product_with_casier
        other = catalog.create_product(reference="AUT-1", name="Autre",
                                       base_unit_id=catalog.list_units()[0].id)
        stock.initial_stock(product.id, 5, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        with pytest.raises(InventoryError):
            inventory.set_counted(session.id, other.id, 3)

    def test_resume_theorique_compte_ecart(self, admin, inventory, stock,
                                           product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        inventory.set_counted(session.id, product.id, 37)
        summary = inventory.summary(session.id)
        assert summary["gaps"] == 1
        assert summary["gap_quantity"] == -3
        assert summary["gap_value"] == -300
        assert summary["total_value"] == 3_700


class TestControleEcarts:
    def test_ecart_sous_seuil_passe(self, admin, inventory, stock,
                                    product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        inventory.set_counted(session.id, product.id, 38)   # écart 200
        assert inventory.check_control(session.id)["pending"] == []
        assert inventory.validate(session.id)["adjusted_lines"] == 1

    def test_ecart_au_dessus_du_seuil_bloque(self, admin, inventory, stock,
                                             product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        inventory.set_counted(session.id, product.id, 20)   # écart 2 000
        control = inventory.check_control(session.id)
        assert control["count"] == 1
        assert control["pending"][0]["product_id"] == product.id
        with pytest.raises(InventoryError):
            inventory.validate(session.id)
        # le stock n'a pas été touché
        assert stock.available(product.id) == 40

    def test_controle_exige_un_commentaire(self, admin, inventory, stock,
                                           product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        inventory.set_counted(session.id, product.id, 20)
        with pytest.raises(InventoryError):
            inventory.review_gap(session.id, product.id, "   ")

    def test_controle_leve_le_blocage(self, admin, inventory, stock,
                                      product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        inventory.set_counted(session.id, product.id, 20)
        inventory.review_gap(session.id, product.id, "Vol constaté, plainte déposée")
        assert inventory.check_control(session.id)["pending"] == []
        assert inventory.get_session(session.id).status == "reviewed"
        summary = inventory.validate(session.id)
        assert summary["adjusted_lines"] == 1
        assert stock.available(product.id) == 20
        line = inventory.lines(session.id)[0]
        assert line.reviewed is True
        assert "plainte" in line.review_comment

    def test_recomptage_invalide_le_controle(self, admin, inventory, stock,
                                             product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id],
                                          threshold_value=1_000)
        inventory.set_counted(session.id, product.id, 20)
        inventory.review_gap(session.id, product.id, "Vérifié")
        inventory.set_counted(session.id, product.id, 39)
        line = inventory.lines(session.id)[0]
        assert line.reviewed is False

    def test_sans_seuil_aucun_controle(self, admin, inventory, stock,
                                       product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 40, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        inventory.set_counted(session.id, product.id, 0)
        assert inventory.check_control(session.id)["pending"] == []
        inventory.validate(session.id)
        assert stock.available(product.id) == 0


class TestValidationEtAbandon:
    def test_validation_tracee_et_non_destructive(self, admin, inventory, stock,
                                                  product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 100, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        inventory.set_counted(session.id, product.id, 94)
        inventory.validate(session.id)
        validated = inventory.get_session(session.id)
        assert validated.status == "validated"
        assert validated.validated_at is not None
        assert validated.validated_by is not None
        line = inventory.lines(session.id)[0]
        assert line.theoretical_qty == 100 and line.counted_qty == 94
        assert stock.available(product.id) == 94
        assert stock.reconcile() == []
        with session_scope() as db_session:
            movements = list(db_session.scalars(select(StockMovement).where(
                StockMovement.reason == "correction_inventaire")))
        assert len(movements) == 1 and movements[0].quantity == -6

    def test_valide_non_modifiable(self, admin, inventory, stock,
                                   product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 10, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        inventory.validate(session.id)
        with pytest.raises(InventoryError):
            inventory.set_counted(session.id, product.id, 5)
        with pytest.raises(InventoryError):
            inventory.validate(session.id)
        with pytest.raises(InventoryError):
            inventory.cancel_session(session.id, "Trop tard")
        with pytest.raises(InventoryError):
            inventory.review_gap(session.id, product.id, "Trop tard")

    def test_abandon_trace(self, admin, inventory, stock, product_with_casier):
        from gestdepot.database.models import AuditLog
        product, _ = product_with_casier
        stock.initial_stock(product.id, 10, unit_cost=100)
        session = inventory.start_session(product_ids=[product.id])
        inventory.set_counted(session.id, product.id, 3)
        with pytest.raises(InventoryError):
            inventory.cancel_session(session.id, "  ")
        inventory.cancel_session(session.id, "Erreur de saisie")
        assert inventory.get_session(session.id).status == "cancelled"
        # un inventaire abandonné ne touche pas au stock et ne se valide pas
        assert stock.available(product.id) == 10
        with pytest.raises(InventoryError):
            inventory.validate(session.id)
        with session_scope() as db_session:
            actions = [log.action for log in db_session.scalars(select(AuditLog)).all()]
        assert "inventory_cancel" in actions

    def test_nouvelle_regulation_possible_apres_validation(self, admin, inventory,
                                                           stock,
                                                           product_with_casier):
        """Une session validée se corrige par un nouvel inventaire (§5.13)."""
        product, _ = product_with_casier
        stock.initial_stock(product.id, 10, unit_cost=100)
        first = inventory.start_session(product_ids=[product.id])
        inventory.set_counted(first.id, product.id, 8)
        inventory.validate(first.id)
        second = inventory.start_session(product_ids=[product.id])
        line = inventory.lines(second.id)[0]
        assert line.theoretical_qty == 8
        inventory.set_counted(second.id, product.id, 9)
        inventory.validate(second.id)
        assert stock.available(product.id) == 9

    def test_lignes_conservees_apres_validation(self, admin, inventory, stock,
                                                product_with_casier):
        product, _ = product_with_casier
        stock.initial_stock(product.id, 12, unit_cost=250)
        session = inventory.start_session(product_ids=[product.id])
        inventory.validate(session.id)
        with session_scope() as db_session:
            line = db_session.scalars(select(InventoryLine)).one()
        assert line.cost == 250
        assert line.theoretical_qty == 12 and line.counted_qty == 12
