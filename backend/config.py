"""
BOUN App — Configuración global de colores, fuentes y constantes.
Inspirado en el logo BOUN: negro profundo + blanco + dorado lobo/luna.
"""
import os

APP_NAME = "BOUN · Análisis MercadoLibre"
APP_VERSION = "1.0.0"
DB_DIR = os.path.expanduser("~/.boun_ml_app")
DB_PATH = os.path.join(DB_DIR, "products.db")
PDF_DIR = os.path.join(DB_DIR, "pdfs")
IMG_DIR = os.path.join(DB_DIR, "images")

# ── Base de datos en la nube (Supabase) — datos compartidos del equipo ────────
# Todas las instalaciones usan esta misma base → datos sincronizados.
# La SQLite local queda como respaldo offline.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ── Paleta de colores ──────────────────────────────────────────────────────────
COLORS = {
    # Fondos — negro cálido BOUN (sleep co.)
    "bg":           "#252427",
    "surface":      "#2B2A2E",
    "card":         "#2F2E33",
    "sidebar":      "#1C1B1E",
    "sidebar_hover":"#2A292D",
    "border":       "#3B3A3F",
    # Acento de marca — verde menta BOUN
    "gold":         "#F5F1EA",
    "gold_hover":   "#FFFFFF",
    "gold_dim":     "#6B6B66",
    # Semáforos (positivo / advertencia / negativo — NO cambian)
    "success":      "#3FCB82",
    "warning":      "#E0A23C",
    "danger":       "#E11D48",
    "info":         "#7FB3E0",
    # Texto — crema
    "text":         "#F5F1EA",
    "text_muted":   "#9B9A96",
    "text_dim":     "#5A595E",
    # Score badges (semáforo)
    "score_high":   "#3FCB82",   # 8-10
    "score_mid":    "#E0A23C",   # 5-7
    "score_low":    "#E11D48",   # 1-4
}

# ── Comisiones MercadoLibre Colombia (% sin IVA) ──────────────────────────────
ML_COMMISSIONS = {
    "Celulares y Smartphones":      0.08,
    "Computadores y Laptops":       0.08,
    "Tablets":                      0.08,
    "Cámaras y Fotografía":         0.11,
    "TV, Audio y Video":            0.11,
    "Electrodomésticos":            0.11,
    "Acondicionadores de Aire":     0.11,
    "Electrónica y Tecnología":     0.13,
    "Ropa y Accesorios":            0.165,
    "Calzado":                      0.165,
    "Relojes y Joyería":            0.165,
    "Hogar y Jardín":               0.13,
    "Muebles":                      0.13,
    "Deportes y Fitness":           0.13,
    "Juguetes y Juegos":            0.13,
    "Bebés":                        0.13,
    "Belleza y Cuidado Personal":   0.13,
    "Salud y Equipamiento Médico":  0.13,
    "Automotriz":                   0.13,
    "Herramientas y Construcción":  0.13,
    "Alimentos y Bebidas":          0.165,
    "Mascotas":                     0.13,
    "Libros, Películas y Música":   0.165,
    "Arte y Antigüedades":          0.165,
    "Industrias y Oficinas":        0.11,
    "Servicios":                    0.00,
    "Otro / General":               0.13,
}

# IVA aplicado sobre la comisión de ML (Colombia)
ML_IVA_ON_COMMISSION = 0.19

# Premium suma 4.5 % más que Classic
ML_PREMIUM_EXTRA = 0.045

# Retenciones combinadas que aplica MercadoLibre Colombia sobre la venta:
# ReteFuente + ReteICA + ReteIVA. Calibrado con datos reales del panel de
# vendedor (ML retiene ~2.8% del precio de venta como "Impuestos").
RETENCION_FUENTE = 0.028

# Rangos de score → color
SCORE_RANGES = [
    (8.0, 10.0, "score_high"),
    (5.0,  7.9, "score_mid"),
    (0.0,  4.9, "score_low"),
]

LISTING_TYPES = ["Clásica", "Premium"]

CURRENCIES = ["COP", "USD"]
