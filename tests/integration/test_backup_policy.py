"""§8.1–§8.3 — politique de sauvegarde, rétention, vérification, restauration."""
import os
from datetime import datetime, timedelta

import pytest

from gestdepot.services.backup_service import BackupError, BackupService


@pytest.fixture()
def backup(admin):
    return BackupService()


@pytest.fixture()
def backup_dir(tmp_path):
    directory = tmp_path / "sauvegardes"
    directory.mkdir()
    return directory


class TestPolitique:
    def test_reglages_par_defaut(self, backup):
        settings = backup.settings()
        assert settings["backup.keep_daily"] == "7"
        assert settings["backup.keep_weekly"] == "4"
        assert settings["backup.auto_close"] == "1"
        assert backup.should_backup_on_close() is True

    def test_enregistrement_des_reglages(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir), keep_daily=10,
                             keep_weekly=2, auto_close=False)
        settings = backup.settings()
        assert settings["backup.directory"] == str(backup_dir)
        assert settings["backup.keep_daily"] == "10"
        assert settings["backup.keep_weekly"] == "2"
        assert backup.should_backup_on_close() is False
        assert backup.destination_dir() == str(backup_dir)

    def test_dossier_inexistant_refuse(self, backup):
        with pytest.raises(BackupError):
            backup.save_settings(directory="/dossier/qui/nexiste/pas")

    def test_retention_quotidienne_invalide(self, backup):
        with pytest.raises(BackupError):
            backup.save_settings(keep_daily=0)
        with pytest.raises(BackupError):
            backup.save_settings(keep_weekly=-1)

    def test_dossier_par_defaut_si_non_configure(self, backup):
        from gestdepot.config import app_paths
        assert backup.destination_dir() == str(app_paths.backups_dir())


class TestCreationEtVerification:
    def test_sauvegarde_dans_le_dossier_configure(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir))
        record = backup.backup(label="test")
        assert record.success is True
        assert record.path.startswith(str(backup_dir))
        assert os.path.exists(record.path)
        assert len(record.checksum or "") == 64
        assert record.size_bytes > 0

    def test_derniere_sauvegarde_reussie(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir))
        record = backup.backup(label="manuelle")
        last = backup.last_successful()
        assert last is not None and last.id == record.id
        assert backup.daily_backup_needed() is False

    def test_verification_fichier_invalide(self, backup, tmp_path):
        broken = tmp_path / "corrompu.db"
        broken.write_bytes(b"ceci n'est pas une base sqlite")
        with pytest.raises(BackupError):
            backup.verify(str(broken))

    def test_verification_fichier_absent(self, backup, tmp_path):
        with pytest.raises(BackupError):
            backup.verify(str(tmp_path / "absent.db"))

    def test_verification_sauvegarde_valide(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir))
        record = backup.backup(label="test")
        assert backup.verify(record.path) is True

    def test_candidats_de_restauration(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir))
        backup.backup(label="un")
        backup.backup(label="deux")
        candidates = backup.list_restore_candidates()
        assert len(candidates) == 2
        assert all(item["valid"] for item in candidates)


class TestRetention:
    def _fake(self, directory, name, days_ago):
        path = directory / name
        path.write_bytes(b"x")
        stamp = (datetime.now() - timedelta(days=days_ago)).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def test_conserve_quotidiennes_et_hebdomadaires(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir), keep_daily=2, keep_weekly=2)
        # 10 jours de sauvegardes + 3 très anciennes
        paths = [self._fake(backup_dir, f"gestdepot_j{j}_20260101_00000{j}.db", j)
                 for j in range(10)]
        old = [self._fake(backup_dir, f"gestdepot_vieux_{i}.db", 30 + i * 10)
               for i in range(3)]
        removed = backup.purge_old()
        remaining = {path.name for path in backup_dir.glob("*.db")}
        # les 2 plus récentes restent (rétention quotidienne)
        assert paths[0].name in remaining and paths[1].name in remaining
        # la rétention hebdomadaire conserve une archive par semaine hors fenêtre
        # quotidienne : au moins un fichier de plus de 7 jours survit
        older = [path for path in paths[7:] + old if path.name in remaining]
        assert older, "aucune archive hebdomadaire conservée"
        # … mais pas tout : les fichiers les plus anciens sont purgés
        assert not all(path.name in remaining for path in old)
        assert removed > 0

    def test_retention_ne_touche_pas_aux_fichiers_recents(self, backup,
                                                          backup_dir):
        backup.save_settings(directory=str(backup_dir), keep_daily=7,
                             keep_weekly=4)
        paths = [self._fake(backup_dir, f"gestdepot_r{i}_x.db", i) for i in range(3)]
        assert backup.purge_old() == 0
        assert all(path.exists() for path in paths)


class TestRestauration:
    def test_restauration_cree_une_sauvegarde_de_securite(self, backup,
                                                          backup_dir):
        backup.save_settings(directory=str(backup_dir))
        first = backup.backup(label="avant")
        backup.restore(first.path, password="secret")
        # la base restaurée connaît la copie de sécurité créée avant elle
        assert backup.last_successful() is not None
        assert any("pre_restore" in record.path for record in backup.history())
        # une copie de sécurité de la base remplacée subsiste sur le disque
        safety = list(backup_dir.glob("gestdepot_pre_restore_*.db"))
        assert safety, "la sauvegarde de sécurité avant restauration est absente"

    def test_restauration_refuse_une_sauvegarde_invalide(self, backup, tmp_path):
        broken = tmp_path / "invalide.db"
        broken.write_bytes(b"pas une base")
        with pytest.raises(BackupError):
            backup.restore(str(broken), password="secret")


class TestAuthentificationRestauration:
    """§8.3 : la restauration exige la ressaisie du mot de passe administrateur."""

    def test_mot_de_passe_absent_refuse(self, backup, backup_dir):
        backup.save_settings(directory=str(backup_dir))
        record = backup.backup(label="avant")
        with pytest.raises(BackupError):
            backup.restore(record.path)

    def test_mot_de_passe_incorrect_refuse(self, backup, backup_dir):
        from gestdepot.security import AuthError
        backup.save_settings(directory=str(backup_dir))
        record = backup.backup(label="avant")
        with pytest.raises(AuthError):
            backup.restore(record.path, password="mauvais")

    def test_utilisateur_sans_permission_refuse(self, backup, backup_dir):

        from gestdepot.database.models import User
        from gestdepot.database.session import session_scope
        from gestdepot.security import auth, hash_password
        backup.save_settings(directory=str(backup_dir))
        record = backup.backup(label="avant")
        caissier = next(role for role in _roles() if role.name == "Caissier")
        with session_scope() as s:
            s.add(User(username="caisse1", role_id=caissier.id,
                       password_hash=hash_password("caisse1pass")))
        auth.login("caisse1", "caisse1pass")
        with pytest.raises(PermissionError):
            backup.restore(record.path, password="caisse1pass")


def _roles():
    from sqlalchemy import select

    from gestdepot.database.models import Role
    from gestdepot.database.session import session_scope
    with session_scope() as s:
        return list(s.scalars(select(Role)))
