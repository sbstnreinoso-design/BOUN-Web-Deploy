"""
Calculadora de costos MercadoLibre Colombia.
Retorna un desglose completo de todos los cargos sobre el precio de venta.
"""
from config import ML_COMMISSIONS, ML_IVA_ON_COMMISSION, ML_PREMIUM_EXTRA, RETENCION_FUENTE


def get_commission_rate(category: str, listing_type: str = "Clásica") -> float:
    """Tasa de comisión bruta (antes de IVA)."""
    base = ML_COMMISSIONS.get(category, 0.13)
    if listing_type == "Premium":
        base = min(base + ML_PREMIUM_EXTRA, 0.20)
    return base


def calculate_fees(
    sale_price: float,
    purchase_price: float,
    category: str,
    listing_type: str = "Clásica",
    shipping_cost: float = 0.0,
    advertising_pct: float = 0.0,
    other_costs: float = 0.0,
    import_tax_pct: float = 0.0,
    commission_rate: float = None,
) -> dict:
    """
    Retorna desglose completo de costos y rentabilidad.

    Todos los valores monetarios en la misma moneda del precio de venta.
    Si commission_rate se pasa explícitamente (ej. comisión REAL de ML
    vía /sites/MCO/listing_prices), se usa esa; si no, se estima por
    categoría con get_commission_rate.
    """
    if sale_price <= 0:
        return _empty_result()

    if commission_rate is None:
        commission_rate = get_commission_rate(category, listing_type)
    commission_base = sale_price * commission_rate
    commission_iva  = commission_base * ML_IVA_ON_COMMISSION
    commission_total = commission_base + commission_iva

    retencion = sale_price * RETENCION_FUENTE

    import_tax = purchase_price * import_tax_pct
    advertising = sale_price * advertising_pct

    total_costs = (
        purchase_price
        + import_tax
        + commission_total
        + retencion
        + shipping_cost
        + advertising
        + other_costs
    )

    net_profit = sale_price - total_costs
    profit_margin = (net_profit / sale_price * 100) if sale_price > 0 else 0
    roi = (net_profit / purchase_price * 100) if purchase_price > 0 else 0

    effective_cost_rate = (total_costs / sale_price * 100) if sale_price > 0 else 0

    return {
        "sale_price":           sale_price,
        "purchase_price":       purchase_price,
        "import_tax":           import_tax,
        "commission_rate_pct":  commission_rate * 100,
        "commission_base":      commission_base,
        "commission_iva":       commission_iva,
        "commission_total":     commission_total,
        "retencion_fuente":     retencion,
        "shipping_cost":        shipping_cost,
        "advertising_cost":     advertising,
        "other_costs":          other_costs,
        "total_costs":          total_costs,
        "net_profit":           net_profit,
        "profit_margin_pct":    profit_margin,
        "roi_pct":              roi,
        "effective_cost_rate":  effective_cost_rate,
        "listing_type":         listing_type,
        "category":             category,
    }


def _empty_result() -> dict:
    keys = [
        "sale_price", "purchase_price", "import_tax",
        "commission_rate_pct", "commission_base", "commission_iva",
        "commission_total", "retencion_fuente", "shipping_cost",
        "advertising_cost", "other_costs", "total_costs",
        "net_profit", "profit_margin_pct", "roi_pct", "effective_cost_rate",
    ]
    return {k: 0.0 for k in keys}


def format_cop(value: float) -> str:
    """Formatea como pesos colombianos."""
    if value >= 0:
        return f"${value:,.0f}"
    return f"-${abs(value):,.0f}"


def format_pct(value: float) -> str:
    return f"{value:.1f}%"
