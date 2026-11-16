"""Stock, lots, inventaires (§6.3)."""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .catalog import Product  # noqa: F401  (annotation de relation)


class StockMovement(Base):
    """Journal immuable : preuve métier (§6.9). Une sortie de vente n'est jamais effacée."""
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)  # signée, en unités de base
    reason: Mapped[str] = mapped_column(String(40), index=True)
    # réception, sortie_vente, retour_client, retour_fournisseur, casse, perte,
    # peremption, correction_inventaire, mouvement_initial
    document_type: Mapped[str | None] = mapped_column(String(40))
    document_id: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[int | None] = mapped_column(Integer)  # XOF / unité de base
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batches.id"))
    comment: Mapped[str | None] = mapped_column(Text)

    product: Mapped["Product"] = relationship("Product", lazy="joined")


class StockBalance(Base):
    """Solde courant maintenu par le service de stock, rapprochable du journal."""
    __tablename__ = "stock_balances"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)        # unités de base
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0)
    weighted_avg_cost: Mapped[int] = mapped_column(Integer, default=0)  # CMP, XOF


class InventorySession(Base):
    __tablename__ = "inventory_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)  # INV-2026-000001
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft → counting → reviewed (contrôle des écarts) → validated ;
    # une session validée n'est plus modifiable : seule une nouvelle
    # régularisation (nouvel inventaire) peut corriger (§5.13)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime)
    validated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # écart de valeur au-delà duquel un contrôle est exigé (§5.13 étape 6)
    threshold_value: Mapped[int] = mapped_column(Integer, default=0)
    review_note: Mapped[str | None] = mapped_column(Text)


class InventoryLine(Base):
    __tablename__ = "inventory_lines"
    __table_args__ = (UniqueConstraint("session_id", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("inventory_sessions.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    theoretical_qty: Mapped[int] = mapped_column(Integer)  # stock théorique au démarrage
    counted_qty: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(Integer)             # coût retenu, XOF
    counted_at: Mapped[datetime | None] = mapped_column(DateTime)
    # contrôle des écarts importants (§5.13 étape 6)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    review_comment: Mapped[str | None] = mapped_column(Text)


class ProductBatch(Base):
    __tablename__ = "product_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    batch_number: Mapped[str | None] = mapped_column(String(60))
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
