"""Service catalogue : produits, catégories, marques, conditionnements, tarifs (§5.6)."""
from sqlalchemy import or_, select

from ..database.models import (Brand, Category, PriceList, Product, ProductCostHistory,
                               ProductPackaging, ProductPrice, Unit)
from ..database.session import session_scope
from ..security import auth


class CatalogError(Exception):
    pass


class CatalogService:
    def list_products(self, search: str | None = None, include_archived: bool = False):
        with session_scope() as s:
            q = select(Product)
            if search:
                like = f"%{search}%"
                q = q.where(or_(Product.name.ilike(like), Product.reference.ilike(like),
                                Product.barcode.ilike(like)))
            if not include_archived:
                q = q.where(Product.archived == False)  # noqa: E712
            return list(s.scalars(q))

    def get(self, product_id: int) -> Product:
        with session_scope() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise CatalogError("Produit introuvable.")
            return p

    def create_product(self, reference: str, name: str, base_unit_id: int,
                       category_id: int | None = None, brand_id: int | None = None,
                       barcode: str | None = None, min_threshold: int = 0,
                       safety_stock: int = 0, initial_cost: int = 0) -> Product:
        auth.Session.current()  # l'UI appelle via utilisateur authentifié
        if initial_cost < 0:
            raise CatalogError("Le coût ne peut pas être négatif.")
        with session_scope() as s:
            if s.scalar(select(Product).where(Product.reference == reference)):
                raise CatalogError(f"La référence {reference} existe déjà.")
            p = Product(reference=reference, name=name, base_unit_id=base_unit_id,
                        category_id=category_id, brand_id=brand_id, barcode=barcode,
                        min_threshold=min_threshold, safety_stock=safety_stock,
                        current_cost=initial_cost)
            s.add(p)
            s.flush()
            if initial_cost:
                s.add(ProductCostHistory(product_id=p.id, cost=initial_cost, source="creation"))
            auth.log("product_create", "Product", p.id, new_value=name, session=s
            return p

    def update_product(self, product_id: int, **fields) -> None:
        with session_scope() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise CatalogError("Produit introuvable.")
            old = {k: getattr(p, k) for k in fields}
            for k, v in fields.items():
                setattr(p, k, v)
            auth.log("product_update", "Product", product_id, old_value=str(old),
                     new_value=str(fields))

    def archive_product(self, product_id: int) -> None:
        """Un produit utilisé dans des opérations n'est jamais supprimé (§5.6)."""
        self.update_product(product_id, archived=True, active=False)
        auth.log("product_archive", "Product", product_id)

    def set_cost(self, product_id: int, cost: int) -> None:
        """Mise à jour du coût courant + historique conservé (T17)."""
        if cost < 0:
            raise CatalogError("Coût négatif.")
        with session_scope() as s:
            p = s.get(Product, product_id)
            old = p.current_cost
            p.current_cost = cost
            s.add(ProductCostHistory(product_id=product_id, cost=cost, source="manual"))
            auth.log("product_cost_change", "Product", product_id,
                     old_value=str(old), new_value=str(cost))

    def add_packaging(self, product_id: int, name: str, factor: int,
                      is_default: bool = False) -> ProductPackaging:
        """Conditionnement configurable, jamais codé en dur (§7.4)."""
        if factor <= 0:
            raise CatalogError("Le facteur doit être positif (ex. 1 casier = 24).")
        with session_scope() as s:
            pk = ProductPackaging(product_id=product_id, name=name, factor=factor,
                                  is_default=is_default)
            s.add(pk)
            s.flush()
            auth.log("packaging_create", "ProductPackaging", pk.id, new_value=f"{name}={factor}", session=s
            return pk

    def list_packagings(self, product_id: int) -> list:
        with session_scope() as s:
            return list(s.scalars(select(ProductPackaging).where(
                ProductPackaging.product_id == product_id,
                ProductPackaging.archived == False)))  # noqa: E712

    def set_price(self, product_id: int, price_list_id: int, unit_price: int,
                  packaging_id: int | None = None) -> None:
        if unit_price < 0:
            raise CatalogError("Prix négatif.")
        with session_scope() as s:
            q = select(ProductPrice).where(
                ProductPrice.product_id == product_id,
                ProductPrice.price_list_id == price_list_id,
                ProductPrice.packaging_id == packaging_id)
            pp = s.scalar(q)
            if pp is None:
                s.add(ProductPrice(product_id=product_id, price_list_id=price_list_id,
                                   packaging_id=packaging_id, unit_price=unit_price))
            else:
                old = pp.unit_price
                pp.unit_price = unit_price
                auth.log("price_change", "ProductPrice", product_id,
                         old_value=str(old), new_value=str(unit_price), session=s

    def get_price(self, product_id: int, price_list_id: int,
                  packaging_id: int | None = None) -> int:
        with session_scope() as s:
            pp = s.scalar(select(ProductPrice).where(
                ProductPrice.product_id == product_id,
                ProductPrice.price_list_id == price_list_id,
                ProductPrice.packaging_id == packaging_id))
            return pp.unit_price if pp else 0

    # --- référentiels -------------------------------------------------
    def create_category(self, name: str) -> Category:
        with session_scope() as s:
            c = Category(name=name)
            s.add(c)
            return c

    def create_brand(self, name: str) -> Brand:
        with session_scope() as s:
            s.add(Brand(name=name))
            s.flush()
            return s.scalar(select(Brand).where(Brand.name == name))

    def list_categories(self):
        with session_scope() as s:
            return list(s.scalars(select(Category)))

    def list_brands(self):
        with session_scope() as s:
            return list(s.scalars(select(Brand)))

    def list_units(self):
        with session_scope() as s:
            return list(s.scalars(select(Unit)))

    def list_price_lists(self):
        with session_scope() as s:
            return list(s.scalars(select(PriceList)))
