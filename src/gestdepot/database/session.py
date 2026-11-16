"""Session SQLAlchemy, création de la base et amorçage (Phase 0→1).

La base est créée automatiquement au premier démarrage dans le répertoire de
données utilisateur (§4.4). Les migrations Alembic sont ensuite vérifiées et
appliquées à chaque démarrage : une nouvelle version de l'application met donc
à niveau les bases existantes sans manipulation (les sauvegardes sont faites
avant, §8).
"""
from __future__ import annotations

import datetime as dt
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import app_paths
from .models import (
    Base,
    CompanySettings,
    DocumentSequence,
    ExpenseCategory,
    Permission,
    PriceList,
    Role,
    RolePermission,
    Unit,
)

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _make_engine(url: str) -> Engine:
    engine = create_engine(url, echo=False, future=True)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - dépend du pilote
        cur = dbapi_conn.cursor()
        # §6.9 : clés étrangères activées, journal WAL = copies de sauvegarde fiables
        cur.execute("PRAGMA foreign_keys=ON")
        try:
            cur.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        cur.close()

    return engine


ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# En mode figé (exécutable PyInstaller), les migrations sont embarquées.
BUNDLED_MIGRATIONS_DIR = Path(sys._MEIPASS) / "gestdepot_migrations" \
    if getattr(sys, "_MEIPASS", None) else None


