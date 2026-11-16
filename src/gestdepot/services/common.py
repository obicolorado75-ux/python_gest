"""Utilitaires partagés par les services métier."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database.models import CashSession, StockBalance
from ..security import auth


def current_user_id() -> int | None:
    cur = auth.Session.current()
    return cur.user.id if cur else None


def has_permission(code: str) -> bool:
    """Vrai si l'utilisateur connecté possède la permission.

    Sans session ouverte (script, test unitaire, tâche de maintenance), la
    vérification est permissive : la couche UI impose toujours une connexion.
    """
    cur = auth.Session.current()
    if cur is None:
        return True
    return cur.has_permission(code)


def require(code: str) -> None:
    """Lève PermissionError si la permission manque (§3 : contrôlée côté métier)."""
    cur = auth.Session.current()
    if cur is None:
        return
    cur.require(code)


def get_balance(session: Session, product_id: int) -> StockBalance:
    bal = session.get(StockBalance, product_id)
    if bal is None:
        bal = StockBalance(product_id=product_id, quantity=0,
                           reserved_quantity=0, weighted_avg_cost=0)
        session.add(bal)
        session.flush()
    return bal


def available_quantity(session: Session, product_id: int) -> int:
    bal = session.get(StockBalance, product_id)
    if bal is None:
        return 0
    return bal.quantity - bal.reserved_quantity


def open_cash_session(session: Session, user_id: int | None) -> CashSession | None:
    """Session de caisse ouverte de l'utilisateur, dans la transaction courante."""
    if user_id is None:
        return None
    return session.scalar(select(CashSession).where(
        CashSession.status == "open", CashSession.user_id == user_id))
