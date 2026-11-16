"""Fixture partagée : base de test en mémoire + utilisateur admin connecté."""
import pytest

from gestdepot.database.session import reset_for_tests
from gestdepot.security import auth, hash_password
from gestdepot.database.models import Role, User
from gestdepot.database.session import session_scope
from sqlalchemy import select


@pytest.fixture()
def db(tmp_path):
    engine = reset_for_tests(f"sqlite:///{tmp_path}/test.db")
    # utilisateur admin de test
    with session_scope() as s:
        role = s.scalar(select(Role).where(Role.name == "Administrateur"))
        s.add(User(username="admin", password_hash=hash_password("secret"),
                   role_id=role.id, full_name="Admin Test"))
    auth.Session.logout()
    yield engine
    auth.Session.logout()


@pytest.fixture()
def admin(db):
    s = auth.login("admin", "secret")
    return s.user
