"""Fournisseurs, achats, réceptions, factures, paiements (§6.6)."""
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .catalog import Product  # noqa: F401  (annotation de relation)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    contact: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(String(120))   # conditions
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    balance: Mapped[int] = mapped_column(Integer, default=0)  # solde dû, XOF
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # ACH-2026-000001
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    expected_date: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft, confirmed, partially_received, received, cancelled — ne touche jamais le stock (§5.11)
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(back_populates="order", lazy="selectin")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    packaging_id: Mapped[int | None] = mapped_column(ForeignKey("product_packagings.id"))
    designation: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)        # en unités de base
    quantity_display: Mapped[int] = mapped_column(Integer, default=1)
    unit_cost: Mapped[int] = mapped_column(Integer)       # prix convenu, XOF
    received_qty: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship(lazy="joined")


class GoodsReceipt(Base):
    """Seule une réception validée augmente le stock (§5.11)."""
    __tablename__ = "goods_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # REC-2026-000001
    order_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    invoice_created: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["GoodsReceiptLine"]] = relationship(back_populates="receipt", lazy="selectin")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    order_line_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)         # unités de base reçues
    quantity_refused: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[int] = mapped_column(Integer)        # coût constaté
    batch_number: Mapped[str | None] = mapped_column(String(60))
    expiry_date: Mapped[Date | None] = mapped_column(Date)

    receipt: Mapped["GoodsReceipt"] = relationship(back_populates="lines")


class SupplierInvoice(Base):
    __tablename__ = "supplier_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(40))
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    paid_amount: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[Date | None] = mapped_column(Date)


class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    amount: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(40), default="especes")
    cash_session_id: Mapped[int | None] = mapped_column(ForeignKey("cash_sessions.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_invoices.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
