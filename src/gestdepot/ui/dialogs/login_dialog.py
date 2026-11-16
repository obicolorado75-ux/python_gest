"""Écran de connexion et assistant de premier lancement (§5.3, §12)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
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
        self.admin = AdminService()
        settings = self.admin.company_settings()
        self.username = ""
        self.password = ""

        logo_path = getattr(settings, "logo_path", None)
        if logo_path and os.path.exists(logo_path):
            self.logo = QLabel()
            self.logo.setPixmap(QPixmap(logo_path).scaledToHeight(
                56, Qt.SmoothTransformation))
            self.layout_root.insertWidget(0, self.logo)
        # ordre imposé : logo (si présent), nom du dépôt, mention hors ligne
        offset = 1 if logo_path and os.path.exists(logo_path) else 0
        heading = QLabel(settings.name or "GestDepot")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.layout_root.insertWidget(0 + offset, heading)
        offline = QLabel("Mode hors ligne — aucune connexion Internet requise")
        offline.setStyleSheet("color: #5f6b7a; font-size: 11px;")
        self.layout_root.insertWidget(1 + offset, offline)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Identifiant")
        self.user_edit.textChanged.connect(self._on_username_changed)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("Mot de passe")
        show = QCheckBox("Afficher le mot de passe")
        show.toggled.connect(lambda checked: self.pass_edit.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password))
        hint = QLabel("Les profils de caisse disposant d'un code PIN peuvent "
                      "l'utiliser à la place du mot de passe.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a; font-size: 11px;")
        self.form.addRow("Identifiant", self.user_edit)
        self.form.addRow("Mot de passe / PIN", self.pass_edit)
        self.form.addRow("", show)
        self.form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Se connecter")
        buttons.button(QDialogButtonBox.Cancel).setText("Quitter")
        buttons.accepted.connect(self._login)
        buttons.rejected.connect(self.reject)
        self.layout_root.addWidget(buttons)
        self.user_edit.setFocus()

    def _on_username_changed(self, text: str) -> None:
        """Un code PIN court bascule le champ en saisie masquée numérique."""
        pin_mode = bool(text.strip()) and self._user_has_pin(text.strip())
        self.pass_edit.setPlaceholderText(
            "Code PIN ou mot de passe" if pin_mode else "Mot de passe")

    def _user_has_pin(self, username: str) -> bool:
        try:
            return any(user.username == username and user.pin_hash
                       for user in self.admin.list_users(include_inactive=False))
        except Exception:  # pragma: no cover - base indisponible
            return False

    def _login(self):
        username = self.user_edit.text().strip()
        secret = self.pass_edit.text()
        user = None
        if secret.isdigit() and self._user_has_pin(username):
            try:
                user = next(u for u in self.admin.list_users(False)
                            if u.username == username)
            except StopIteration:  # pragma: no cover - défensif
                user = None
        try:
            if user is not None:
                session = auth.login_pin(user.id, secret)
            else:
                session = auth.login(username, secret)
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
