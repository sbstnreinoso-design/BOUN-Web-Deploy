"""
Algoritmo de puntuación de viabilidad de producto (1.0 – 10.0).

Factores y pesos:
  Margen de ganancia neta      35 %
  Volumen de ventas mensuales  25 %
  Nivel de competencia (inv.)  20 %
  Volumen de búsquedas         10 %
  Calificación de compradores  10 %
"""
import math


# Benchmarks de referencia para normalización
_BENCH = {
    "margin_pct":    {"great": 40, "ok": 20, "bad": 5},
    "monthly_sales": {"great": 500, "ok": 100, "bad": 10},
    "competitors":   {"low": 10, "mid": 50, "high": 200},
    "search_volume": {"great": 5000, "ok": 1000, "bad": 100},
    "avg_rating":    {"great": 4.5, "ok": 3.5, "bad": 2.0},
}


def _normalize_margin(margin_pct: float) -> float:
    """0–1 dado el margen de ganancia (%)."""
    b = _BENCH["margin_pct"]
    if margin_pct <= 0:
        return 0.0
    if margin_pct >= b["great"]:
        return 1.0
    if margin_pct >= b["ok"]:
        return 0.5 + 0.5 * (margin_pct - b["ok"]) / (b["great"] - b["ok"])
    if margin_pct >= b["bad"]:
        return 0.15 + 0.35 * (margin_pct - b["bad"]) / (b["ok"] - b["bad"])
    return max(0.0, 0.15 * margin_pct / b["bad"])


def _normalize_sales(monthly_sales: int) -> float:
    """0–1 dado ventas mensuales."""
    b = _BENCH["monthly_sales"]
    if monthly_sales <= 0:
        return 0.0
    if monthly_sales >= b["great"]:
        return 1.0
    if monthly_sales >= b["ok"]:
        return 0.5 + 0.5 * (monthly_sales - b["ok"]) / (b["great"] - b["ok"])
    if monthly_sales >= b["bad"]:
        return 0.1 + 0.4 * (monthly_sales - b["bad"]) / (b["ok"] - b["bad"])
    return max(0.0, 0.1 * monthly_sales / b["bad"])


def _normalize_competition(competitors: int) -> float:
    """0–1 donde más competencia = valor más bajo."""
    b = _BENCH["competitors"]
    if competitors <= 0:
        return 1.0
    if competitors <= b["low"]:
        return 0.85 + 0.15 * (1 - competitors / b["low"])
    if competitors <= b["mid"]:
        return 0.5 + 0.35 * (1 - (competitors - b["low"]) / (b["mid"] - b["low"]))
    if competitors <= b["high"]:
        return 0.1 + 0.4 * (1 - (competitors - b["mid"]) / (b["high"] - b["mid"]))
    # Más de 200 vendedores: saturado
    extra = min(competitors - b["high"], b["high"])
    return max(0.0, 0.1 * (1 - extra / b["high"]))


def _normalize_search(search_volume: int) -> float:
    """0–1 dado volumen de búsquedas mensual."""
    b = _BENCH["search_volume"]
    if search_volume <= 0:
        return 0.0
    if search_volume >= b["great"]:
        return 1.0
    if search_volume >= b["ok"]:
        return 0.5 + 0.5 * (search_volume - b["ok"]) / (b["great"] - b["ok"])
    return max(0.0, 0.5 * search_volume / b["ok"])


def _normalize_rating(avg_rating: float) -> float:
    """0–1 dado calificación promedio (escala 1–5)."""
    if avg_rating <= 0:
        return 0.3  # Sin calificación → neutro
    b = _BENCH["avg_rating"]
    if avg_rating >= b["great"]:
        return 1.0
    if avg_rating >= b["ok"]:
        return 0.5 + 0.5 * (avg_rating - b["ok"]) / (b["great"] - b["ok"])
    return max(0.0, 0.5 * (avg_rating - 1) / (b["ok"] - 1))


def calculate_score(
    profit_margin_pct: float,
    monthly_sales: int,
    competitor_count: int,
    search_volume: int,
    avg_rating: float,
) -> float:
    """Retorna score 1.0–10.0."""
    weights = {
        "margin":      0.35,
        "sales":       0.25,
        "competition": 0.20,
        "search":      0.10,
        "rating":      0.10,
    }
    raw = (
        _normalize_margin(profit_margin_pct)      * weights["margin"]
        + _normalize_sales(monthly_sales)         * weights["sales"]
        + _normalize_competition(competitor_count) * weights["competition"]
        + _normalize_search(search_volume)         * weights["search"]
        + _normalize_rating(avg_rating)            * weights["rating"]
    )
    # Llevar rango 0–1 → 1–10, con mínimo 1.0
    score = 1.0 + raw * 9.0
    return round(min(10.0, max(1.0, score)), 1)


def score_label(score: float) -> str:
    if score >= 8.0:
        return "Excelente"
    if score >= 6.0:
        return "Bueno"
    if score >= 4.0:
        return "Regular"
    return "Bajo"


def score_color_key(score: float) -> str:
    if score >= 8.0:
        return "score_high"
    if score >= 5.0:
        return "score_mid"
    return "score_low"
