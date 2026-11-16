"""Service sauvegarde/restauration avec intégrité vérifiée (§8)."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..config import app_paths
from ..database import session as db_session
from ..database.models import AppSetting, BackupHistory
from ..database.session import session_scope
from ..security import auth
from . import common


class BackupError(Exception):
    pass


BACKUP_SETTINGS = {
    "backup.directory": "Dossier des sauvegardes (vide = dossier par défaut)",
    "backup.keep_daily": "Nombre de sauvegardes quotidiennes conservées",
    "backup.keep_weekly": "Nombre de sauvegardes hebdomadaires conservées",
    "backup.auto_close": "Sauvegarde à la fermeture (1 = oui, 0 = non)",
}


class BackupService:
    # --- politique de sauvegarde (§8.1) -----------------------------------
    def settings(self) -> dict:
        """Réglages de sauvegarde, avec valeurs par défaut sûres."""
        defaults = {"backup.directory": "", "backup.keep_daily": "7",
                    "backup.keep_weekly": "4", "backup.auto_close": "1"}
        with session_scope() as s:
            stored = {row.key: row.value for row in s.scalars(select(AppSetting))}
        merged = {}
        for key, default in defaults.items():
            value = stored.get(key)
            merged[key] = value if value not in (None, "") else default
        return merged

    def save_settings(self, directory: str | None = None,
                      keep_daily: int | None = None,
                      keep_weekly: int | None = None,
                      auto_close: bool | None = None) -> dict:
        """Enregistre la politique de sauvegarde (dossier, rétention)."""
        common.require("backup.manage")
        updates = {}
        if directory is not None:
            directory = directory.strip()
            if directory and not os.path.isdir(directory):
                raise BackupError(f"Dossier introuvable : {directory}")
            updates["backup.directory"] = directory
        if keep_daily is not None:
            if keep_daily < 1:
                raise BackupError("Conservez au moins une sauvegarde quotidienne.")
            updates["backup.keep_daily"] = str(keep_daily)
        if keep_weekly is not None:
            if keep_weekly < 0:
                raise BackupError("Nombre de sauvegardes hebdomadaires invalide.")
            updates["backup.keep_weekly"] = str(keep_weekly)
        if auto_close is not None:
            updates["backup.auto_close"] = "1" if auto_close else "0"
        with session_scope() as s:
            for key, value in updates.items():
                setting = s.get(AppSetting, key)
                if setting is None:
                    s.add(AppSetting(key=key, value=value))
                else:
                    setting.value = value
            auth.log("backup_settings", "AppSetting", None,
                     new_value=str(updates), session=s)
        return self.settings()

    def destination_dir(self) -> str:
        """Dossier de sauvegarde effectif : réglage utilisateur ou dossier par défaut."""
        configured = self.settings().get("backup.directory") or ""
        if configured and os.path.isdir(configured):
            return configured
        return str(app_paths.backups_dir())

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
        dest_dir = destination or self.destination_dir()
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

    def should_backup_on_close(self) -> bool:
        """La sauvegarde à la fermeture est-elle activée (§8.1) ?"""
        return self.settings().get("backup.auto_close", "1") == "1"

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

    def restore(self, backup_path: str, password: str | None = None) -> str:
        """Restauration contrôlée (§8.3).

        1. authentification administrateur : permission `restore.run` **et**
           mot de passe ressaisi (`password`) — une session laissée ouverte sur
           un poste de caisse ne suffit pas
        2. vérification d'intégrité de la sauvegarde choisie
        3. sauvegarde de sécurité de la base actuelle
        4. fermeture des connexions puis restauration contrôlée
        """
        common.require("restore.run")
        if auth.Session.current() is not None:
            if not password:
                raise BackupError(
                    "Restauration refusée : le mot de passe de "
                    "l'administrateur doit être ressaisi.")
            auth.require_admin_password(password)
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
        # La base restaurée est antérieure : son historique ignore la copie de
        # sécurité créée juste avant. On la réenregistre pour que l'opérateur
        # retrouve toujours de quoi revenir en arrière (§8.3).
        with session_scope() as s:
            s.add(BackupHistory(path=safety.path, size_bytes=safety.size_bytes,
                                success=True, checksum=safety.checksum,
                                message="Sauvegarde de sécurité avant restauration"))
            auth.log("restore_run", "BackupHistory", None, new_value=backup_path,
                     comment=f"safety={safety.path}", session=s)
        return backup_path

    def list_restore_candidates(self):
        """Sauvegardes valides disponibles pour restauration."""
        out = []
        directory = Path(self.destination_dir())
        if not directory.exists():
            return out
        directory = Path(self.destination_dir())
        entries = sorted(directory.glob("*.db"),
                         key=lambda item: item.stat().st_mtime, reverse=True)
        for entry in entries:
            try:
                ok = self.verify(str(entry))
            except BackupError:
                ok = False
            out.append({"path": str(entry), "name": entry.name,
                        "size": entry.stat().st_size,
                        "modified": datetime.fromtimestamp(entry.stat().st_mtime),
                        "valid": ok})
        return out

    def purge_old(self, keep_daily: int | None = None,
                  keep_weekly: int | None = None) -> int:
        """Rétention : N sauvegardes quotidiennes + N hebdomadaires (§8.1).

        La sauvegarde hebdomadaire retenue est la plus récente de chaque semaine
        ISO ; elle n'est jamais supprimée par la rétention quotidienne.
        """
        common.require("backup.manage")
        settings = self.settings()
        keep_daily = keep_daily if keep_daily is not None \
            else int(settings["backup.keep_daily"])
        keep_weekly = keep_weekly if keep_weekly is not None \
            else int(settings["backup.keep_weekly"])
        directory = Path(self.destination_dir())
        # tri par date de fichier : le nom peut varier (manuel, quotidienne…)
        files = sorted(directory.glob("gestdepot_*.db"),
                       key=lambda item: item.stat().st_mtime, reverse=True)
        # 1. rétention quotidienne : les N sauvegardes les plus récentes
        keep = {str(entry) for entry in files[:keep_daily]}
        # 2. rétention hebdomadaire : la plus récente des N semaines NON déjà
        #    couvertes par la fenêtre quotidienne, afin de conserver une archive
        #    par semaine en plus des fichiers récents
        covered: set[tuple[int, int]] = set()
        for entry in files[:keep_daily]:
            stamp = datetime.fromtimestamp(entry.stat().st_mtime)
            covered.add(stamp.isocalendar()[:2])
        weeks = 0
        for entry in files[keep_daily:]:
            if weeks >= keep_weekly:
                break
            stamp = datetime.fromtimestamp(entry.stat().st_mtime)
            key = stamp.isocalendar()[:2]
            if key in covered:
                continue
            keep.add(str(entry))
            covered.add(key)
            weeks += 1
        removed = 0
        for old in files:
            if str(old) in keep:
                continue
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
        if removed:
            auth.log("backup_purge", "BackupHistory", None,
                     new_value=f"{removed} fichier(s)")
        return removed
