"""Service ventes/caisse : vente atomique, paiements, retours, crédits (§5.5, §7.2).

Toute validation de vente crée vente + lignes + mouvements de stock + mouvements
de caisse/paiement + solde client + consignes dans une SEULE transaction.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database.models import (
    CashMovement,
    Customer,
    CustomerCreditEvent,
    CustomerPayment,
    DepositMovement,
    PaymentAllocation,
    Product,
    ProductPackaging,
    ReturnablePackaging,
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
)
from ..database.session import next_document_number, session_scope
from ..security import auth
from . import common
from .catalog_service import CatalogService
from .stock_service import StockError, StockService

PAYMENT_METHODS = ["especes", "orange_money", "mtn_money", "moov_money", "wave",
                   "virement", "cheque", "autre"]

PAYMENT_LABELS = {
    "especes": "Espèces",
    "orange_money": "Orange Money",
    "mtn_money": "MTN Mobile Money",
    "moov_money": "Moov Money",
    "wave": "Wave",
    "virement": "Virement bancaire",
    "cheque": "Chèque",
    "autre": "Autre",
}


class SalesError(Exception):
    pass


class SalesService:
    def __init__(self):
        self.stock = StockService()
        self.catalog = CatalogService()

    # --- préparation du panier -------------------------------------------
    def price_for(self, product_id: int, packaging_id: int | None,
                  price_list_id: int | None) -> tuple[int, int]:
        """Retourne (prix appliqué au conditionnement, facteur de conversion)."""
        factor = self.catalog.factor_of(packaging_id)
        price = self.catalog.resolve_price(product_id, price_list_id, packaging_id)
        return price, factor

    def draft_lines(self, items: list[dict], price_list_id: int | None,
                    manual_discount: int = 0,
                    check_stock: bool = True) -> dict:
        """Calcule les lignes du panier.

        items : [{product_id, packaging_id, quantity_display, base_qty}]
        - la quantité est convertie en unités de base (§7.4)
        - le stock disponible est vérifié avant validation (§5.5)
        - le coût figé est le CMP courant du produit (T17)
        """
        if not items:
            raise SalesError("Le panier est vide.")
        lines = []
        total = 0
        with session_scope() as s:
            for it in items:
                product = s.get(Product, it["product_id"])
                if product is None:
                    raise SalesError("Produit introuvable.")
                if product.archived:
                    raise SalesError(f"Le produit {product.name} est archivé.")
                packaging_id = it.get("packaging_id") or None
                factor = 1
                unit_label = product.base_unit.name if product.base_unit else "Unité"
                if packaging_id:
                    pk = s.get(ProductPackaging, packaging_id)
                    if pk is None or pk.product_id != product.id:
                        raise SalesError("Conditionnement incompatible avec le produit.")
                    factor = pk.factor
                    unit_label = pk.name
                qty_display = int(it.get("quantity_display") or 0)
                base_qty = int(it.get("base_qty") or 0)
                if qty_display < 0 or base_qty < 0:
                    raise SalesError("Quantité négative interdite.")
                qty_base = qty_display * factor + base_qty
                if qty_base <= 0:
                    raise SalesError("Quantité nulle interdite.")
                if check_stock:
                    avail = common.available_quantity(s, product.id)
                    if qty_base > avail:
                        raise SalesError(
                            f"Stock insuffisant pour {product.name} : "
                            f"disponible {avail}, demandé {qty_base}.")
                price = self.catalog.resolve_price(product.id, price_list_id,
                                                   packaging_id)
                if price <= 0:
                    raise SalesError(
                        f"Aucun prix défini pour {product.name} ({unit_label}).")
                bal = common.get_balance(s, product.id)
                # total de ligne = prix au conditionnement × nb de conditionnements
                #                    + reliquat à l'unité de base (§7.5)
                if packaging_id:
                    unit_base_price = self.catalog.resolve_price(
                        product.id, price_list_id, None)
                    line_total = qty_display * price + base_qty * unit_base_price
                else:
                    line_total = qty_base * price
                lines.append({
                    "product_id": product.id,
                    "packaging_id": packaging_id,
                    "designation": product.name,
                    "unit_label": unit_label,
                    "quantity": qty_base,
                    "quantity_display": qty_display,
                    "base_qty": base_qty,
                    "unit_price": price,
                    "factor": factor,
                    "unit_cost": bal.weighted_avg_cost or product.current_cost,
                    "total": line_total,
                })
                total += line_total
        gross = total
        if manual_discount < 0:
            raise SalesError("Remise négative interdite.")
        if manual_discount > gross:
            raise SalesError("La remise dépasse le total de la vente.")
        return {"lines": lines, "gross_total": gross,
                "total": gross - manual_discount, "discount": manual_discount}

    # --- validation atomique ---------------------------------------------
    def confirm_sale(self, items: list[dict], payment_method: str,
                     paid_amount: int, customer_id: int | None = None,
                     price_list_id: int | None = None, manual_discount: int = 0,
                     deposit_packaging_id: int | None = None,
                     deposit_qty: int = 0,
                     allow_credit_excess: bool = False,
                     note: str | None = None) -> Sale:
        """Vente complète en une transaction (T03–T06, §7.2)."""
        common.require("sales.create")
        if payment_method not in PAYMENT_METHODS:
            raise SalesError("Moyen de paiement inconnu.")
        if paid_amount < 0:
            raise SalesError("Montant encaissé invalide.")
        if manual_discount and not common.has_permission("sales.discount"):
            raise SalesError("Remise non autorisée pour cet utilisateur.")

        prep = self.draft_lines(items, price_list_id, manual_discount)
        total_goods = prep["total"]
        deposit_amount = 0
        if deposit_qty > 0:
            if not deposit_packaging_id:
                raise SalesError("Précisez le type d'emballage consigné.")
            with session_scope() as s:
                rp = s.get(ReturnablePackaging, deposit_packaging_id)
                if rp is None:
                    raise SalesError("Type d'emballage inconnu.")
                deposit_amount = rp.deposit_value * deposit_qty
        total = total_goods + deposit_amount
        if paid_amount > total:
            raise SalesError("Le montant encaissé dépasse le total à payer.")
        credit = total - paid_amount
        if credit > 0 and not customer_id:
            raise SalesError("Vente à crédit impossible sans client identifié.")

        user_id = common.current_user_id()
        with session_scope() as s:
            customer = None
            if customer_id:
                customer = s.get(Customer, customer_id)
                if customer is None:
                    raise SalesError("Client introuvable.")
                if not customer.active:
                    raise SalesError("Client inactif.")
                if credit > 0 and customer.credit_limit > 0:
                    projected = customer.balance + credit
                    if projected > customer.credit_limit:
                        # T04/§5.5 : blocage sauf autorisation explicite tracée
                        if not allow_credit_excess or not common.has_permission(
                                "customers.credit_override"):
                            raise SalesError(
                                f"Plafond de crédit dépassé : dû {customer.balance} + "
                                f"{credit} > plafond {customer.credit_limit}.")
                        auth.log("credit_limit_override", "Customer", customer.id,
                                 new_value=str(projected), session=s)

            number = next_document_number(s, "VTE")
            cash_session = common.open_cash_session(s, user_id)
            sale = Sale(number=number, customer_id=customer_id, status="confirmed",
                        total_amount=total, discount_amount=manual_discount,
                        deposit_amount=deposit_amount, paid_amount=paid_amount,
                        payment_method=payment_method,
                        cash_session_id=cash_session.id if cash_session else None,
                        user_id=user_id, note=note)
            s.add(sale)
            s.flush()

            for ln in prep["lines"]:
                # la collection est alimentée en mémoire pour rester lisible
                # après fermeture de la session (objets détachés)
                sale.lines.append(SaleLine(
                    sale=sale, product_id=ln["product_id"],
                    packaging_id=ln["packaging_id"], designation=ln["designation"],
                    unit_label=ln["unit_label"], quantity=ln["quantity"],
                    quantity_display=ln["quantity_display"],
                    unit_price=ln["unit_price"], discount=0,
                    unit_cost=ln["unit_cost"], total=ln["total"]))
                try:
                    # sortie de stock, coût CMP figé sur la ligne de vente
                    self.stock._apply(s, ln["product_id"], -ln["quantity"],
                                      "sortie_vente", document_type="sale",
                                      document_id=sale.id,
                                      unit_cost=ln["unit_cost"])
                except StockError as exc:
                    raise SalesError(str(exc)) from exc

            # consignes : emballages remis au client, distincts du CA (§5.8)
            if deposit_amount:
                rp = s.get(ReturnablePackaging, deposit_packaging_id)
                s.add(DepositMovement(packaging_id=deposit_packaging_id,
                                      quantity=deposit_qty, reason="remis_client",
                                      customer_id=customer_id,
                                      document_type="sale", document_id=sale.id,
                                      deposit_value=rp.deposit_value,
                                      user_id=user_id))
                self._cash_movement(s, cash_session, "in", deposit_amount,
                                    payment_method, "consigne", "sale", sale.id)

            # paiement + caisse (§5.12)
            if paid_amount > 0:
                cp = CustomerPayment(number=next_document_number(s, "PAY"),
                                     customer_id=customer_id, amount=paid_amount,
                                     payment_method=payment_method, sale_id=sale.id,
                                     cash_session_id=cash_session.id
                                     if cash_session else None,
                                     user_id=user_id)
                s.add(cp)
                s.flush()
                s.add(PaymentAllocation(payment_id=cp.id, sale_id=sale.id,
                                        amount=min(paid_amount, total_goods)))
                self._cash_movement(s, cash_session, "in", paid_amount,
                                    payment_method, "encaissement_vente",
                                    "sale", sale.id)

            # créance (§5.9)
            if credit > 0:
                assert customer is not None
                customer.balance += credit
                s.add(CustomerCreditEvent(customer_id=customer.id, delta=credit,
                                          reason="vente_credit",
                                          document_type="sale", document_id=sale.id))

            auth.log("sale_confirm", "Sale", sale.id,
                     new_value=f"{number}={total}", session=s)
            return sale

    def _cash_movement(self, s: Session, cash_session, direction: str, amount: int,
                       method: str, reason: str, doc_type=None, doc_id=None):
        """Seuls les flux espèces alimentent le solde physique de caisse (§5.12).

        Les encaissements Mobile Money / virement sont enregistrés comme
        mouvements non-espèces afin de rester consultables (T11).
        """
        if cash_session is None or amount == 0:
            return
        s.add(CashMovement(session_id=cash_session.id, direction=direction,
                           amount=amount, payment_method=method, reason=reason,
                           document_type=doc_type, document_id=doc_id,
                           user_id=common.current_user_id()))

    # --- paiements de créances --------------------------------------------
    def pay_credit(self, customer_id: int, amount: int, payment_method: str = "especes",
                   sale_id: int | None = None,
                   comment: str | None = None) -> CustomerPayment:
        """Règlement partiel : réduit la créance sans modifier le CA (T06)."""
        common.require("payments.create")
        if amount <= 0:
            raise SalesError("Montant de paiement invalide.")
        if payment_method not in PAYMENT_METHODS:
            raise SalesError("Moyen de paiement inconnu.")
        user_id = common.current_user_id()
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise SalesError("Client introuvable.")
            if customer.balance <= 0:
                raise SalesError("Aucune créance ouverte pour ce client.")
            amount = min(amount, customer.balance)  # §5.9 : limite du solde restant
            cash_session = common.open_cash_session(s, user_id)
            cp = CustomerPayment(number=next_document_number(s, "PAY"),
                                 customer_id=customer_id, amount=amount,
                                 payment_method=payment_method, sale_id=sale_id,
                                 cash_session_id=cash_session.id
                                 if cash_session else None,
                                 user_id=user_id, comment=comment)
            s.add(cp)
            s.flush()
            if sale_id:
                due = self._sale_outstanding(s, sale_id)
                s.add(PaymentAllocation(payment_id=cp.id, sale_id=sale_id,
                                        amount=min(amount, due)))
            customer.balance -= amount
            s.add(CustomerCreditEvent(customer_id=customer_id, delta=-amount,
                                      reason="reglement",
                                      document_type="customer_payment",
                                      document_id=cp.id))
            self._cash_movement(s, cash_session, "in", amount, payment_method,
                                "reglement_creance", "customer_payment", cp.id)
            auth.log("payment_create", "CustomerPayment", cp.id,
                     new_value=str(amount), session=s)
            return cp

    def _sale_cash_collected(self, s: Session, sale_id: int) -> int:
        """Montant encore réellement encaissé (espèces) sur une vente.

        Sert de plafond aux remboursements : on ne rembourse pas plus que ce qui
        a été encaissé. La part réglée au-delà (Mobile Money, virement) est
        remboursée par le même moyen, hors caisse espèces.
        """
        sale = s.get(Sale, sale_id)
        if sale is None:
            return 0
        collected = s.scalar(select(func.coalesce(func.sum(CashMovement.amount), 0))
                             .where(CashMovement.document_type == "sale",
                                    CashMovement.document_id == sale_id,
                                    CashMovement.direction == "in",
                                    CashMovement.payment_method == "especes")) or 0
        refunded = s.scalar(select(func.coalesce(func.sum(CashMovement.amount), 0))
                            .where(CashMovement.document_type == "sale_return",
                                   CashMovement.direction == "out",
                                   CashMovement.payment_method == "especes",
                                   CashMovement.document_id.in_(
                                       select(SaleReturn.id).where(
                                           SaleReturn.sale_id == sale_id)))) or 0
        return max(int(collected) - int(refunded), 0)

    def _sale_outstanding(self, s: Session, sale_id: int) -> int:
        sale = s.get(Sale, sale_id)
        if sale is None:
            return 0
        allocated = s.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
                             .where(PaymentAllocation.sale_id == sale_id)) or 0
        returned = s.scalar(select(func.coalesce(func.sum(SaleReturn.total_amount), 0))
                            .where(SaleReturn.sale_id == sale_id)) or 0
        return max(sale.total_amount - allocated - returned, 0)

    def customer_statement(self, customer_id: int):
        """Relevé de compte : ventes, paiements, retours et solde (§5.9)."""
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise SalesError("Client introuvable.")
            sales = list(s.scalars(select(Sale).where(Sale.customer_id == customer_id)
                                   .order_by(Sale.at)))
            payments = list(s.scalars(select(CustomerPayment)
                                      .where(CustomerPayment.customer_id == customer_id)
                                      .order_by(CustomerPayment.at)))
            returns = list(s.scalars(select(SaleReturn).join(
                Sale, Sale.id == SaleReturn.sale_id)
                .where(Sale.customer_id == customer_id).order_by(SaleReturn.at)))
            return {"customer": customer, "sales": sales, "payments": payments,
                    "returns": returns, "balance": customer.balance}

    # --- retours (§7.3) -----------------------------------------------------
    def return_sale(self, sale_id: int, returns: list[dict],
                    refund_method: str = "especes",
                    reason: str | None = None) -> SaleReturn:
        """returns : [{sale_line_id, quantity (unités de base), resellable}].

        Contrepassation tracée, jamais de suppression (§7.3, T07).
        """
        common.require("sales.return")
        if not returns:
            raise SalesError("Aucune ligne à retourner.")
        if refund_method not in ("especes", "avoir", "autre"):
            raise SalesError("Mode de remboursement inconnu.")
        user_id = common.current_user_id()
        with session_scope() as s:
            sale = s.get(Sale, sale_id)
            if sale is None or sale.status == "cancelled":
                raise SalesError("Vente introuvable ou annulée.")
            returned_so_far: dict[int, int] = {}
            for line_id, qty in s.execute(
                    select(SaleReturnLine.sale_line_id, func.sum(SaleReturnLine.quantity))
                    .where(SaleReturnLine.sale_line_id.in_(
                        [r["sale_line_id"] for r in returns]))
                    .group_by(SaleReturnLine.sale_line_id)).all():
                returned_so_far[line_id] = int(qty or 0)

            total_refund = 0
            prepared = []
            for r in returns:
                sl = s.get(SaleLine, r["sale_line_id"])
                if sl is None or sl.sale_id != sale_id:
                    raise SalesError("Ligne ne correspondant pas à la vente.")
                qty = int(r.get("quantity") or 0)
                if qty <= 0:
                    raise SalesError("Quantité retournée invalide.")
                already = returned_so_far.get(sl.id, 0)
                if qty + already > sl.quantity:
                    raise SalesError(
                        f"Retour excessif sur {sl.designation} : vendu {sl.quantity}, "
                        f"déjà retourné {already}, demandé {qty}.")
                # remboursement au prorata du prix réellement facturé
                unit_refund = sl.total / sl.quantity if sl.quantity else 0
                total_refund += round(qty * unit_refund)
                prepared.append((sl, r, qty))

            number = next_document_number(s, "RET")
            ret = SaleReturn(number=number, sale_id=sale_id,
                             total_amount=total_refund, refund_method=refund_method,
                             user_id=user_id, reason=reason)
            s.add(ret)
            s.flush()
            cash_session = common.open_cash_session(s, user_id)
            for sl, r, qty in prepared:
                resellable = bool(r.get("resellable", True))
                s.add(SaleReturnLine(return_id=ret.id, sale_line_id=sl.id,
                                     quantity=qty, resellable=resellable))
                if resellable:
                    # marchandise physiquement récupérée et revendable (§7.3)
                    self.stock._apply(s, sl.product_id, qty, "retour_client",
                                      document_type="sale_return", document_id=ret.id)
                # non revendable : la marchandise n'entre pas en stock

            # statut : tout retourné ou partiellement
            total_sold = sum(l.quantity for l in sale.lines)
            total_returned = (s.scalar(
                select(func.coalesce(func.sum(SaleReturnLine.quantity), 0))
                .join(SaleReturn, SaleReturn.id == SaleReturnLine.return_id)
                .where(SaleReturn.sale_id == sale_id)) or 0)
            sale.status = ("returned" if total_returned >= total_sold
                           else "partially_returned")

            if refund_method == "especes":
                # on ne sort de la caisse que ce qui y est réellement entré (§5.12)
                already_returned = s.scalar(
                    select(func.coalesce(func.sum(SaleReturn.total_amount), 0))
                    .where(SaleReturn.sale_id == sale_id,
                           SaleReturn.id != ret.id)) or 0
                refundable = max(self._sale_cash_collected(s, sale_id),
                                 int(sale.paid_amount) - int(already_returned))
                cash_refund = min(total_refund, refundable)
                if cash_refund:
                    self._cash_movement(s, cash_session, "out", cash_refund,
                                        "especes", "remboursement_client",
                                        "sale_return", ret.id)
            if sale.customer_id:
                customer = s.get(Customer, sale.customer_id)
                # un retour réduit d'abord la dette du client ; au-delà, il reste un
                # trop-perçu/avoir que le remboursement espèces vient solder.
                due_reduction = min(total_refund, max(customer.balance, 0))
                if due_reduction:
                    customer.balance -= due_reduction
                    s.add(CustomerCreditEvent(customer_id=sale.customer_id,
                                              delta=-due_reduction, reason="retour",
                                              document_type="sale_return",
                                              document_id=ret.id))
            auth.log("sale_return", "SaleReturn", ret.id,
                     new_value=f"{number}={total_refund}", comment=reason, session=s)
            return ret

    def cancel_sale(self, sale_id: int, reason: str) -> None:
        """Annulation tracée référençant le document d'origine (§7.3)."""
        common.require("sales.cancel")
        with session_scope() as s:
            sale = s.get(Sale, sale_id)
            if sale is None:
                raise SalesError("Vente introuvable.")
            if sale.status == "cancelled":
                raise SalesError("Vente déjà annulée.")
            if not (reason or "").strip():
                raise SalesError("Le motif d'annulation est obligatoire.")
            for sl in sale.lines:
                self.stock._apply(s, sl.product_id, sl.quantity, "retour_client",
                                  document_type="sale_cancel", document_id=sale.id,
                                  comment=f"Annulation vente {sale.number}: {reason}")
            sale.status = "cancelled"
            if sale.customer_id:
                credit_back = self._sale_outstanding(s, sale.id)
                if credit_back > 0:
                    customer = s.get(Customer, sale.customer_id)
                    customer.balance = max(customer.balance - credit_back, 0)
                    s.add(CustomerCreditEvent(customer_id=sale.customer_id,
                                              delta=-credit_back, reason="annulation",
                                              document_type="sale", document_id=sale.id))
            auth.log("sale_cancel", "Sale", sale_id, new_value=sale.number,
                     comment=reason, session=s)

    # --- consultations ------------------------------------------------------
    def sales_of_period(self, start: datetime, end: datetime):
        with session_scope() as s:
            return list(s.scalars(select(Sale).where(
                Sale.at >= start, Sale.at <= end)
                .order_by(Sale.at.desc())))

    def recent_sales(self, limit: int = 50):
        with session_scope() as s:
            return list(s.scalars(select(Sale).order_by(Sale.at.desc(),
                                                        Sale.id.desc()).limit(limit)))

    def get_sale(self, sale_id: int) -> Sale:
        with session_scope() as s:
            sale = s.get(Sale, sale_id)
            if sale is None:
                raise SalesError("Vente introuvable.")
            return sale

    def customer_balance(self, customer_id: int) -> int:
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise SalesError("Client introuvable.")
            return customer.balance

    def list_customers(self, search: str | None = None):
        with session_scope() as s:
            q = select(Customer).where(Customer.active.is_(True))
            if search:
                like = f"%{search}%"
                q = q.where(Customer.name.ilike(like) | Customer.code.ilike(like)
                            | Customer.phone.ilike(like))
            return list(s.scalars(q.order_by(Customer.name)))

    def get_customer(self, customer_id: int) -> Customer:
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise SalesError("Client introuvable.")
            return customer

    def create_customer(self, code: str, name: str, phone=None, customer_type="detail",
                        price_list_id=None, credit_limit=0, address=None) -> Customer:
        common.require("customers.manage")
        code = (code or "").strip()
        name = (name or "").strip()
        if not code or not name:
            raise SalesError("Le code et le nom du client sont obligatoires.")
        if credit_limit < 0:
            raise SalesError("Plafond de crédit invalide.")
        with session_scope() as s:
            if s.scalar(select(Customer.id).where(Customer.code == code)):
                raise SalesError(f"Le code client {code} existe déjà.")
            customer = Customer(code=code, name=name, phone=phone,
                                customer_type=customer_type, address=address,
                                price_list_id=price_list_id,
                                credit_limit=credit_limit)
            s.add(customer)
            s.flush()
            auth.log("customer_create", "Customer", customer.id, new_value=name,
                     session=s)
            return customer

    def update_customer(self, customer_id: int, **fields) -> None:
        common.require("customers.manage")
        allowed = {"name", "phone", "address", "customer_type", "price_list_id",
                   "credit_limit", "active"}
        unknown = set(fields) - allowed
        if unknown:
            raise SalesError(f"Champs non modifiables : {', '.join(sorted(unknown))}")
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise SalesError("Client introuvable.")
            old = {k: getattr(customer, k) for k in fields}
            for k, v in fields.items():
                setattr(customer, k, v)
            auth.log("customer_update", "Customer", customer_id, old_value=str(old),
                     new_value=str(fields), session=s)

    def archive_customer(self, customer_id: int) -> None:
        """Désactivation logique : l'historique reste consultable (§5.9)."""
        common.require("customers.manage")
        with session_scope() as s:
            customer = s.get(Customer, customer_id)
            if customer is None:
                raise SalesError("Client introuvable.")
            customer.active = False
            auth.log("customer_archive", "Customer", customer_id, session=s)

    def daily_takings(self, day_start: datetime, day_end: datetime):
        """Encaissements par moyen de paiement (§5.4, §5.12)."""
        with session_scope() as s:
            rows = s.execute(
                select(CashMovement.payment_method,
                       func.sum(CashMovement.amount))
                .where(CashMovement.at >= day_start, CashMovement.at <= day_end,
                       CashMovement.direction == "in")
                .group_by(CashMovement.payment_method)).all()
            return {method: int(amount or 0) for method, amount in rows}

    def sales_summary(self, start: datetime, end: datetime) -> dict:
        """Chiffre d'affaires net des retours et coût des marchandises vendues."""
        with session_scope() as s:
            gross = s.scalar(select(func.coalesce(func.sum(Sale.total_amount), 0))
                             .where(Sale.at >= start, Sale.at <= end,
                                    Sale.status != "cancelled")) or 0
            discounts = s.scalar(select(func.coalesce(func.sum(Sale.discount_amount), 0))
                                 .where(Sale.at >= start, Sale.at <= end,
                                        Sale.status != "cancelled")) or 0
            deposits = s.scalar(select(func.coalesce(func.sum(Sale.deposit_amount), 0))
                                .where(Sale.at >= start, Sale.at <= end,
                                       Sale.status != "cancelled")) or 0
            returns = s.scalar(select(func.coalesce(func.sum(SaleReturn.total_amount), 0))
                               .where(SaleReturn.at >= start, SaleReturn.at <= end)) or 0
            cogs = s.scalar(select(func.coalesce(
                func.sum(SaleLine.quantity * SaleLine.unit_cost), 0))
                .join(Sale, Sale.id == SaleLine.sale_id)
                .where(Sale.at >= start, Sale.at <= end,
                       Sale.status != "cancelled")) or 0
            # un retour réintègre la marchandise : son coût sort du coût vendu (§5.14)
            returned_cogs = s.scalar(select(func.coalesce(
                func.sum(SaleReturnLine.quantity * SaleLine.unit_cost), 0))
                .join(SaleLine, SaleLine.id == SaleReturnLine.sale_line_id)
                .join(SaleReturn, SaleReturn.id == SaleReturnLine.return_id)
                .where(SaleReturn.at >= start, SaleReturn.at <= end)) or 0
            count = s.scalar(select(func.count(Sale.id))
                             .where(Sale.at >= start, Sale.at <= end,
                                    Sale.status != "cancelled")) or 0
            net_sales = int(gross) - int(deposits) - int(returns)
            net_cogs = int(cogs) - int(returned_cogs)
            return {
                "sales_count": int(count),
                "gross_sales": int(gross),
                "discounts": int(discounts),
                "deposits": int(deposits),
                "returns": int(returns),
                "net_sales": net_sales,
                "cogs": net_cogs,
                "gross_margin": net_sales - net_cogs,
            }
