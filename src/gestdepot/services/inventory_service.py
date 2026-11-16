"""Service inventaires physiques (§5.13) : théorique, compté, écart, régularisation."""
from __future__ import annotations

from sqlalchemy import select

from ..database.models import InventoryLine, InventorySession, Product, StockBalance
from ..database.session import next_document_number, session_scope
from ..security import auth
from . import common


class InventoryError(Exception):
    pass


class InventoryService:
    def start_session(self, product_ids: list[int] | None = None,
                      comment: str | None = None) -> InventorySession:
        """Crée une session d'inventaire et fige le stock théorique au démarrage."""
        common.require("inventory.manage")
        with session_scope() as s:
            number = next_document_number(s, "INV")
            session = InventorySession(number=number, status="draft",
                                       user_id=common.current_user_id(),
                                       comment=comment)
            s.add(session)
            s.flush()
            query = select(Product).where(Product.archived.is_(False))
            if product_ids:
                query = query.where(Product.id.in_(product_ids))
            for product in s.scalars(query.order_by(Product.name)):
                bal = s.get(StockBalance, product.id)
                cost = (bal.weighted_avg_cost if bal else 0) or product.current_cost
                s.add(InventoryLine(session_id=session.id, product_id=product.id,
                                    theoretical_qty=bal.quantity if bal else 0,
                                    counted_qty=bal.quantity if bal else 0,
                                    cost=cost))
            auth.log("inventory_start", "InventorySession", session.id,
                     new_value=number, session=s)
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
            if session.status != "draft":
                raise InventoryError("Inventaire validé : correction impossible.")
            line = s.scalar(select(InventoryLine).where(
                InventoryLine.session_id == session_id,
                InventoryLine.product_id == product_id))
            if line is None:
                raise InventoryError("Produit absent de cet inventaire.")
            line.counted_qty = counted_qty

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
