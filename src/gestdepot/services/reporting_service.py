"""Service rapports et tableau de bord (§5.4, §5.15, §5.14).

Tous les chiffres sont calculés à partir des opérations sources, jamais saisis.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from ..database.models import (
    CashMovement,
    Customer,
    CustomerOrder,
    CustomerPayment,
    Delivery,
    Expense,
    Sale,
    SaleLine,
    SaleReturn,
    Supplier,
    SupplierInvoice,
)
from ..database.session import session_scope
from ..domain import rules


class Period:
    """Période de reporting (bornes incluses, demi-ouverte sur les heures)."""

    def __init__(self, start: datetime, end: datetime, label: str = ""):
        if end < start:
            raise ValueError("Période invalide : fin antérieure au début.")
        self.start = start
        self.end = end
        self.label = label

    @classmethod
    def today(cls) -> "Period":
        day = date.today()
        return cls(datetime.combine(day, time.min),
                   datetime.combine(day, time.max), "Aujourd'hui")

    @classmethod
    def yesterday(cls) -> "Period":
        day = date.today() - timedelta(days=1)
        return cls(datetime.combine(day, time.min),
                   datetime.combine(day, time.max), "Hier")

    @classmethod
    def last_days(cls, days: int = 7) -> "Period":
        end_day = date.today()
        start_day = end_day - timedelta(days=days - 1)
        return cls(datetime.combine(start_day, time.min),
                   datetime.combine(end_day, time.max), f"{days} derniers jours")

    @classmethod
    def current_month(cls) -> "Period":
        today = date.today()
        return cls(datetime.combine(today.replace(day=1), time.min),
                   datetime.combine(today, time.max), "Mois en cours")

    @classmethod
    def custom(cls, start: date, end: date) -> "Period":
        return cls(datetime.combine(start, time.min),
                   datetime.combine(end, time.max),
                   f"du {start:%d/%m/%Y} au {end:%d/%m/%Y}")


class ReportingService:
    def dashboard(self, period: Period) -> dict:
        """Indicateurs du tableau de bord (§5.4)."""
        from .cash_service import CashService
        from .sales_service import SalesService
        from .stock_service import StockService

        sales = SalesService()
        stock = StockService()
        cash = CashService()

        summary = sales.sales_summary(period.start, period.end)
        expenses = cash.expenses_total(period.start, period.end)
        gross_margin = summary["gross_margin"]
        with session_scope() as s:
            receivables = int(s.scalar(
                select(func.coalesce(func.sum(Customer.balance), 0))
                .where(Customer.active.is_(True))) or 0)
            payables = int(s.scalar(
                select(func.coalesce(func.sum(Supplier.balance), 0))
                .where(Supplier.active.is_(True))) or 0)
            # §5.4 : activité de livraison et crédits échus
            orders_to_prepare = int(s.scalar(
                select(func.count(CustomerOrder.id)).where(
                    CustomerOrder.status.in_(("confirmed", "preparing")))) or 0)
            deliveries_pending = int(s.scalar(
                select(func.count(Delivery.id)).where(
                    Delivery.status.in_(("pending", "preparing",
                                         "in_transit")))) or 0)
            overdue_credit = int(s.scalar(
                select(func.coalesce(func.sum(Sale.total_amount
                                              - Sale.paid_amount), 0))
                .where(Sale.status == "confirmed",
                       Sale.total_amount > Sale.paid_amount,
                       Sale.at < period.start - timedelta(days=30))) or 0)
            payments = s.execute(
                select(CustomerPayment.payment_method,
                       func.coalesce(func.sum(CustomerPayment.amount), 0))
                .where(CustomerPayment.at >= period.start,
                       CustomerPayment.at <= period.end)
                .group_by(CustomerPayment.payment_method)).all()
            cash_in = s.execute(
                select(CashMovement.payment_method,
                       func.coalesce(func.sum(CashMovement.amount), 0))
                .where(CashMovement.at >= period.start,
                       CashMovement.at <= period.end,
                       CashMovement.direction == "in")
                .group_by(CashMovement.payment_method)).all()
        alerts = stock.stock_levels(only_alerts=True)
        return {
            "period": period.label,
            "sales_count": summary["sales_count"],
            "net_sales": summary["net_sales"],
            "gross_sales": summary["gross_sales"],
            "discounts": summary["discounts"],
            "deposits": summary["deposits"],
            "returns": summary["returns"],
            "cogs": summary["cogs"],
            "gross_margin": gross_margin,
            "expenses": expenses,
            "estimated_result": rules.estimated_result(gross_margin, expenses),
            "receivables": receivables,
            "payables": payables,
            "payments_by_method": {m: int(a or 0) for m, a in payments},
            "cash_in_by_method": {m: int(a or 0) for m, a in cash_in},
            "stock_value": stock.stock_value(),
            "low_stock": [a for a in alerts if a["status"] == "sous_seuil"],
            "out_of_stock": [a for a in alerts if a["status"] == "rupture"],
            "products_count": len(stock.stock_levels()),
            "orders_to_prepare": orders_to_prepare,
            "deliveries_pending": deliveries_pending,
            "overdue_credit": overdue_credit,
        }

    def sales_by_day(self, period: Period):
        """Ventes par jour (chiffre d'affaires net hors retours)."""
        with session_scope() as s:
            rows = s.execute(
                select(func.date(Sale.at), func.coalesce(func.sum(Sale.total_amount), 0))
                .where(Sale.at >= period.start, Sale.at <= period.end,
                       Sale.status != "cancelled")
                .group_by(func.date(Sale.at)).order_by(func.date(Sale.at))).all()
            return [(str(day), int(amount or 0)) for day, amount in rows]

    def top_products(self, period: Period, limit: int = 10, by: str = "quantity"):
        """Produits les plus vendus ou les plus rentables (§5.4)."""
        with session_scope() as s:
            q = (select(SaleLine.designation,
                        func.coalesce(func.sum(SaleLine.quantity), 0),
                        func.coalesce(func.sum(SaleLine.total), 0),
                        func.coalesce(func.sum((SaleLine.unit_price - SaleLine.unit_cost)
                                               * SaleLine.quantity), 0))
                 .join(Sale, Sale.id == SaleLine.sale_id)
                 .where(Sale.at >= period.start, Sale.at <= period.end,
                        Sale.status != "cancelled")
                 .group_by(SaleLine.designation))
            rows = s.execute(q).all()
        data = [{"designation": d, "quantity": int(q), "revenue": int(r),
                 "margin": int(m)} for d, q, r, m in rows]
        key = "margin" if by == "margin" else "quantity"
        data.sort(key=lambda row: row[key], reverse=True)
        return data[:limit]

    def sales_by_category(self, period: Period):
        from ..database.models import Category, Product
        with session_scope() as s:
            rows = s.execute(
                select(func.coalesce(Category.name, "Sans catégorie"),
                       func.coalesce(func.sum(SaleLine.total), 0))
                .select_from(SaleLine)
                .join(Sale, Sale.id == SaleLine.sale_id)
                .join(Product, Product.id == SaleLine.product_id)
                .outerjoin(Category, Category.id == Product.category_id)
                .where(Sale.at >= period.start, Sale.at <= period.end,
                       Sale.status != "cancelled")
                .group_by(Category.name)).all()
            return [(name, int(total or 0)) for name, total in rows]

    def margin_report(self, period: Period) -> dict:
        """Marges et rentabilité de période (§5.14)."""
        from .sales_service import SalesService
        summary = SalesService().sales_summary(period.start, period.end)
        margin = summary["gross_margin"]
        return {
            "net_sales": summary["net_sales"],
            "cogs": summary["cogs"],
            "gross_margin": margin,
            "margin_rate": rules.margin_rate(margin, summary["cogs"]),
            "markup_rate": rules.markup_rate(margin, summary["net_sales"]),
        }

    def sales_report(self, period: Period):
        with session_scope() as s:
            return list(s.scalars(select(Sale).where(
                Sale.at >= period.start, Sale.at <= period.end)
                .order_by(Sale.at)))

    def returns_report(self, period: Period):
        with session_scope() as s:
            return list(s.scalars(select(SaleReturn).where(
                SaleReturn.at >= period.start, SaleReturn.at <= period.end)
                .order_by(SaleReturn.at)))

    def expenses_report(self, period: Period):
        with session_scope() as s:
            return list(s.scalars(select(Expense).where(
                Expense.at >= period.start, Expense.at <= period.end)
                .order_by(Expense.at)))

    def payments_report(self, period: Period):
        with session_scope() as s:
            return list(s.scalars(select(CustomerPayment).where(
                CustomerPayment.at >= period.start, CustomerPayment.at <= period.end)
                .order_by(CustomerPayment.at)))

    def supplier_balances(self):
        with session_scope() as s:
            return [{"supplier": sup.name, "balance": sup.balance}
                    for sup in s.scalars(select(Supplier)
                                         .where(Supplier.active.is_(True))
                                         .order_by(Supplier.name))]

    def open_invoices(self):
        with session_scope() as s:
            rows = []
            for invoice in s.scalars(select(SupplierInvoice)
                                     .order_by(SupplierInvoice.at.desc())):
                remaining = invoice.total_amount - invoice.paid_amount
                if remaining > 0:
                    rows.append({"number": invoice.number,
                                 "total": invoice.total_amount,
                                 "paid": invoice.paid_amount,
                                 "remaining": remaining,
                                 "due_date": invoice.due_date})
            return rows
