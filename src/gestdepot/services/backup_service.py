"""Service sauvegarde/restauration avec intégrité vérifiée (§8)."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime

from sqlalchemy import select

from ..config import app_paths
from ..database import session as db_session
from ..database.models import BackupHistory
from ..database.session import session_scope
from ..security import auth
from . import common


class BackupError(Exception):
    pass


class BackupService:
    def _live_path(self) -> str:
        engine = db_session.current_engine()
        path = engine.url.database
        if not path or path == ":memory:":
            raise BackupError("La base en mémoire ne peut pas être sauvegardée.")
        return path

    def _sha256(self, path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _integrity(self, path: str) -> str:
        """PRAGMA integrity_check ; un fichier illisible est signalé, pas levé."""
        try:
            conn = sqlite3.connect(path)
        except sqlite3.Error as exc:  # pragma: no cover - défensif
            return f"illisible : {exc}"
        try:
            return conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            return f"fichier invalide : {exc}"
        finally:
            conn.close()

    def backup(self, destination: str | None = None,
               label: str = "manual") -> BackupHistory:
        """Sauvegarde cohérente via l'API de sauvegarde SQLite (§8.2).

        - copie cohérente (WAL inclus), jamais un simple `copy` de fichier
        - PRAGMA integrity_check sur la copie avant de la déclarer valide
        - date, taille, empreinte et résultat enregistrés
        """
        common.require("backup.manage")
        live_path = self._live_path()
        dest_dir = destination or str(app_paths.backups_dir())
        os.makedirs(dest_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(dest_dir, f"gestdepot_{label}_{stamp}.db")
        src = sqlite3.connect(live_path)
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
        check = self._integrity(dest)
        size = os.path.getsize(dest)
        checksum = self._sha256(dest)
        with session_scope() as s:
            record = BackupHistory(path=dest, size_bytes=size,
                                   success=(check == "ok"), checksum=checksum,
                                   message=None if check == "ok" else check)
            s.add(record)
            auth.log("backup_create", "BackupHistory", None,
                     new_value=dest, comment=label, session=s)
            s.flush()
        if check != "ok":
            raise BackupError(f"Copie invalide ({check}), sauvegarde rejetée.")
        return record

    def history(self, limit: int = 50):
        with session_scope() as s:
            return list(s.scalars(select(BackupHistory)
                                  .order_by(BackupHistory.at.desc(),
                                            BackupHistory.id.desc()).limit(limit)))

    def last_successful(self) -> BackupHistory | None:
        with session_scope() as s:
            return s.scalar(select(BackupHistory)
                            .where(BackupHistory.success.is_(True))
                            .order_by(BackupHistory.at.desc(),
                                      BackupHistory.id.desc()))

    def daily_backup_needed(self) -> bool:
        """Sauvegarde automatique quotidienne au premier démarrage (§8.1)."""
        last = self.last_successful()
        if last is None:
            return True
        return last.at.date() < datetime.now().date()

    def verify(self, backup_path: str) -> bool:
        if not os.path.exists(backup_path):
            raise BackupError("Fichier de sauvegarde introuvable.")
        check = self._integrity(backup_path)
        if check != "ok":
            raise BackupError(f"Sauvegarde corrompue : {check}")
        try:
            conn = sqlite3.connect(backup_path)
            try:
                tables = conn.execute(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type='table'").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"Sauvegarde illisible : {exc}") from exc
        if not tables:
            raise BackupError("Sauvegarde vide : aucune table.")
        return True

    def restore(self, backup_path: str) -> str:
        """Restauration contrôlée (§8.3).

        1. authentification administrateur (permission restore.run)
        2. vérification d'intégrité de la sauvegarde choisie
        3. sauvegarde de sécurité de la base actuelle
        4. fermeture des connexions puis restauration contrôlée
        """
        common.require("restore.run")
        self.verify(backup_path)
        live_path = self._live_path()
        # sauvegarde de sécurité avant écrasement
        safety = self.backup(label="pre_restore")
        engine = db_session.current_engine()
        url = str(engine.url)
        engine.dispose()
        # supprime les fichiers WAL/SHM résiduels de la base active
        for suffix in ("-wal", "-shm"):
            leftover = live_path + suffix
            if os.path.exists(leftover):
                os.remove(leftover)
        shutil.copy2(backup_path, live_path)
        # réouverture contrôlée de la base restaurée
        db_session.init_engine(url)
        auth.log("restore_run", "BackupHistory", None, new_value=backup_path,
                 comment=f"safety={safety.path}")
        return backup_path

    def list_restore_candidates(self):
        """Sauvegardes valides disponibles pour restauration."""
        out = []
        directory = app_paths.backups_dir()
        if not directory.exists():
            return out
        for entry in sorted(directory.glob("*.db"), reverse=True):
            try:
                ok = self.verify(str(entry))
            except BackupError:
                ok = False
            out.append({"path": str(entry), "name": entry.name,
                        "size": entry.stat().st_size,
                        "modified": datetime.fromtimestamp(entry.stat().st_mtime),
                        "valid": ok})
        return out

    def purge_old(self, keep_daily: int = 7) -> int:
        """Rétention : conserve les N sauvegardes les plus récentes (§8.1)."""
        common.require("backup.manage")
        directory = app_paths.backups_dir()
        files = sorted(directory.glob("gestdepot_*.db"), reverse=True)
        removed = 0
        for old in files[keep_daily:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
        return removed
