"""Tableau de bord : indicateurs de la période et alertes locales (§5.4)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...domain.rules import label_status
from ...services.reporting_service import Period
from ..widgets import DataTable, Page, card, money

PERIODS = {
    "Aujourd'hui": Period.today,
    "Hier": Period.yesterday,
    "7 derniers jours": lambda: Period.last_days(7),
    "Mois en cours": Period.current_month,
}


class DashboardPage(Page):
    title = "Tableau de bord"
    subtitle = ("Indicateurs calculés à partir des opérations enregistrées — "
                "hors ligne.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        self.period_box = QComboBox()
        self.period_box.addItems(PERIODS.keys())
        self.period_box.currentTextChanged.connect(lambda _: self.refresh())
        self.actions.addWidget(QLabel("Période :"))
        self.actions.addWidget(self.period_box)
        self.add_action("Rafraîchir", self.refresh)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #5f6b7a;")
        self.summary_label.setWordWrap(True)
        self.root.insertWidget(2, self.summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self.body.addWidget(scroll)
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.cards: dict[str, object] = {}
        self.cards_grid = QGridLayout()
        self.cards_grid.setHorizontalSpacing(12)
        self.cards_grid.setVerticalSpacing(12)
        self.cards_grid.setColumnStretch(0, 1)
        self.cards_grid.setColumnStretch(1, 1)
        self.cards_grid.setColumnStretch(2, 1)
        self.cards_grid.setAlignment(Qt.AlignTop)
        layout.addLayout(self.cards_grid)
        layout.addSpacing(6)

        self.customers_title = QLabel("Créances clients")
        self.customers_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(self.customers_title)
        self.debtors = DataTable(["Client", "Plafond", "Solde dû", "Téléphone"])
        self.debtors.setFixedHeight(150)
        layout.addWidget(self.debtors)

        alerts_title = QLabel("Alertes de stock")
        alerts_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(alerts_title)
        self.alerts = DataTable(["Produit", "Disponible", "Seuil", "Statut"])
        self.alerts.setFixedHeight(190)
        layout.addWidget(self.alerts)

        activity_title = QLabel("Dernières ventes")
        activity_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(activity_title)
        self.recent = DataTable(["N°", "Date", "Client", "Total", "Payé", "Statut"])
        self.recent.setFixedHeight(220)
        layout.addWidget(self.recent)
        layout.addStretch(1)

    MIN_CARD_ROW_HEIGHT = 96

    CARD_TITLES = [
        ("net_sales", "Chiffre d'affaires net"),
        ("gross_margin", "Marge brute estimée"),
        ("estimated_result", "Résultat estimatif de gestion"),
        ("receivables", "Créances clients"),
        ("payables", "Dettes fournisseurs"),
        ("stock_value", "Valeur du stock"),
    ]

    def _build_cards(self) -> None:
        """Les cartes sont créées une seule fois puis mises à jour (§5.4)."""
        if self.cards:
            return
        for index, (key, title) in enumerate(self.CARD_TITLES):
            widget = card(title, "—", "")
            widget.setMinimumHeight(self.MIN_CARD_ROW_HEIGHT)
            self.cards[key] = widget
            self.cards_grid.addWidget(widget, index // 3, index % 3,
                                      Qt.AlignTop)

    def _update_cards(self, data: dict) -> None:
        hints = {
            "net_sales": f"Ventes {money(data['gross_sales'])} − consignes "
                         f"{money(data['deposits'])} − retours {money(data['returns'])}",
            "gross_margin": f"Coût des marchandises vendues {money(data['cogs'])}",
            "estimated_result": f"Après {money(data['expenses'])} de dépenses",
            "receivables": "Soldes clients ouverts",
            "payables": "Soldes fournisseurs ouverts",
            "stock_value": f"{data['products_count']} produits suivis",
        }
        for key, _title in self.CARD_TITLES:
            widget = self.cards[key]
            widget.value_label.setText(money(data[key]))
            widget.hint_label.setText(hints[key])

    def refresh(self) -> None:
        period = PERIODS[self.period_box.currentText()]()
        data = self.services["reporting"].dashboard(period)

        self._build_cards()
        self._update_cards(data)

        self.alerts.load([[row["name"], row["available"], row["min_threshold"],
                           "Rupture" if row["status"] == "rupture" else "Sous seuil"]
                          for row in data["low_stock"] + data["out_of_stock"]],
                         numeric_columns={1, 2},
                         colors={3: {"Rupture": "#B3261E", "Sous seuil": "#B26A00"}})

        debtors = [customer for customer in self.services["sales"].list_customers()
                   if customer.balance > 0]
        debtors.sort(key=lambda item: item.balance, reverse=True)
        self.debtors.load([[customer.name, money(customer.credit_limit),
                            money(customer.balance), customer.phone or "—"]
                           for customer in debtors], numeric_columns={1, 2})
        self.customers_title.setText(
            f"Créances clients ({len(debtors)} client(s) débiteur(s))")

        sales = self.services["sales"].recent_sales(limit=20)
        self.recent.load([[sale.number, sale.at.strftime("%d/%m/%Y %H:%M"),
                           (sale.customer.name if sale.customer else "Comptoir"),
                           money(sale.total_amount), money(sale.paid_amount),
                           label_status(sale.status)] for sale in sales],
                         numeric_columns={3, 4})

        payments = data["payments_by_method"]
        if payments:
            from ...services.sales_service import PAYMENT_LABELS
            summary = "Encaissements par moyen de paiement (période) : " + "  ·  ".join(
                f"{PAYMENT_LABELS.get(key, key)} {money(value)}"
                for key, value in sorted(payments.items()))
            self.summary_label.setText(summary)
        else:
            self.summary_label.setText("Aucun encaissement enregistré sur la période.")
