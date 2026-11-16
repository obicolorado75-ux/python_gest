"""Service stock : journal immuable, soldes, réceptions, CMP (§5.7, §5.11)."""
from sqlalchemy import func, select

from ..database.models import (GoodsReceipt, GoodsReceiptLine, Product, PurchaseOrder,
                               PurchaseOrderLine, StockBalance, StockMovement, Supplier,
                               SupplierInvoice)
from ..database.session import next_document_number, session_scope
from ..security import auth
from .catalog_service import CatalogError, CatalogService


class StockError(Exception):
    pass


class StockService:
    def balance(self, product_id: int) -> StockBalance:
        with session_scope() as s:
            b = s.get(StockBalance, product_id)
            if b is None:
                b = StockBalance(product_id=product_id)
                s.add(b)
                s.flush()
            return b

    def available(self, product_id: int) -> int:
        b = self.balance(product_id)
        return b.quantity - b.reserved_quantity

    def _apply(self, s, product_id: int, qty: int, reason: str, document_type=None,
               document_id=None, unit_cost=None, batch_id=None, comment=None):
        """Mouvement + solde dans la même transaction (§5.7)."""
        if qty == 0:
            raise StockError("Quantité nulle.")
        bal = s.get(StockBalance, product_id)
        if bal is None:
            bal = StockBalance(product_id=product_id)
            s.add(bal)
            s.flush()
        if qty < 0 and bal.quantity + qty < 0:
            raise StockError("Stock insuffisant : le mouvement rendrait le solde négatif.")
        cur = auth.Session.current()
        mv = StockMovement(product_id=product_id, quantity=qty, reason=reason,
                           document_type=document_type, document_id=document_id,
                           unit_cost=unit_cost, batch_id=batch_id, comment=comment,
                           user_id=cur.user.id if cur else None)
        s.add(mv)
        bal.quantity += qty
        if qty > 0 and unit_cost is not None:
            # CMP mobile (§5.14)
            from ..domain.rules import weighted_avg_cost
            bal.weighted_avg_cost = weighted_avg_cost(
                bal.quantity - qty, bal.weighted_avg_cost, qty, unit_cost)
        return mv

    def initial_stock(self, product_id: int, qty: int, unit_cost: int, comment="Stock initial"):
        with session_scope() as s:
            mv = self._apply(s, product_id, qty, "mouvement_initial", unit_cost=unit_cost,
                             comment=comment)
            auth.log("stock_initial", "Product", product_id, new_value=str(qty), session=s
            return mv.id

    def adjust(self, product_id: int, qty: int, reason: str, comment=None):
        auth.Session.current().require("stock.adjust")
        with session_scope() as s:
            mv = self._apply(s, product_id, qty, reason, comment=comment)
            auth.log("stock_adjust", "Product", product_id, new_value=str(qty), session=s
            return mv.id

    # --- achats & réceptions ------------------------------------------
    def create_purchase_order(self, supplier_id: int, lines: list[dict]) -> PurchaseOrder:
        """lines : [{product_id, packaging_id, designation, quantity, quantity_display,
        unit_cost}] — une commande seule ne modifie pas le stock (§5.11)."""
        if not lines:
            raise StockError("Commande vide.")
        with session_scope() as s:
            number = next_document_number(s, "ACH")
            po = PurchaseOrder(number=number, supplier_id=supplier_id, status="confirmed",
                               total_amount=sum(l["quantity"] * l["unit_cost"] for l in lines))
            s.add(po)
            s.flush()
            for l in lines:
                s.add(PurchaseOrderLine(order_id=po.id, **l))
            auth.log("purchase_order_create", "PurchaseOrder", po.id, new_value=number, session=s
            return po

    def receive(self, order_id: int, receipts: list[dict]) -> GoodsReceipt:
        """Réception complète ou partielle (T09) : seules les quantités reçues
        entrent en stock, avec mise à jour du coût et CMP.
        receipts : [{order_line_id, quantity, quantity_refused, unit_cost,
                     batch_number, expiry_date}]"""
        if not receipts:
            raise StockError("Réception vide.")
        with session_scope() as s:
            po = s.get(PurchaseOrder, order_id)
            if po is None or po.status in ("received", "cancelled"):
                raise StockError("Commande introuvable ou déjà soldée.")
            number = next_document_number(s, "REC")
            gr = GoodsReceipt(number=number, order_id=order_id, supplier_id=po.supplier_id)
            s.add(gr)
            s.flush()
            total = 0
            cat = CatalogService()
            for r in receipts:
                qty = r["quantity"]
                if qty <= 0:
                    raise StockError("Quantité reçue doit être positive.")
                line = s.get(PurchaseOrderLine, r["order_line_id"])
                remaining = line.quantity - line.received_qty
                if qty > remaining:
                    raise StockError(
                        f"Réception ({qty}) supérieure au reliquat ({remaining}).")
                cost = r.get("unit_cost", line.unit_cost)
                grl = GoodsReceiptLine(receipt_id=gr.id, order_line_id=line.id,
                                       product_id=line.product_id, quantity=qty,
                                       quantity_refused=r.get("quantity_refused", 0),
                                       unit_cost=cost,
                                       batch_number=r.get("batch_number"),
                                       expiry_date=r.get("expiry_date"))
                s.add(grl)
                line.received_qty += qty
                # entrée en stock + mise à jour du CMP
                self._apply(s, line.product_id, qty, "reception",
                            document_type="goods_receipt", document_id=gr.id,
                            unit_cost=cost)
                # coût courant + historique fournisseur
                p = s.get(Product, line.product_id)
                p.current_cost = cost
                from ..database.models import ProductCostHistory
                s.add(ProductCostHistory(product_id=line.product_id, cost=cost,
                                         source="reception"))
                total += qty * cost
            gr.total_amount = total
            # statut commande
            lines = list(s.scalars(select(PurchaseOrderLine).where(
                PurchaseOrderLine.order_id == order_id)))
            po.status = ("received" if all(l.received_qty >= l.quantity for l in lines)
                         else "partially_received")
            # facture fournisseur => solde dû
            inv = SupplierInvoice(number=number, receipt_id=gr.id, supplier_id=po.supplier_id,
                                  total_amount=total)
            s.add(inv)
            sup = s.get(Supplier, po.supplier_id)
            sup.balance += total
            auth.log("goods_receipt", "GoodsReceipt", gr.id, new_value=number, session=s
            return gr

    def movements(self, product_id: int | None = None, limit: int = 200):
        with session_scope() as s:
            q = select(StockMovement).order_by(StockMovement.at.desc()).limit(limit)
            if product_id:
                q = q.where(StockMovement.product_id == product_id)
            return list(s.scalars(q))

    def low_stock_products(self):
        """Produits sous seuil ou en rupture (§1.1, §5.4)."""
        with session_scope() as s:
            rows = s.execute(
                select(Product, StockBalance).outerjoin(
                    StockBalance, StockBalance.product_id == Product.id)
                .where(Product.active == True, Product.archived == False)).all()  # noqa: E712
            out = []
            for p, b in rows:
                qty = b.quantity if b else 0
                if qty <= p.min_threshold:
                    out.append((p, qty, "rupture" if qty <= 0 else "sous_seuil"))
            return out

    def reconcile(self):
        """Rapprochement soldes courants / journal (§7.7)."""
        with session_scope() as s:
            sums = dict(s.execute(
                select(StockMovement.product_id, func.sum(StockMovement.quantity))
                .group_by(StockMovement.product_id)).all())
            mismatches = []
            for bal in s.scalars(select(StockBalance)):
                journal = sums.get(bal.product_id, 0)
                if journal != bal.quantity:
                    mismatches.append((bal.product_id, bal.quantity, journal))
            return mismatches
