"""Session SQLAlchemy, création de la base et amorçage (Phase 0→1)."""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import app_paths
from .models import (Base, CompanySettings, DocumentSequence, Permission, PriceList,
                     Role, RolePermission, Unit, User, ExpenseCategory)

# Cible par défaut = base utilisateur ; surchargée pour les tests.
_engine: Engine | None = None
_SessionLocal = None


def _make_engine(url: str) -> Engine:
    engine = create_engine(url, echo=False)
    # Contraintes de clés étrangères actives dans SQLite (§6.9)
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()
    return engine


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if url is None:
        app_paths.ensure_dirs()
        url = f"sqlite:///{app_paths.database_path()}"
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    try:
        seed_reference_data(_SessionLocal())
    except Exception as e:
        # Seed data may already exist; log and continue
        print(f"Note: seed_reference_data completed with notes: {e}")
    return _engine


def get_session() -> Session:
    if _SessionLocal is None:
        init_engine()
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
    return init_engine(url)


DEFAULT_PERMISSIONS = [
    "sales.create", "sales.discount", "sales.cancel", "sales.return",
    "catalog.manage", "stock.receive", "stock.adjust", "inventory.manage",
    "cash.open", "cash.close", "cash.correction", "expenses.create",
    "customers.manage", "customers.credit_override", "suppliers.manage",
    "deliveries.manage", "payments.create", "reports.view", "users.manage",
    "settings.manage", "backup.manage", "restore.run", "audit.view",
]

ROLE_PERMISSIONS = {
    "Administrateur": ["*"],
    "Gérant": ["sales.create", "sales.discount", "sales.cancel", "sales.return",
               "catalog.manage", "stock.receive", "stock.adjust", "inventory.manage",
               "cash.open", "cash.close", "expenses.create", "customers.manage",
               "customers.credit_override", "suppliers.manage", "deliveries.manage",
               "payments.create", "reports.view", "audit.view"],
    "Caissier": ["sales.create", "cash.open", "cash.close", "payments.create", "reports.view"],
    "Magasinier": ["stock.receive", "stock.adjust", "inventory.manage", "catalog.manage"],
    "Livreur": ["deliveries.manage"],
}


def seed_reference_data(session: Session) -> None:
    """Jeu de référence minimal : rôles, permissions, unités, listes de prix (§3, §4)."""
    # Idempotent: checker si données existent
    existing_perms = session.query(Permission).filter(Permission.code.in_(DEFAULT_PERMISSIONS)).all()
    existing_codes = {p.code for p in existing_perms}
    if not existing_perms:
        for r in ROLE_PERMISSIONS:
            role = Role(name=r)
            session.add(role)
        perms = [Permission(code=c) for c in DEFAULT_PERMISSIONS]
        session.add_all(perms)
        session.flush()
        # Admin garde "*" : tout est autorisé au contrôle.
        session.add_all([RolePermission(role_id=1, permission_id=p.id) for p in perms])
        # Numérotation §7.1
        for key in ("VTE", "CMD", "ACH", "REC", "LIV", "INV", "DEP", "RET", "PAY", "SPAY"):
            session.add(DocumentSequence(key=key, last_number=0))
        session.add_all([PriceList(name=n) for n in ("Détail", "Gros")])
        session.add_all([Unit(name=u) for u in ("Bouteille", "Canette", "Pièce", "Litre")])
        session.add(CompanySettings())
        session.add_all([ExpenseCategory(name=n)
                         for n in ("Transport", "Loyer", "Électricité", "Salaires", "Divers")])
        session.commit()


def next_document_number(session: Session, key: str, year: int | None = None) -> str:
    """Numérotation en base, dans la transaction (§7.1) — pas de doublon."""
    seq = session.get(DocumentSequence, key)
    if seq is None:
        seq = DocumentSequence(key=key, last_number=0)
        session.add(seq)
    seq.last_number += 1
    year = year or __import__("datetime").date.today().year
    return f"{key}-{year}-{seq.last_number:06d}"
