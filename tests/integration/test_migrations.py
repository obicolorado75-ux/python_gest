"""Vérification des migrations Alembic (§4.1, §10.1)."""
import sqlite3
import subprocess
import sys

from sqlalchemy import inspect

from gestdepot.database.models import Base
from gestdepot.database.session import reset_for_tests


def _alembic(database: str, *arguments: str) -> subprocess.CompletedProcess:
    command = [sys.executable, "-m", "alembic", "-x", f"url=sqlite:///{database}",
               *arguments]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


class TestMigrations:
    def test_upgrade_head_cree_toutes_les_tables(self, tmp_path):
        database = tmp_path / "migrated.db"
        result = _alembic(str(database), "upgrade", "head")
        assert result.returncode == 0, result.stderr
        connection = sqlite3.connect(database)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        missing = set(Base.metadata.tables) - tables
        assert not missing, f"Tables absentes après migration : {missing}"
        assert "alembic_version" in tables

    def test_alembic_est_a_jour_avec_les_modeles(self, tmp_path):
        """Aucune divergence entre les modèles et la dernière migration."""
        database = tmp_path / "check.db"
        assert _alembic(str(database), "upgrade", "head").returncode == 0
        result = _alembic(str(database), "check")
        assert result.returncode == 0, (
            "Les modèles ont divergé des migrations : "
            f"{result.stdout}{result.stderr}")

    def test_base_creee_sans_migration_aussi(self, tmp_path):
        """Le démarrage direct (create_all) reste possible pour le prototype."""
        engine = reset_for_tests(f"sqlite:///{tmp_path}/direct.db")
        tables = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables) <= tables
