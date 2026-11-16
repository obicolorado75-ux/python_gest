"""Commandes clients et livraisons (§5.10).

Cycle complet, contrôlé par les services :

    brouillon → confirmée → en préparation → prête
              → partiellement livrée → livrée

Règles structurantes (§5.10, §7.2) :

- une commande **brouillon** ne touche jamais le stock ;
- la **réservation** est optionnelle (réglage `deliveries.reserve_stock`) ou
  demandée par commande ; la quantité réservée n'est plus disponible pour une
  autre vente (`SalesService.draft_lines` contrôle le disponible) ;
- la **sortie de stock** n'a lieu qu'à la confirmation de la livraison, en même
  temps que la vente : vente + stock + paiement + créance + consignes sont
  écrites dans une seule transaction et jamais deux fois ;
- une livraison **partielle** laisse un reliquat explicite sur la commande ;
- un **échec** ne supprime ni la commande ni les paiements déjà reçus.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database.models import (
    AppSetting,
    Customer,
    CustomerOrder,
    CustomerOrderLine,
    Delivery,
    DeliveryLine,
    GeneratedDocument,
    Sale,
    StockBalance,
)
from ..database.session import next_document_number, session_scope
from ..security import auth
from . import common
from .payment_methods import codes as payment_codes
from .sales_service import SalesService

ORDER_STATUSES = {
    "draft": "Brouillon",
    "confirmed": "Confirmée",
    "preparing": "En préparation",
    "ready": "Prête",
    "partially_delivered": "Partiellement livrée",
    "delivered": "Livrée",
    "cancelled": "Annulée",
}

DELIVERY_STATUSES = {
    "pending": "Planifiée",
    "preparing": "En préparation",
    "in_transit": "En route",
    "delivered": "Livrée",
    "partial": "Livrée partiellement",
    "failed": "Échec de livraison",
    "cancelled": "Annulée",
}

RESERVE_SETTING = "deliveries.reserve_stock"


class DeliveryError(Exception):
    pass


def reserve_by_default() -> bool:
    """Le réglage autorise-t-il la réservation de stock par défaut (§5.10) ?"""
    try:
        with session_scope() as s:
            setting = s.get(AppSetting, RESERVE_SETTING)
            return (setting.value if setting else "1") == "1"
    except Exception:  # base pas encore prête
        return True


class DeliveryService:
    def __init__(self):
        self.sales = SalesService()

    # --- commandes clients -------------------------------------------------
    def create_order(self, customer_id: int, items: list[dict],
                     expected_date: date | None = None,
                     price_list_id: int | None = None,
                     manual_discount: int = 0, delivery_fee: int = 0,
                     address: str | None = None, note: str | None = None,
                     reserve_stock: bool | None = None) -> CustomerOrder:
        """Crée une commande en brouillon : aucun effet sur le stock (§5.10)."""
        common.require("deliveries.manage")
        if not items:
            raise DeliveryError("La commande doit contenir au moins une ligne.")
        if delivery_fee < 0:
            raise DeliveryError("Frais de livraison négatifs interdits.")
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise DeliveryError("Client introuvable.")
            if not customer.active:
                raise DeliveryError("Client inactif.")
            price_list_id = price_list_id or customer.price_list_id
            # la disponibilité n'est pas encore contrôlée : une commande peut
            # porter sur une marchandise attendue en réapprovisionnement
            prep = self.sales.draft_lines(items, price_list_id, manual_discount,
                                          check_stock=False)
            number = next_document_number(s, "CMD")
            order = CustomerOrder(
                number=number, customer_id=customer_id, status="draft",
                desired_date=expected_date, price_list_id=price_list_id,
                discount_amount=manual_discount, delivery_fee=delivery_fee,
                total_amount=prep["total"],
                reserve_stock=(reserve_by_default() if reserve_stock is None
                               else reserve_stock),
                address=address or customer.address, note=note,
                user_id=common.current_user_id())
            s.add(order)
            s.flush()
            for ln in prep["lines"]:
                order.lines.append(CustomerOrderLine(
                    order=order, product_id=ln["product_id"],
                    packaging_id=ln["packaging_id"],
                    designation=ln["designation"], unit_label=ln["unit_label"],
                    quantity=ln["quantity"],
                    quantity_display=ln["quantity_display"],
                    unit_price=ln["unit_price"], total=ln["total"]))
            auth.log("order_create", "CustomerOrder", order.id,
                     new_value=f"{number}={prep['total']}", session=s)
            return order

    def get_order(self, order_id: int) -> dict:
        """Détail d'une commande avec reliquats et livraisons."""
        with session_scope() as s:
            order = s.get(CustomerOrder, order_id)
            if order is None:
                raise DeliveryError("Commande introuvable.")
            lines = [{
                "product_id": line.product_id,
                "packaging_id": line.packaging_id,
                "designation": line.designation,
                "unit_label": line.unit_label,
                "quantity": line.quantity,
                "quantity_display": line.quantity_display,
                "unit_price": line.unit_price,
                "total": line.total,
                "delivered_qty": line.delivered_qty,
                "remaining": line.remaining,
            } for line in order.lines]
            deliveries = [{
                "id": d.id, "number": d.number, "status": d.status,
                "driver": d.driver, "scheduled_date": d.scheduled_date,
                "delivered_at": d.delivered_at,
                "delivered_qty": d.delivered_qty,
                "failure_reason": d.failure_reason,
            } for d in sorted(order.deliveries, key=lambda d: d.id)]
            return {
                "id": order.id, "number": order.number,
                "customer": order.customer.name if order.customer else "—",
                "customer_id": order.customer_id,
                "status": order.status,
                "status_label": ORDER_STATUSES.get(order.status, order.status),
                "created_at": order.created_at,
                "expected_date": order.desired_date,
                "total_amount": order.total_amount,
                "delivery_fee": order.delivery_fee,
                "address": order.address,
                "reserve_stock": order.reserve_stock,
                "note": order.note,
                "lines": lines,
                "deliveries": deliveries,
                "remaining": sum(line["remaining"] for line in lines),
            }

    def orders(self, status: str | None = None, limit: int = 200):
        with session_scope() as s:
            query = select(CustomerOrder).order_by(CustomerOrder.id.desc())
            if status:
                query = query.where(CustomerOrder.status == status)
            return list(s.scalars(query.limit(limit)))

    def confirm_order(self, order_id: int, reserve_stock: bool | None = None) -> dict:
        """Brouillon → confirmée. Réserve le stock si demandé (§5.10)."""
        common.require("deliveries.manage")
        with session_scope() as s:
            order = s.get(CustomerOrder, order_id)
            if order is None:
                raise DeliveryError("Commande introuvable.")
            if order.status != "draft":
                raise DeliveryError(
                    f"Seule une commande en brouillon peut être confirmée "
                    f"(statut actuel : {ORDER_STATUSES.get(order.status, order.status)}).")
            if not order.lines:
                raise DeliveryError("Commande vide : ajoutez au moins une ligne.")
            order.status = "confirmed"
            reserved = 0
            if reserve_stock if reserve_stock is not None else order.reserve_stock:
                order.reserve_stock = True
                for line in order.lines:
                    bal = common.get_balance(s, line.product_id)
                    available = bal.quantity - bal.reserved_quantity
                    if line.quantity > available:
                        raise DeliveryError(
                            f"Réservation impossible pour {line.designation} : "
                            f"disponible {available}, demandé {line.quantity}. "
                            "Décochez la réservation pour commander sans réserver.")
                    bal.reserved_quantity += line.quantity
                    line.reserved_qty = line.quantity
                    reserved += line.quantity
            auth.log("order_confirm", "CustomerOrder", order.id,
                     new_value=f"reserved={reserved}", session=s)
            return {"id": order.id, "number": order.number,
                    "reserved": reserved}

    def set_order_status(self, order_id: int, status: str) -> dict:
        """Préparation : confirmée → en préparation → prête."""
        common.require("deliveries.manage")
        allowed = {"preparing", "ready"}
        if status not in allowed:
            raise DeliveryError("Statut de préparation inconnu.")
        with session_scope() as s:
            order = s.get(CustomerOrder, order_id)
            if order is None:
                raise DeliveryError("Commande introuvable.")
            if order.status not in ("confirmed", "preparing", "ready"):
                raise DeliveryError(
                    "La commande doit être confirmée avant d'être préparée.")
            order.status = status
            auth.log("order_status", "CustomerOrder", order.id, new_value=status,
                     session=s)
            return {"id": order.id, "status": status}

    def cancel_order(self, order_id: int, reason: str) -> dict:
        """Annulation : motif obligatoire, réservation libérée (§5.10, §7.3)."""
        common.require("deliveries.manage")
        reason = (reason or "").strip()
        if not reason:
            raise DeliveryError("Indiquez le motif d'annulation de la commande.")
        with session_scope() as s:
            order = s.get(CustomerOrder, order_id)
            if order is None:
                raise DeliveryError("Commande introuvable.")
            if order.status == "cancelled":
                raise DeliveryError("Cette commande est déjà annulée.")
            if order.status == "delivered":
                raise DeliveryError("Une commande livrée ne peut pas être annulée.")
            self._release_reservation(s, order)
            order.status = "cancelled"
            order.cancelled_reason = reason
            auth.log("order_cancel", "CustomerOrder", order.id, comment=reason,
                     session=s)
            return {"id": order.id, "status": "cancelled"}

    # --- livraisons --------------------------------------------------------
    def plan_delivery(self, order_id: int | None, customer_id: int | None = None,
                      scheduled_date: date | None = None, driver: str | None = None,
                      vehicle: str | None = None, address: str | None = None,
                      fee: int = 0, lines: list[dict] | None = None) -> Delivery:
        """Prépare une livraison (quantités préparées), sans sortie de stock."""
        common.require("deliveries.manage")
        if fee < 0:
            raise DeliveryError("Frais de livraison négatifs interdits.")
        with session_scope() as s:
            order = None
            if order_id is not None:
                order = s.get(CustomerOrder, order_id)
                if order is None:
                    raise DeliveryError("Commande introuvable.")
                if order.status in ("draft", "cancelled", "delivered"):
                    raise DeliveryError(
                        "Confirmez la commande avant de planifier sa livraison.")
                customer_id = order.customer_id
            if customer_id is None:
                raise DeliveryError("Précisez le client de la livraison.")
            if s.get(Customer, customer_id) is None:
                raise DeliveryError("Client introuvable.")
            delivery = Delivery(
                number=next_document_number(s, "LIV"), order_id=order_id,
                customer_id=customer_id, status="pending",
                scheduled_date=scheduled_date or date.today(),
                driver=driver, vehicle=vehicle,
                address=address or (order.address if order else None),
                fee=fee, user_id=common.current_user_id())
            s.add(delivery)
            s.flush()
            prepared = 0
            if order is not None:
                wanted = {int(entry["order_line_id"]): int(entry["quantity"])
                          for entry in (lines or []) if entry.get("quantity")}
                for line in order.lines:
                    qty = wanted.get(line.id, line.remaining)
                    if qty <= 0:
                        continue
                    if qty > line.remaining:
                        raise DeliveryError(
                            f"Quantité préparée supérieure au reliquat pour "
                            f"{line.designation} ({line.remaining} restant).")
                    delivery.lines.append(DeliveryLine(
                        delivery=delivery, order_line_id=line.id,
                        product_id=line.product_id,
                        packaging_id=line.packaging_id,
                        designation=line.designation,
                        unit_label=line.unit_label,
                        quantity_display=line.quantity_display,
                        unit_price=line.unit_price,
                        prepared_qty=qty, delivered_qty=0))
                    prepared += qty
                delivery.prepared_qty = prepared
                if order.status in ("confirmed", "ready"):
                    order.status = "preparing" if order.status == "confirmed" \
                        else order.status
            auth.log("delivery_plan", "Delivery", delivery.id,
                     new_value=f"{delivery.number}={prepared}", session=s)
            return delivery

    def start_delivery(self, delivery_id: int) -> dict:
        """Départ du livreur : planifiée/préparée → en route."""
        common.require("deliveries.manage")
        with session_scope() as s:
            delivery = s.get(Delivery, delivery_id)
            if delivery is None:
                raise DeliveryError("Livraison introuvable.")
            if delivery.status not in ("pending", "preparing"):
                raise DeliveryError(
                    f"Cette livraison ne peut pas partir "
                    f"({DELIVERY_STATUSES.get(delivery.status, delivery.status)}).")
            delivery.status = "in_transit"
            auth.log("delivery_start", "Delivery", delivery.id,
                     new_value="in_transit", session=s)
            return {"id": delivery.id, "status": "in_transit"}

    def confirm_delivery(self, delivery_id: int,
                         lines: list[dict] | None = None,
                         proof: str | None = None,
                         collected_amount: int = 0,
                         payment_method: str | None = None,
                         payments: list[dict] | None = None) -> dict:
        """Confirme la livraison : vente + sortie de stock, une seule fois.

        ``lines`` : [{"delivery_line_id": 3, "delivered_qty": 12}] (unités de
        base). Les lignes omises sont réputées livrées à la quantité préparée.
        Une confirmation partielle laisse un reliquat sur la commande.
        """
        common.require("deliveries.manage")
        if collected_amount < 0:
            raise DeliveryError("Montant encaissé invalide.")
        if payment_method and payment_method not in payment_codes():
            raise DeliveryError("Moyen de paiement inconnu.")
        with session_scope() as s:
            delivery = s.get(Delivery, delivery_id)
            if delivery is None:
                raise DeliveryError("Livraison introuvable.")
            if delivery.status in ("delivered", "cancelled"):
                raise DeliveryError(
                    "Cette livraison est déjà clôturée : le stock ne peut pas "
                    "être sorti une deuxième fois.")
            if delivery.status == "failed":
                raise DeliveryError(
                    "Livraison en échec : replanifiez-la avant de confirmer.")
            wanted = {int(entry["delivery_line_id"]): int(entry["delivered_qty"])
                      for entry in (lines or [])}
            items = []
            delivered_total = 0
            just_delivered: dict[int, int] = {}   # delivery_line_id → quantité
            for line in delivery.lines:
                qty = wanted.get(line.id, line.prepared_qty - line.delivered_qty)
                if qty < 0 or qty > line.prepared_qty - line.delivered_qty:
                    raise DeliveryError(
                        f"Quantité livrée incohérente pour {line.designation}.")
                if qty == 0:
                    continue
                line.delivered_qty += qty
                just_delivered[line.id] = qty
                delivered_total += qty
                items.append({"product_id": line.product_id,
                              "packaging_id": None, "quantity_display": 0,
                              "base_qty": qty})
            if delivered_total == 0:
                raise DeliveryError(
                    "Aucune quantité livrée : utilisez « Échec de livraison » "
                    "si la marchandise n'a pas été remise.")

            order = s.get(CustomerOrder, delivery.order_id) \
                if delivery.order_id else None
            items = self._merge_items(items)
            sale = None
            if items:
                # prix négociés de la commande conservés : la vente réutilise
                # les lignes figées plutôt que de recalculer les tarifs
                sale = self.sales.confirm_sale(
                    items=[{**item,
                            "unit_price": self._unit_price_for(delivery, item,
                                                               order)}
                           for item in items],
                    payment_method=payment_method or "especes",
                    paid_amount=collected_amount,
                    customer_id=delivery.customer_id,
                    price_list_id=order.price_list_id if order else None,
                    delivery_fees=delivery.fee,
                    note=f"Livraison {delivery.number}",
                    payments=payments,
                    session=s,
                    delivery_id=delivery.id)
                delivery.sale_id = sale.id
            delivery.delivered_qty = (delivery.delivered_qty or 0) + delivered_total
            delivery.collected_amount = collected_amount
            delivery.payment_method = payment_method or "especes"
            delivery.proof_comment = proof
            delivery.delivered_at = datetime.now()
            if order is not None:
                self._consume_reservation(s, order, delivery, just_delivered)
            complete = bool(order) and all(
                line.delivered_qty >= line.quantity for line in order.lines)
            if order is not None:
                if complete:
                    order.status = "delivered"
                elif all(line.delivered_qty > 0 for line in order.lines) or \
                        any(line.delivered_qty for line in order.lines):
                    order.status = "partially_delivered"
            delivery.status = "delivered" if (complete or order is None) else "partial"
            auth.log("delivery_confirm", "Delivery", delivery.id,
                     new_value=f"{delivery.number}={delivered_total}"
                               f"/sale={sale.number if sale else '-'}", session=s)
            return {"id": delivery.id, "status": delivery.status,
                    "delivered_qty": delivered_total,
                    "sale_id": sale.id if sale else None,
                    "sale_number": sale.number if sale else None,
                    "remaining": (order.total_amount and sum(
                        line.remaining for line in order.lines)) if order else 0}

    def fail_delivery(self, delivery_id: int, reason: str) -> dict:
        """Échec : la commande et les paiements déjà reçus sont conservés."""
        common.require("deliveries.manage")
        reason = (reason or "").strip()
        if not reason:
            raise DeliveryError("Indiquez le motif de l'échec de livraison.")
        with session_scope() as s:
            delivery = s.get(Delivery, delivery_id)
            if delivery is None:
                raise DeliveryError("Livraison introuvable.")
            if delivery.status in ("delivered", "cancelled"):
                raise DeliveryError("Cette livraison est déjà clôturée.")
            delivery.status = "failed"
            delivery.failure_reason = reason
            if delivery.order_id:
                order = s.get(CustomerOrder, delivery.order_id)
                if order is not None and order.status not in ("delivered",
                                                              "cancelled"):
                    # retour à un statut planifiable : rien n'est effacé
                    order.status = "confirmed" if not order.deliveries or all(
                        d.status == "failed" for d in order.deliveries) else \
                        order.status
            auth.log("delivery_fail", "Delivery", delivery.id, comment=reason,
                     session=s)
            return {"id": delivery.id, "status": "failed"}

    def delivery_note(self, delivery_id: int, open_after: bool = False) -> str:
        """Bon de livraison A4 généré dans le dossier documents (§5.10, §9)."""
        from ..printing import delivery_note_html, write_document
        from .admin_service import AdminService

        detail = self.get_delivery(delivery_id)
        settings = AdminService().company_settings()
        company = {"name": settings.name, "address": settings.address,
                   "phone": settings.phone,
                   "document_footer": settings.document_footer}
        path = write_document(f"bon_livraison_{detail['number']}",
                              delivery_note_html(detail, company),
                              open_after=open_after)
        with session_scope() as s:
            s.add(GeneratedDocument(reference=detail["number"],
                                    document_type="bon_livraison",
                                    file_path=path))
            auth.log("delivery_note", "Delivery", delivery_id, new_value=path,
                     session=s)
        return path

    def deliveries(self, status: str | None = None, limit: int = 200):
        with session_scope() as s:
            query = select(Delivery).order_by(Delivery.id.desc())
            if status:
                query = query.where(Delivery.status == status)
            return list(s.scalars(query.limit(limit)))

    def get_delivery(self, delivery_id: int) -> dict:
        with session_scope() as s:
            delivery = s.get(Delivery, delivery_id)
            if delivery is None:
                raise DeliveryError("Livraison introuvable.")
            return {
                "id": delivery.id, "number": delivery.number,
                "status": delivery.status,
                "status_label": DELIVERY_STATUSES.get(delivery.status,
                                                      delivery.status),
                "customer": delivery.customer.name if delivery.customer else "—",
                "customer_id": delivery.customer_id,
                "order_number": delivery.order.number if delivery.order else None,
                "driver": delivery.driver, "vehicle": delivery.vehicle,
                "address": delivery.address,
                "scheduled_date": delivery.scheduled_date,
                "delivered_at": delivery.delivered_at,
                "fee": delivery.fee,
                "proof": delivery.proof_comment,
                "collected_amount": delivery.collected_amount,
                "sale_number": None if not delivery.sale_id else
                s.get(Sale, delivery.sale_id).number,
                "prepared_qty": delivery.prepared_qty,
                "delivered_qty": delivery.delivered_qty,
                "failure_reason": delivery.failure_reason,
                "lines": [{
                    "id": line.id, "designation": line.designation,
                    "unit_label": line.unit_label,
                    "unit_price": line.unit_price,
                    "prepared_qty": line.prepared_qty,
                    "delivered_qty": line.delivered_qty,
                    "remaining": line.prepared_qty - line.delivered_qty,
                } for line in delivery.lines],
            }

    # --- utilitaires -------------------------------------------------------
    @staticmethod
    def _merge_items(items: list[dict]) -> list[dict]:
        """Regroupe les lignes d'un même produit/conditionnement."""
        merged: dict[tuple, dict] = {}
        for item in items:
            key = (item["product_id"], item["packaging_id"])
            if key in merged:
                merged[key]["base_qty"] += item["base_qty"]
            else:
                merged[key] = dict(item)
        return list(merged.values())

    @staticmethod
    def _unit_price_for(delivery: Delivery, item: dict, order) -> int | None:
        """Prix négocié de la ligne de commande (jamais recalculé au départ)."""
        if order is None:
            return None
        for line in order.lines:
            if line.product_id == item["product_id"]:
                return line.unit_price
        return None

    @staticmethod
    def _designation_for(delivery: Delivery, item: dict) -> str | None:
        for line in delivery.lines:
            if line.product_id == item["product_id"]:
                return line.designation
        return None

    @staticmethod
    def _consume_reservation(s: Session, order: CustomerOrder,
                             delivery: Delivery,
                             just_delivered: dict[int, int]) -> None:
        """Reporte les quantités livrées et libère la réservation au prorata."""
        for line in delivery.lines:
            quantity = just_delivered.get(line.id, 0)
            if not quantity:
                continue
            for order_line in order.lines:
                if order_line.id != line.order_line_id:
                    continue
                released = min(order_line.reserved_qty, quantity)
                if released:
                    order_line.reserved_qty -= released
                    bal = s.get(StockBalance, order_line.product_id)
                    if bal is not None:
                        bal.reserved_quantity = max(
                            0, bal.reserved_quantity - released)
                order_line.delivered_qty += quantity

    @staticmethod
    def _release_reservation(s: Session, order: CustomerOrder) -> None:
        for line in order.lines:
            if not line.reserved_qty:
                continue
            bal = s.get(StockBalance, line.product_id)
            if bal is not None:
                bal.reserved_quantity = max(0, bal.reserved_quantity -
                                            line.reserved_qty)
            line.reserved_qty = 0
