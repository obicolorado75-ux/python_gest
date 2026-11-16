"""Service catalogue : produits, catégories, marques, conditionnements, tarifs (§5.6)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select

from ..database.models import (
    Brand,
    Category,
    PriceList,
    Product,
    ProductBarcode,
    ProductCostHistory,
    ProductPackaging,
    ProductPrice,
    Unit,
)
from ..database.session import session_scope
from ..security import auth
from . import common

# Sentinelle pour l'absence de conditionnement dans les contraintes uniques.
BASE_PACKAGING = 0


class CatalogError(Exception):
    pass


class CatalogService:
    # --- produits -----------------------------------------------------
    def list_products(self, search: str | None = None, include_archived: bool = False,
                      category_id: int | None = None):
        with session_scope() as s:
            q = select(Product)
            if search:
                like = f"%{search.strip()}%"
                q = q.where(or_(Product.name.ilike(like),
                                Product.reference.ilike(like),
                                Product.barcode.ilike(like)))
            if category_id:
                q = q.where(Product.category_id == category_id)
            if not include_archived:
                q = q.where(Product.archived.is_(False))
            return list(s.scalars(q.order_by(Product.name)))

    def get(self, product_id: int) -> Product:
        with session_scope() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise CatalogError("Produit introuvable.")
            return p

    def create_product(self, reference: str, name: str, base_unit_id: int,
                       category_id: int | None = None, brand_id: int | None = None,
                       barcode: str | None = None, min_threshold: int = 0,
                       safety_stock: int = 0, initial_cost: int = 0,
                       description: str | None = None,
                       primary_supplier_id: int | None = None) -> Product:
        common.require("catalog.manage")
        reference = (reference or "").strip()
        name = (name or "").strip()
        if not reference:
            raise CatalogError("La référence interne est obligatoire.")
        if not name:
            raise CatalogError("La désignation est obligatoire.")
        if initial_cost < 0:
            raise CatalogError("Le coût ne peut pas être négatif.")
        if min_threshold < 0 or safety_stock < 0:
            raise CatalogError("Les seuils ne peuvent pas être négatifs.")
        with session_scope() as s:
            if s.get(Unit, base_unit_id) is None:
                raise CatalogError("Unité de stock de base inconnue.")
            if s.scalar(select(Product.id).where(Product.reference == reference)):
                raise CatalogError(f"La référence {reference} existe déjà.")
            if barcode and s.scalar(select(Product.id).where(Product.barcode == barcode)):
                raise CatalogError(f"Le code-barres {barcode} est déjà utilisé.")
            p = Product(reference=reference, name=name, base_unit_id=base_unit_id,
                        category_id=category_id, brand_id=brand_id, barcode=barcode,
                        description=description, min_threshold=min_threshold,
                        safety_stock=safety_stock, current_cost=initial_cost,
                        primary_supplier_id=primary_supplier_id)
            s.add(p)
            s.flush()
            if initial_cost:
                s.add(ProductCostHistory(product_id=p.id, cost=initial_cost,
                                         source="creation"))
            if barcode:
                s.add(ProductBarcode(product_id=p.id, barcode=barcode))
            auth.log("product_create", "Product", p.id, new_value=name, session=s)
            return p

    def update_product(self, product_id: int, **fields) -> None:
        common.require("catalog.manage")
        allowed = {"name", "description", "category_id", "brand_id", "barcode",
                   "min_threshold", "safety_stock", "primary_supplier_id",
                   "track_lots", "track_expiry", "active",
                   "packaging_deposit_product_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise CatalogError(f"Champs non modifiables : {', '.join(sorted(unknown))}")
        with session_scope() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise CatalogError("Produit introuvable.")
            old = {k: getattr(p, k) for k in fields}
            for k, v in fields.items():
                setattr(p, k, v)
            auth.log("product_update", "Product", product_id, old_value=str(old),
                     new_value=str(fields), session=s)

    def archive_product(self, product_id: int) -> None:
        """Un produit utilisé dans des opérations n'est jamais supprimé (§5.6)."""
        common.require("catalog.manage")
        with session_scope() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise CatalogError("Produit introuvable.")
            p.archived = True
            p.active = False
            auth.log("product_archive", "Product", product_id, session=s)

    def set_cost(self, product_id: int, cost: int) -> None:
        """Mise à jour du coût courant + historique conservé (T17)."""
        common.require("catalog.manage")
        if cost < 0:
            raise CatalogError("Coût négatif.")
        with session_scope() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise CatalogError("Produit introuvable.")
            old = p.current_cost
            p.current_cost = cost
            s.add(ProductCostHistory(product_id=product_id, cost=cost, source="manual"))
            auth.log("product_cost_change", "Product", product_id,
                     old_value=str(old), new_value=str(cost), session=s)

    def cost_on(self, product_id: int, day: date | None = None) -> int:
        """Coût en vigueur à une date donnée (historique des coûts, §5.14)."""
        day = day or date.today()
        with session_scope() as s:
            row = s.scalar(select(ProductCostHistory)
                           .where(ProductCostHistory.product_id == product_id,
                                  ProductCostHistory.effective_date <= day)
                           .order_by(ProductCostHistory.effective_date.desc(),
                                     ProductCostHistory.id.desc()))
            return row.cost if row else 0

    # --- conditionnements (§7.4) ---------------------------------------
    def add_packaging(self, product_id: int, name: str, factor: int,
                      is_default: bool = False) -> ProductPackaging:
        """Conditionnement configurable, jamais codé en dur (§7.4)."""
        common.require("catalog.manage")
        name = (name or "").strip()
        if factor <= 0:
            raise CatalogError("Le facteur doit être positif (ex. 1 casier = 24).")
        if not name:
            raise CatalogError("Le libellé du conditionnement est obligatoire.")
        with session_scope() as s:
            if s.get(Product, product_id) is None:
                raise CatalogError("Produit introuvable.")
            if s.scalar(select(ProductPackaging).where(
                    ProductPackaging.product_id == product_id,
                    ProductPackaging.name == name)):
                raise CatalogError(f"Le conditionnement {name} existe déjà.")
            pk = ProductPackaging(product_id=product_id, name=name, factor=factor,
                                  is_default=is_default)
            s.add(pk)
            s.flush()
            auth.log("packaging_create", "ProductPackaging", pk.id,
                     new_value=f"{name}={factor}", session=s)
            return pk

    def update_packaging(self, packaging_id: int, name: str | None = None,
                         factor: int | None = None) -> None:
        common.require("catalog.manage")
        with session_scope() as s:
            pk = s.get(ProductPackaging, packaging_id)
            if pk is None:
                raise CatalogError("Conditionnement introuvable.")
            old = f"{pk.name}={pk.factor}"
            if name:
                pk.name = name.strip()
            if factor is not None:
                if factor <= 0:
                    raise CatalogError("Le facteur doit être positif.")
                pk.factor = factor
            auth.log("packaging_update", "ProductPackaging", packaging_id,
                     old_value=old, new_value=f"{pk.name}={pk.factor}", session=s)

    def list_packagings(self, product_id: int, include_archived: bool = False):
        with session_scope() as s:
            q = select(ProductPackaging).where(ProductPackaging.product_id == product_id)
            if not include_archived:
                q = q.where(ProductPackaging.archived.is_(False))
            return list(s.scalars(q.order_by(ProductPackaging.factor)))

    def factor_of(self, packaging_id: int | None) -> int:
        """Nombre d'unités de base contenu dans un conditionnement."""
        if not packaging_id:
            return 1
        with session_scope() as s:
            pk = s.get(ProductPackaging, packaging_id)
            if pk is None:
                raise CatalogError("Conditionnement introuvable.")
            return pk.factor

    # --- tarifs ---------------------------------------------------------
    def set_price(self, product_id: int, price_list_id: int, unit_price: int,
                  packaging_id: int | None = None) -> None:
        common.require("catalog.manage")
        if unit_price < 0:
            raise CatalogError("Prix négatif.")
        with session_scope() as s:
            q = select(ProductPrice).where(
                ProductPrice.product_id == product_id,
                ProductPrice.price_list_id == price_list_id,
                ProductPrice.packaging_id == (packaging_id or None))
            pp = s.scalar(q)
            if pp is None:
                s.add(ProductPrice(product_id=product_id, price_list_id=price_list_id,
                                   packaging_id=packaging_id or None,
                                   unit_price=unit_price))
            else:
                old = pp.unit_price
                pp.unit_price = unit_price
                auth.log("price_change", "ProductPrice", product_id,
                         old_value=str(old), new_value=str(unit_price), session=s)

    def get_price(self, product_id: int, price_list_id: int | None,
                  packaging_id: int | None = None) -> int:
        """Prix exact du couple (liste, conditionnement), sans repli."""
        with session_scope() as s:
            pp = s.scalar(select(ProductPrice).where(
                ProductPrice.product_id == product_id,
                ProductPrice.price_list_id == price_list_id,
                ProductPrice.packaging_id == (packaging_id or None)))
            return pp.unit_price if pp else 0

    def default_price_list_id(self) -> int | None:
        """Liste tarifaire par défaut (celle du détail) quand aucun client n'est choisi."""
        with session_scope() as s:
            row = s.scalar(select(PriceList).where(PriceList.name == "Détail",
                                                   PriceList.archived.is_(False)))
            if row is not None:
                return row.id
            return s.scalar(select(PriceList.id)
                            .where(PriceList.archived.is_(False))
                            .order_by(PriceList.id))

    def resolve_price(self, product_id: int, price_list_id: int | None,
                      packaging_id: int | None = None) -> int:
        """Prix applicable avec repli : conditionnement → unité de base (§7.5).

        Sans liste précisée (vente au comptoir sans client), la liste par défaut
        est appliquée.
        """
        with session_scope() as s:
            if price_list_id is None:
                price_list_id = self.default_price_list_id()
            lists = [price_list_id]
            if price_list_id is not None:
                lists.append(None)
            # Un prix au conditionnement ne se déduit jamais du prix unitaire :
            # vendre un casier au prix de la bouteille serait une erreur de
            # facturation. Le repli se fait uniquement entre listes tarifaires.
            for list_id in lists:
                pp = s.scalar(select(ProductPrice).where(
                    ProductPrice.product_id == product_id,
                    ProductPrice.price_list_id == list_id,
                    ProductPrice.packaging_id == (packaging_id or None)))
                if pp and pp.unit_price:
                    return pp.unit_price
            return 0

    # --- référentiels ----------------------------------------------------
    def create_category(self, name: str) -> Category:
        common.require("catalog.manage")
        with session_scope() as s:
            name = (name or "").strip()
            if not name:
                raise CatalogError("Nom de catégorie obligatoire.")
            if s.scalar(select(Category).where(Category.name == name)):
                raise CatalogError(f"La catégorie {name} existe déjà.")
            c = Category(name=name)
            s.add(c)
            s.flush()
            return c

    def create_brand(self, name: str) -> Brand:
        common.require("catalog.manage")
        with session_scope() as s:
            name = (name or "").strip()
            if not name:
                raise CatalogError("Nom de marque obligatoire.")
            if s.scalar(select(Brand).where(Brand.name == name)):
                raise CatalogError(f"La marque {name} existe déjà.")
            b = Brand(name=name)
            s.add(b)
            s.flush()
            return b

    def create_unit(self, name: str) -> Unit:
        common.require("catalog.manage")
        with session_scope() as s:
            name = (name or "").strip()
            if not name:
                raise CatalogError("Nom d'unité obligatoire.")
            if s.scalar(select(Unit).where(Unit.name == name)):
                raise CatalogError(f"L'unité {name} existe déjà.")
            u = Unit(name=name)
            s.add(u)
            s.flush()
            return u

    def create_price_list(self, name: str) -> PriceList:
        common.require("catalog.manage")
        with session_scope() as s:
            name = (name or "").strip()
            if not name:
                raise CatalogError("Nom de liste de prix obligatoire.")
            if s.scalar(select(PriceList).where(PriceList.name == name)):
                raise CatalogError(f"La liste {name} existe déjà.")
            pl = PriceList(name=name)
            s.add(pl)
            s.flush()
            return pl

    def list_categories(self):
        with session_scope() as s:
            return list(s.scalars(select(Category).where(
                Category.archived.is_(False)).order_by(Category.name)))

    def list_brands(self):
        with session_scope() as s:
            return list(s.scalars(select(Brand).where(
                Brand.archived.is_(False)).order_by(Brand.name)))

    def list_units(self):
        with session_scope() as s:
            return list(s.scalars(select(Unit).order_by(Unit.name)))

    def list_price_lists(self):
        with session_scope() as s:
            return list(s.scalars(select(PriceList).where(
                PriceList.archived.is_(False)).order_by(PriceList.id)))

    def price_list_id_for(self, name: str) -> int | None:
        with session_scope() as s:
            return s.scalar(select(PriceList.id).where(PriceList.name == name))

    # --- import Excel/CSV (§5.6, §12) -----------------------------------
    def preview_import(self, rows: list[dict]) -> list[dict]:
        """Prévisualisation d'import : détecte doublons et erreurs, sans écrire."""
        report = []
        seen: set[str] = set()
        with session_scope() as s:
            existing = set(s.scalars(select(Product.reference)))
            unit_by_name = {u.name.lower(): u.id for u in s.scalars(select(Unit))}
        for index, row in enumerate(rows, start=2):
            ref = str(row.get("reference") or "").strip()
            name = str(row.get("name") or row.get("designation") or "").strip()
            errors = []
            if not ref:
                errors.append("Référence manquante")
            elif ref in existing:
                errors.append("Référence déjà présente en base")
            elif ref in seen:
                errors.append("Référence en double dans le fichier")
            if not name:
                errors.append("Désignation manquante")
            unit_name = str(row.get("unit") or row.get("unite") or "Bouteille").strip()
            unit_id = unit_by_name.get(unit_name.lower())
            if unit_id is None:
                errors.append(f"Unité inconnue : {unit_name}")
            try:
                cost = int(row.get("cost") or row.get("cout") or 0)
                threshold = int(row.get("min_threshold") or 0)
            except (TypeError, ValueError):
                errors.append("Coût ou seuil non numérique")
                cost, threshold = 0, 0
            seen.add(ref)
            report.append({"line": index, "reference": ref, "name": name,
                           "unit": unit_name, "unit_id": unit_id, "cost": cost,
                           "min_threshold": threshold,
                           "ok": not errors, "errors": errors})
        return report

    def import_products(self, rows: list[dict]) -> list[Product]:
        """Import confirmé : n'écrase jamais une référence existante (§12)."""
        report = self.preview_import(rows)
        invalid = [r for r in report if not r["ok"]]
        if invalid:
            raise CatalogError(
                f"{len(invalid)} ligne(s) invalide(s) : corrigez la prévisualisation "
                "avant d'importer.")
        created = []
        for r in report:
            created.append(self.create_product(
                reference=r["reference"], name=r["name"],
                base_unit_id=r["unit_id"], initial_cost=r["cost"],
                min_threshold=r["min_threshold"]))
        return created

    # --- tableau de bord --------------------------------------------------
    def count_products(self) -> int:
        with session_scope() as s:
            return s.scalar(select(func.count(Product.id)).where(
                Product.archived.is_(False))) or 0
