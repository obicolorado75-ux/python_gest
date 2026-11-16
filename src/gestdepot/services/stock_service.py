"""Service stock : journal immuable, soldes, réceptions, CMP (§5.7, §5.11)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database.models import (
    CashMovement,
    GoodsReceipt,
    GoodsReceiptLine,
    Product,
    ProductCostHistory,
    PurchaseOrder,
    PurchaseOrderLine,
    StockBalance,
    StockMovement,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
)
from ..database.session import next_document_number, session_scope
from ..domain.rules import PAYMENT_METHODS, weighted_avg_cost
from ..security import auth
from . import common

# Motifs de mouvement autorisés (§5.7)
MOVEMENT_REASONS = {
    "mouvement_initial", "reception", "sortie_vente", "retour_client",
    "retour_fournisseur", "casse", "perte", "peremption",
    "correction_inventaire",
}


class StockError(Exception):
    pass


class StockService:
    # --- lecture -------------------------------------------------------
    def balance(self, product_id: int) -> StockBalance:
        with session_scope() as s:
            return common.get_balance(s, product_id)

    def available(self, product_id: int) -> int:
        with session_scope() as s:
            return common.available_quantity(s, product_id)

    def stock_levels(self, search: str | None = None, only_alerts: bool = False):
        """Vue stock : physique, réservé, disponible, valeur, seuil, statut (§5.7)."""
        with session_scope() as s:
            q = (select(Product, StockBalance)
                 .outerjoin(StockBalance, StockBalance.product_id == Product.id)
                 .where(Product.archived.is_(False)))
            if search:
                like = f"%{search}%"
                q = q.where(Product.name.ilike(like) | Product.reference.ilike(like))
            rows = []
            for product, bal in s.execute(q.order_by(Product.name)).all():
                qty = bal.quantity if bal else 0
                reserved = bal.reserved_quantity if bal else 0
                cost = bal.weighted_avg_cost if bal else product.current_cost
                status = "rupture" if qty <= 0 else (
                    "sous_seuil" if qty <= product.min_threshold else "ok")
                if only_alerts and status == "ok":
                    continue
                rows.append({
                    "product_id": product.id,
                    "reference": product.reference,
                    "name": product.name,
                    "quantity": qty,
                    "reserved": reserved,
                    "available": qty - reserved,
                    "unit": product.base_unit.name if product.base_unit else "",
                    "unit_cost": cost,
                    "value": qty * cost,
                    "min_threshold": product.min_threshold,
                    "status": status,
                })
            return rows

    def movements(self, product_id: int | None = None, limit: int = 200,
                  start=None, end=None):
        with session_scope() as s:
            q = select(StockMovement).order_by(StockMovement.at.desc(),
                                               StockMovement.id.desc()).limit(limit)
            if product_id:
                q = q.where(StockMovement.product_id == product_id)
            if start is not None:
                q = q.where(StockMovement.at >= start)
            if end is not None:
                q = q.where(StockMovement.at <= end)
            return list(s.scalars(q))

    def journal_total(self, product_id: int) -> int:
        with session_scope() as s:
            return s.scalar(select(func.coalesce(func.sum(StockMovement.quantity), 0))
                            .where(StockMovement.product_id == product_id)) or 0

    # --- écriture (journal + solde dans la même transaction) ------------
    def _apply(self, s: Session, product_id: int, qty: int, reason: str,
               document_type=None, document_id=None, unit_cost=None,
               batch_id=None, comment=None) -> StockMovement:
        """Mouvement + solde dans la même transaction (§5.7).

        Une quantité négative qui rendrait le solde négatif est refusée (T04).
        """
        if reason not in MOVEMENT_REASONS:
            raise StockError(f"Motif de mouvement inconnu : {reason}")
        if qty == 0:
            raise StockError("Quantité nulle interdite.")
        product = s.get(Product, product_id)
        if product is None:
            raise StockError("Produit introuvable.")
        bal = common.get_balance(s, product_id)
        if qty < 0 and bal.quantity + qty < 0:
            raise StockError(
                f"Stock insuffisant pour {product.name} : "
                f"solde {bal.quantity}, mouvement {qty}.")
        mv = StockMovement(product_id=product_id, quantity=qty, reason=reason,
                           document_type=document_type, document_id=document_id,
                           unit_cost=unit_cost, batch_id=batch_id, comment=comment,
                           user_id=common.current_user_id())
        s.add(mv)
        previous_qty = bal.quantity
        bal.quantity += qty
        if qty > 0 and unit_cost is not None and unit_cost >= 0:
            # CMP mobile (§5.14) — coût moyen pondéré sur les entrées uniquement
            bal.weighted_avg_cost = weighted_avg_cost(
                previous_qty, bal.weighted_avg_cost, qty, unit_cost)
            if product.current_cost != unit_cost:
                product.current_cost = unit_cost
        s.flush()
        return mv

    def apply_movement(self, product_id: int, qty: int, reason: str,
                       comment: str | None = None, unit_cost: int | None = None,
                       document_type: str | None = None,
                       document_id: int | None = None) -> int:
        """Mouvement manuel (casse, perte, péremption, retour fournisseur…)."""
        common.require("stock.adjust")
        with session_scope() as s:
            mv = self._apply(s, product_id, qty, reason, unit_cost=unit_cost,
                             document_type=document_type, document_id=document_id,
                             comment=comment)
            auth.log("stock_adjust", "Product", product_id,
                     new_value=f"{reason}:{qty}", comment=comment, session=s)
            return mv.id

    def initial_stock(self, product_id: int, qty: int, unit_cost: int,
                      comment: str = "Stock initial") -> int:
        common.require("stock.adjust")
        if qty <= 0:
            raise StockError("La quantité initiale doit être positive.")
        if unit_cost < 0:
            raise StockError("Le coût ne peut pas être négatif.")
        with session_scope() as s:
            mv = self._apply(s, product_id, qty, "mouvement_initial",
                             unit_cost=unit_cost, comment=comment)
            auth.log("stock_initial", "Product", product_id, new_value=str(qty),
                     session=s)
            return mv.id

    def adjust(self, product_id: int, qty: int, reason: str,
               comment: str | None = None) -> int:
        """Ajustement manuel : casse, perte, péremption, entrée initiale…"""
        common.require("stock.adjust")
        if reason in ("reception", "sortie_vente", "correction_inventaire"):
            raise StockError("Ce motif est réservé aux procédures dédiées.")
        with session_scope() as s:
            mv = self._apply(s, product_id, qty, reason, comment=comment)
            auth.log("stock_adjust", "Product", product_id, new_value=str(qty),
                     comment=comment, session=s)
            return mv.id

    # --- fournisseurs ----------------------------------------------------
    def create_supplier(self, code: str, name: str, **fields) -> Supplier:
        common.require("suppliers.manage")
        with session_scope() as s:
            code = (code or "").strip()
            if not code:
                raise StockError("Le code fournisseur est obligatoire.")
            if s.scalar(select(Supplier.id).where(Supplier.code == code)):
                raise StockError(f"Le code fournisseur {code} existe déjà.")
            sup = Supplier(code=code, name=name, **fields)
            s.add(sup)
            s.flush()
            auth.log("supplier_create", "Supplier", sup.id, new_value=name, session=s)
            return sup

    def get_supplier(self, supplier_id: int) -> Supplier:
        with session_scope() as s:
            supplier = s.get(Supplier, supplier_id)
            if supplier is None:
                raise StockError("Fournisseur introuvable.")
            return supplier

    def list_suppliers(self, search: str | None = None):
        with session_scope() as s:
            q = select(Supplier).where(Supplier.active.is_(True))
            if search:
                like = f"%{search}%"
                q = q.where(Supplier.name.ilike(like) | Supplier.code.ilike(like))
            return list(s.scalars(q.order_by(Supplier.name)))

    # --- commandes d'achat (§5.11) ---------------------------------------
    def create_purchase_order(self, supplier_id: int, lines: list[dict],
                              expected_date: date | None = None,
                              comment: str | None = None,
                              discount: int = 0, other_fees: int = 0,
                              freight_fees: int = 0) -> PurchaseOrder:
        """Une commande d'achat seule ne modifie JAMAIS le stock (§5.11).

        lines : [{product_id, packaging_id, designation, quantity (unités de base),
                  quantity_display, unit_cost}]
        discount : remise globale négociée (FCFA)
        freight_fees / other_fees : frais d'approche, répartis au prorata des
        montants de ligne lors de la réception (méthode configurable §5.11).
        """
        common.require("stock.receive")
        if not lines:
            raise StockError("Commande vide.")
        if discount < 0 or freight_fees < 0 or other_fees < 0:
            raise StockError("Remise ou frais négatifs interdits.")
        with session_scope() as s:
            if s.get(Supplier, supplier_id) is None:
                raise StockError("Fournisseur introuvable.")
            number = next_document_number(s, "ACH")
            total = 0
            prepared = []
            rate = 0
            for line in lines:
                product = s.get(Product, line["product_id"])
                if product is None:
                    raise StockError("Produit introuvable dans la commande.")
                qty = int(line.get("quantity") or 0)
                cost = int(line.get("unit_cost") or 0)
                if qty <= 0:
                    raise StockError("Quantité commandée invalide.")
                if cost < 0:
                    raise StockError("Prix convenu invalide.")
                total += qty * cost
                prepared.append({
                    "product_id": product.id,
                    "packaging_id": line.get("packaging_id"),
                    "designation": line.get("designation") or product.name,
                    "quantity": qty,
                    "quantity_display": int(line.get("quantity_display") or 1),
                    "unit_cost": cost,
                })
            charges = freight_fees + other_fees
            if charges and not total:
                raise StockError("Frais d'approche impossibles sur une commande "
                                 "de montant nul.")
            # remise plafonnée au montant des lignes
            gross = total
            applied_discount = min(discount, gross)
            # coefficient appliqué au coût convenu de chaque ligne : il répartit
            # la remise et les frais d'approche au prorata des montants de ligne
            # (somme des coûts « landed » × quantités = total de la commande)
            factor = (gross - applied_discount + charges) / gross if gross else 1
            rate = factor
            total = gross - applied_discount + charges
            po = PurchaseOrder(number=number, supplier_id=supplier_id,
                               status="confirmed", total_amount=total,
                               expected_date=expected_date, comment=comment,
                               discount_amount=applied_discount,
                               freight_fees=freight_fees, other_fees=other_fees,
                               user_id=common.current_user_id())
            s.add(po)
            s.flush()
            for line in prepared:
                line["landed_cost"] = round(line["unit_cost"] * rate)
                # alimentation de la collection en mémoire : la commande reste
                # lisible (lignes comprises) après fermeture de la session
                po.lines.append(PurchaseOrderLine(**line))
            s.flush()
            auth.log("purchase_order_create", "PurchaseOrder", po.id,
                     new_value=f"{number}={total}", session=s)
            return po

    def get_purchase_order(self, order_id: int) -> PurchaseOrder:
        with session_scope() as s:
            po = s.get(PurchaseOrder, order_id)
            if po is None:
                raise StockError("Commande d'achat introuvable.")
            return po

    def pending_purchase_orders(self):
        """Commandes attendues (suggestion de réapprovisionnement, §5.11)."""
        with session_scope() as s:
            return list(s.scalars(select(PurchaseOrder).where(
                PurchaseOrder.status.in_(("confirmed", "partially_received")))
                .order_by(PurchaseOrder.ordered_at.desc())))

    def receive(self, order_id: int, receipts: list[dict],
                comment: str | None = None) -> GoodsReceipt:
        """Réception complète ou partielle (T09).

        Seules les quantités reçues entrent en stock, avec mise à jour du CMP et
        de l'historique des coûts ; une facture fournisseur est créée et le solde
        dû du fournisseur augmenté — le tout dans une seule transaction.
        """
        common.require("stock.receive")
        if not receipts:
            raise StockError("Réception vide.")
        with session_scope() as s:
            po = s.get(PurchaseOrder, order_id)
            if po is None:
                raise StockError("Commande introuvable.")
            if po.status in ("received", "cancelled"):
                raise StockError("Commande déjà soldée ou annulée.")
            number = next_document_number(s, "REC")
            gr = GoodsReceipt(number=number, order_id=order_id,
                              supplier_id=po.supplier_id,
                              user_id=common.current_user_id(), comment=comment)
            s.add(gr)
            s.flush()
            total = 0
            for r in receipts:
                qty = int(r.get("quantity") or 0)
                if qty <= 0:
                    raise StockError("La quantité reçue doit être positive.")
                line = s.get(PurchaseOrderLine, r["order_line_id"])
                if line is None or line.order_id != order_id:
                    raise StockError("Ligne de commande introuvable.")
                remaining = line.quantity - line.received_qty
                if qty > remaining:
                    raise StockError(
                        f"Réception ({qty}) supérieure au reliquat ({remaining}).")
                # coût retenu = coût constaté, à défaut coût convenu majoré des
                # frais d'approche répartis (§5.11)
                default_cost = line.landed_cost or line.unit_cost
                cost = int(r.get("unit_cost", default_cost) or 0)
                if cost < 0:
                    raise StockError("Coût de réception invalide.")
                s.add(GoodsReceiptLine(
                    receipt_id=gr.id, order_line_id=line.id,
                    product_id=line.product_id, quantity=qty,
                    quantity_refused=int(r.get("quantity_refused") or 0),
                    unit_cost=cost, batch_number=r.get("batch_number"),
                    expiry_date=r.get("expiry_date")))
                line.received_qty += qty
                self._apply(s, line.product_id, qty, "reception",
                            document_type="goods_receipt", document_id=gr.id,
                            unit_cost=cost)
                s.add(ProductCostHistory(product_id=line.product_id, cost=cost,
                                         source="reception"))
                total += qty * cost
            gr.total_amount = total
            lines = list(s.scalars(select(PurchaseOrderLine).where(
                PurchaseOrderLine.order_id == order_id)))
            po.status = ("received" if all(l.received_qty >= l.quantity for l in lines)
                         else "partially_received")
            invoice = SupplierInvoice(number=number, receipt_id=gr.id,
                                      supplier_id=po.supplier_id,
                                      total_amount=total)
            s.add(invoice)
            s.flush()
            sup = s.get(Supplier, po.supplier_id)
            sup.balance += total
            gr.invoice_created = True
            auth.log("goods_receipt", "GoodsReceipt", gr.id,
                     new_value=f"{number}={total}", session=s)
            return gr

    # --- paiements fournisseurs (§5.11, §5.12) ----------------------------
    def pay_supplier(self, supplier_id: int, amount: int,
                     payment_method: str = "especes",
                     invoice_id: int | None = None,
                     comment: str | None = None) -> SupplierPayment:
        """Règlement partiel ou total d'un fournisseur.

        Le solde dû diminue sans toucher au stock ; les espèces sortent de la
        session de caisse ouverte et un mouvement de caisse est enregistré pour
        chaque moyen (seules les espèces changent le solde physique, §5.12).
        """
        common.require("suppliers.pay")
        if amount <= 0:
            raise StockError("Montant de paiement invalide.")
        if payment_method not in PAYMENT_METHODS:
            raise StockError("Moyen de paiement inconnu.")
        user_id = common.current_user_id()
        with session_scope() as s:
            supplier = s.get(Supplier, supplier_id)
            if supplier is None:
                raise StockError("Fournisseur introuvable.")
            if amount > supplier.balance:
                raise StockError(
                    f"Le paiement ({amount}) dépasse le solde dû ({supplier.balance}).")
            invoice = None
            if invoice_id:
                invoice = s.get(SupplierInvoice, invoice_id)
                if invoice is None or invoice.supplier_id != supplier_id:
                    raise StockError("Facture fournisseur introuvable.")
                outstanding = invoice.total_amount - invoice.paid_amount
                if amount > outstanding:
                    raise StockError(
                        f"Le paiement dépasse le reste dû de la facture "
                        f"({outstanding}).")
            payment = SupplierPayment(supplier_id=supplier_id, amount=amount,
                                      payment_method=payment_method,
                                      invoice_id=invoice_id,
                                      comment=comment, user_id=user_id,
                                      cash_session_id=None)
            s.add(payment)
            supplier.balance -= amount
            if invoice is not None:
                invoice.paid_amount += amount
            cash_session = common.open_cash_session(s, user_id)
            if cash_session is not None:
                payment.cash_session_id = cash_session.id
                s.add(CashMovement(session_id=cash_session.id, direction="out",
                                   amount=amount, payment_method=payment_method,
                                   reason="paiement_fournisseur",
                                   document_type="supplier_payment",
                                   document_id=payment.id, user_id=user_id))
            s.flush()
            auth.log("supplier_payment", "SupplierPayment", payment.id,
                     new_value=f"{supplier.code}={amount}", comment=comment,
                     session=s)
            return payment

    def list_payments(self, supplier_id: int | None = None, limit: int = 200):
        with session_scope() as s:
            q = select(SupplierPayment).order_by(SupplierPayment.at.desc(),
                                                 SupplierPayment.id.desc()).limit(limit)
            if supplier_id:
                q = q.where(SupplierPayment.supplier_id == supplier_id)
            return list(s.scalars(q))

    def list_purchase_orders(self, limit: int = 200, status: str | None = None):
        """Toutes les commandes, y compris soldées et annulées (§5.11)."""
        with session_scope() as s:
            q = (select(PurchaseOrder)
                 .order_by(PurchaseOrder.ordered_at.desc(), PurchaseOrder.id.desc())
                 .limit(limit))
            if status:
                q = q.where(PurchaseOrder.status == status)
            return list(s.scalars(q))

    def purchased_by_supplier(self) -> dict[int, int]:
        """Cumul des réceptions validées par fournisseur (historique des achats)."""
        with session_scope() as s:
            rows = s.execute(
                select(GoodsReceipt.supplier_id, func.coalesce(func.sum(
                    GoodsReceipt.total_amount), 0))
                .group_by(GoodsReceipt.supplier_id)).all()
            return {supplier_id: int(total or 0) for supplier_id, total in rows}

    def supplier_invoices(self, supplier_id: int | None = None, only_due: bool = False):
        with session_scope() as s:
            q = select(SupplierInvoice).order_by(SupplierInvoice.at.desc(),
                                                 SupplierInvoice.id.desc())
            if supplier_id:
                q = q.where(SupplierInvoice.supplier_id == supplier_id)
            rows = list(s.scalars(q))
        if only_due:
            rows = [inv for inv in rows if inv.total_amount > inv.paid_amount]
        return rows

    # --- annulation / réouverture d'une commande (§5.11) ------------------
    def cancel_order(self, order_id: int, reason: str) -> None:
        """Annule une commande non réceptionnée ; jamais de suppression muette."""
        common.require("stock.receive")
        if not (reason or "").strip():
            raise StockError("Le motif d'annulation est obligatoire.")
        with session_scope() as s:
            po = s.get(PurchaseOrder, order_id)
            if po is None:
                raise StockError("Commande introuvable.")
            if po.status in ("received", "cancelled"):
                raise StockError("Commande déjà soldée ou annulée.")
            po.status = "cancelled"
            auth.log("purchase_order_cancel", "PurchaseOrder", order_id,
                     new_value=po.number, comment=reason, session=s)

    def reopen_order(self, order_id: int, reason: str) -> None:
        """Rouvre une commande soldée par erreur : date d'effet + audit (§7.2).

        Le reliquat réapparaît pour une réception ultérieure ; rien n'est modifié
        sur les réceptions déjà validées.
        """
        common.require("stock.receive")
        if not (reason or "").strip():
            raise StockError("Le motif de réouverture est obligatoire.")
        with session_scope() as s:
            po = s.get(PurchaseOrder, order_id)
            if po is None:
                raise StockError("Commande introuvable.")
            if po.status not in ("received", "cancelled"):
                raise StockError("Seule une commande soldée ou annulée peut être "
                                 "rouverte.")
            lines = list(s.scalars(select(PurchaseOrderLine).where(
                PurchaseOrderLine.order_id == order_id)))
            received_any = any(line.received_qty > 0 for line in lines)
            po.status = "partially_received" if received_any else "confirmed"
            auth.log("purchase_order_reopen", "PurchaseOrder", order_id,
                     new_value=po.number, comment=reason, session=s)

    # --- alertes et rapprochement ----------------------------------------
    def low_stock_products(self):
        """Produits sous seuil ou en rupture (§1.1, §5.4)."""
        return [(row["product_id"], row["quantity"], row["status"])
                for row in self.stock_levels(only_alerts=True)]

    def stock_value(self) -> int:
        """Valeur du stock au coût moyen pondéré (§5.4)."""
        with session_scope() as s:
            total = 0
            for bal in s.scalars(select(StockBalance)):
                total += bal.quantity * bal.weighted_avg_cost
            return total

    def reconcile(self):
        """Rapprochement soldes courants / journal (§7.7).

        Retourne une liste de tuples (product_id, solde, somme du journal).
        Aucune réparation silencieuse : la correction passe par un inventaire.
        """
        with session_scope() as s:
            sums = dict(s.execute(
                select(StockMovement.product_id, func.sum(StockMovement.quantity))
                .group_by(StockMovement.product_id)).all())
            mismatches = []
            for bal in s.scalars(select(StockBalance)):
                journal = int(sums.get(bal.product_id, 0) or 0)
                if journal != bal.quantity:
                    mismatches.append((bal.product_id, bal.quantity, journal))
            return mismatches

    def reorder_suggestions(self, horizon_days: int = 7):
        """Suggestions de réapprovisionnement, à valider par le gérant (§5.11)."""
        from ..domain.rules import reorder_quantity
        with session_scope() as s:
            expected: dict[int, int] = {}
            for line in s.scalars(select(PurchaseOrderLine).join(
                    PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
                    .where(PurchaseOrder.status.in_(("confirmed",
                                                     "partially_received")))):
                expected[line.product_id] = (expected.get(line.product_id, 0)
                                             + (line.quantity - line.received_qty))
            out = []
            for row in self.stock_levels():
                if row["status"] == "ok":
                    continue
                product = s.get(Product, row["product_id"])
                supplier = s.get(Supplier, product.primary_supplier_id) \
                    if product.primary_supplier_id else None
                qty = reorder_quantity(
                    avg_daily_sales=0, lead_time_days=supplier.lead_time_days if supplier else 0,
                    safety_stock=product.safety_stock, available=row["available"],
                    expected_orders=expected.get(row["product_id"], 0),
                    horizon_days=horizon_days)
                out.append({"product_id": product.id, "name": product.name,
                            "available": row["available"],
                            "safety_stock": product.safety_stock,
                            "supplier": supplier.name if supplier else None,
                            "suggested_qty": qty})
            return out
