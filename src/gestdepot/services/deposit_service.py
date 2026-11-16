"""Service consignes/emballages (§5.8)."""
from sqlalchemy import func, select

from ..database.models import DepositMovement, ReturnablePackaging
from ..database.session import session_scope
from ..security import auth


class DepositError(Exception):
    pass


class DepositService:
    def create_packaging(self, code: str, label: str, deposit_value: int,
                         capacity=None) -> ReturnablePackaging:
        if deposit_value < 0:
            raise DepositError("Consigne négative.")
        with session_scope() as s:
            rp = ReturnablePackaging(code=code, label=label, deposit_value=deposit_value,
                                     capacity=capacity)
            s.add(rp)
            s.flush()
            auth.log("packaging_type_create", "ReturnablePackaging", rp.id, new_value=label, session=s
            return rp

    def list_packagings(self):
        with session_scope() as s:
            return list(s.scalars(select(ReturnablePackaging).where(
                ReturnablePackaging.active == True)))  # noqa: E712

    def move(self, packaging_id: int, quantity: int, reason: str,
             customer_id=None, supplier_id=None, document_type=None, document_id=None):
        """Quantité positive = remise/entrée, négative = retour/sortie.
        Retours partiels autorisés (§5.8, T08)."""
        cur = auth.Session.current()
        with session_scope() as s:
            rp = s.get(ReturnablePackaging, packaging_id)
            s.add(DepositMovement(packaging_id=packaging_id, quantity=quantity,
                                  reason=reason, customer_id=customer_id,
                                  supplier_id=supplier_id, document_type=document_type,
                                  document_id=document_id, deposit_value=rp.deposit_value,
                                  user_id=cur.user.id if cur else None))
            auth.log("deposit_move", "ReturnablePackaging", packaging_id,
                     new_value=f"{reason}:{quantity}", session=s

    def customer_balance(self, customer_id: int, packaging_id: int | None = None):
        """Solde en quantité (due) par type d'emballage (§6.4, T08)."""
        with session_scope() as s:
            q = select(DepositMovement.packaging_id, func.sum(DepositMovement.quantity)) \
                .where(DepositMovement.customer_id == customer_id) \
                .group_by(DepositMovement.packaging_id)
            if packaging_id:
                q = q.where(DepositMovement.packaging_id == packaging_id)
            return dict(s.execute(q).all())

    def movements(self, customer_id=None, limit=200):
        with session_scope() as s:
            q = select(DepositMovement).order_by(DepositMovement.at.desc()).limit(limit)
            if customer_id:
                q = q.where(DepositMovement.customer_id == customer_id)
            return list(s.scalars(q))
