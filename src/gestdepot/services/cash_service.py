"""Service caisse : sessions, mouvements, dépenses, clôture (§5.12)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from ..database.models import CashMovement, CashSession, Expense, ExpenseCategory
from ..database.session import next_document_number, session_scope
from ..security import auth
from . import common
from .payment_methods import codes as payment_codes

# motifs de mouvement de caisse admis (§5.12) : les motifs métier sont créés par
# les services concernés, la saisie manuelle se limite à ces trois-là
MANUAL_REASONS = {"retrait", "apport", "correction"}


class CashError(Exception):
    pass


class CashService:
    # --- session de caisse --------------------------------------------------
    def open_session(self, opening_fund: int = 0, user_id: int | None = None) -> CashSession:
        common.require("cash.open")
        if opening_fund < 0:
            raise CashError("Le fond de caisse ne peut pas être négatif.")
        user_id = user_id or common.current_user_id()
        if user_id is None:
            raise CashError("Aucun utilisateur connecté.")
        with session_scope() as s:
            existing = s.scalar(select(CashSession).where(
                CashSession.status == "open", CashSession.user_id == user_id))
            if existing:
                raise CashError("Une session de caisse est déjà ouverte.")
            cash_session = CashSession(user_id=user_id, opening_fund=opening_fund)
            s.add(cash_session)
            s.flush()
            auth.log("cash_open", "CashSession", cash_session.id,
                     new_value=str(opening_fund), session=s)
            return cash_session

    def current_session(self) -> CashSession | None:
        user_id = common.current_user_id()
        if user_id is None:
            return None
        with session_scope() as s:
            return common.open_cash_session(s, user_id)

    def get_session(self, session_id: int) -> CashSession:
        with session_scope() as s:
            cash_session = s.get(CashSession, session_id)
            if cash_session is None:
                raise CashError("Session de caisse introuvable.")
            return cash_session

    def theoretical_amount(self, session_id: int) -> int:
        """Solde théorique espèces = fond + entrées - sorties (espèces seulement).

        Les encaissements Mobile Money, virements et chèques sont suivis
        séparément et n'entrent pas dans le solde physique (§5.12, T11).
        """
        with session_scope() as s:
            cash_session = s.get(CashSession, session_id)
            if cash_session is None:
                raise CashError("Session de caisse introuvable.")
            total = cash_session.opening_fund
            for mv in s.scalars(select(CashMovement).where(
                    CashMovement.session_id == session_id)):
                if mv.payment_method != "especes":
                    continue
                total += mv.amount if mv.direction == "in" else -mv.amount
            return total

    def movements_by_method(self, session_id: int) -> dict[str, int]:
        """Totaux par moyen de paiement (espèces et non espèces séparés)."""
        totals: dict[str, int] = {}
        with session_scope() as s:
            for method, direction, amount in s.execute(
                    select(CashMovement.payment_method, CashMovement.direction,
                           CashMovement.amount)
                    .where(CashMovement.session_id == session_id)).all():
                sign = 1 if direction == "in" else -1
                totals[method] = totals.get(method, 0) + sign * amount
        return totals

    def close_session(self, session_id: int, counted_amount: int,
                      comment: str | None = None) -> CashSession:
        """Clôture : écart conservé, commenté et audité (T12)."""
        common.require("cash.close")
        if counted_amount < 0:
            raise CashError("Le montant compté ne peut pas être négatif.")
        with session_scope() as s:
            cash_session = s.get(CashSession, session_id)
            if cash_session is None:
                raise CashError("Session de caisse introuvable.")
            if cash_session.status != "open":
                raise CashError("Session déjà clôturée.")
            theo = self.theoretical_amount(session_id)
            cash_session.theoretical_amount = theo
            cash_session.counted_amount = counted_amount
            cash_session.difference = counted_amount - theo
            cash_session.close_comment = comment
            cash_session.status = "closed"
            cash_session.closed_at = datetime.now()
            auth.log("cash_close", "CashSession", session_id,
                     new_value=f"theo={theo};counted={counted_amount};"
                               f"diff={cash_session.difference}",
                     comment=comment, session=s)
            return cash_session

    def list_sessions(self, limit: int = 50):
        with session_scope() as s:
            return list(s.scalars(select(CashSession)
                                  .order_by(CashSession.opened_at.desc())
                                  .limit(limit)))

    def movements(self, session_id: int):
        with session_scope() as s:
            return list(s.scalars(select(CashMovement).where(
                CashMovement.session_id == session_id)
                .order_by(CashMovement.at, CashMovement.id)))

    def register_movement(self, direction: str, amount: int, reason: str,
                          payment_method: str = "especes",
                          comment: str | None = None) -> CashMovement:
        """Retrait, apport ou correction autorisée (§5.12)."""
        common.require("cash.open")
        if direction not in ("in", "out"):
            raise CashError("Sens de mouvement invalide.")
        if amount <= 0:
            raise CashError("Montant de mouvement invalide.")
        if payment_method not in payment_codes():
            raise CashError("Moyen de paiement inconnu.")
        if reason not in ("retrait", "apport", "correction"):
            raise CashError(
                "Seuls un retrait, un apport ou une correction se saisissent "
                "directement : les autres mouvements proviennent des ventes, "
                "règlements, dépenses et achats.")
        if reason == "correction":
            common.require("cash.correction")
            if not (comment or "").strip():
                raise CashError("Une correction de caisse exige un motif.")
        else:
            common.require("cash.open")
        with session_scope() as s:
            cash_session = common.open_cash_session(s, common.current_user_id())
            if cash_session is None:
                raise CashError("Aucune session de caisse ouverte.")
            mv = CashMovement(session_id=cash_session.id, direction=direction,
                              amount=amount, payment_method=payment_method,
                              reason=reason, comment=comment,
                              user_id=common.current_user_id())
            s.add(mv)
            s.flush()
            auth.log("cash_movement", "CashMovement", mv.id,
                     new_value=f"{direction}:{amount}:{reason}", session=s)
            return mv

    # --- correction d'une session clôturée (§5.12) ---------------------------
    def correct_closed_session(self, session_id: int, amount: int, direction: str,
                               reason: str, comment: str | None = None,
                               new_counted_amount: int | None = None) -> CashMovement:
        """Seule procédure autorisée pour modifier une caisse clôturée.

        Le mouvement de correction est horodaté, rattaché à la session corrigée
        (`corrects_session_id`) et audité ; le montant compté et l'écart de la
        session sont recalculés sans effacer l'historique de la clôture
        (l'ancien écart reste dans le journal d'audit).
        """
        common.require("cash.correction")
        if amount <= 0:
            raise CashError("Montant de correction invalide.")
        if direction not in ("in", "out"):
            raise CashError("Sens de correction invalide.")
        if not (reason or "").strip():
            raise CashError("Le motif de correction est obligatoire.")
        user_id = common.current_user_id()
        with session_scope() as s:
            target = s.get(CashSession, session_id)
            if target is None:
                raise CashError("Session de caisse introuvable.")
            if target.status == "open":
                raise CashError("Cette session est encore ouverte : saisissez "
                                "plutôt un mouvement de caisse.")
            before = (f"theo={target.theoretical_amount};"
                      f"counted={target.counted_amount};diff={target.difference}")
            movement = CashMovement(
                session_id=session_id, direction=direction, amount=amount,
                payment_method="especes", reason="correction",
                document_type="cash_session", document_id=session_id,
                comment=f"{reason}" + (f" — {comment}" if comment else ""),
                user_id=user_id, corrects_session_id=session_id,
                corrected_at=datetime.now(), correction_reason=reason)
            s.add(movement)
            # nouveau comptage : soit fourni, soit déduit du sens de la correction
            counted = (new_counted_amount if new_counted_amount is not None
                       else int(target.counted_amount or 0)
                       + (amount if direction == "in" else -amount))
            if counted < 0:
                raise CashError("Le montant compté corrigé ne peut pas être négatif.")
            target.counted_amount = counted
            target.theoretical_amount = self.theoretical_amount(session_id)
            target.difference = counted - int(target.theoretical_amount or 0)
            auth.log("cash_session_correct", "CashSession", session_id,
                     old_value=before,
                     new_value=(f"theo={target.theoretical_amount};"
                                f"counted={target.counted_amount};"
                                f"diff={target.difference}"),
                     comment=f"{reason} ({direction} {amount})", session=s)
            return movement

    def corrections(self, session_id: int | None = None):
        """Historique des corrections de caisse (§5.12)."""
        with session_scope() as s:
            q = (select(CashMovement)
                 .where(CashMovement.corrects_session_id.is_not(None))
                 .order_by(CashMovement.at.desc(), CashMovement.id.desc()))
            if session_id:
                q = q.where(CashMovement.corrects_session_id == session_id)
            return list(s.scalars(q))

    # --- dépenses -------------------------------------------------------------
    def add_expense(self, amount: int, category_id: int | None,
                    payment_method: str = "especes", beneficiary=None,
                    comment=None, receipt_path=None,
                    at: datetime | None = None) -> Expense:
        """Dépense : solde théorique de caisse diminué si espèces (T10)."""
        common.require("expenses.create")
        if amount <= 0:
            raise CashError("Montant de dépense invalide.")
        if payment_method not in payment_codes():
            raise CashError("Moyen de paiement inconnu.")
        user_id = common.current_user_id()
        with session_scope() as s:
            if category_id is not None and s.get(ExpenseCategory, category_id) is None:
                raise CashError("Catégorie de dépense introuvable.")
            if at is not None and at > datetime.now():
                raise CashError("Une dépense ne peut pas être datée dans le futur.")
            number = next_document_number(s, "DEP")
            cash_session = common.open_cash_session(s, user_id)
            expense = Expense(number=number, category_id=category_id, amount=amount,
                              **( {"at": at} if at is not None else {} ),
                              payment_method=payment_method, beneficiary=beneficiary,
                              comment=comment, receipt_path=receipt_path,
                              session_id=cash_session.id if cash_session else None,
                              user_id=user_id)
            s.add(expense)
            s.flush()
            if cash_session is not None:
                s.add(CashMovement(session_id=cash_session.id, direction="out",
                                   amount=amount, payment_method=payment_method,
                                   reason="depense", document_type="expense",
                                   document_id=expense.id, user_id=user_id))
            auth.log("expense_create", "Expense", expense.id,
                     new_value=f"{number}={amount}", session=s)
            return expense

    def cancel_expense(self, expense_id: int, reason: str) -> None:
        """Annule une dépense par contre-mouvement tracé, jamais par suppression.

        La dépense reste consultable ; le montant est réintégré à la caisse
        ouverte (espèces uniquement, §5.12) et l'opération est auditée.
        """
        common.require("expenses.create")
        if not (reason or "").strip():
            raise CashError("Le motif d'annulation est obligatoire.")
        user_id = common.current_user_id()
        with session_scope() as s:
            expense = s.get(Expense, expense_id)
            if expense is None:
                raise CashError("Dépense introuvable.")
            if expense.cancelled_at is not None:
                raise CashError("Dépense déjà annulée.")
            expense.cancelled_at = datetime.now()
            expense.cancel_reason = reason
            cash_session = common.open_cash_session(s, user_id)
            if cash_session is not None:
                s.add(CashMovement(session_id=cash_session.id, direction="in",
                                   amount=expense.amount,
                                   payment_method=expense.payment_method,
                                   reason="correction", document_type="expense",
                                   document_id=expense.id,
                                   comment=f"Annulation {expense.number} : {reason}",
                                   user_id=user_id))
            auth.log("expense_cancel", "Expense", expense.id,
                     new_value=expense.number, comment=reason, session=s)

    def expenses_by_category(self, start=None, end=None):
        """Répartition des dépenses par catégorie (§5.14, rapports)."""
        with session_scope() as s:
            q = (select(ExpenseCategory.name,
                        func.coalesce(func.sum(Expense.amount), 0))
                 .join(Expense, Expense.category_id == ExpenseCategory.id)
                 .where(Expense.cancelled_at.is_(None))
                 .group_by(ExpenseCategory.name)
                 .order_by(func.coalesce(func.sum(Expense.amount), 0).desc()))
            if start is not None:
                q = q.where(Expense.at >= start)
            if end is not None:
                q = q.where(Expense.at <= end)
            return [(name, int(total)) for name, total in s.execute(q).all()]

    def list_expenses(self, limit: int = 200, start=None, end=None):
        with session_scope() as s:
            q = select(Expense).order_by(Expense.at.desc()).limit(limit)
            if start is not None:
                q = q.where(Expense.at >= start)
            if end is not None:
                q = q.where(Expense.at <= end)
            return list(s.scalars(q))

    def expenses_total(self, start, end) -> int:
        with session_scope() as s:
            return int(s.scalar(select(func.coalesce(func.sum(Expense.amount), 0))
                                .where(Expense.at >= start, Expense.at <= end,
                                       Expense.cancelled_at.is_(None))) or 0)

    def list_expense_categories(self):
        with session_scope() as s:
            return list(s.scalars(select(ExpenseCategory).order_by(
                ExpenseCategory.name)))

    def delete_expense_category(self, category_id: int) -> None:
        """Désactive impossible : une catégorie utilisée ne doit pas disparaître."""
        common.require("settings.manage")
        with session_scope() as s:
            category = s.get(ExpenseCategory, category_id)
            if category is None:
                raise CashError("Catégorie introuvable.")
            used = s.scalar(select(func.count(Expense.id))
                            .where(Expense.category_id == category_id))
            if used:
                raise CashError(
                    f"Catégorie utilisée par {used} dépense(s) : elle ne peut pas "
                    "être supprimée.")
            auth.log("expense_category_delete", "ExpenseCategory", category_id,
                     old_value=category.name, session=s)
            s.delete(category)

    def create_expense_category(self, name: str) -> ExpenseCategory:
        common.require("settings.manage")
        with session_scope() as s:
            name = (name or "").strip()
            if not name:
                raise CashError("Nom de catégorie obligatoire.")
            if s.scalar(select(ExpenseCategory).where(ExpenseCategory.name == name)):
                raise CashError(f"La catégorie {name} existe déjà.")
            cat = ExpenseCategory(name=name)
            s.add(cat)
            s.flush()
            return cat
