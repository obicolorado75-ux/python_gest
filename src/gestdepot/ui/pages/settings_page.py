"""Paramètres, utilisateurs, audit et sauvegarde/restauration (§5.16, §8)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...security import auth
from ..widgets import DataTable, Page, confirm, info, refresh_after


class UserDialog(QDialog):
    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouvel utilisateur")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.role = QComboBox()
        for role in services["admin"].list_roles():
            self.role.addItem(role.name, role.id)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.pin = QLineEdit()
        self.pin.setPlaceholderText("facultatif — 4 à 8 chiffres")
        form.addRow("Identifiant *", self.username)
        form.addRow("Nom complet", self.full_name)
        form.addRow("Rôle", self.role)
        form.addRow("Mot de passe *", self.password)
        form.addRow("Code PIN", self.pin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Créer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.services["admin"].create_user(
                self.username.text().strip(), self.password.text(),
                self.role.currentText(), full_name=self.full_name.text().strip(),
                pin=self.pin.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Utilisateur", str(exc))
            return
        self.accept()


class SettingsPage(Page):
    title = "Paramètres et sauvegarde"

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._build_company_tab()
        self._build_users_tab()
        self._build_backup_tab()
        self._build_audit_tab()

    # --- dépôt ---------------------------------------------------------------
    def _build_company_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.address_edit = QLineEdit()
        self.footer_edit = QLineEdit()
        form.addRow("Nom du dépôt", self.name_edit)
        form.addRow("Téléphone", self.phone_edit)
        form.addRow("Adresse", self.address_edit)
        form.addRow("Pied de page des documents", self.footer_edit)
        layout.addLayout(form)
        currency = QLabel("Devise : FCFA (XOF) — montants en nombres entiers, "
                          "sans décimale.")
        currency.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(currency)
        save = QHBoxLayout()
        save.addWidget(QPushButton("Enregistrer les paramètres",
                                   clicked=self.save_company))
        save.addStretch(1)
        layout.addLayout(save)
        offline = QLabel(
            "Mode hors ligne : GestDepot fonctionne sans Internet. Les données "
            "restent sur ce poste — pensez à copier régulièrement les "
            "sauvegardes sur un support distinct (clé USB, disque externe).")
        offline.setWordWrap(True)
        offline.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(offline)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Dépôt")

    def save_company(self) -> None:
        try:
            self.services["admin"].update_company_settings(
                name=self.name_edit.text().strip() or "Mon dépôt",
                phone=self.phone_edit.text().strip() or None,
                address=self.address_edit.text().strip() or None,
                document_footer=self.footer_edit.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Paramètres", str(exc))
            return
        info(self, "Paramètres enregistrés.", "Paramètres")

    # --- utilisateurs ---------------------------------------------------------
    def _build_users_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        actions = QHBoxLayout()
        actions.addWidget(QPushButton("Nouvel utilisateur", clicked=self.new_user))
        actions.addWidget(QPushButton("Réinitialiser le mot de passe",
                                      clicked=self.reset_password))
        actions.addWidget(QPushButton("Désactiver", clicked=self.deactivate_user))
        actions.addStretch(1)
        layout.addLayout(actions)
        self.users_table = DataTable(["Identifiant", "Nom", "Rôle", "Statut"])
        layout.addWidget(self.users_table, 1)
        self.tabs.addTab(tab, "Utilisateurs")

    # --- sauvegarde ------------------------------------------------------------
    def _build_backup_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        actions = QHBoxLayout()
        actions.addWidget(QPushButton("Sauvegarder maintenant",
                                      clicked=self.backup_now))
        actions.addWidget(QPushButton("Restaurer une sauvegarde",
                                      clicked=self.restore))
        actions.addWidget(QPushButton("Vérifier une sauvegarde",
                                      clicked=self.verify_backup))
        actions.addStretch(1)
        layout.addLayout(actions)

        policy = QFormLayout()
        self.backup_dir = QLineEdit()
        self.backup_dir.setPlaceholderText("Dossier par défaut (ou disque externe)")
        self.keep_daily = QSpinBox()
        self.keep_daily.setRange(1, 365)
        self.keep_weekly = QSpinBox()
        self.keep_weekly.setRange(0, 104)
        self.auto_close = QCheckBox("Sauvegarder à la fermeture de l'application")
        self.auto_close.setChecked(True)
        policy_row = QHBoxLayout()
        policy_row.addWidget(self.backup_dir, 1)
        policy_row.addWidget(QPushButton("Choisir…", clicked=self.choose_backup_dir))
        policy_widget = QWidget()
        policy_widget.setLayout(policy_row)
        policy_row.setContentsMargins(0, 0, 0, 0)
        policy.addRow("Dossier de sauvegarde", policy_widget)
        retention = QHBoxLayout()
        retention.addWidget(QLabel("Quotidiennes :"))
        retention.addWidget(self.keep_daily)
        retention.addWidget(QLabel("Hebdomadaires :"))
        retention.addWidget(self.keep_weekly)
        retention.addStretch(1)
        retention_widget = QWidget()
        retention_widget.setLayout(retention)
        retention.setContentsMargins(0, 0, 0, 0)
        policy.addRow("Rétention", retention_widget)
        policy.addRow("", self.auto_close)
        layout.addLayout(policy)
        layout.addWidget(QPushButton("Enregistrer la politique de sauvegarde",
                                     clicked=self.save_backup_policy))
        note = QLabel("La sauvegarde utilise l'API SQLite et vérifie l'intégrité de "
                      "la copie. Aucune sauvegarde automatique ne peut s'exécuter "
                      "lorsque l'application est fermée.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(note)
        self.last_backup_label = QLabel("")
        self.last_backup_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.last_backup_label)
        self.backups_table = DataTable(["Date", "Fichier", "Taille", "Empreinte",
                                        "Résultat"])
        layout.addWidget(self.backups_table, 1)
        self.tabs.addTab(tab, "Sauvegarde")

    # --- audit ------------------------------------------------------------------
    def _build_audit_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.audit_table = DataTable(["Date", "Action", "Objet", "Détail"])
        layout.addWidget(self.audit_table, 1)
        self.tabs.addTab(tab, "Journal d'audit")

    # --- rafraîchissement --------------------------------------------------------
    def refresh(self) -> None:
        admin = self.services["admin"]
        settings = admin.company_settings()
        self.name_edit.setText(settings.name or "")
        self.phone_edit.setText(settings.phone or "")
        self.address_edit.setText(settings.address or "")
        self.footer_edit.setText(settings.document_footer or "")

        self._users = admin.list_users()
        self.users_table.load([[user.username, user.full_name or "—",
                                user.role.name if user.role else "—",
                                "Actif" if user.active else "Désactivé"]
                               for user in self._users],
                              colors={3: {"Actif": "#1B7F3B",
                                          "Désactivé": "#B3261E"}})

        try:
            policy = self.services["backup"].settings()
            self.backup_dir.setText(policy.get("backup.directory", ""))
            self.keep_daily.setValue(int(policy.get("backup.keep_daily", "7")))
            self.keep_weekly.setValue(int(policy.get("backup.keep_weekly", "4")))
            self.auto_close.setChecked(policy.get("backup.auto_close", "1") == "1")
        except Exception:
            pass
        try:
            last = self.services["backup"].last_successful()
        except Exception:
            last = None
        self.last_backup_label.setText(
            "Dernière sauvegarde réussie : "
            + (last.at.strftime("%d/%m/%Y %H:%M") if last else "aucune"))

        try:
            backups = self.services["backup"].history(limit=40)
        except Exception:
            backups = []
        self.backups_table.load([
            [b.at.strftime("%d/%m/%Y %H:%M"), b.path.split("/")[-1].split("\\")[-1],
             f"{b.size_bytes / 1024:.0f} Ko",
             (b.checksum or "")[:12],
             "OK" if b.success else "Échec"] for b in backups],
            colors={4: {"OK": "#1B7F3B", "Échec": "#B3261E"}})

        session = auth.Session.current()
        if session and session.has_permission("audit.view"):
            try:
                logs = admin.audit_logs(limit=200)
            except Exception:
                logs = []
            self.audit_table.load([[log.at.strftime("%d/%m/%Y %H:%M"), log.action,
                                    f"{log.object_type or ''} {log.object_id or ''}",
                                    (log.new_value or log.comment or "")[:80]]
                                   for log in logs])

    @refresh_after
    def new_user(self):
        if UserDialog(self.services, self).exec():
            return True

    @refresh_after
    def reset_password(self):
        row = self.users_table.selected_row()
        if row is None or row >= len(self._users):
            QMessageBox.information(self, "Utilisateur",
                                    "Sélectionnez un utilisateur.")
            return
        user = self._users[row]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Nouveau mot de passe — {user.username}")
        layout = QVBoxLayout(dialog)
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("Nouveau mot de passe (6 caractères minimum)"))
        layout.addWidget(password)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            self.services["admin"].set_password(user.id, password.text())
            return True

    @refresh_after
    def deactivate_user(self):
        row = self.users_table.selected_row()
        if row is None or row >= len(self._users):
            QMessageBox.information(self, "Utilisateur",
                                    "Sélectionnez un utilisateur.")
            return
        user = self._users[row]
        if not confirm(self, f"Désactiver « {user.username} » ?\n\n"
                             "Son historique reste consultable."):
            return
        self.services["admin"].deactivate_user(user.id)
        return True

    def choose_backup_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        directory = QFileDialog.getExistingDirectory(
            self, "Dossier des sauvegardes", self.backup_dir.text() or "")
        if directory:
            self.backup_dir.setText(directory)

    @refresh_after
    def save_backup_policy(self):
        self.services["backup"].save_settings(
            directory=self.backup_dir.text().strip(),
            keep_daily=self.keep_daily.value(),
            keep_weekly=self.keep_weekly.value(),
            auto_close=self.auto_close.isChecked())
        removed = self.services["backup"].purge_old()
        message = "Politique de sauvegarde enregistrée."
        if removed:
            message += f"\n{removed} ancienne(s) sauvegarde(s) purgée(s)."
        info(self, message, "Sauvegarde")
        return True

    @refresh_after
    def verify_backup(self):
        candidates = self.services["backup"].list_restore_candidates()
        if not candidates:
            QMessageBox.information(self, "Sauvegarde",
                                    "Aucune sauvegarde à vérifier.")
            return
        from PySide6.QtWidgets import QInputDialog
        labels = [f"{item['name']} — "
                  f"{'valide' if item['valid'] else 'INVALIDE'}"
                  for item in candidates]
        choice, ok = QInputDialog.getItem(self, "Vérifier une sauvegarde",
                                          "Fichier :", labels, 0, False)
        if not ok:
            return
        item = candidates[labels.index(choice)]
        self.services["backup"].verify(item["path"])
        info(self, f"Sauvegarde vérifiée (integrity_check OK) :\n{item['name']}",
             "Sauvegarde")
        return True

    @refresh_after
    def backup_now(self):
        record = self.services["backup"].backup(label="manuelle")
        info(self, f"Sauvegarde créée et vérifiée :\n{record.path}\n"
                   f"Taille : {record.size_bytes / 1024:.0f} Ko", "Sauvegarde")
        return True

    @refresh_after
    def restore(self):
        candidates = self.services["backup"].list_restore_candidates()
        valid = [candidate for candidate in candidates if candidate["valid"]]
        if not valid:
            QMessageBox.information(self, "Restauration",
                                    "Aucune sauvegarde valide disponible.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Restaurer une sauvegarde")
        dialog.resize(560, 360)
        layout = QVBoxLayout(dialog)
        warning = QLabel("La base actuelle sera sauvegardée puis remplacée. "
                         "L'opération est réservée aux administrateurs et tracée.")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #B3261E;")
        layout.addWidget(warning)
        table = DataTable(["Fichier", "Date", "Taille"])
        table.load([[c["name"], c["modified"].strftime("%d/%m/%Y %H:%M"),
                     f"{c['size'] / 1024:.0f} Ko"] for c in valid])
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Restaurer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if not dialog.exec():
            return
        row = table.selected_row()
        if row is None:
            QMessageBox.information(self, "Restauration",
                                    "Sélectionnez une sauvegarde.")
            return
        if not confirm(self, "Confirmer la restauration ? L'application devra être "
                             "redémarrée."):
            return
        self.services["backup"].restore(valid[row]["path"])
        info(self, "Restauration terminée. Redémarrez l'application.",
             "Restauration")
        return True
