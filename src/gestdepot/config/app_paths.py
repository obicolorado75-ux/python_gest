"""Chemins de données utilisateur (§4.4)."""
import os
import sys
from pathlib import Path

APP_NAME = "GestDepot"


def data_dir() -> Path:
    """Répertoire de données utilisateur, jamais dans le dossier d'installation."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def ensure_dirs() -> dict:
    d = data_dir()
    subdirs = {}
    for name in ("database", "backups", "exports", "documents", "logs", "attachments"):
        p = d / name
        p.mkdir(parents=True, exist_ok=True)
        subdirs[name] = p
    return subdirs


def database_path() -> Path:
    return data_dir() / "database" / "gestdepot.db"


def logs_dir() -> Path:
    return data_dir() / "logs"


def backups_dir() -> Path:
    return data_dir() / "backups"


def exports_dir() -> Path:
    return data_dir() / "exports"
