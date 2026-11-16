"""Service caisse : sessions, mouvements, dépenses, clôture (§5.12)."""
from sqlalchemy import func, select

from ..database.models import CashMovement, CashSession, Expense, ExpenseCategory
from ..database.session import next_document_number, session_scope
from ..security import auth
from .sales_service import PAYMENT_METHODS, SalesError


class CashError(Exception):
    pass


class CashService:
    def open_session(self, opening_fund: int = 0) -> CashSession:
        cur = auth.Session.current()
        cur.require("cash.open")
        with session_scope() as s:
            existing = s.scalar(select(CashSession).where(
                CashSession.status == "open", CashSession.user_id == cur.user.id))
            if existing:
                raise CashError("Une session de caisse est déjà ouverte.")
            sess = CashSession(user_id=cur.user.id, opening_fund=opening_fund)
            s.add(sess)
            s.flush()
            auth.log("cash_open", "CashSession", sess.id, new_value=str(opening_fund), session=s)
            return sess

    def current_session(self) -> CashSession | None:
        cur = auth.Session.current()
        if not cur:
            return None
        with session_scope() as s:
            return s.scalar(select(CashSession).where(
                CashSession.status == "open", CashSession.user_id == cur.user.id))

    def theoretical_amount(self, session_id: int) -> int:
        """Solde théorique espèces = fond + entrées - sorties (espèces uniquement)."""
        with session_scope() as s:
            sess = s.get(CashSession, session_id)
            total = sess.opening_fund
            for mv in s.scalars(select(CashMovement).where(
                    CashMovement.session_id == session_id)):
                if mv.payment_method != "especes":
                    continue  # Mobile Money etc. suivis séparément (§5.12, T11)
                total += mv.amount if mv.direction == "in" else -mv.amount
            return total

    def close_session(self, session_id: int, counted_amount: int,
                      comment: str | None = None) -> CashSession:
        """Clôture : écart conservé et audité (T12)."""
        cur = auth.Session.current()
        cur.require("cash.close")
        with session_scope() as s:
            sess = s.get(CashSession, session_id)
            if sess.status != "open":
                raise CashError("Session déjà clôturée.")
            theo = self.theoretical_amount(session_id)
            sess.theoretical_amount = theo
            sess.counted_amount = counted_amount
            sess.difference = counted_amount - theo
            sess.close_comment = comment
            sess.status = "closed"
            sess.closed_at = func.now()
            auth.log("cash_close", "CashSession", session_id,
                     new_value=f"theo={theo};counted={counted_amount};diff={sess.difference}",
                     comment=comment, session=s)
            return sess

    def add_expense(self, amount: int, category_id: int | None, payment_method="especes",
                    beneficiary=None, comment=None, receipt_path=None) -> Expense:
        cur = auth.Session.current()
        if amount <= 0:
            raise CashError("Montant de dépense invalide.")
        with session_scope() as s:
            number = next_document_number(s, "DEP")
            sess = self.current_session()
            exp = Expense(number=number, category_id=category_id, amount=amount,
                          payment_method=payment_method, beneficiary=beneficiary,
                          comment=comment, receipt_path=receipt_path,
                          session_id=sess.id if sess else None,
                          user_id=cur.user.id if cur else None)
            s.add(exp)
            s.flush()
            if sess and payment_method == "especes":
                s.add(CashMovement(session_id=sess.id, direction="out", amount=amount,
                                   payment_method="especes", reason="depense",
                                   document_type="expense", document_id=exp.id,
                                   user_id=cur.user.id if cur else None))
            auth.log("expense_create", "Expense", exp.id,
                     new_value=f"{number}={amount}", session=s)
            return exp

    def list_expenses(self):
        with session_scope() as s:
            return list(s.scalars(select(Expense).order_by(Expense.at.desc()).limit(200)))

    def movements(self, session_id: int):
        with session_scope() as s:
            return list(s.scalars(select(CashMovement).where(
                CashMovement.session_id == session_id).order_by(CashMovement.at)))
