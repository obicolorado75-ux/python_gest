"""Caisse et dépenses : ouverture, mouvements, dépenses, clôture (§5.12)."""
from __future__ import annotations

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
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

from ...services import payment_methods
from ..widgets import DataTable, Page, confirm, info, money, refresh_after

MOVEMENT_REASON_LABELS = {
    "encaissement_vente": "Encaissement vente",
    "reglement_creance": "Règlement créance",
    "remboursement_client": "Remboursement client",
    "paiement_fournisseur": "Paiement fournisseur",
    "depense": "Dépense",
    "retrait": "Retrait",
    "apport": "Apport",
    "consigne": "Consigne",
    "remboursement_consigne": "Remboursement consigne",
    "correction": "Correction",
}


class ExpenseDialog(QDialog):
    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Nouvelle dépense")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.category = QComboBox()
        for category in services["cash"].list_expense_categories():
            self.category.addItem(category.name, category.id)
        self.beneficiary = QLineEdit()
        self.amount = QSpinBox()
        self.amount.setRange(1, 1_000_000_000)
        self.amount.setSingleStep(500)
        self.method = QComboBox()
        labels = payment_methods.labels()
        for method in payment_methods.codes():
            self.method.addItem(labels[method], method)
        self.date = QDateTimeEdit(QDateTime.currentDateTime())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.receipt = QLineEdit()
        self.receipt.setPlaceholderText("Référence du justificatif (facultatif)")
        self.comment = QLineEdit()
        form.addRow("Catégorie", self.category)
        form.addRow("Bénéficiaire", self.beneficiary)
        form.addRow("Montant", self.amount)
        form.addRow("Date", self.date)
        form.addRow("Moyen de paiement", self.method)
        form.addRow("Justificatif", self.receipt)
        form.addRow("Commentaire", self.comment)
        layout.addLayout(form)
        hint = QLabel("Une dépense en espèces diminue le solde théorique de caisse.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        if self.category.currentData() is None:
            QMessageBox.information(self, "Dépense",
                                    "Choisissez une catégorie de dépense.")
            return
        try:
            self.services["cash"].add_expense(
                self.amount.value(), self.category.currentData(),
                payment_method=self.method.currentData(),
                beneficiary=self.beneficiary.text().strip() or None,
                comment=self.comment.text().strip() or None,
                receipt_path=self.receipt.text().strip() or None,
                at=self.date.dateTime().toPython())
        except Exception as exc:
            QMessageBox.warning(self, "Dépense", str(exc))
            return
        self.accept()


class CloseDialog(QDialog):
    def __init__(self, services, session, parent=None):
        super().__init__(parent)
        self.services = services
        self.session = session
        self.setWindowTitle("Clôture de caisse")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        theoretical = services["cash"].theoretical_amount(session.id)
        header = QLabel(f"Solde théorique espèces : {money(theoretical)}")
        header.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(header)
        form = QFormLayout()
        self.counted = QSpinBox()
        self.counted.setRange(0, 1_000_000_000)
        self.counted.setSingleStep(500)
        self.counted.setValue(theoretical)
        self.comment = QLineEdit()
        form.addRow("Montant compté", self.counted)
        form.addRow("Commentaire", self.comment)
        layout.addLayout(form)
        self.gap = QLabel("")
        self.gap.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.gap)
        self.counted.valueChanged.connect(
            lambda value: self.gap.setText(
                f"Écart : {money(value - theoretical)}"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Clôturer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._theoretical = theoretical

    def _save(self):
        try:
            closed = self.services["cash"].close_session(
                self.session.id, self.counted.value(),
                self.comment.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Clôture", str(exc))
            return
        info(self, f"Caisse clôturée.\nÉcart enregistré : "
                   f"{money(closed.difference)}", "Clôture")
        self.accept()


class MovementDialog(QDialog):
    """Retrait, apport ou correction de caisse (§5.12)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Mouvement de caisse")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("Retrait d'espèces", ("out", "retrait"))
        self.kind.addItem("Apport d'espèces", ("in", "apport"))
        self.kind.addItem("Correction autorisée", None)
        self.amount = QSpinBox()
        self.amount.setRange(1, 1_000_000_000)
        self.amount.setSingleStep(500)
        self.method = QComboBox()
        labels = payment_methods.labels()
        for method in payment_methods.codes():
            self.method.addItem(labels[method], method)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Motif (obligatoire pour une correction)")
        form.addRow("Opération", self.kind)
        form.addRow("Montant", self.amount)
        form.addRow("Moyen", self.method)
        form.addRow("Motif", self.comment)
        layout.addLayout(form)
        self.direction = QComboBox()
        self.direction.addItem("Entrée de caisse", "in")
        self.direction.addItem("Sortie de caisse", "out")
        form.addRow("Sens (correction)", self.direction)
        self.direction_row_visible(False)
        hint = QLabel("Seuls les mouvements en espèces modifient le solde physique. "
                      "Une correction est journalisée et auditée.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Enregistrer")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._kind_changed)

    def direction_row_visible(self, visible: bool) -> None:
        self.direction.setVisible(visible)
        label = self.layout().itemAt(0).layout().labelForField(self.direction)
        if label is not None:
            label.setVisible(visible)

    def _kind_changed(self) -> None:
        self.direction_row_visible(self.kind.currentData() is None)

    def _save(self):
        data = self.kind.currentData()
        direction, reason = data if data else (self.direction.currentData(),
                                               "correction")
        try:
            self.services["cash"].register_movement(
                direction, self.amount.value(), reason,
                payment_method=self.method.currentData(),
                comment=self.comment.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Mouvement de caisse", str(exc))
            return
        self.accept()


class CorrectionDialog(QDialog):
    """Correction d'une session clôturée, avec motif et nouveau comptage."""

    def __init__(self, services, session, parent=None):
        super().__init__(parent)
        self.services = services
        self.session = session
        self.setWindowTitle("Corriger une caisse clôturée")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        header = QLabel(
            f"Session du {session.opened_at:%d/%m/%Y %H:%M} — compté "
            f"{money(session.counted_amount or 0)}, théorique "
            f"{money(session.theoretical_amount or 0)}, écart "
            f"{money(session.difference or 0)}")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: 600;")
        layout.addWidget(header)
        form = QFormLayout()
        self.direction = QComboBox()
        self.direction.addItem("Entrée de caisse (manquant constaté)", "in")
        self.direction.addItem("Sortie de caisse (excédent constaté)", "out")
        self.amount = QSpinBox()
        self.amount.setRange(1, 1_000_000_000)
        self.amount.setSingleStep(500)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motif de la correction (obligatoire)")
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Précisions (facultatif)")
        form.addRow("Sens", self.direction)
        form.addRow("Montant", self.amount)
        form.addRow("Motif", self.reason)
        form.addRow("Précisions", self.comment)
        layout.addLayout(form)
        hint = QLabel("La correction est un mouvement horodaté rattaché à la session "
                      "corrigée : rien n'est effacé, l'écart est recalculé et "
                      "l'opération est inscrite au journal d'audit.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Corriger")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.services["cash"].correct_closed_session(
                self.session.id, self.amount.value(), self.direction.currentData(),
                self.reason.text().strip(), self.comment.text().strip() or None)
        except Exception as exc:
            QMessageBox.warning(self, "Correction refusée", str(exc))
            return
        self.accept()


class CategoryDialog(QDialog):
    """Gestion des catégories de dépenses (§5.12)."""

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.setWindowTitle("Catégories de dépenses")
        self.setMinimumSize(460, 340)
        layout = QVBoxLayout(self)
        self.table = DataTable(["Catégorie"])
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nouvelle catégorie")
        row.addWidget(self.name, 1)
        row.addWidget(QPushButton("Ajouter", clicked=self._add))
        row.addWidget(QPushButton("Supprimer", clicked=self._delete))
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Fermer")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load()

    def _load(self):
        self._categories = self.services["cash"].list_expense_categories()
        self.table.load([[category.name] for category in self._categories])

    def _add(self):
        try:
            self.services["cash"].create_expense_category(self.name.text())
        except Exception as exc:
            QMessageBox.warning(self, "Catégorie", str(exc))
            return
        self.name.clear()
        self._load()

    def _delete(self):
        row = self.table.selected_row()
        if row is None or row >= len(self._categories):
            QMessageBox.information(self, "Catégorie", "Sélectionnez une catégorie.")
            return
        category = self._categories[row]
        if not confirm(self, f"Supprimer la catégorie « {category.name} » ?"):
            return
        try:
            self.services["cash"].delete_expense_category(category.id)
        except Exception as exc:
            QMessageBox.warning(self, "Suppression impossible", str(exc))
            return
        self._load()


class CashPage(Page):
    title = "Caisse et dépenses"
    subtitle = ("Le solde de caisse ne comprend que les espèces ; Mobile Money et "
                "virements sont suivis séparément.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Ouvrir une caisse", self.open_session, primary=True)
        self.add_action("Retrait / apport", self.new_movement)
        self.add_action("Nouvelle dépense", self.new_expense)
        self.add_action("Annuler une dépense", self.cancel_expense)
        self.add_action("Clôturer la caisse", self.close_session)
        self.add_action("Corriger une caisse", self.correct_session)
        self.add_action("Catégories de dépenses", self.manage_categories)
        self.add_stretch()

        self.state_label = QLabel("")
        self.state_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.body.addWidget(self.state_label)

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)

        movements_tab = QWidget()
        movements_layout = QVBoxLayout(movements_tab)
        self.movements = DataTable(["Date", "Sens", "Montant", "Moyen", "Motif"])
        movements_layout.addWidget(self.movements)
        self.tabs.addTab(movements_tab, "Mouvements de la caisse ouverte")

        expenses_tab = QWidget()
        expenses_layout = QVBoxLayout(expenses_tab)
        self.expenses = DataTable(["N°", "Date", "Montant", "Moyen",
                                   "Bénéficiaire", "Catégorie", "Justificatif",
                                   "Statut", "Commentaire"])
        expenses_layout.addWidget(self.expenses)
        self.tabs.addTab(expenses_tab, "Dépenses")

        sessions_tab = QWidget()
        sessions_layout = QVBoxLayout(sessions_tab)
        self.sessions = DataTable(["Ouverture", "Clôture", "Fond", "Théorique",
                                   "Compté", "Écart", "Statut", "Commentaire"])
        self.sessions.doubleClicked.connect(lambda _: self.correct_session())
        sessions_layout.addWidget(self.sessions)
        self.tabs.addTab(sessions_tab, "Historique des sessions")

        corrections_tab = QWidget()
        corrections_layout = QVBoxLayout(corrections_tab)
        self.corrections = DataTable(["Date", "Session", "Sens", "Montant",
                                      "Motif"])
        corrections_layout.addWidget(self.corrections)
        self.tabs.addTab(corrections_tab, "Corrections")

    def refresh(self) -> None:
        cash = self.services["cash"]
        session = cash.current_session()
        self._session = session
        if session is None:
            self.state_label.setText("Aucune session de caisse ouverte pour cet "
                                     "utilisateur.")
            self.state_label.setStyleSheet("font-size: 13px; font-weight: 600; "
                                           "color: #B26A00;")
            self.movements.load([])
        else:
            theoretical = cash.theoretical_amount(session.id)
            by_method = cash.movements_by_method(session.id)
            extra = "  ·  ".join(f"{payment_methods.labels().get(method, method)} "
                                 f"{money(amount)}"
                                 for method, amount in by_method.items()
                                 if method != "especes")
            self.state_label.setText(
                f"Caisse ouverte le {session.opened_at:%d/%m/%Y %H:%M} — "
                f"fond {money(session.opening_fund)} — théorique espèces "
                f"{money(theoretical)}" + (f"  ·  {extra}" if extra else ""))
            self.state_label.setStyleSheet("font-size: 13px; font-weight: 600; "
                                           "color: #12324f;")
            self.movements.load([
                [mv.at.strftime("%d/%m/%Y %H:%M"),
                 "Entrée" if mv.direction == "in" else "Sortie",
                 money(mv.amount), payment_methods.labels().get(mv.payment_method,
                                                      mv.payment_method),
                 MOVEMENT_REASON_LABELS.get(mv.reason, mv.reason)]
                for mv in cash.movements(session.id)],
                numeric_columns={2},
                colors={1: {"Entrée": "#1B7F3B", "Sortie": "#B3261E"}})

        categories = {c.id: c.name for c in cash.list_expense_categories()}
        self._expenses = cash.list_expenses(limit=100)
        self.expenses.load([[exp.number, exp.at.strftime("%d/%m/%Y"),
                             money(exp.amount),
                             payment_methods.labels().get(exp.payment_method,
                                                exp.payment_method),
                             exp.beneficiary or "—",
                             categories.get(exp.category_id, "—"),
                             exp.receipt_path or "—",
                             "Annulée" if exp.cancelled_at else "Enregistrée",
                             exp.cancel_reason or exp.comment or ""]
                            for exp in self._expenses],
                           numeric_columns={2},
                           colors={7: {"Annulée": "#B3261E",
                                       "Enregistrée": "#1B7F3B"}})

        self.corrections.load([
            [mv.at.strftime("%d/%m/%Y %H:%M") if mv.at else "",
             f"#{mv.corrects_session_id}",
             "Entrée" if mv.direction == "in" else "Sortie",
             money(mv.amount), mv.correction_reason or mv.comment or ""]
            for mv in cash.corrections()], numeric_columns={3},
            colors={2: {"Entrée": "#1B7F3B", "Sortie": "#B3261E"}})

        self.sessions.load([
            [s.opened_at.strftime("%d/%m/%Y %H:%M"),
             s.closed_at.strftime("%d/%m/%Y %H:%M") if s.closed_at else "—",
             money(s.opening_fund),
             money(s.theoretical_amount) if s.theoretical_amount is not None else "—",
             money(s.counted_amount) if s.counted_amount is not None else "—",
             money(s.difference) if s.difference is not None else "—",
             "Ouverte" if s.status == "open" else "Clôturée",
             s.close_comment or ""]
            for s in cash.list_sessions()], numeric_columns={2, 3, 4, 5},
            colors={6: {"Ouverte": "#1B7F3B", "Clôturée": "#5f6b7a"}})

    @refresh_after
    def open_session(self):
        if self._session is not None:
            QMessageBox.information(self, "Caisse",
                                    "Une session est déjà ouverte.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Ouverture de caisse")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        fund = QSpinBox()
        fund.setRange(0, 1_000_000_000)
        fund.setSingleStep(500)
        form.addRow("Fond de caisse initial", fund)
        layout.addLayout(form)
        hint = QLabel("Comptez l'espèce présent dans le tiroir avant de commencer.")
        hint.setStyleSheet("color: #5f6b7a;")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Ouvrir")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            self.services["cash"].open_session(fund.value())
            return True

    @refresh_after
    def new_expense(self):
        if self._session is None:
            if not confirm(self, "Aucune caisse ouverte. Enregistrer la dépense "
                                 "sans session de caisse ?"):
                return
        if ExpenseDialog(self.services, self).exec():
            return True

    @refresh_after
    def new_movement(self):
        if self._session is None:
            QMessageBox.information(self, "Caisse",
                                    "Ouvrez d'abord une session de caisse.")
            return
        if MovementDialog(self.services, self).exec():
            return True

    @refresh_after
    def cancel_expense(self):
        expenses = getattr(self, "_expenses", [])
        if self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(1)
        row = self.expenses.selected_row()
        if row is None or row >= len(expenses):
            QMessageBox.information(self, "Dépense",
                                    "Sélectionnez une dépense dans l'onglet "
                                    "« Dépenses ».")
            return
        expense = expenses[row]
        if expense.cancelled_at is not None:
            QMessageBox.information(self, "Dépense", "Dépense déjà annulée.")
            return
        from PySide6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(
            self, "Annuler la dépense",
            f"Motif de l'annulation de {expense.number} "
            f"({money(expense.amount)}) :")
        if not ok or not reason.strip():
            return
        self.services["cash"].cancel_expense(expense.id, reason.strip())
        return True

    @refresh_after
    def correct_session(self):
        sessions = self.services["cash"].list_sessions()
        closed = [item for item in sessions if item.status != "open"]
        if not closed:
            QMessageBox.information(self, "Correction",
                                    "Aucune session clôturée à corriger.")
            return
        target = None
        if self.tabs.currentIndex() == 2:
            row = self.sessions.selected_row()
            if row is not None and row < len(sessions) and \
                    sessions[row].status != "open":
                target = sessions[row]
        if target is None:
            from PySide6.QtWidgets import QInputDialog
            labels = [f"{s.opened_at:%d/%m/%Y %H:%M} — écart "
                      f"{money(s.difference or 0)}" for s in closed]
            choice, ok = QInputDialog.getItem(
                self, "Corriger une caisse clôturée", "Session à corriger :",
                labels, 0, False)
            if not ok:
                return
            target = closed[labels.index(choice)]
        if CorrectionDialog(self.services, target, self).exec():
            return True

    def manage_categories(self):
        CategoryDialog(self.services, self).exec()
        self.refresh()

    @refresh_after
    def close_session(self):
        if self._session is None:
            QMessageBox.information(self, "Caisse", "Aucune session ouverte.")
            return
        if CloseDialog(self.services, self._session, self).exec():
            return True
