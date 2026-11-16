"""Crée la base locale et un jeu de démonstration clairement identifié (§12)."""
from gestdepot.app import bootstrap_database, seed_demo_data
from gestdepot.security import auth
from gestdepot.services.admin_service import AdminService

if __name__ == "__main__":
    bootstrap_database()
    admin = AdminService()
    if not admin.has_any_user():
        admin.create_user("admin", "admin123", "Administrateur",
                          full_name="Administrateur de démonstration")
    auth.login("admin", "admin123")
    try:
        seed_demo_data()
    except RuntimeError as exc:
        print(f"Rien à faire : {exc}")
    else:
        print("Base de démonstration prête — identifiant : admin / admin123")
