"""§5.3 — écran de connexion : message neutre, limitation, PIN, journalisation."""
import pytest

from gestdepot.security import AuthError, auth


class TestConnexion:
    def test_message_neutre_identifiant_inconnu(self, db):
        with pytest.raises(AuthError) as unknown:
            auth.login("inconnu", "secret")
        with pytest.raises(AuthError) as bad_password:
            auth.login("admin", "mauvais")
        assert str(unknown.value) == str(bad_password.value)
        assert "incorrect" in str(unknown.value)

    def test_journalisation_des_acces(self, db):
        from gestdepot.services.admin_service import AdminService
        auth.login("admin", "secret")
        assert any(log.action == "login_ok"
                   for log in AdminService().audit_logs(limit=5))
        auth.Session.logout()
        with pytest.raises(AuthError):
            auth.login("inconnu", "faux")
        assert any(log.action == "login_failed" and log.comment == "inconnu"
                   for log in AdminService().audit_logs(limit=10))

    def test_limitation_progressive(self, db):
        for _ in range(auth.MAX_ATTEMPTS):
            with pytest.raises(AuthError):
                auth.login("admin", "faux")
        with pytest.raises(AuthError) as blocked:
            auth.login("admin", "secret")
        assert "Trop de tentatives" in str(blocked.value)

    def test_compte_desactive_refuse(self, db, admin):
        from gestdepot.services.admin_service import AdminService
        service = AdminService()
        user = service.create_user("temporaire", "motdepasse", "Caissier")
        service.deactivate_user(user.id)
        auth.Session.logout()
        with pytest.raises(AuthError):
            auth.login("temporaire", "motdepasse")

    def test_verrouillage_de_session(self, db, admin):
        auth.Session.logout()
        assert auth.Session.current() is None


class TestConnexionPin:
    @pytest.fixture()
    def pin_user(self, admin):
        from gestdepot.services.admin_service import AdminService
        service = AdminService()
        user = service.create_user("caisse1", "motdepasse", "Caissier",
                                   pin="1234")
        auth.Session.logout()
        return user

    def test_pin_valide_ouvre_la_session(self, pin_user):
        session = auth.login_pin(pin_user.id, "1234")
        assert session.user.username == "caisse1"

    def test_pin_incorrect_refuse(self, pin_user):
        with pytest.raises(AuthError):
            auth.login_pin(pin_user.id, "9999")

    def test_pin_limite_les_tentatives(self, pin_user):
        for _ in range(auth.MAX_ATTEMPTS):
            with pytest.raises(AuthError):
                auth.login_pin(pin_user.id, "0000")
        with pytest.raises(AuthError) as blocked:
            auth.login_pin(pin_user.id, "1234")
        assert "Trop de tentatives" in str(blocked.value)

    def test_utilisateur_sans_pin_refuse(self, db, admin):
        with pytest.raises(AuthError):
            auth.login_pin(admin.id, "1234")
