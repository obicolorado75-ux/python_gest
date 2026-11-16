"""Service sauvegarde/restauration avec intégrité vérifiée (§8)."""
import hashlib
import shutil
import sqlite3
from datetime import datetime

from sqlalchemy import select

from ..config import app_paths
from ..database.models import BackupHistory
from ..database.session import session_scope
from ..security import auth


class BackupError(Exception):
    pass


class BackupService:
    def backup(self, destination: str | None = None) -> BackupHistory:
        """Sauvegarde cohérente via l'API de sauvegarde SQLite (§8.2),
        avec PRAGMA integrity_check sur la copie."""
        from ..database.session import _engine  # engine courant
        if _engine is None:
            raise BackupError("Base non initialisée.")
        src_path = _engine.url.database
        dest_dir = destination or str(app_paths.backups_dir())
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = f"{dest_dir}/gestdepot_{stamp}.db"
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)          # copie cohérente, WAL inclus
        src.close()
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        dst.close()
        if check != "ok":
            raise BackupError(f"Copie invalide ({check}), sauvegarde rejetée.")
        size = __import__("os").path.getsize(dest)
        checksum = self._sha256(dest)
        with session_scope() as s:
            rec = BackupHistory(path=dest, size_bytes=size, success=True, checksum=checksum)
            s.add(rec)
        auth.log("backup_create", "BackupHistory", None, new_value=dest)
        return rec

    def _sha256(self, path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def history(self, limit: int = 50):
        with session_scope() as s:
            return list(s.scalars(select(BackupHistory)
                                  .order_by(BackupHistory.at.desc()).limit(limit)))

    def restore(self, backup_path: str) -> None:
        """Restauration contrôlée (§8.3) : auth admin, sauvegarde de sécurité,
        vérification d'intégrité avant d'écraser."""
        auth.Session.current().require("restore.run")
        check = sqlite3.connect(backup_path)
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        tables = check.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        check.close()
        if result != "ok" or tables == 0:
            raise BackupError("Sauvegarde invalide : restauration refusée.")
        from ..database.session import _engine
        live_path = _engine.url.database
        # sauvegarde de sécurité de la base actuelle
        self.backup()
        import os
        _engine.dispose()
        shutil.copy2(backup_path, live_path)
        auth.log("restore_run", None, None, new_value=backup_path)
