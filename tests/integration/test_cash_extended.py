"""§5.12 — caisse : sessions, mouvements, dépenses, corrections auditées."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from gestdepot.database.models import AuditLog, CashMovement
from gestdepot.database.session import session_scope
from gestdepot.services.cash_service import CashError


class TestSessions:
    def test_ouverture_unique_par_utilisateur(self, admin, cash):
        first = cash.open_session(opening_fund=10_000)
        assert first.status == "open"
        with pytest.raises(CashError):
            cash.open_session(opening_fund=5_000)

    def test_fond_negatif_refuse(self, admin, cash):
        with pytest.raises(CashError):
            cash.open_session(opening_fund=-1)

    def test_cloture_conserve_l_ecart(self, admin, cash, sales, stocked_product,
                                      catalog):
        product, _ = stocked_product
        cash_session = cash.open_session(opening_fund=5_000)
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="especes", paid_amount=1_500,
            price_list_id=catalog.list_price_lists()[0].id)
        cash.add_expense(2_000, cash.list_expense_categories()[0].id)
        assert cash.theoretical_amount(cash_session.id) == 4_500
        closed = cash.close_session(cash_session.id, 4_300, "Manque 200")
        assert closed.status == "closed"
        assert closed.difference == -200
        assert closed.close_comment == "Manque 200"
        with pytest.raises(CashError):
            cash.close_session(cash_session.id, 4_300)

    def test_moyens_non_especes_suivis_separement(self, admin, cash, sales,
                                                  stocked_product, catalog):
        """T11 : un encaissement Wave ne change pas le solde physique."""
        product, _ = stocked_product
        cash_session = cash.open_session(opening_fund=1_000)
        sales.confirm_sale(
            items=[{"product_id": product.id, "packaging_id": None,
                    "quantity_display": 10}],
            payment_method="wave", paid_amount=1_500,
            price_list_id=catalog.list_price_lists()[0].id)
        assert cash.theoretical_amount(cash_session.id) == 1_000
        assert cash.movements_by_method(cash_session.id)["wave"] == 1_500


class TestMouvements:
    def test_retrait_et_apport(self, admin, cash):
        cash_session = cash.open_session(opening_fund=10_000)
        cash.register_movement("out", 3_000, "retrait", comment="Versement banque")
        cash.register_movement("in", 2_000, "apport")
        assert cash.theoretical_amount(cash_session.id) == 9_000

    def test_sans_session_ouverte_refuse(self, admin, cash):
        with pytest.raises(CashError):
            cash.register_movement("out", 1_000, "retrait")

    def test_motif_metier_non_saisissable(self, admin, cash):
        """On ne peut pas fabriquer un encaissement de vente à la main."""
        cash.open_session(opening_fund=0)
        with pytest.raises(CashError):
            cash.register_movement("in", 5_000, "encaissement_vente")

    def test_montant_et_moyen_valides(self, admin, cash):
        cash.open_session(opening_fund=0)
        with pytest.raises(CashError):
            cash.register_movement("in", 0, "apport")
        with pytest.raises(CashError):
            cash.register_movement("in", 100, "apport", payment_method="bitcoin")
        with pytest.raises(CashError):
            cash.register_movement("sideways", 100, "apport")

    def test_correction_exige_un_motif(self, admin, cash):
        cash.open_session(opening_fund=1_000)
        with pytest.raises(CashError):
            cash.register_movement("in", 500, "correction")


class TestDepenses:
    def test_depense_diminue_la_caisse_especes(self, admin, cash):
        cash_session = cash.open_session(opening_fund=10_000)
        expense = cash.add_expense(3_000, cash.list_expense_categories()[0].id,
                                   beneficiary="Bailleur")
        assert expense.number.startswith("DEP-")
        assert cash.theoretical_amount(cash_session.id) == 7_000

    def test_depense_non_especes_hors_caisse(self, admin, cash):
        cash_session = cash.open_session(opening_fund=10_000)
        cash.add_expense(3_000, cash.list_expense_categories()[0].id,
                         payment_method="virement")
        assert cash.theoretical_amount(cash_session.id) == 10_000

    def test_depense_datee_et_future_refusee(self, admin, cash):
        category = cash.list_expense_categories()[0].id
        yesterday = datetime.now() - timedelta(days=1)
        expense = cash.add_expense(1_500, category, at=yesterday)
        assert expense.at.date() == yesterday.date()
        with pytest.raises(CashError):
            cash.add_expense(1_000, category, at=datetime.now() + timedelta(days=2))

    def test_categorie_inconnue_refusee(self, admin, cash):
        with pytest.raises(CashError):
            cash.add_expense(1_000, 9_999)

    def test_montant_invalide(self, admin, cash):
        category = cash.list_expense_categories()[0].id
        with pytest.raises(CashError):
            cash.add_expense(0, category)

    def test_annulation_tracee_et_caisse_reintegree(self, admin, cash):
        cash_session = cash.open_session(opening_fund=10_000)
        expense = cash.add_expense(2_500, cash.list_expense_categories()[0].id)
        assert cash.theoretical_amount(cash_session.id) == 7_500
        with pytest.raises(CashError):
            cash.cancel_expense(expense.id, "  ")
        cash.cancel_expense(expense.id, "Double saisie")
        assert cash.theoretical_amount(cash_session.id) == 10_000
        cancelled = [item for item in cash.list_expenses()
                     if item.id == expense.id][0]
        assert cancelled.cancelled_at is not None
        assert cancelled.cancel_reason == "Double saisie"
        with pytest.raises(CashError):
            cash.cancel_expense(expense.id, "Deuxième fois")
        # la dépense annulée sort des totaux
        start = datetime.now() - timedelta(days=1)
        assert cash.expenses_total(start, datetime.now() + timedelta(days=1)) == 0

    def test_repartition_par_categorie(self, admin, cash):
        categories = cash.list_expense_categories()
        cash.add_expense(1_000, categories[0].id)
        cash.add_expense(3_000, categories[1].id)
        breakdown = dict(cash.expenses_by_category())
        assert breakdown[categories[1].name] == 3_000
        assert breakdown[categories[0].name] == 1_000

    def test_categorie_utilisee_non_supprimable(self, admin, cash):
        category = cash.list_expense_categories()[0]
        cash.add_expense(500, category.id)
        with pytest.raises(CashError):
            cash.delete_expense_category(category.id)
        other = cash.create_expense_category("Embouteillage")
        cash.delete_expense_category(other.id)
        assert "Embouteillage" not in [c.name for c in cash.list_expense_categories()]


class TestCorrectionSessionCloturee:
    def test_correction_recalcule_ecart_et_audit(self, admin, cash):
        cash_session = cash.open_session(opening_fund=5_000)
        closed = cash.close_session(cash_session.id, 4_600, "Erreur de comptage")
        assert closed.difference == -400
        movement = cash.correct_closed_session(
            closed.id, 400, "in", "Billet retrouvé",
            comment="Billet de 400 dans le tiroir")
        assert movement.corrects_session_id == closed.id
        assert movement.correction_reason == "Billet retrouvé"
        refreshed = cash.get_session(closed.id)
        assert refreshed.counted_amount == 5_000
        assert refreshed.difference == 0
        with session_scope() as session:
            actions = [log.action for log in session.scalars(select(AuditLog)).all()]
            stored = session.get(CashMovement, movement.id)
            assert stored.correction_reason == "Billet retrouvé"
        assert "cash_session_correct" in actions
        assert [m.id for m in cash.corrections(closed.id)] == [movement.id]

    def test_correction_sur_session_ouverte_refusee(self, admin, cash):
        cash_session = cash.open_session(opening_fund=1_000)
        with pytest.raises(CashError):
            cash.correct_closed_session(cash_session.id, 100, "in", "Test")

    def test_correction_exige_motif_et_permission(self, admin, cash):
        cash_session = cash.open_session(opening_fund=1_000)
        cash.close_session(cash_session.id, 1_000)
        with pytest.raises(CashError):
            cash.correct_closed_session(cash_session.id, 100, "in", "   ")
        with pytest.raises(CashError):
            cash.correct_closed_session(cash_session.id, 0, "in", "Motif")

    def test_comptage_corrige_negatif_refuse(self, admin, cash):
        cash_session = cash.open_session(opening_fund=1_000)
        closed = cash.close_session(cash_session.id, 500)
        with pytest.raises(CashError):
            cash.correct_closed_session(closed.id, 900, "out", "Trop de sortie")

    def test_correction_par_nouveau_comptage(self, admin, cash):
        cash_session = cash.open_session(opening_fund=2_000)
        closed = cash.close_session(cash_session.id, 1_800)
        cash.correct_closed_session(closed.id, 200, "in", "Recount",
                                    new_counted_amount=2_000)
        assert cash.get_session(closed.id).difference == 0