def _alembic_config(url: str):
    from alembic.config import Config
    cfg = Config(str(ALEMBIC_INI) if ALEMBIC_INI.exists() else None)
    cfg.set_main_option("script_location",
                        str(BUNDLED_MIGRATIONS_DIR or MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    # env.py lit cet attribut en priorité : les migrations s'appliquent à la base
    # réellement ouverte par l'application, jamais à une base de développement
    cfg.attributes["url"] = url
    return cfg


def _database_state(engine: Engine) -> str:
    """'empty', 'unmanaged' (tables sans version) ou 'managed' (alembic_version)."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        return "managed"
    return "unmanaged" if tables else "empty"


def upgrade_database(engine: Engine, url: str | None = None) -> None:
    """Applique les migrations Alembic à une base existante (§4.1, §8).

    Une base créée par ``create_all`` avant l'introduction des migrations est
    « adoptée » (stamp de la révision de base) puis mise à niveau : c'est ce qui
    garantit qu'une nouvelle version de l'application retrouve ses données avec
    les colonnes ajoutées, sans intervention manuelle.
    """
    from alembic import command
    state = _database_state(engine)
    if state == "empty":
        return
    cfg = _alembic_config(url or str(engine.url))
    if state == "unmanaged":
        Base.metadata.create_all(engine)  # tables manquantes éventuelles
        command.stamp(cfg, "head")
        return
    command.upgrade(cfg, "head")


def init_engine(url: str | None = None) -> Engine:
    """Initialise le moteur, garantit le schéma et applique les migrations."""
    global _engine, _SessionLocal
    if url is None:
        app_paths.ensure_dirs()
        url = f"sqlite:///{app_paths.database_path()}"
    if _engine is not None:
        _engine.dispose()
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    Base.metadata.create_all(_engine)
    # base neuve : create_all a créé le schéma complet → on le rattache à head,
    # base existante : upgrade des migrations en attente
    upgrade_database(_engine, url)
    with _SessionLocal() as s:
        seed_reference_data(s)
    return _engine


def current_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Base non initialisée : appelez init_engine().")
    return _engine


def get_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Session:
    """Transaction atomique : tout est validé ou tout est annulé (§7.2)."""
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reset_for_tests(url: str) -> Engine:
    """Réinitialise l'état global sur une base dédiée (fixtures pytest)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    return init_engine(url)


DEFAULT_PERMISSIONS: dict[str, str] = {
    "sales.create": "Créer une vente",
    "sales.discount": "Appliquer une remise",
    "sales.cancel": "Annuler une vente",
    "sales.return": "Enregistrer un retour",
    "catalog.manage": "Gérer le catalogue",
    "stock.receive": "Réceptionner une commande",
    "stock.adjust": "Ajuster le stock",
    "inventory.manage": "Gérer les inventaires",
    "cash.open": "Ouvrir une caisse",
    "cash.close": "Clôturer une caisse",
    "cash.correction": "Corriger une caisse clôturée",
    "expenses.create": "Enregistrer une dépense",
    "customers.manage": "Gérer les clients",
    "customers.credit_override": "Dépasser un plafond de crédit",
    "suppliers.manage": "Gérer les fournisseurs",
    "suppliers.pay": "Régler un fournisseur",
    "deposits.manage": "Gérer les consignes et emballages",
    "deliveries.manage": "Gérer les livraisons",
    "payments.create": "Encaisser un paiement",
    "reports.view": "Consulter les rapports",
    "users.manage": "Gérer les utilisateurs",
    "settings.manage": "Gérer les paramètres",
    "backup.manage": "Créer une sauvegarde",
    "restore.run": "Restaurer une sauvegarde",
    "audit.view": "Consulter le journal d'audit",
}

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "Administrateur": ["*"],
    "Gérant": ["sales.create", "sales.discount", "sales.cancel", "sales.return",
               "catalog.manage", "stock.receive", "stock.adjust", "inventory.manage",
               "cash.open", "cash.close", "expenses.create", "customers.manage",
               "customers.credit_override", "suppliers.manage", "suppliers.pay",
               "deposits.manage", "deliveries.manage",
               "payments.create", "reports.view", "audit.view"],
    "Caissier": ["sales.create", "cash.open", "cash.close", "payments.create",
                 "reports.view"],
    "Magasinier": ["stock.receive", "stock.adjust", "inventory.manage", "catalog.manage"],
    "Livreur": ["deliveries.manage"],
}

DOCUMENT_KEYS = ("VTE", "CMD", "ACH", "REC", "LIV", "INV", "DEP", "RET", "PAY", "SPAY")


def seed_reference_data(session: Session) -> None:
    """Jeu de référence minimal : rôles, permissions, unités, listes de prix (§3, §4).

    Idempotent : ne recrée rien si les données existent déjà.
    """
    # 1. Permissions + rôles (toujours synchronisés avec le code)
    existing = {p.code: p for p in session.scalars(select(Permission))}
    for code, description in DEFAULT_PERMISSIONS.items():
        perm = existing.get(code)
        if perm is None:
            perm = Permission(code=code, description=description)
            session.add(perm)
            existing[code] = perm
    session.flush()

    roles = {r.name: r for r in session.scalars(select(Role))}
    for name in ROLE_PERMISSIONS:
        if name not in roles:
            role = Role(name=name)
            session.add(role)
            roles[name] = role
    session.flush()

    for role_name, codes in ROLE_PERMISSIONS.items():
        if codes == ["*"]:
            continue
        role = roles[role_name]
        current = set(session.scalars(select(RolePermission.permission_id).where(
            RolePermission.role_id == role.id)))
        for code in codes:
            perm = existing[code]
            if perm.id not in current:
                session.add(RolePermission(role_id=role.id, permission_id=perm.id))

    # 2. Numérotation (§7.1)
    keys = set(session.scalars(select(DocumentSequence.key)))
    for key in DOCUMENT_KEYS:
        if key not in keys:
            session.add(DocumentSequence(key=key, last_number=0))

    # 3. Référentiels par défaut
    if not session.scalar(select(PriceList.id).limit(1)):
        session.add_all([PriceList(name=n) for n in ("Détail", "Gros", "Revendeur")])
    if not session.scalar(select(Unit.id).limit(1)):
        session.add_all([Unit(name=u) for u in ("Bouteille", "Canette", "Pièce", "Litre")])
    if not session.scalar(select(ExpenseCategory.id).limit(1)):
        session.add_all([ExpenseCategory(name=n) for n in
                         ("Transport", "Loyer", "Électricité", "Salaires", "Divers")])
    if not session.scalar(select(CompanySettings.id).limit(1)):
        session.add(CompanySettings())
    session.commit()


def next_document_number(session: Session, key: str, year: int | None = None) -> str:
    """Numérotation en base, dans la transaction courante (§7.1) — pas de doublon."""
    seq = session.get(DocumentSequence, key)
    if seq is None:
        seq = DocumentSequence(key=key, last_number=0)
        session.add(seq)
        session.flush()
    seq.last_number += 1
    session.flush()
    year = year or dt.date.today().year
    return f"{key}-{year}-{seq.last_number:06d}"
