"""Livraisons, caisse, dépenses, sauvegardes, numérotation (§6.7, §6.8)."""
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # CMD-...
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    desired_date: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # draft, confirmed, preparing, ready, partially_delivered, delivered, cancelled
    # brouillon => aucune modification de stock (§5.10)
    reserve_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    delivery_fee: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["CustomerOrderLine"]] = relationship(back_populates="order", lazy="selectin")


class CustomerOrderLine(Base):
    __tablename__ = "customer_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("customer_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    packaging_id: Mapped[int | None] = mapped_column(ForeignKey("product_packagings.id"))
    designation: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)          # unités de base
    quantity_display: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int] = mapped_column(Integer)
    delivered_qty: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)

    order: Mapped["CustomerOrder"] = relationship(back_populates="lines")


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # LIV-...
    order_id: Mapped[int | None] = mapped_column(ForeignKey("customer_orders.id"), index=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    driver: Mapped[str | None] = mapped_column(String(120))
    vehicle: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    scheduled_date: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending, preparing, in_transit, delivered, failed, cancelled
    fee: Mapped[int] = mapped_column(Integer, default=0)
    proof_comment: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["DeliveryLine"]] = relationship(back_populates="delivery", lazy="selectin")


class DeliveryLine(Base):
    __tablename__ = "delivery_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    prepared_qty: Mapped[int] = mapped_column(Integer, default=0)   # unités de base
    delivered_qty: Mapped[int] = mapped_column(Integer, default=0)

    delivery: Mapped["Delivery"] = relationship(back_populates="lines")


class CashSession(Base):
    """Ouverture, mouvements, clôture (§5.12)."""
    __tablename__ = "cash_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    opening_fund: Mapped[int] = mapped_column(Integer, default=0)       # fond initial
    theoretical_amount: Mapped[int | None] = mapped_column(Integer)      # montant théorique
    counted_amount: Mapped[int | None] = mapped_column(Integer)          # montant compté
    difference: Mapped[int | None] = mapped_column(Integer)              # écart conservé
    close_comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")      # open, closed


class CashMovement(Base):
    __tablename__ = "cash_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("cash_sessions.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    direction: Mapped[str] = mapped_column(String(10))   # in / out
    amount: Mapped[int] = mapped_column(Integer)          # XOF entier
    payment_method: Mapped[str] = mapped_column(String(40), default="especes")
    reason: Mapped[str] = mapped_column(String(40), index=True)
    # encaissement_vente, reglement_creance, remboursement_client, paiement_fournisseur,
    # depense, retrait, apport, consigne, correction
    document_type: Mapped[str | None] = mapped_column(String(40))
    document_id: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)  # DEP-2026-000001
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("expense_categories.id"))
    beneficiary: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(40), default="especes")
    receipt_path: Mapped[str | None] = mapped_column(String(500))  # justificatif
    comment: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("cash_sessions.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class BackupHistory(Base):
    __tablename__ = "backup_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    checksum: Mapped[str | None] = mapped_column(String(128))  # empreinte (§8.2)
    message: Mapped[str | None] = mapped_column(Text)


class DocumentSequence(Base):
    """Compteur de numérotation, géré en base dans la transaction (§7.1)."""
    __tablename__ = "document_sequences"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)  # "VTE", "ACH"...
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(60))
    file_path: Mapped[str | None] = mapped_column(String(500))
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
