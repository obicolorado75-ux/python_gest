"""Service administration : utilisateurs, rôles, paramètres du dépôt (§3, §5.16)."""
from __future__ import annotations

from sqlalchemy import select

from ..database.models import (
    AppSetting,
    AuditLog,
    CompanySettings,
    Permission,
    Role,
    RolePermission,
    User,
)
from ..database.session import session_scope
from ..security import auth
from ..security.auth import hash_password
from . import common


class AdminError(Exception):
    pass


class AdminService:
    # --- paramètres du dépôt ------------------------------------------------
    def company_settings(self) -> CompanySettings:
        with session_scope() as s:
            settings = s.scalar(select(CompanySettings).limit(1))
            if settings is None:
                settings = CompanySettings()
                s.add(settings)
                s.flush()
            return settings

    def update_company_settings(self, **fields) -> None:
        common.require("settings.manage")
        allowed = {"name", "address", "phone", "logo_path", "document_footer",
                   "date_format"}
        unknown = set(fields) - allowed
        if unknown:
            raise AdminError(f"Champs non modifiables : {', '.join(sorted(unknown))}")
        with session_scope() as s:
            settings = s.scalar(select(CompanySettings).limit(1))
            if settings is None:
                settings = CompanySettings()
                s.add(settings)
                s.flush()
            old = {k: getattr(settings, k) for k in fields}
            for key, value in fields.items():
                setattr(settings, key, value)
            auth.log("settings_update", "CompanySettings", settings.id,
                     old_value=str(old), new_value=str(fields), session=s)

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with session_scope() as s:
            setting = s.get(AppSetting, key)
            return setting.value if setting else default

    def set_setting(self, key: str, value: str) -> None:
        common.require("settings.manage")
        with session_scope() as s:
            setting = s.get(AppSetting, key)
            if setting is None:
                s.add(AppSetting(key=key, value=value))
            else:
                setting.value = value

    # --- utilisateurs (§3) ---------------------------------------------------
    def list_roles(self):
        with session_scope() as s:
            return list(s.scalars(select(Role).order_by(Role.id)))

    def list_users(self, include_inactive: bool = True):
        with session_scope() as s:
            q = select(User).order_by(User.username)
            if not include_inactive:
                q = q.where(User.active.is_(True))
            return list(s.scalars(q))

    def has_any_user(self) -> bool:
        with session_scope() as s:
            return s.scalar(select(User.id).limit(1)) is not None

    def create_user(self, username: str, password: str, role_name: str,
                    full_name: str = "", pin: str | None = None,
                    require_admin: bool = True) -> User:
        """Crée un utilisateur. Le tout premier utilisateur (assistant de premier
        lancement) peut être créé sans session ouverte."""
        username = (username or "").strip()
        if not username:
            raise AdminError("L'identifiant est obligatoire.")
        if len(password or "") < 6:
            raise AdminError("Le mot de passe doit contenir au moins 6 caractères.")
        if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
            raise AdminError("Le code PIN doit contenir de 4 à 8 chiffres.")
        with session_scope() as s:
            if s.scalar(select(User.id).where(User.username == username)):
                raise AdminError(f"L'identifiant {username} existe déjà.")
            role = s.scalar(select(Role).where(Role.name == role_name))
            if role is None:
                raise AdminError(f"Rôle inconnu : {role_name}")
            user = User(username=username, full_name=full_name,
                        password_hash=hash_password(password),
                        pin_hash=hash_password(pin) if pin else None,
                        role_id=role.id, active=True)
            s.add(user)
            s.flush()
            auth.log("user_create", "User", user.id, new_value=username, session=s)
            return user

    def update_user(self, user_id: int, **fields) -> None:
        """Modification d'un utilisateur, mot de passe/PIN exclus (voir dédiés)."""
        common.require("users.manage")
        allowed = {"full_name", "role_id", "active"}
        unknown = set(fields) - allowed
        if unknown:
            raise AdminError(f"Champs non modifiables : {', '.join(sorted(unknown))}")
        with session_scope() as s:
            user = s.get(User, user_id)
            if user is None:
                raise AdminError("Utilisateur introuvable.")
            old = {k: getattr(user, k) for k in fields}
            for key, value in fields.items():
                setattr(user, key, value)
            auth.log("user_update", "User", user_id, old_value=str(old),
                     new_value=str(fields), session=s)

    def set_password(self, user_id: int, password: str) -> None:
        if len(password or "") < 6:
            raise AdminError("Le mot de passe doit contenir au moins 6 caractères.")
        with session_scope() as s:
            user = s.get(User, user_id)
            if user is None:
                raise AdminError("Utilisateur introuvable.")
            user.password_hash = hash_password(password)
            auth.log("user_password_change", "User", user_id, session=s)

    def set_pin(self, user_id: int, pin: str | None) -> None:
        common.require("users.manage")
        if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
            raise AdminError("Le code PIN doit contenir de 4 à 8 chiffres.")
        with session_scope() as s:
            user = s.get(User, user_id)
            if user is None:
                raise AdminError("Utilisateur introuvable.")
            user.pin_hash = hash_password(pin) if pin else None
            auth.log("user_pin_change", "User", user_id, session=s)

    def deactivate_user(self, user_id: int) -> None:
        """Désactivation : l'historique reste consultable, jamais de suppression."""
        common.require("users.manage")
        current = auth.Session.current()
        if current and current.user.id == user_id:
            raise AdminError("Impossible de désactiver votre propre compte.")
        with session_scope() as s:
            user = s.get(User, user_id)
            if user is None:
                raise AdminError("Utilisateur introuvable.")
            user.active = False
            auth.log("user_deactivate", "User", user_id, session=s)

    def role_permissions(self, role_id: int) -> set[str]:
        with session_scope() as s:
            role = s.get(Role, role_id)
            if role is None:
                return set()
            if role.name == "Administrateur":
                return {"*"}
            return set(s.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)))

    def list_permissions(self):
        with session_scope() as s:
            return list(s.scalars(select(Permission).order_by(Permission.code)))

    # --- audit (§3) ------------------------------------------------------------
    def audit_logs(self, limit: int = 200, action: str | None = None):
        common.require("audit.view")
        with session_scope() as s:
            q = select(AuditLog).order_by(AuditLog.at.desc(),
                                          AuditLog.id.desc()).limit(limit)
            if action:
                q = q.where(AuditLog.action == action)
            return list(s.scalars(q))
