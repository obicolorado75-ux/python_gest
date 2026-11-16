"""Écran de connexion et assistant de premier lancement (§5.3, §12)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...security import AuthError, auth


class _BaseDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.form = QFormLayout()
        self.layout_root = QVBoxLayout(self)
        self.layout_root.addLayout(self.form)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #B3261E;")
        self.error.setWordWrap(True)
        self.layout_root.addWidget(self.error)


class LoginDialog(_BaseDialog):
    """Connexion : message neutre, mode hors ligne indiqué."""

    def __init__(self, parent=None):
        from ...services.admin_service import AdminService
        super().__init__("Connexion — GestDepot", parent)
        settings = AdminService().company_settings()
        self.username = ""
        self.password = ""

        heading = QLabel(settings.name or "GestDepot")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.layout_root.insertWidget(0, heading)
        offline = QLabel("Mode hors ligne — aucune connexion Internet requise")
        offline.setStyleSheet("color: #5f6b7a; font-size: 11px;")
        self.layout_root.insertWidget(1, offline)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Identifiant")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("Mot de passe")
        show = QCheckBox("Afficher le mot de passe")
        show.toggled.connect(lambda checked: self.pass_edit.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password))
        self.form.addRow("Identifiant", self.user_edit)
        self.form.addRow("Mot de passe", self.pass_edit)
        self.form.addRow("", show)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Se connecter")
        buttons.button(QDialogButtonBox.Cancel).setText("Quitter")
        buttons.accepted.connect(self._login)
        buttons.rejected.connect(self.reject)
        self.layout_root.addWidget(buttons)
        self.user_edit.setFocus()

    def _login(self):
        try:
            session = auth.login(self.user_edit.text().strip(),
                                 self.pass_edit.text())
        except AuthError as exc:
            self.error.setText(str(exc))
            self.pass_edit.clear()
            self.pass_edit.setFocus()
            return
        self.username = session.user.username
        self.password = self.pass_edit.text()
        self.accept()


class FirstRunDialog(_BaseDialog):
    """Assistant de premier lancement : dépôt + compte administrateur."""

    def __init__(self, parent=None):
        super().__init__("Premier lancement — GestDepot", parent)
        from ...services.admin_service import AdminService
        self.admin = AdminService()
        self.username = ""
        self.password = ""

        heading = QLabel("Bienvenue dans GestDepot")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.layout_root.insertWidget(0, heading)
        intro = QLabel("Créez le compte administrateur et nommez votre dépôt. "
                       "Toutes les données resteront sur cet ordinateur.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5f6b7a;")
        self.layout_root.insertWidget(1, intro)

        self.depot_edit = QLineEdit(self.admin.company_settings().name or "Mon dépôt")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("ex. admin")
        self.full_name_edit = QLineEdit()
        self.full_name_edit.setPlaceholderText("Nom du responsable")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        self.pin_edit = QLineEdit()
        self.pin_edit.setPlaceholderText("facultatif — 4 à 8 chiffres")
        self.form.addRow("Nom du dépôt", self.depot_edit)
        self.form.addRow("Identifiant", self.user_edit)
        self.form.addRow("Nom complet", self.full_name_edit)
        self.form.addRow("Mot de passe", self.pass_edit)
        self.form.addRow("Confirmation", self.confirm_edit)
        self.form.addRow("Code PIN", self.pin_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Créer et démarrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Quitter")
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        self.layout_root.addWidget(buttons)

    def _create(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()
        if password != self.confirm_edit.text():
            self.error.setText("Les deux mots de passe ne correspondent pas.")
            return
        try:
            self.admin.update_company_settings(name=self.depot_edit.text().strip()
                                               or "Mon dépôt")
            self.admin.create_user(username, password, "Administrateur",
                                   full_name=self.full_name_edit.text().strip(),
                                   pin=self.pin_edit.text().strip() or None)
        except Exception as exc:
            self.error.setText(str(exc))
            return
        self.username = username
        self.password = password
        self.accept()
