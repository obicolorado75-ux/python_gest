"""Sécurité : hachage Argon2id, permissions, journal d'audit (§3)."""
from __future__ import annotations

from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select

from ..database.models import AuditLog, Permission, Role, RolePermission, User
from ..database.session import session_scope

_ph = PasswordHasher()  # Argon2id par défaut

# Limitation progressive des tentatives (§5.3) : mémoire de processus.
MAX_ATTEMPTS = 5
LOCK_SECONDS = 60
_failed: dict[str, tuple[int, datetime]] = {}


def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("Mot de passe vide interdit.")
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False


class AuthError(Exception):
    pass


class Session:
    """Session applicative courante : utilisateur connecté et ses permissions."""

    _current: "Session | None" = None

    def __init__(self, user: User, permissions: set[str]):
        self.user = user
        self.permissions = permissions

    def has_permission(self, code: str) -> bool:
        return "*" in self.permissions or code in self.permissions

    def require(self, code: str) -> None:
        if not self.has_permission(code):
            raise PermissionError(f"Permission refusée : {code}")

    @classmethod
    def current(cls) -> "Session | None":
        return cls._current

    @classmethod
    def logout(cls) -> None:
        cls._current = None


def _role_permissions(session, role: Role) -> set[str]:
    if role.name == "Administrateur":
        return {"*"}
    codes = session.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)).all()
    return set(codes)


def login(username: str, password: str) -> Session:
    """Message neutre en cas d'identifiants incorrects (§5.3)."""
    key = username.strip().lower()
    attempts, last = _failed.get(key, (0, datetime.min))
    if attempts >= MAX_ATTEMPTS and datetime.now() - last < timedelta(seconds=LOCK_SECONDS):
        raise AuthError("Trop de tentatives. Réessayez dans un instant.")

    with session_scope() as s:
        user = s.scalar(select(User).where(User.username == username))
        if user is None or not user.active or not verify_password(password, user.password_hash):
            _failed[key] = (attempts + 1, datetime.now())
            s.add(AuditLog(action="login_failed", comment=username))
            raise AuthError("Identifiant ou mot de passe incorrect.")
        role = s.get(Role, user.role_id)
        perms = _role_permissions(s, role) if role else set()
        s.add(AuditLog(action="login_ok", actor_id=user.id))
        sess = Session(user, perms)
    _failed.pop(key, None)
    Session._current = sess
    return sess


def login_pin(user_id: int, pin: str) -> Session:
    """Déverrouillage rapide d'un poste de caisse par code PIN (§3)."""
    with session_scope() as s:
        user = s.get(User, user_id)
        if user is None or not user.active or not user.pin_hash:
            raise AuthError("Code PIN indisponible pour cet utilisateur.")
        if not verify_password(pin, user.pin_hash):
            s.add(AuditLog(action="pin_failed", actor_id=user_id))
            raise AuthError("Code PIN incorrect.")
        role = s.get(Role, user.role_id)
        perms = _role_permissions(s, role) if role else set()
        s.add(AuditLog(action="login_ok", actor_id=user.id, comment="pin"))
        sess = Session(user, perms)
    Session._current = sess
    return sess


def log(action: str, object_type: str | None = None, object_id: int | None = None,
        old_value: str | None = None, new_value: str | None = None,
        comment: str | None = None, session=None) -> None:
    """Journalise l'action.

    Si ``session`` (Session ORM) est fournie, l'entrée d'audit fait partie de la
    même transaction métier (cohérence + évite les verrous SQLite) ; sinon une
    transaction dédiée est ouverte.
    """
    cur = Session.current()
    entry = AuditLog(
        actor_id=cur.user.id if cur else None,
        action=action, object_type=object_type, object_id=object_id,
        old_value=old_value, new_value=new_value, comment=comment)
    if session is not None:
        session.add(entry)
    else:
        with session_scope() as s:
            s.add(entry)
