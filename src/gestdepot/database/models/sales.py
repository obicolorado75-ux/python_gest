"""Clients, ventes, retours, paiements (§6.5)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .catalog import PriceList  # noqa: F401  (annotation de relation)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    customer_type: Mapped[str] = mapped_column(String(40), default="detail")  # detail, gros, revendeur
    price_list_id: Mapped[int | None] = mapped_column(ForeignKey("price_lists.id"))
    credit_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = pas de crédit
    balance: Mapped[int] = mapped_column(Integer, default=0)       # solde dû, XOF
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    price_list: Mapped["PriceList | None"] = relationship(lazy="joined")


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # VTE-2026-000001
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft, confirmed, partially_returned, cancelled
    total_amount: Mapped[int] = mapped_column(Integer, default=0)   # total figé, XOF
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)
    deposit_amount: Mapped[int] = mapped_column(Integer, default=0)  # consignes séparées du CA
    paid_amount: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str | None] = mapped_column(String(40))
    cash_session_id: Mapped[int | None] = mapped_column(ForeignKey("cash_sessions.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["SaleLine"]] = relationship(back_populates="sale", lazy="selectin")
    customer: Mapped["Customer | None"] = relationship(lazy="joined")


class SaleLine(Base):
    """Instantané figé : désignation, unité, prix, remise, coût (§5.5, §6.9)."""
    __tablename__ = "sale_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    packaging_id: Mapped[int | None] = mapped_column(ForeignKey("product_packagings.id"))
    designation: Mapped[str] = mapped_column(String(200))  # figée
    unit_label: Mapped[str] = mapped_column(String(60))    # figée, ex "Casier"
    quantity: Mapped[int] = mapped_column(Integer)          # en unités de base (T03 : 51)
    quantity_display: Mapped[int] = mapped_column(Integer, default=1)  # nb de conditionnements
    unit_price: Mapped[int] = mapped_column(Integer)        # prix appliqué, figé
    discount: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[int] = mapped_column(Integer)         # coût CMP figé à la vente (T17)
    total: Mapped[int] = mapped_column(Integer)

    sale: Mapped["Sale"] = relationship(back_populates="lines")


class SaleReturn(Base):
    __tablename__ = "sale_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    refund_method: Mapped[str] = mapped_column(String(40), default="especes")  # especes, avoir, autre
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["SaleReturnLine"]] = relationship(back_populates="return_", lazy="selectin")


class SaleReturnLine(Base):
    __tablename__ = "sale_return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("sale_returns.id"), index=True)
    sale_line_id: Mapped[int] = mapped_column(ForeignKey("sale_lines.id"))
    quantity: Mapped[int] = mapped_column(Integer)  # en unités de base
    resellable: Mapped[bool] = mapped_column(Boolean, default=True)  # §7.3

    return_: Mapped["SaleReturn"] = relationship(back_populates="lines")


class CustomerPayment(Base):
    __tablename__ = "customer_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    # NULL = encaissement au comptoir (vente sans client identifié)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"),
                                                    index=True)
    amount: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(40), default="especes")
    cash_session_id: Mapped[int | None] = mapped_column(ForeignKey("cash_sessions.id"))
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)


class SalePayment(Base):
    """Détail des encaissements d'une vente (§5.5 : paiement mixte).

    Une vente peut être réglée par plusieurs moyens (ex. 10 000 en espèces +
    5 000 par Wave). ``sales.payment_method`` reste renseigné avec le moyen
    principal pour l'affichage rapide ; le détail vit ici et chaque ligne
    alimente la caisse avec son propre moyen de paiement (§5.12).
    """
    __tablename__ = "sale_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    payment_method: Mapped[str] = mapped_column(String(40))
    amount: Mapped[int] = mapped_column(Integer)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_payments.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class HeldSale(Base):
    """Vente suspendue au comptoir (§5.5 : « suspendre / reprendre une vente »).

    Le panier est conservé en JSON, sans aucune écriture de stock, de caisse ni
    de créance : une vente suspendue n'existe pas encore comptablement. Elle
    n'est pas un document numéroté (VTE-…) tant qu'elle n'est pas validée.
    """
    __tablename__ = "held_sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    price_list_id: Mapped[int | None] = mapped_column(ForeignKey("price_lists.id"))
    deposit_packaging_id: Mapped[int | None] = mapped_column(
        ForeignKey("returnable_packaging.id"))
    deposit_qty: Mapped[int] = mapped_column(Integer, default=0)
    discount: Mapped[int] = mapped_column(Integer, default=0)
    items_json: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)

    customer: Mapped["Customer | None"] = relationship(lazy="joined")


class PaymentAllocation(Base):
    """Affectation d'un paiement à une ou plusieurs ventes (§5.9)."""
    __tablename__ = "payment_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("customer_payments.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)


class CustomerCreditEvent(Base):
    """Journal du compte client : créances, règlements, avoirs (§6.5)."""
    __tablename__ = "customer_credit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    delta: Mapped[int] = mapped_column(Integer)  # + créance, - règlement
    reason: Mapped[str] = mapped_column(String(40))
    document_type: Mapped[str | None] = mapped_column(String(40))
    document_id: Mapped[int | None] = mapped_column(Integer)
