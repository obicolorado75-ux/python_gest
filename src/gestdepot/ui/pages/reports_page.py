"""Rapports et exports : ventes, marges, encaissements, stock (§5.15)."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLabel, QVBoxLayout

from ...reports.exports import export_excel, export_pdf
from ...services.reporting_service import Period
from ..widgets import DataTable, Page, info, money, refresh_after

REPORTS = ["Ventes", "Marges et rentabilité", "Encaissements",
           "Dépenses", "Stock valorisé"]


class ReportsPage(Page):
    title = "Marges et rapports"
    subtitle = ("Les exports Excel et PDF sont des copies de consultation : ils ne "
                "modifient jamais les données.")

    def __init__(self, services, parent=None):
        super().__init__(services, parent)
        bar = QHBoxLayout()
        self.report_box = QComboBox()
        self.report_box.addItems(REPORTS)
        self.report_box.currentTextChanged.connect(lambda _: self.refresh())
        bar.addWidget(QLabel("Rapport :"))
        bar.addWidget(self.report_box)
        bar.addWidget(QLabel("Du"))
        self.start = QDateEdit(date.today().replace(day=1))
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("dd/MM/yyyy")
        self.start.dateChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.start)
        bar.addWidget(QLabel("au"))
        self.end = QDateEdit(date.today())
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("dd/MM/yyyy")
        self.end.dateChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.end)
        bar.addStretch(1)
        self.body.addLayout(bar)

        self.add_action("Export Excel", self.to_excel, primary=True)
        self.add_action("Export PDF", self.to_pdf)
        self.add_stretch()

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: 600;")
        self.body.addWidget(self.summary)
        self.table_holder = QVBoxLayout()
        self.body.addLayout(self.table_holder, 1)
        self.table = DataTable(["Libellé", "Valeur"])
        self.table_holder.addWidget(self.table)

    def _period(self) -> Period:
        return Period.custom(self.start.date().toPython(),
                             self.end.date().toPython())

    def _build(self) -> tuple[list[str], list[list], dict[str, int]]:
        """Retourne (en-têtes, lignes, totaux) pour le rapport sélectionné."""
        period = self._period()
        reporting = self.services["reporting"]
        kind = self.report_box.currentText()

        if kind == "Ventes":
            sales = reporting.sales_report(period)
            headers = ["N°", "Date", "Client", "Statut", "Total", "Payé", "Reste"]
            rows = [[s.number, s.at.strftime("%d/%m/%Y"),
                     s.customer.name if s.customer else "Comptoir", s.status,
                     s.total_amount, s.paid_amount, s.total_amount - s.paid_amount]
                    for s in sales]
            totals = {"Chiffre d'affaires": sum(s.total_amount for s in sales),
                      "Encaissé": sum(s.paid_amount for s in sales)}
            return headers, rows, totals

        if kind == "Marges et rentabilité":
            margin = reporting.margin_report(period)
            summary = self.services["sales"].sales_summary(period.start, period.end)
            headers = ["Indicateur", "Valeur"]
            rows = [["Ventes nettes de retours", money(margin["net_sales"])],
                    ["Coût des marchandises vendues", money(margin["cogs"])],
                    ["Marge brute", money(margin["gross_margin"])],
                    ["Taux de marge (%)", f"{margin['margin_rate']}"],
                    ["Taux de marque (%)", f"{margin['markup_rate']}"],
                    ["Nombre de ventes", str(summary["sales_count"])]]
            totals = {"Marge brute": margin["gross_margin"]}
            return headers, rows, totals

        if kind == "Encaissements":
            payments = reporting.payments_report(period)
            headers = ["Date", "N°", "Moyen", "Montant"]
            rows = [[p.at.strftime("%d/%m/%Y %H:%M"), p.number, p.payment_method,
                     p.amount] for p in payments]
            totals = {"Total encaissé": sum(p.amount for p in payments)}
            return headers, rows, totals

        if kind == "Dépenses":
            expenses = reporting.expenses_report(period)
            headers = ["Date", "N°", "Montant", "Moyen", "Bénéficiaire"]
            rows = [[e.at.strftime("%d/%m/%Y"), e.number, e.amount,
                     e.payment_method, e.beneficiary or "—"] for e in expenses]
            totals = {"Total dépenses": sum(e.amount for e in expenses)}
            return headers, rows, totals

        levels = self.services["stock"].stock_levels()
        headers = ["Référence", "Produit", "Quantité", "Coût moyen", "Valeur",
                   "Seuil", "Statut"]
        rows = [[row["reference"], row["name"], row["quantity"], row["unit_cost"],
                 row["value"], row["min_threshold"], row["status"]]
                for row in levels]
        totals = {"Valeur totale du stock": sum(row["value"] for row in levels)}
        return headers, rows, totals

    def _rebuild_table(self, headers: list[str]) -> None:
        """Recrée le tableau quand le rapport change de colonnes."""
        if self.table.columnCount() == len(headers) and \
                [self.table.horizontalHeaderItem(i).text()
                 for i in range(self.table.columnCount())] == headers:
            return
        self.table_holder.removeWidget(self.table)
        self.table.deleteLater()
        self.table = DataTable(headers)
        self.table_holder.addWidget(self.table)

    def _format_rows(self, headers: list[str], rows: list[list]) -> list[list]:
        """Formate les montants pour l'affichage, en conservant les autres valeurs."""
        money_tokens = ("montant", "total", "prix", "valeur", "payé", "reste",
                        "solde", "encaissé", "plafond", "coût")
        money_columns = {index for index, header in enumerate(headers)
                         if any(token in header.lower() for token in money_tokens)}
        formatted = []
        for row in rows:
            formatted.append([money(cell) if (index in money_columns
                                              and isinstance(cell, int)) else cell
                              for index, cell in enumerate(row)])
        return formatted

    def refresh(self) -> None:
        headers, rows, totals = self._build()
        self._rebuild_table(headers)
        self.table.load(self._format_rows(headers, rows)[:500])
        period = self._period()
        summary = "  ·  ".join(f"{label} {money(value)}" for label, value in
                              totals.items())
        self.summary.setText(f"{period.label} — {len(rows)} ligne(s)  ·  {summary}")

    def _company(self) -> dict:
        settings = self.services["admin"].company_settings()
        return {"name": settings.name, "address": settings.address,
                "phone": settings.phone, "document_footer": settings.document_footer}

    @refresh_after
    def to_excel(self):
        headers, rows, totals = self._build()
        path = export_excel(self.report_box.currentText(), headers, rows, totals,
                            file_name=f"rapport_{self.report_box.currentText()}")
        info(self, f"Export Excel créé :\n{path}", "Export Excel")
        return True

    @refresh_after
    def to_pdf(self):
        headers, rows, totals = self._build()
        path = export_pdf(self.report_box.currentText(), headers,
                          [[money(cell) if isinstance(cell, int) else cell
                            for cell in row] for row in rows],
                          period=self._period().label, company=self._company(),
                          totals=totals,
                          file_name=f"rapport_{self.report_box.currentText()}")
        info(self, f"Export PDF créé :\n{path}", "Export PDF")
        return True
