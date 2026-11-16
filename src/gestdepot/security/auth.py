"""Sécurité : hachage Argon2id, permissions, journal d'audit (§3)."""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select

from ..database.models import AuditLog, Role, User
from ..database.session import session_scope

_ph = PasswordHasher()  # Argon2id par défaut


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except (VerifyMismatchError, ValueError):
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
        if "*" in self.permissions:
            return True
        return code in self.permissions

    def require(self, code: str) -> None:
        if not self.has_permission(code):
            raise PermissionError(f"Permission refusée : {code}")

    @classmethod
    def current(cls) -> "Session | None":
        return cls._current

    @classmethod
    def logout(cls) -> None:
        cls._current = None


def login(username: str, password: str) -> Session:
    """Message neutre en cas d'identifiants incorrects (§5.3)."""
    with session_scope() as s:
        user = s.scalar(select(User).where(User.username == username))
        if user is None or not user.active or not verify_password(password, user.password_hash):
            s.add(AuditLog(action="login_failed", comment=username))
            raise AuthError("Identifiant ou mot de passe incorrect.")
        perms = set()
        role = s.scalar(select(Role).where(Role.id == user.role_id))
        if role and role.name == "Administrateur":
            perms.add("*")
        s.add(AuditLog(action="login_ok", actor_id=user.id))
        sess = Session(user, perms)
    Session._current = sess
    return sess


def log(action: str, object_type: str | None = None, object_id: int | None = None,
        old_value: str | None = None, new_value: str | None = None,
        comment: str | None = None, session=None) -> None:
    """Journalise l'action. Si `session` (Session ORM) est fournie, l'entrée
    d'audit fait partie de la même transaction métier (évite les verrous SQLite) ;
    sinon une transaction dédiée est ouverte."""
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
