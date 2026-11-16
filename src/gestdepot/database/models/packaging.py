"""Consignes et emballages (§6.4)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ReturnablePackaging(Base):
    """Casier, bouteille, fût, bonbonne... (§5.8)."""
    __tablename__ = "returnable_packaging"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    capacity: Mapped[int | None] = mapped_column(Integer)
    deposit_value: Mapped[int] = mapped_column(Integer, default=0)  # consigne unitaire XOF
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DepositMovement(Base):
    """Quantité remise (+) / rendue (-) / perdue / ajustée, partie concernée."""
    __tablename__ = "deposit_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    packaging_id: Mapped[int] = mapped_column(ForeignKey("returnable_packaging.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)  # signée
    reason: Mapped[str] = mapped_column(String(40), index=True)
    # remis_client, retourne_client, recu_fournisseur, rendu_fournisseur, casse, ajuste
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    document_type: Mapped[str | None] = mapped_column(String(40))
    document_id: Mapped[int | None] = mapped_column(Integer)
    deposit_value: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)

    packaging: Mapped["ReturnablePackaging"] = relationship()
