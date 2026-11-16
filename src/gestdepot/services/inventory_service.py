"""Service inventaires physiques (§5.13) : théorique, compté, écart, régularisation."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ..database.models import InventoryLine, InventorySession, Product, StockBalance
from ..database.session import next_document_number, session_scope
from ..security import auth
from . import common


class InventoryError(Exception):
    pass


class InventoryService:
    def start_session(self, product_ids: list[int] | None = None,
                      comment: str | None = None,
                      threshold_value: int = 0) -> InventorySession:
        """Crée une session d'inventaire et fige le stock théorique au démarrage.

        Global si ``product_ids`` est vide, ciblé sinon (§5.13 étapes 1-3).
        ``threshold_value`` : au-delà de cet écart de valeur, un contrôle est
        exigé avant validation (étape 6).
        """
        common.require("inventory.manage")
        if threshold_value < 0:
            raise InventoryError("Seuil de contrôle négatif.")
        with session_scope() as s:
            number = next_document_number(s, "INV")
            session = InventorySession(number=number, status="draft",
                                       user_id=common.current_user_id(),
                                       comment=comment,
                                       threshold_value=threshold_value)
            s.add(session)
            s.flush()
            query = select(Product).where(Product.archived.is_(False))
            if product_ids:
                query = query.where(Product.id.in_(product_ids))
            counted = 0
            for product in s.scalars(query.order_by(Product.name)):
                bal = s.get(StockBalance, product.id)
                cost = (bal.weighted_avg_cost if bal else 0) or product.current_cost
                s.add(InventoryLine(session_id=session.id, product_id=product.id,
                                    theoretical_qty=bal.quantity if bal else 0,
                                    counted_qty=bal.quantity if bal else 0,
                                    cost=cost))
                counted += 1
            if not counted:
                raise InventoryError("Aucun produit à inventorier.")
            auth.log("inventory_start", "InventorySession", session.id,
                     new_value=number, session=s)
            return session

    def get_session(self, session_id: int) -> InventorySession:
        with session_scope() as s:
            session = s.get(InventorySession, session_id)
            if session is None:
                raise InventoryError("Session d'inventaire introuvable.")
            return session

    def lines(self, session_id: int):
        with session_scope() as s:
            return list(s.scalars(select(InventoryLine).where(
                InventoryLine.session_id == session_id).order_by(
                    InventoryLine.product_id)))

    def set_counted(self, session_id: int, product_id: int,
                    counted_qty: int) -> None:
        common.require("inventory.manage")
        if counted_qty < 0:
            raise InventoryError("La quantité comptée ne peut pas être négative.")
        with session_scope() as s:
            session = s.get(InventorySession, session_id)
            if session is None:
                raise InventoryError("Session d'inventaire introuvable.")
            if session.status not in ("draft", "counting", "reviewed"):
                raise InventoryError(
                    "Inventaire validé : seule une nouvelle régularisation "
                    "(nouvel inventaire) peut corriger les quantités.")
            line = s.scalar(select(InventoryLine).where(
                InventoryLine.session_id == session_id,
                InventoryLine.product_id == product_id))
            if line is None:
                raise InventoryError("Produit absent de cet inventaire.")
            if line.counted_qty != counted_qty:
                line.counted_at = datetime.now()
                line.reviewed = False   # tout recomptage invalide le contrôle
            line.counted_qty = counted_qty
            if session.status == "draft":
                session.status = "counting"

    def check_control(self, session_id: int) -> dict:
        """Quelles lignes exigent un contrôle (§5.13 étape 6) ?

        Un écart de valeur dépasse le seuil de la session, ou la quantité varie
        sans motif : la ligne doit être revue (`review_gap`) avant validation.
        """
        with session_scope() as s:
            session = s.get(InventorySession, session_id)
            if session is None:
                raise InventoryError("Session d'inventaire introuvable.")
            lines = list(s.scalars(select(InventoryLine).where(
                InventoryLine.session_id == session_id)))
            pending = []
            for line in lines:
                gap_qty = line.counted_qty - line.theoretical_qty
                if not gap_qty:
                    continue
                gap_value = gap_qty * line.cost
                if line.reviewed:
                    continue
                if (session.threshold_value
                        and abs(gap_value) >= session.threshold_value):
                    pending.append({"product_id": line.product_id,
                                    "gap": gap_qty, "value": gap_value,
                                    "reason": "seuil"})
            return {"threshold": session.threshold_value,
                    "pending": pending, "count": len(pending)}

    def review_gap(self, session_id: int, product_id: int,
                   comment: str) -> None:
        """Enregistre le contrôle d'un écart important (§5.13 étape 6)."""
        common.require("inventory.manage")
        if not (comment or "").strip():
            raise InventoryError("Le commentaire de contrôle est obligatoire.")
        with session_scope() as s:
            session = s.get(InventorySession, session_id)
            if session is None:
                raise InventoryError("Session d'inventaire introuvable.")
            if session.status == "validated":
                raise InventoryError("Inventaire déjà validé.")
            line = s.scalar(select(InventoryLine).where(
                InventoryLine.session_id == session_id,
                InventoryLine.product_id == product_id))
            if line is None:
                raise InventoryError("Produit absent de cet inventaire.")
            line.reviewed = True
            line.review_comment = comment
            if session.status in ("draft", "counting"):
                session.status = "reviewed"
            auth.log("inventory_gap_review", "InventoryLine", line.id,
                     new_value=f"{line.counted_qty - line.theoretical_qty}",
                     comment=comment, session=s)

    def cancel_session(self, session_id: int, reason: str) -> None:
        """Abandon d'un inventaire non validé : tracé, jamais supprimé (§4.6)."""
        common.require("inventory.manage")
        if not (reason or "").strip():
            raise InventoryError("Le motif d'abandon est obligatoire.")
        with session_scope() as s:
            session = s.get(InventorySession, session_id)
            if session is None:
                raise InventoryError("Session d'inventaire introuvable.")
            if session.status == "validated":
                raise InventoryError("Un inventaire validé ne peut pas être annulé.")
            session.status = "cancelled"
            auth.log("inventory_cancel", "InventorySession", session_id,
                     new_value=session.number, comment=reason, session=s)

    def summary(self, session_id: int) -> dict:
        with session_scope() as s:
            lines = list(s.scalars(select(InventoryLine).where(
                InventoryLine.session_id == session_id)))
            gaps = [l for l in lines if l.counted_qty != l.theoretical_qty]
            return {
                "lines": len(lines),
                "gaps": len(gaps),
                "gap_quantity": sum(l.counted_qty - l.theoretical_qty for l in lines),
                "gap_value": sum((l.counted_qty - l.theoretical_qty) * l.cost
                                 for l in lines),
                "total_value": sum(l.counted_qty * l.cost for l in lines),
            }

    def validate(self, session_id: int) -> dict:
        """Validation : génère les mouvements de régularisation tracés (§5.13, T13).

        Non destructif : l'inventaire conserve théorique, compté, écart et coût.
        """
        common.require("inventory.manage")
        with session_scope() as s:
            session = s.get(InventorySession, session_id)
            if session is None:
                raise InventoryError("Session d'inventaire introuvable.")
            if session.status == "validated":
                raise InventoryError("Inventaire déjà validé.")
            if session.status == "cancelled":
                raise InventoryError("Inventaire annulé : validation impossible.")
            control = self.check_control(session_id)
            if control["pending"]:
                raise InventoryError(
                    f"{control['count']} écart(s) important(s) doivent être "
                    "contrôlés (seuil "
                    f"{control['threshold']} FCFA) avant validation.")
            from .stock_service import StockService
            stock = StockService()
            adjusted = 0
            for line in s.scalars(select(InventoryLine).where(
                    InventoryLine.session_id == session_id)):
                gap = line.counted_qty - line.theoretical_qty
                if gap == 0:
                    continue
                stock._apply(s, line.product_id, gap, "correction_inventaire",
                             document_type="inventory",
                             document_id=session.id,
                             unit_cost=line.cost,
                             comment=f"Inventaire {session.number} : "
                                     f"théorique {line.theoretical_qty}, "
                                     f"compté {line.counted_qty}")
                adjusted += 1
            session.status = "validated"
            session.validated_at = datetime.now()
            session.validated_by = common.current_user_id()
            summary = self.summary(session_id)
            summary["adjusted_lines"] = adjusted
            auth.log("inventory_validate", "InventorySession", session_id,
                     new_value=f"{session.number};écart={summary['gap_quantity']}",
                     session=s)
            return summary

    def list_sessions(self, limit: int = 50):
        with session_scope() as s:
            return list(s.scalars(select(InventorySession)
                                  .order_by(InventorySession.at.desc())
                                  .limit(limit)))
