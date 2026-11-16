"""Catalogue : catégories, marques, unités, produits, conditionnements, tarifs (§6.2)."""
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Unit(Base):
    __tablename__ = "units"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)  # bouteille, canette...
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    base_unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    barcode: Mapped[str | None] = mapped_column(String(60), index=True)
    min_threshold: Mapped[int] = mapped_column(Integer, default=0)      # seuil minimum
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)       # stock de sécurité
    primary_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    track_lots: Mapped[bool] = mapped_column(Boolean, default=False)
    track_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    packaging_deposit_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("returnable_packaging.id", use_alter=True))
    current_cost: Mapped[int] = mapped_column(Integer, default=0)       # prix d'achat courant, XOF
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[date] = mapped_column(Date, default=date.today)

    category: Mapped["Category"] = relationship(lazy="joined")
    brand: Mapped["Brand"] = relationship(lazy="joined")
    base_unit: Mapped["Unit"] = relationship(lazy="joined")
    packagings: Mapped[list["ProductPackaging"]] = relationship(back_populates="product", lazy="selectin")
    prices: Mapped[list["ProductPrice"]] = relationship(back_populates="product", lazy="selectin")
    costs: Mapped[list["ProductCostHistory"]] = relationship(back_populates="product")


class ProductBarcode(Base):
    __tablename__ = "product_barcodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    barcode: Mapped[str] = mapped_column(String(60), unique=True, index=True)


class ProductPackaging(Base):
    """Conditionnement de vente : 1 conditionnement = factor unités de base (§7.4)."""
    __tablename__ = "product_packagings"
    __table_args__ = (UniqueConstraint("product_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))         # "Casier", "Carton de 6"...
    factor: Mapped[int] = mapped_column(Integer)          # nb d'unités de base
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped["Product"] = relationship(back_populates="packagings")


class PriceList(Base):
    """Détail, gros, revendeur, liste personnalisée."""
    __tablename__ = "price_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class ProductPrice(Base):
    __tablename__ = "product_prices"
    __table_args__ = (UniqueConstraint("product_id", "price_list_id", "packaging_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id"))
    packaging_id: Mapped[int | None] = mapped_column(ForeignKey("product_packagings.id"))
    # NULL packaging_id => prix à l'unité de base
    unit_price: Mapped[int] = mapped_column(Integer)      # XOF
    valid_from: Mapped[date | None] = mapped_column(Date)

    product: Mapped["Product"] = relationship(back_populates="prices")
    price_list: Mapped["PriceList"] = relationship()


class ProductCostHistory(Base):
    """Historique des coûts d'achat (§6.2) — les marges historiques s'appuient dessus (T17)."""
    __tablename__ = "product_cost_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    cost: Mapped[int] = mapped_column(Integer)            # XOF / unité de base
    effective_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")

    product: Mapped["Product"] = relationship(back_populates="costs")
