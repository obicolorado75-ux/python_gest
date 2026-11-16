"""Service ventes/caisse : vente atomique, paiements, retours, crédits (§5.5, §7.2).

Toute validation de vente crée vente + lignes + mouvements de stock + mouvements
de caisse/paiement + solde client + consignes dans une SEULE transaction.
"""
from datetime import datetime

from sqlalchemy import select

from ..database.models import (CashMovement, CashSession, Customer, CustomerCreditEvent,
                               CustomerPayment, DepositMovement, PaymentAllocation,
                               Product, ProductPackaging, ReturnablePackaging, Sale,
                               SaleLine, SaleReturn, SaleReturnLine, StockBalance,
                               StockMovement)
from ..database.session import next_document_number, session_scope
from ..security import auth
from .stock_service import StockError, StockService

PAYMENT_METHODS = ["especes", "orange_money", "mtn_moMo", "moov_money", "wave",
                   "virement", "cheque", "autre"]


class SalesError(Exception):
    pass


class SalesService:
    def __init__(self):
        self.stock = StockService()

    # --- préparation ---------------------------------------------------
    def price_for(self, product_id: int, packaging_id: int | None,
                  price_list_id: int | None) -> tuple[int, int]:
        """Retourne (prix appliqué, factor) pour une ligne de vente."""
        with session_scope() as s:
            factor = 1
            if packaging_id:
                pk = s.get(ProductPackaging, packaging_id)
                factor = pk.factor
            from ..database.models import ProductPrice
            pp = s.scalar(select(ProductPrice).where(
                ProductPrice.product_id == product_id,
                ProductPrice.packaging_id == packaging_id,
                ProductPrice.price_list_id == price_list_id))
            if pp is None and price_list_id is not None:
                pp = s.scalar(select(ProductPrice).where(
                    ProductPrice.product_id == product_id,
                    ProductPrice.packaging_id == packaging_id,
                    ProductPrice.price_list_id.is_(None)))
            price = pp.unit_price if pp else 0
            return price, factor

    def draft_lines(self, items: list[dict], price_list_id: int | None,
                    manual_discount: int = 0) -> dict:
        """items : [{product_id, packaging_id, quantity_display, base_qty}].
        Calcule les lignes et vérifie le stock avant validation (§5.5)."""
        lines = []
        total = 0
        with session_scope() as s:
            for it in items:
                price, factor = self.price_for(it["product_id"], it.get("packaging_id"),
                                               price_list_id)
                qty_base = it["quantity_display"] * factor + it.get("base_qty", 0)
                if it["quantity_display"] <= 0 and it.get("base_qty", 0) <= 0:
                    raise SalesError("Quantité nulle ou négative interdite.")
                p = s.get(Product, it["product_id"])
                bal = s.get(StockBalance, it["product_id"])
                avail = (bal.quantity - bal.reserved_quantity) if bal else 0
                if qty_base > avail:
                    raise SalesError(
                        f"Stock insuffisant pour {p.name} : disponible {avail}, demandé {qty_base}.")
                bal_q = bal.quantity
                cmp_cost = bal.weighted_avg_cost if bal else 0
                line_total = qty_base * price  # prix par unité de base si packaging=None
                if packaging_factor := factor:
                    pass
                lines.append({
                    "product_id": it["product_id"],
                    "packaging_id": it.get("packaging_id"),
                    "designation": p.name,
                    "unit_label": ("Unité" if not it.get("packaging_id") else None),
                    "quantity": qty_base,
                    "quantity_display": it["quantity_display"],
                    "base_qty": it.get("base_qty", 0),
                    "unit_price": price,
                    "factor": factor,
                    "unit_cost": cmp_cost,
                    "total": line_total,
                })
                total += line_total
        total -= manual_discount
        return {"lines": lines, "total": total, "discount": manual_discount}

    # --- validation atomique -------------------------------------------
    def confirm_sale(self, items: list[dict], payment_method: str,
                     paid_amount: int, customer_id: int | None = None,
                     price_list_id: int | None = None, manual_discount: int = 0,
                     deposit_packaging_id: int | None = None,
                     deposit_qty: int = 0, allow_credit_excess: bool = False) -> Sale:
        """Vente complète en une transaction (T03–T06, §7.2)."""
        cur = auth.Session.current()
        if payment_method not in PAYMENT_METHODS:
            raise SalesError("Moyen de paiement inconnu.")
        prep = self.draft_lines(items, price_list_id, manual_discount)
        total = prep["total"]
        if paid_amount < 0 or paid_amount > total and customer_id is None:
            paid_amount = total
        credit = total - paid_amount
        if credit > 0:
            if not customer_id:
                raise SalesError("Vente à crédit impossible sans client.")
        deposit_amount = 0
        if deposit_packaging_id and deposit_qty > 0:
            with session_scope() as s:
                rp = s.get(ReturnablePackaging, deposit_packaging_id)
                deposit_amount = rp.deposit_value * deposit_qty
            total += deposit_amount
            credit = total - paid_amount

        with session_scope() as s:
            # contrôle du plafond de crédit (§5.5)
            customer = None
            if customer_id:
                customer = s.get(Customer, customer_id)
                if credit > 0 and customer.credit_limit > 0:
                    projected = customer.balance + credit
                    if projected > customer.credit_limit and not allow_credit_excess:
                        auth.Session.current().require("customers.credit_override")
                        # sans la permission, blocage : procédure d'autorisation explicite
                        if not auth.Session.current().has_permission("customers.credit_override"):
                            raise SalesError(
                                f"Plafond de crédit dépassé ({projected} > {customer.credit_limit}).")
            number = next_document_number(s, "VTE")
            cash_session = s.scalar(select(CashSession).where(
                CashSession.status == "open",
                CashSession.user_id == (cur.user.id if cur else 0)))
            sale = Sale(number=number, customer_id=customer_id, status="confirmed",
                        total_amount=total, discount_amount=manual_discount,
                        deposit_amount=deposit_amount, paid_amount=paid_amount,
                        payment_method=payment_method,
                        cash_session_id=cash_session.id if cash_session else None,
                        user_id=cur.user.id if cur else None)
            s.add(sale)
            s.flush()

            for ln in prep["lines"]:
                s.add(SaleLine(
                    sale_id=sale.id, product_id=ln["product_id"],
                    packaging_id=ln["packaging_id"], designation=ln["designation"],
                    unit_label=ln["unit_label"] or "Casier/Unité",
                    quantity=ln["quantity"], quantity_display=ln["quantity_display"],
                    unit_price=ln["unit_price"], unit_cost=ln["unit_cost"],
                    total=ln["quantity"] * ln["unit_price"] if ln["factor"] == 1
                    else ln["quantity_display"] * ln["unit_price"] + ln["base_qty"] * ln["unit_price"]))
                # sortie de stock (coût CMP figé)
                try:
                    self.stock._apply(s, ln["product_id"], -ln["quantity"], "sortie_vente",
                                      document_type="sale", document_id=sale.id)
                except StockError as e:
                    raise SalesError(str(e))

            # consignes : emballages remis au client (§5.8)
            if deposit_amount:
                self._deposit_out(s, deposit_packaging_id, deposit_qty, customer_id, sale.id)

            # paiement + caisse
            if paid_amount > 0:
                cp = CustomerPayment(number=next_document_number(s, "PAY"),
                                     customer_id=customer_id, amount=paid_amount,
                                     payment_method=payment_method,
                                     sale_id=sale.id,
                                     cash_session_id=cash_session.id if cash_session else None,
                                     user_id=cur.user.id if cur else None)
                s.add(cp)
                s.flush()
                s.add(PaymentAllocation(payment_id=cp.id, sale_id=sale.id,
                                        amount=paid_amount))
                self._cash_movement(s, cash_session, "in", paid_amount, payment_method,
                                    "encaissement_vente", "sale", sale.id)
                if payment_method == "especes":
                    pass  # flux espèces uniquement dans le solde de caisse physique
            # créance
            if credit > 0:
                customer.balance += credit
                s.add(CustomerCreditEvent(customer_id=customer_id, delta=credit,
                                          reason="vente_credit",
                                          document_type="sale", document_id=sale.id))
            auth.log("sale_confirm", "Sale", sale.id, new_value=f"{number}={total}", session=s
            return sale

    def _deposit_out(self, s, packaging_id, qty, customer_id, sale_id):
        rp = s.get(ReturnablePackaging, packaging_id)
        cur = auth.Session.current()
        s.add(DepositMovement(packaging_id=packaging_id, quantity=qty,
                              reason="remis_client", customer_id=customer_id,
                              document_type="sale", document_id=sale_id,
                              deposit_value=rp.deposit_value,
                              user_id=cur.user.id if cur else None))

    def _cash_movement(self, s, session, direction, amount, method, reason,
                       doc_type=None, doc_id=None):
        """Seuls les flux espèces affectent le solde physique de caisse (§5.12)."""
        if session is None or method != "especes":
            return  # Mobile Money, virement : suivis séparément (T11)
        cur = auth.Session.current()
        s.add(CashMovement(session_id=session.id, direction=direction, amount=amount,
                           payment_method=method, reason=reason,
                           document_type=doc_type, document_id=doc_id,
                           user_id=cur.user.id if cur else None))

    # --- paiements de créances ------------------------------------------
    def pay_credit(self, customer_id: int, amount: int, payment_method: str = "especes",
                   sale_id: int | None = None) -> CustomerPayment:
        """Règlement partiel : réduit la créance sans modifier le CA (T06)."""
        if amount <= 0:
            raise SalesError("Montant de paiement invalide.")
        cur = auth.Session.current()
        with session_scope() as s:
            c = s.get(Customer, customer_id)
            if c.balance <= 0:
                raise SalesError("Aucune créance ouverte.")
            amount = min(amount, c.balance)  # affectation limitée au solde restant (§5.9)
            cash_session = s.scalar(select(CashSession).where(
                CashSession.status == "open",
                CashSession.user_id == (cur.user.id if cur else 0)))
            cp = CustomerPayment(number=next_document_number(s, "PAY"),
                                 customer_id=customer_id, amount=amount,
                                 payment_method=payment_method, sale_id=sale_id,
                                 cash_session_id=cash_session.id if cash_session else None,
                                 user_id=cur.user.id if cur else None)
            s.add(cp)
            s.flush()
            if sale_id:
                s.add(PaymentAllocation(payment_id=cp.id, sale_id=sale_id, amount=amount))
            c.balance -= amount
            s.add(CustomerCreditEvent(customer_id=customer_id, delta=-amount,
                                      reason="reglement",
                                      document_type="customer_payment", document_id=cp.id))
            self._cash_movement(s, cash_session, "in", amount, payment_method,
                                "reglement_creance", "customer_payment", cp.id)
            auth.log("payment_create", "CustomerPayment", cp.id, new_value=str(amount), session=s
            return cp

    # --- retours (§7.3) ---------------------------------------------------
    def return_sale(self, sale_id: int, returns: list[dict],
                    refund_method: str = "especes", reason: str | None = None) -> SaleReturn:
        """returns : [{sale_line_id, quantity(en base), resellable}].
        Contrepassation tracée, jamais de suppression (§7.3, T07)."""
        cur = auth.Session.current()
        with session_scope() as s:
            sale = s.get(Sale, sale_id)
            if sale is None or sale.status == "cancelled":
                raise SalesError("Vente introuvable ou annulée.")
            # les quantités retournées ne dépassent pas les quantités vendues (§7.3)
            returned_so_far = {}
            for prev in s.scalars(select(SaleReturnLine).where(
                    SaleReturnLine.sale_line_id.in_([r["sale_line_id"] for r in returns]))):
                returned_so_far[prev.sale_line_id] = \
                    returned_so_far.get(prev.sale_line_id, 0) + prev.quantity
            total_refund = 0
            with_lines = []
            for r in returns:
                sl = s.get(SaleLine, r["sale_line_id"])
                if sl.sale_id != sale_id:
                    raise SalesError("Ligne ne correspond pas à la vente.")
                already = returned_so_far.get(sl.id, 0)
                if r["quantity"] + already > sl.quantity:
                    raise SalesError(
                        f"Retour excessif : vendu {sl.quantity}, déjà retourné {already}.")
                refund = r["quantity"] * sl.unit_price
                total_refund += refund
                with_lines.append((sl, r))
            number = next_document_number(s, "RET")
            ret = SaleReturn(number=number, sale_id=sale_id, total_amount=total_refund,
                             refund_method=refund_method,
                             user_id=cur.user.id if cur else None, reason=reason)
            s.add(ret)
            s.flush()
            cash_session = s.scalar(select(CashSession).where(
                CashSession.status == "open",
                CashSession.user_id == (cur.user.id if cur else 0)))
            for sl, r in with_lines:
                s.add(SaleReturnLine(return_id=ret.id, sale_line_id=sl.id,
                                     quantity=r["quantity"],
                                     resellable=r.get("resellable", True)))
                # réintégration du stock si revendable (§7.3)
                if r.get("resellable", True):
                    self.stock._apply(s, sl.product_id, r["quantity"], "retour_client",
                                      document_type="sale_return", document_id=ret.id)
                else:
                    self.stock._apply(s, sl.product_id, -0, "casse",
                                      document_type="sale_return", document_id=ret.id) \
                        if False else None
            # remboursement
            sale.status = "partially_returned"
            if refund_method == "especes":
                self._cash_movement(s, cash_session, "out", total_refund, "especes",
                                    "remboursement_client", "sale_return", ret.id)
            if sale.customer_id:
                c = s.get(Customer, sale.customer_id)
                c.balance -= total_refund
                s.add(CustomerCreditEvent(customer_id=sale.customer_id,
                                          delta=-total_refund, reason="retour",
                                          document_type="sale_return", document_id=ret.id))
            auth.log("sale_return", "SaleReturn", ret.id, new_value=f"{number}={total_refund}", session=s
            return ret

    def cancel_sale(self, sale_id: int, reason: str) -> None:
        """Annulation tracée référençant le document d'origine (§7.3)."""
        auth.Session.current().require("sales.cancel")
        with session_scope() as s:
            sale = s.get(Sale, sale_id)
            if sale is None or sale.status == "cancelled":
                raise SalesError("Vente introuvable ou déjà annulée.")
            for sl in sale.lines:
                self.stock._apply(s, sl.product_id, sl.quantity, "retour_client",
                                  document_type="sale_cancel", document_id=sale.id,
                                  comment=f"Annulation vente {sale.number}: {reason}")
            sale.status = "cancelled"
            if sale.customer_id:
                credit_back = sale.total_amount - sale.paid_amount
                if credit_back > 0:
                    c = s.get(Customer, sale.customer_id)
                    c.balance -= credit_back
                    s.add(CustomerCreditEvent(customer_id=sale.customer_id,
                                              delta=-credit_back, reason="annulation",
                                              document_type="sale", document_id=sale.id))
            auth.log("sale_cancel", "Sale", sale_id, new_value=sale.number,
                     comment=reason, session=s

    # --- consultations -----------------------------------------------------
    def sales_of_period(self, start: datetime, end: datetime):
        with session_scope() as s:
            return list(s.scalars(select(Sale).where(
                Sale.at >= start, Sale.at <= end).order_by(Sale.at)))

    def customer_balance(self, customer_id: int) -> int:
        with session_scope() as s:
            return s.get(Customer, customer_id).balance

    def list_customers(self, search: str | None = None):
        with session_scope() as s:
            q = select(Customer).where(Customer.active == True)  # noqa: E712
            if search:
                q = q.where(Customer.name.ilike(f"%{search}%"))
            return list(s.scalars(q))

    def create_customer(self, code: str, name: str, phone=None, customer_type="detail",
                        price_list_id=None, credit_limit=0) -> Customer:
        with session_scope() as s:
            c = Customer(code=code, name=name, phone=phone, customer_type=customer_type,
                         price_list_id=price_list_id, credit_limit=credit_limit)
            s.add(c)
            auth.log("customer_create", "Customer", c.id, new_value=name, session=s
            s.flush()
            return c
