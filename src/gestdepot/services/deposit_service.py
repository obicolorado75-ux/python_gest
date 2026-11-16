"""Service consignes/emballages (§5.8)."""
from __future__ import annotations

from sqlalchemy import func, select

from ..database.models import DepositMovement, ReturnablePackaging
from ..database.session import session_scope
from ..security import auth
from . import common

# Motifs : sens positif = l'emballage est chez le client / reçu du fournisseur
DEPOSIT_REASONS = {
    "remis_client", "retourne_client", "recu_fournisseur", "rendu_fournisseur",
    "casse", "ajuste",
}


class DepositError(Exception):
    pass


class DepositService:
    def create_packaging(self, code: str, label: str, deposit_value: int,
                         capacity=None, supplier_id=None) -> ReturnablePackaging:
        common.require("settings.manage")
        code = (code or "").strip()
        label = (label or "").strip()
        if not code or not label:
            raise DepositError("Code et libellé de l'emballage obligatoires.")
        if deposit_value < 0:
            raise DepositError("Consigne négative.")
        with session_scope() as s:
            if s.scalar(select(ReturnablePackaging.id).where(
                    ReturnablePackaging.code == code)):
                raise DepositError(f"Le code emballage {code} existe déjà.")
            rp = ReturnablePackaging(code=code, label=label,
                                     deposit_value=deposit_value, capacity=capacity,
                                     supplier_id=supplier_id)
            s.add(rp)
            s.flush()
            auth.log("packaging_type_create", "ReturnablePackaging", rp.id,
                     new_value=f"{code}={deposit_value}", session=s)
            return rp

    def list_packagings(self):
        with session_scope() as s:
            return list(s.scalars(select(ReturnablePackaging).where(
                ReturnablePackaging.active.is_(True)).order_by(
                    ReturnablePackaging.label)))

    def get_packaging(self, packaging_id: int) -> ReturnablePackaging:
        with session_scope() as s:
            rp = s.get(ReturnablePackaging, packaging_id)
            if rp is None:
                raise DepositError("Type d'emballage introuvable.")
            return rp

    def move(self, packaging_id: int, quantity: int, reason: str,
             customer_id=None, supplier_id=None, document_type=None,
             document_id=None, comment=None) -> int:
        """Quantité positive = remise/entrée, négative = retour/sortie.

        Les retours partiels sont autorisés (§5.8, T08).
        """
        if reason not in DEPOSIT_REASONS:
            raise DepositError(f"Motif de consigne inconnu : {reason}")
        if quantity == 0:
            raise DepositError("Quantité de consigne nulle.")
        if reason.startswith("remis") or reason.startswith("retourne"):
            if customer_id is None:
                raise DepositError("Un client est nécessaire pour ce mouvement.")
        if reason.startswith("recu") or reason.startswith("rendu"):
            if supplier_id is None:
                raise DepositError("Un fournisseur est nécessaire pour ce mouvement.")
        with session_scope() as s:
            rp = s.get(ReturnablePackaging, packaging_id)
            if rp is None:
                raise DepositError("Type d'emballage introuvable.")
            if customer_id is not None and quantity < 0:
                owed = self._customer_qty(s, customer_id, packaging_id)
                if owed + quantity < 0:
                    raise DepositError(
                        f"Retour supérieur au solde consigné du client "
                        f"({owed} {rp.label}).")
            mv = DepositMovement(packaging_id=packaging_id, quantity=quantity,
                                 reason=reason, customer_id=customer_id,
                                 supplier_id=supplier_id,
                                 document_type=document_type,
                                 document_id=document_id,
                                 deposit_value=rp.deposit_value,
                                 comment=comment,
                                 user_id=common.current_user_id())
            s.add(mv)
            s.flush()
            auth.log("deposit_move", "ReturnablePackaging", packaging_id,
                     new_value=f"{reason}:{quantity}", session=s)
            return mv.id

    def _customer_qty(self, s, customer_id: int, packaging_id: int | None = None) -> int:
        q = select(func.coalesce(func.sum(DepositMovement.quantity), 0)).where(
            DepositMovement.customer_id == customer_id)
        if packaging_id:
            q = q.where(DepositMovement.packaging_id == packaging_id)
        return int(s.scalar(q) or 0)

    def customer_balance(self, customer_id: int, packaging_id: int | None = None):
        """Solde en quantité (due par le client) par type d'emballage (§6.4, T08)."""
        with session_scope() as s:
            q = (select(DepositMovement.packaging_id,
                        func.coalesce(func.sum(DepositMovement.quantity), 0))
                 .where(DepositMovement.customer_id == customer_id)
                 .group_by(DepositMovement.packaging_id))
            if packaging_id:
                q = q.where(DepositMovement.packaging_id == packaging_id)
            return {pid: int(qty) for pid, qty in s.execute(q).all()}

    def customer_balance_value(self, customer_id: int) -> int:
        """Valeur des emballages consignés détenus par le client."""
        total = 0
        with session_scope() as s:
            for pid, qty in self.customer_balance(customer_id).items():
                rp = s.get(ReturnablePackaging, pid)
                if rp and qty:
                    total += qty * rp.deposit_value
        return total

    def supplier_balance(self, supplier_id: int):
        with session_scope() as s:
            q = (select(DepositMovement.packaging_id,
                        func.coalesce(func.sum(DepositMovement.quantity), 0))
                 .where(DepositMovement.supplier_id == supplier_id)
                 .group_by(DepositMovement.packaging_id))
            return {pid: int(qty) for pid, qty in s.execute(q).all()}

    def movements(self, customer_id=None, supplier_id=None, limit=200):
        with session_scope() as s:
            q = (select(DepositMovement)
                 .order_by(DepositMovement.at.desc(), DepositMovement.id.desc())
                 .limit(limit))
            if customer_id:
                q = q.where(DepositMovement.customer_id == customer_id)
            if supplier_id:
                q = q.where(DepositMovement.supplier_id == supplier_id)
            return list(s.scalars(q))
