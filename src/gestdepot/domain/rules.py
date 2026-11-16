"""Règles de calcul indépendantes de l'UI (couche Domaine)."""
MONEY_UNITS = "FCFA"


def format_xof(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " FCFA"


def margin_unit(sale_price: int, unit_cost: int) -> int:
    """Marge brute unitaire = prix de vente - coût (§5.14)."""
    return sale_price - unit_cost


def margin_rate(margin: int, cost: int) -> float:
    """Taux de marge = marge / coût × 100."""
    if cost == 0:
        return 0.0
    return round(margin / cost * 100, 1)


def markup_rate(margin: int, sale_price: int) -> float:
    """Taux de marque = marge / prix de vente × 100."""
    if sale_price == 0:
        return 0.0
    return round(margin / sale_price * 100, 1)


def period_gross_margin(net_sales: int, cogs: int) -> int:
    """Marge brute de période = ventes nettes - coût des marchandises vendues."""
    return net_sales - cogs


def estimated_result(gross_margin: int, expenses: int) -> int:
    """Résultat estimatif de gestion (jamais « résultat comptable »)."""
    return gross_margin - expenses


def convert_quantity(qty_display: int, factor: int, base_qty: int = 0) -> int:
    """2 casiers (24) + 3 bouteilles = 51 unités de base (§7.4, T03)."""
    if qty_display < 0 or base_qty < 0:
        raise ValueError("Quantité négative interdite.")
    return qty_display * factor + base_qty


def reorder_quantity(avg_daily_sales: float, lead_time_days: int, safety_stock: int,
                     available: int, expected_orders: int, horizon_days: int) -> int:
    """Quantité recommandée = besoin jusqu'au prochain réappro + sécurité
    - disponible - commandes attendues (§5.11)."""
    need = round(avg_daily_sales * (lead_time_days + horizon_days))
    qty = need + safety_stock - available - expected_orders
    return max(qty, 0)


def weighted_avg_cost(current_qty: int, current_avg: int, incoming_qty: int,
                      incoming_cost: int) -> int:
    """Coût moyen pondéré mobile (§5.14)."""
    total_qty = current_qty + incoming_qty
    if total_qty <= 0:
        return 0
    return round((current_qty * current_avg + incoming_qty * incoming_cost) / total_qty)
