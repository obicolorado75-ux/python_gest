"""Moyens de paiement configurables (§5.12).

La liste par défaut vit dans la couche domaine (`domain.rules`) ; ce module
résout la liste **effective** à partir des réglages (`app_settings`), en
respectant le mode hors ligne : aucune valeur mise en cache n'est validée à la
place d'un réglage lu en base.
"""
from __future__ import annotations

from ..database.models import AppSetting
from ..database.session import session_scope
from ..domain.rules import PAYMENT_METHOD_LABELS, PAYMENT_METHODS

SETTING_KEY = "payments.methods"

# Moyens toujours indispensables au fonctionnement de la caisse.
REQUIRED_METHODS = ("especes",)

DEFAULT_METHODS: tuple[str, ...] = tuple(PAYMENT_METHODS)


def parse(raw: str | None) -> list[str]:
    """Décode la valeur stockée (`code|libellé` par ligne)."""
    if not raw:
        return list(DEFAULT_METHODS)
    methods: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        code = line.split("|", 1)[0].strip()
        if code and code not in methods:
            methods.append(code)
    return methods or list(DEFAULT_METHODS)


def serialize(codes: list[str]) -> str:
    """Encode une liste de codes pour stockage."""
    seen: list[str] = []
    for code in codes:
        if code and code not in seen:
            seen.append(code)
    return "\n".join(seen)


def _raw() -> str | None:
    try:
        with session_scope() as session:
            setting = session.get(AppSetting, SETTING_KEY)
            return setting.value if setting else None
    except Exception:  # base pas encore prête (démarrage) → valeurs par défaut
        return None


def custom_labels(raw: str | None = None) -> dict[str, str]:
    """Libellés des moyens ajoutés par l'utilisateur (format `code|libellé`)."""
    raw = _raw() if raw is None else raw
    labels: dict[str, str] = {}
    for line in (raw or "").splitlines():
        if "|" in line:
            code, label = line.split("|", 1)
            code, label = code.strip(), label.strip()
            if code and label:
                labels[code] = label
    return labels


def resolve(services=None) -> list[str]:
    """Liste effective des codes de moyens de paiement (appelable sans services)."""
    return parse(_raw())


def codes() -> tuple[str, ...]:
    """Codes disponibles, sans doublon, dans l'ordre configuré."""
    return tuple(resolve())


def labels() -> dict[str, str]:
    """Libellés français pour chaque code effectif (personnalisés inclus)."""
    custom = custom_labels()
    return {code: custom.get(code)
            or PAYMENT_METHOD_LABELS.get(code, code.replace("_", " ").title())
            for code in codes()}


def is_valid(code: str | None) -> bool:
    return bool(code) and code in codes()


def save(codes_list: list[str], custom: dict[str, str] | None = None) -> list[str]:
    """Enregistre la liste (permission `settings.manage`, contrôle métier)."""
    from ..security import auth
    from . import common
    common.require("settings.manage")
    cleaned: list[str] = []
    for code in codes_list:
        code = (code or "").strip().lower().replace(" ", "_")
        if not code or code in cleaned:
            continue
        if not all(char.isalnum() or char == "_" for char in code):
            raise ValueError(f"Code de moyen de paiement invalide : {code}")
        cleaned.append(code)
    missing = [code for code in REQUIRED_METHODS if code not in cleaned]
    if missing:
        raise ValueError("Le moyen de paiement « Espèces » est obligatoire.")
    with session_scope() as session:
        setting = session.get(AppSetting, SETTING_KEY)
        custom = custom_labels() | {code: label for code, label in
                                    (custom or {}).items() if code in cleaned}
        payload = "\n".join(code + (f"|{custom[code]}" if code in custom else "")
                            for code in cleaned)
        if setting is None:
            from ..database.models import AppSetting as _Setting
            session.add(_Setting(key=SETTING_KEY, value=payload))
        else:
            setting.value = payload
        auth.log("payment_methods_update", "AppSetting", None,
                 new_value=payload, session=session)
    return cleaned


def add(code: str, label: str | None = None) -> list[str]:
    """Ajoute un moyen de paiement (code technique dérivé du libellé si absent)."""
    code = (code or "").strip().lower().replace(" ", "_")
    if not code:
        raise ValueError("Indiquez un nom de moyen de paiement.")
    current = list(codes())
    if code in current:
        raise ValueError(f"« {label or code} » existe déjà.")
    if label and not label.strip():
        label = None
    extra = {code: label.strip()} if label else {}
    return save(current + [code], custom=extra)
