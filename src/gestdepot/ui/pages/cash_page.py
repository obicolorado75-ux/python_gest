"""Caisse et dépenses : ouverture, mouvements, dépenses, clôture (§5.12)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...services.sales_service import PAYMENT_LABELS, PAYMENT_METHODS
from ..widgets import DataTable, Page, confirm, info, money, refresh_after


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
        for method in PAYMENT_METHODS:
            self.method.addItem(PAYMENT_LABELS[method], method)
        self.comment = QLineEdit()
        form.addRow("Catégorie", self.category)
        form.addRow("Bénéficiaire", self.beneficiary)
        form.addRow("Montant", self.amount)
        form.addRow("Moyen de paiement", self.method)
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
        try:
            self.services["cash"].add_expense(
                self.amount.value(), self.category.currentData(),
                payment_method=self.method.currentData(),
                beneficiary=self.beneficiary.text().strip() or None,
                comment=self.comment.text().strip() or None)
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


class CashPage(Page):
    title = "Caisse et dépenses"
    subtitle = ("Le solde de caisse ne comprend que les espèces ; Mobile Money et "
                "virements sont suivis séparément.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.add_action("Ouvrir une caisse", self.open_session, primary=True)
        self.add_action("Nouvelle dépense", self.new_expense)
        self.add_action("Clôturer la caisse", self.close_session)
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
                                   "Bénéficiaire", "Commentaire"])
        expenses_layout.addWidget(self.expenses)
        self.tabs.addTab(expenses_tab, "Dépenses")

        sessions_tab = QWidget()
        sessions_layout = QVBoxLayout(sessions_tab)
        self.sessions = DataTable(["Ouverture", "Clôture", "Fond", "Théorique",
                                   "Compté", "Écart", "Statut"])
        sessions_layout.addWidget(self.sessions)
        self.tabs.addTab(sessions_tab, "Historique des sessions")

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
            extra = "  ·  ".join(f"{PAYMENT_LABELS.get(method, method)} "
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
                 money(mv.amount), PAYMENT_LABELS.get(mv.payment_method,
                                                      mv.payment_method),
                 mv.reason] for mv in cash.movements(session.id)],
                numeric_columns={2},
                colors={1: {"Entrée": "#1B7F3B", "Sortie": "#B3261E"}})

        self.expenses.load([[exp.number, exp.at.strftime("%d/%m/%Y"),
                             money(exp.amount),
                             PAYMENT_LABELS.get(exp.payment_method,
                                                exp.payment_method),
                             exp.beneficiary or "—", exp.comment or ""]
                            for exp in cash.list_expenses(limit=100)],
                           numeric_columns={2})

        self.sessions.load([
            [s.opened_at.strftime("%d/%m/%Y %H:%M"),
             s.closed_at.strftime("%d/%m/%Y %H:%M") if s.closed_at else "—",
             money(s.opening_fund),
             money(s.theoretical_amount) if s.theoretical_amount is not None else "—",
             money(s.counted_amount) if s.counted_amount is not None else "—",
             money(s.difference) if s.difference is not None else "—",
             "Ouverte" if s.status == "open" else "Clôturée"]
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
    def close_session(self):
        if self._session is None:
            QMessageBox.information(self, "Caisse", "Aucune session ouverte.")
            return
        if CloseDialog(self.services, self._session, self).exec():
            return True
