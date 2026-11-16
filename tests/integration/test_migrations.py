"""Vérification des migrations Alembic (§4.1, §10.1)."""
import sqlite3
import subprocess
import sys

from sqlalchemy import inspect

from gestdepot.database.models import Base
from gestdepot.database.session import reset_for_tests

# révision de tête attendue : à mettre à jour avec la dernière migration
MIGRATION_HEAD = "97151b198b7d"


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


class TestMiseANiveauAutomatique:
    """Une base d'une version antérieure est mise à jour au démarrage (§4.1, §8)."""

    def _old_database(self, tmp_path, revision):
        import subprocess
        import sys
        path = tmp_path / "old.db"
        url = f"sqlite:///{path}"
        subprocess.run([sys.executable, "-m", "alembic", "-x", f"url={url}",
                        "upgrade", revision], check=True, capture_output=True)
        return str(path), url

    def test_colonnes_ajoutees_au_demarrage(self, tmp_path):
        from sqlalchemy import inspect
        from sqlalchemy import text as sql_text

        from gestdepot.database.session import init_engine
        _path, url = self._old_database(tmp_path, "92b311107557")
        engine = init_engine(url)
        columns = [c["name"] for c in inspect(engine).get_columns("purchase_orders")]
        assert "discount_amount" in columns and "freight_fees" in columns
        with engine.connect() as conn:
            version = conn.execute(
                sql_text("select version_num from alembic_version")).scalar()
        assert version == MIGRATION_HEAD
        # deuxième démarrage : idempotent, rien n'est rejoué
        init_engine(url)

    def test_base_sans_version_adoptee(self, tmp_path):
        """Base créée par create_all (avant Alembic) : adopted sans perte."""
        from sqlalchemy import create_engine

        from gestdepot.database.models import Base
        from gestdepot.database.session import init_engine
        path = tmp_path / "legacy.db"
        url = f"sqlite:///{path}"
        legacy = create_engine(url)
        Base.metadata.create_all(legacy)
        legacy.dispose()
        engine = init_engine(url)
        with engine.connect() as conn:
            from sqlalchemy import text as sql_text
            version = conn.execute(
                sql_text("select version_num from alembic_version")).scalar()
        assert version == MIGRATION_HEAD
