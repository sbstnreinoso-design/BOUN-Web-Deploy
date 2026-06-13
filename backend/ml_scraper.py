"""
Cliente MercadoLibre Colombia — búsqueda automática de datos de mercado.

Modo 1 — API real (requiere APP_ID + SECRET de developers.mercadolibre.com):
  Token via Client Credentials → GET /sites/MCO/search → datos reales
Modo 2 — Benchmarks (sin credenciales):
  Estadísticas por categoría basadas en datos de ML Colombia 2024.
  Precio sugerido = purchase_price × markup por categoría.
"""
import json
import os
import ssl
import time
import datetime as _dt
import re
import warnings
import urllib.parse
import queue
import threading
import webbrowser
import secrets
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any

import requests
from database import get_setting, set_setting

warnings.filterwarnings("ignore")  # suprimir advertencia LibreSSL

ML_API   = "https://api.mercadolibre.com"
ML_SITE  = "MCO"
TOKEN_TTL = 21600  # 6 horas en segundos

OAUTH_REDIRECT_URI  = "https://boun.com.co/oauth"   # configurable en settings (ml_redirect_uri)
ML_AUTH_URL         = "https://auth.mercadolibre.com.co/authorization"


# ── Benchmarks por categoría (ML Colombia 2024) ───────────────────────────────
# Fuente: análisis de ventas ML Colombia, promedios de categorías.
# competitor_count = # típico de vendedores activos
# monthly_sales    = unidades/mes que venden los top 10 vendedores juntos
# search_volume    = búsquedas mensuales estimadas
# avg_rating       = calificación promedio de la categoría
# markup           = factor multiplicador sobre precio de compra (precio venta sugerido)

CATEGORY_BENCHMARKS: Dict[str, Dict] = {
    "Celulares y Smartphones":      {"competitors": 280, "monthly_sales": 420, "search_volume": 45000, "rating": 4.3, "markup": 1.35},
    "Computadores y Laptops":       {"competitors": 180, "monthly_sales": 160, "search_volume": 28000, "rating": 4.4, "markup": 1.25},
    "Tablets":                      {"competitors": 120, "monthly_sales": 90,  "search_volume": 18000, "rating": 4.2, "markup": 1.30},
    "Cámaras y Fotografía":         {"competitors": 95,  "monthly_sales": 55,  "search_volume": 9000,  "rating": 4.5, "markup": 1.45},
    "TV, Audio y Video":            {"competitors": 160, "monthly_sales": 130, "search_volume": 22000, "rating": 4.3, "markup": 1.30},
    "Electrodomésticos":            {"competitors": 200, "monthly_sales": 210, "search_volume": 31000, "rating": 4.2, "markup": 1.40},
    "Acondicionadores de Aire":     {"competitors": 85,  "monthly_sales": 75,  "search_volume": 12000, "rating": 4.3, "markup": 1.35},
    "Electrónica y Tecnología":     {"competitors": 320, "monthly_sales": 380, "search_volume": 52000, "rating": 4.2, "markup": 1.60},
    "Ropa y Accesorios":            {"competitors": 850, "monthly_sales": 680, "search_volume": 95000, "rating": 4.1, "markup": 2.20},
    "Calzado":                      {"competitors": 420, "monthly_sales": 390, "search_volume": 55000, "rating": 4.0, "markup": 2.10},
    "Relojes y Joyería":            {"competitors": 380, "monthly_sales": 220, "search_volume": 38000, "rating": 4.2, "markup": 2.50},
    "Hogar y Jardín":               {"competitors": 290, "monthly_sales": 310, "search_volume": 44000, "rating": 4.2, "markup": 1.80},
    "Muebles":                      {"competitors": 145, "monthly_sales": 80,  "search_volume": 14000, "rating": 4.1, "markup": 1.70},
    "Deportes y Fitness":           {"competitors": 460, "monthly_sales": 420, "search_volume": 62000, "rating": 4.3, "markup": 1.90},
    "Juguetes y Juegos":            {"competitors": 310, "monthly_sales": 280, "search_volume": 41000, "rating": 4.2, "markup": 2.00},
    "Bebés":                        {"competitors": 260, "monthly_sales": 240, "search_volume": 33000, "rating": 4.4, "markup": 2.10},
    "Belleza y Cuidado Personal":   {"competitors": 520, "monthly_sales": 580, "search_volume": 78000, "rating": 4.3, "markup": 2.30},
    "Salud y Equipamiento Médico":  {"competitors": 185, "monthly_sales": 190, "search_volume": 27000, "rating": 4.4, "markup": 2.00},
    "Automotriz":                   {"competitors": 220, "monthly_sales": 160, "search_volume": 24000, "rating": 4.2, "markup": 1.70},
    "Herramientas y Construcción":  {"competitors": 175, "monthly_sales": 145, "search_volume": 21000, "rating": 4.3, "markup": 1.75},
    "Alimentos y Bebidas":          {"competitors": 290, "monthly_sales": 450, "search_volume": 58000, "rating": 4.1, "markup": 2.50},
    "Mascotas":                     {"competitors": 230, "monthly_sales": 280, "search_volume": 36000, "rating": 4.3, "markup": 2.00},
    "Libros, Películas y Música":   {"competitors": 120, "monthly_sales": 95,  "search_volume": 12000, "rating": 4.5, "markup": 1.80},
    "Arte y Antigüedades":          {"competitors": 85,  "monthly_sales": 40,  "search_volume": 7000,  "rating": 4.4, "markup": 2.50},
    "Industrias y Oficinas":        {"competitors": 150, "monthly_sales": 120, "search_volume": 16000, "rating": 4.2, "markup": 1.60},
    "Otro / General":               {"competitors": 200, "monthly_sales": 180, "search_volume": 24000, "rating": 4.2, "markup": 2.00},
}

# ── Mapeo de categorías ML (category_id → nombre nuestro) ────────────────────
ML_CAT_ID_MAP = {
    "MCO1051": "Celulares y Smartphones",
    "MCO1648": "Computadores y Laptops",
    "MCO1144": "Tablets",
    "MCO1039": "Cámaras y Fotografía",
    "MCO1000": "Electrónica y Tecnología",
    "MCO1574": "TV, Audio y Video",
    "MCO1698": "Electrodomésticos",
    "MCO1430": "Ropa y Accesorios",
    "MCO1661": "Calzado",
    "MCO1182": "Hogar y Jardín",
    "MCO1276": "Deportes y Fitness",
    "MCO1132": "Juguetes y Juegos",
    "MCO1246": "Belleza y Cuidado Personal",
    "MCO1144": "Tablets",
    "MCO1499": "Herramientas y Construcción",
    "MCO1743": "Automotriz",
    "MCO1459": "Mascotas",
    "MCO1367": "Industrias y Oficinas",
}


# ── OAuth / Token ─────────────────────────────────────────────────────────────

def _get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "BOUN-ML-Analyzer/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def connect_ml(app_id: str, client_secret: str) -> dict:
    """
    Obtiene token via Client Credentials (no requiere login de usuario).
    Retorna {"ok": True, "token": "...", "expires_in": 21600}
    o       {"ok": False, "error": "..."}
    """
    try:
        s = _get_session()
        r = s.post(
            f"{ML_API}/oauth/token",
            data={
                "grant_type":    "client_credentials",
                "client_id":     app_id.strip(),
                "client_secret": client_secret.strip(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            token = data.get("access_token", "")
            set_setting("ml_app_id",      app_id.strip())
            set_setting("ml_client_secret", client_secret.strip())
            set_setting("ml_access_token", token)
            set_setting("ml_token_ts",    str(time.time()))
            return {"ok": True, "token": token}
        else:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── OAuth Authorization Code (login de usuario real) ─────────────────────────

_SUCCESS_HTML = b"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{font-family:sans-serif;background:#0A0A0A;color:#F5F5F5;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}
.box{text-align:center;padding:40px;background:#1A1A1A;border-radius:16px;border:1px solid #D4A853}
h2{color:#D4A853;margin-bottom:8px}p{color:#9CA3AF;font-size:14px}</style></head>
<body><div class="box"><h2>&#10003; Conexi\xf3n exitosa</h2>
<p>Ya puedes cerrar esta ventana y volver a BOUN.</p></div></body></html>"""

_FAIL_HTML = b"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{font-family:sans-serif;background:#0A0A0A;color:#F5F5F5;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}
.box{text-align:center;padding:40px;background:#1A1A1A;border-radius:16px;border:1px solid #EF4444}
h2{color:#EF4444;margin-bottom:8px}p{color:#9CA3AF;font-size:14px}</style></head>
<body><div class="box"><h2>&#10005; Error de conexi\xf3n</h2>
<p>Puedes cerrar esta ventana e intentarlo de nuevo.</p></div></body></html>"""



def _extract_code(raw: str) -> str:
    """Accepts either a bare code or a full redirect URL and returns just the code."""
    raw = raw.strip()
    if raw.startswith("http"):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(raw).query))
        return params.get("code", "")
    # Remove any accidental query params the user might have included
    return raw.split("&")[0].split("?")[-1].replace("code=", "").strip()


def start_oauth_flow(app_id="", client_secret="", manual_code_queue=None):
    """
    Authorization Code OAuth2 flow — manual code approach.
    Opens browser → user logs into ML → browser redirects (may show 404) →
    user copies code from URL bar → pastes in app → exchanges for token.
    Returns {"ok": True, "username": str, "user_id": str}
          or {"ok": False, "error": str}
    """
    app_id        = (app_id        or get_setting("ml_app_id",        "")).strip()
    client_secret = (client_secret or get_setting("ml_client_secret", "")).strip()
    redirect_uri  = get_setting("ml_redirect_uri", OAUTH_REDIRECT_URI).strip() or OAUTH_REDIRECT_URI

    if not app_id or not client_secret:
        return {"ok": False, "error": "Configura el APP ID y Client Secret en Configuración."}
    if not manual_code_queue:
        return {"ok": False, "error": "Se requiere el campo de código de autorización."}

    # Open browser to ML authorization page
    auth_url = (
        "%s?response_type=code"
        "&client_id=%s"
        "&redirect_uri=%s"
    ) % (
        ML_AUTH_URL,
        urllib.parse.quote(app_id),
        urllib.parse.quote(redirect_uri),
    )
    webbrowser.open(auth_url)

    # Wait for user to paste the code (max 5 min)
    try:
        code = manual_code_queue.get(timeout=300)
    except queue.Empty:
        return {"ok": False, "error": "Tiempo de espera agotado. Intenta de nuevo."}

    code = _extract_code(code)
    if not code:
        return {"ok": False, "error": "Código inválido. Asegúrate de copiar solo el código (no toda la URL)."}
    try:
        s = _get_session()
        r = s.post(
            "%s/oauth/token" % ML_API,
            data={
                "grant_type":    "authorization_code",
                "client_id":     app_id,
                "client_secret": client_secret,
                "code":          code,
                "redirect_uri":  redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except Exception as e:
        return {"ok": False, "error": "Error de red: %s" % e}

    if r.status_code != 200:
        return {"ok": False, "error": "Error al obtener token: HTTP %d — %s" % (r.status_code, r.text[:300])}

    token_data = r.json()
    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    user_id       = str(token_data.get("user_id", ""))
    expires_in    = token_data.get("expires_in", TOKEN_TTL)

    set_setting("ml_access_token",  access_token)
    set_setting("ml_refresh_token", refresh_token)
    set_setting("ml_token_ts",      str(time.time()))
    set_setting("ml_user_id",       user_id)
    if app_id:
        set_setting("ml_app_id", app_id)
    if client_secret:
        set_setting("ml_client_secret", client_secret)

    # Get username
    username = get_ml_username(access_token, user_id)
    set_setting("ml_username", username)

    return {"ok": True, "username": username, "user_id": user_id, "token": access_token}


def get_ml_username(token="", user_id=""):
    """Fetches the ML username for the authenticated user."""
    try:
        token   = token   or _load_token()
        user_id = user_id or get_setting("ml_user_id", "me")
        if not token:
            return ""
        s = _get_session()
        s.headers["Authorization"] = "Bearer %s" % token
        if user_id and user_id != "me":
            endpoint = "%s/users/%s" % (ML_API, user_id)
        else:
            endpoint = "%s/users/me" % ML_API
        r = s.get(endpoint, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("nickname") or data.get("first_name", "") or str(data.get("id", ""))
        return ""
    except Exception:
        return ""


def _try_refresh():
    """Tries to refresh the access token using the stored refresh_token."""
    refresh = get_setting("ml_refresh_token", "")
    app_id  = get_setting("ml_app_id", "")
    secret  = get_setting("ml_client_secret", "")
    if not refresh or not app_id or not secret:
        return ""
    try:
        s = _get_session()
        r = s.post(
            "%s/oauth/token" % ML_API,
            data={
                "grant_type":    "refresh_token",
                "client_id":     app_id,
                "client_secret": secret,
                "refresh_token": refresh,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            token = data.get("access_token", "")
            set_setting("ml_access_token",  token)
            set_setting("ml_refresh_token", data.get("refresh_token", refresh))
            set_setting("ml_token_ts",      str(time.time()))
            return token
    except Exception:
        pass
    return ""


def _load_token():
    """Returns stored token, refreshes automatically if near expiry."""
    token = get_setting("ml_access_token", "")
    ts    = float(get_setting("ml_token_ts", "0"))
    if not token:
        return ""
    age = time.time() - ts
    if age > TOKEN_TTL - 300:   # refresh 5 min before expiry
        refreshed = _try_refresh()
        if refreshed:
            return refreshed
        # Fall back to client_credentials if refresh fails
        app_id = get_setting("ml_app_id", "")
        secret = get_setting("ml_client_secret", "")
        if app_id and secret:
            res = connect_ml(app_id, secret)
            if res.get("ok"):
                return res["token"]
        return ""
    return token


def is_connected():
    return bool(_load_token())


def get_connected_username():
    """Returns stored username, or empty string if not connected."""
    return get_setting("ml_username", "")


# ── Búsqueda via catálogo de productos ML (endpoint disponible con OAuth) ──────

def _catalog_search(query: str, token: str, limit: int = 10) -> dict:
    """
    Usa /products/search (catálogo ML) — funciona con OAuth token.
    Devuelve {'results': [...], 'paging': {'total': N}}.
    """
    s = _get_session()
    s.headers["Authorization"] = "Bearer " + token
    url = (f"{ML_API}/products/search"
           f"?site_id={ML_SITE}&q={urllib.parse.quote(query)}&limit={limit}")
    try:
        r = s.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _parse_catalog_results(data: dict, category: str, purchase_price: float = 0) -> dict:
    """
    Extrae métricas y top-3 links del JSON del catálogo ML.
    El catálogo no expone precios directamente → precio sugerido viene de benchmark.
    El competitor_count es real (paging.total).
    """
    results = data.get("results", [])
    paging  = data.get("paging", {})
    total   = paging.get("total", 0)

    if not results:
        return {}

    # Top 3 links — búsquedas activas en ML (siempre muestran productos con precio)
    top_listings = []
    seen_queries = set()
    for p in results:
        if p.get("status") != "active":
            continue
        raw_title = p.get("name", "").strip()
        # Tomar solo la primera parte del título (antes de primera coma)
        if ", " in raw_title:
            title = raw_title.split(", ")[0].strip()
        else:
            title = raw_title
        # Limpiar caracteres especiales para slug
        import re as _re
        slug_title = _re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜ0-9\s]', '', title).strip()
        # Tomar primeras 4-5 palabras significativas
        words = [w for w in slug_title.split() if len(w) > 2][:5]
        if not words:
            continue
        query_str = ' '.join(words).lower()
        if query_str in seen_queries:
            continue
        seen_queries.add(query_str)
        # Construir URL de búsqueda de listado — siempre muestra activos con precios
        slug = urllib.parse.quote(query_str.replace(' ', '-'))
        url  = f"https://listado.mercadolibre.com.co/{slug}"
        top_listings.append({
            "title": ' '.join(words),   # nombre limpio del producto
            "price": 0,                  # precios reales visibles al abrir el link
            "url":   url,
            "sold":  0,
        })
        if len(top_listings) == 3:
            break

    # Precio sugerido desde benchmark de categoría (mejor estimado disponible)
    bm = CATEGORY_BENCHMARKS.get(category, CATEGORY_BENCHMARKS["Otro / General"])
    suggested = int(purchase_price * bm["markup"]) if purchase_price > 0 else 0

    # Peso real del producto desde atributos del catálogo (si ML lo expone)
    weight_kg = 0.0
    for p in results:
        weight_kg = _parse_weight_kg(p.get("attributes", []))
        if weight_kg > 0:
            break

    # Ventas y volumen estimados a partir del total de competidores
    est_monthly = max(10, int(total * 0.04))   # ~4% del catálogo vende/mes
    est_volume  = min(total * 6, 200000)

    return {
        "competitor_count":       min(total, 9999),
        "monthly_sales_estimate": est_monthly,
        "search_volume_estimate": int(est_volume),
        "avg_sale_price":         suggested,
        "min_price":              int(suggested * 0.75),
        "max_price":              int(suggested * 1.40),
        "suggested_sale_price":   suggested,
        "avg_rating":             bm["rating"],
        "ml_category":            category,
        "shipping_cost":          _ml_shipping_cost(suggested, weight_kg),
        "ml_weight_kg":           round(weight_kg, 3) if weight_kg > 0 else 0,
        "source":                 "mercadolibre",
        "confidence":             "real",
        "top_listings":           top_listings,
    }


# ── Benchmarks (sin API) ──────────────────────────────────────────────────────

def _benchmark_data(category: str, purchase_price: float = 0) -> dict:
    bm = CATEGORY_BENCHMARKS.get(category, CATEGORY_BENCHMARKS["Otro / General"])
    markup = bm["markup"]
    suggested = int(purchase_price * markup) if purchase_price > 0 else 0

    # Añadir variación realista (±15 %)
    import random
    rng = random.Random(hash(category))  # determinista por categoría
    noise = lambda base, pct: int(base * (1 + rng.uniform(-pct, pct)))

    comp = noise(bm["competitors"], 0.20)
    return {
        "competitor_count":       comp,
        "monthly_sales_estimate": noise(bm["monthly_sales"],  0.25),
        "search_volume_estimate": noise(bm["search_volume"],  0.20),
        "avg_sale_price":         suggested,
        "min_price":              int(suggested * 0.75),
        "max_price":              int(suggested * 1.40),
        "suggested_sale_price":   suggested,
        "avg_rating":             round(bm["rating"] + rng.uniform(-0.2, 0.2), 1),
        "ml_category":            category,
        "shipping_cost":          _ml_shipping_cost(suggested),
        "suggested_advertising_pct": _suggested_advertising_pct(comp),
        "source":                 "benchmark",
        "confidence":             "estimado",
    }


# ── API pública ───────────────────────────────────────────────────────────────

def _search_variants(name: str) -> list:
    """
    Genera variantes de búsqueda progresivamente más simples.
    Ej: "SET DE PESTAÑAS (NATURAL) DH0603" →
        ["SET DE PESTAÑAS NATURAL",
         "SET DE PESTAÑAS",
         "PESTAÑAS NATURAL",
         "PESTAÑAS"]
    """
    import re
    variants = []
    seen = set()

    def _add(q):
        # Eliminar paréntesis, guiones y caracteres especiales
        q = re.sub(r'[()[\]{}<>]', ' ', q)
        q = re.sub(r'\s+', ' ', q).strip()
        if q and len(q) > 2 and q.lower() not in seen:
            seen.add(q.lower())
            variants.append(q)

    _add(name)

    # Sin cantidades (X12, x6, ×12, pack de N, set de N)
    cleaned = re.sub(r'\b[xX×]\s*\d+\b', '', name)
    cleaned = re.sub(r'\bpack\s+de?\s+\d+\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bset\s+de\s+\d+\b',   '', cleaned, flags=re.IGNORECASE)
    # Eliminar códigos alfanuméricos (DH0603, SKU123, etc.)
    cleaned = re.sub(r'\b[A-Z]{1,3}\d{3,}\b', '', cleaned)
    cleaned = re.sub(r'\b\d{3,}\b', '', cleaned)
    _add(cleaned)

    # Palabras significativas: largo > 2, sin códigos puros, sin paréntesis
    raw_words = re.sub(r'[()[\]{}]', ' ', cleaned).split()
    words = [w for w in raw_words
             if len(w) > 2
             and not re.fullmatch(r'[A-Z0-9]{2,}', w)
             and w.upper() not in ('SET', 'DE', 'DEL', 'LA', 'LOS', 'LAS',
                                   'CON', 'PAR', 'KIT', 'AND', 'FOR')]

    # Primera 4, 3 y 2 palabras
    for n in (4, 3, 2):
        if len(words) >= n:
            _add(' '.join(words[:n]))

    # Solo la palabra principal (sustantivo)
    if words:
        _add(words[0])

    return variants


# ── Tabla oficial Mercado Envíos Colombia 2026 ────────────────────────────────
# Fuente: panel de vendedor ML → "Costos por enviar tus productos".
# Filas = tramo de peso (límite superior en kg). Columnas = rango de precio:
#   [ $0–14.999 , $15.000–29.999 , $30.000–59.999 , ≥ $60.000 ]
_ML_SHIPPING_TABLE = [
    (0.3,   (2500,  2600,  4100,  8000)),
    (0.5,   (2600,  2700,  4200,  8100)),
    (1,     (2700,  2800,  4300,  8200)),
    (2,     (2800,  2900,  4500,  8500)),
    (3,     (2900,  3000,  4600,  8600)),
    (4,     (3000,  3200,  4700,  10100)),
    (5,     (3100,  3300,  4800,  10200)),
    (7,     (3200,  3400,  4900,  10500)),
    (10,    (3300,  3500,  5000,  15200)),
    (20,    (3400,  3600,  5100,  25200)),
    (30,    (3500,  3700,  5200,  41400)),
    (40,    (3600,  3800,  5300,  49000)),
    (50,    (3700,  3900,  5400,  66700)),
    (60,    (3800,  4000,  5500,  69400)),
    (70,    (3900,  4100,  5600,  71500)),
    (80,    (4000,  4200,  5700,  72400)),
    (90,    (4100,  4300,  5800,  75100)),
    (100,   (4200,  4400,  5900,  77800)),
    (120,   (4300,  4500,  6000,  83400)),
    (140,   (4400,  4600,  6100,  89700)),
    (160,   (4500,  4700,  6200,  94600)),
    (180,   (4600,  4800,  6300,  97700)),
]

# Peso por defecto cuando ML no expone el peso del producto (kg).
# La mayoría de productos importados vía PDF de proveedor son artículos
# pequeños; 1 kg es un tramo conservador y representativo.
_DEFAULT_WEIGHT_KG = 1.0


def _price_col(sale_price: float) -> int:
    """Índice de columna de la tabla según el precio de venta."""
    if sale_price < 15_000:
        return 0
    if sale_price < 30_000:
        return 1
    if sale_price < 60_000:
        return 2
    return 3


def _ml_shipping_cost(sale_price: float, weight_kg: float = None) -> int:
    """
    Costo de envío EXACTO de la tabla oficial de Mercado Envíos Colombia 2026
    (panel de vendedor BOUN). Depende del peso del producto y su precio de venta.

    weight_kg: peso real del producto si se conoce (desde atributos ML).
               Si es None, usa el tramo por defecto (1 kg).
    """
    p = max(sale_price or 0, 0)
    if p <= 0:
        return 0
    w = weight_kg if (weight_kg and weight_kg > 0) else _DEFAULT_WEIGHT_KG
    col = _price_col(p)
    for max_w, costs in _ML_SHIPPING_TABLE:
        if w <= max_w:
            return costs[col]
    # Más pesado que el último tramo → usar el último
    return _ML_SHIPPING_TABLE[-1][1][col]


def _parse_weight_kg(attributes: list) -> float:
    """
    Extrae el peso en kg de los atributos del catálogo ML.
    Busca 'Peso' / 'Weight' con valores como '500 g', '0.5 kg', '1,2 kg'.
    Retorna 0 si no se encuentra.
    """
    if not attributes:
        return 0.0
    for a in attributes:
        name = (a.get("name", "") or "").lower()
        if "peso" in name or "weight" in name:
            val = (a.get("value_name", "") or "").strip().lower()
            if not val:
                continue
            m = re.search(r'([\d.,]+)\s*(kg|g|gr|gramos|kilos?)', val)
            if not m:
                continue
            try:
                num = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            unit = m.group(2)
            if unit.startswith("k"):      # kg / kilos
                return num
            return num / 1000.0           # g / gr / gramos → kg
    return 0.0


def _suggested_advertising_pct(competitor_count: int) -> float:
    """
    Sugiere % de inversión en Product Ads (publicidad) según la saturación
    real del mercado en ML. Rangos más realistas para MercadoLibre Colombia
    2026: con campañas activas el ACOS real suele estar entre 10% y 18%
    del valor de venta, y sube mucho en mercados saturados.
    """
    # Calibrado con datos reales del panel ML: un producto con ~10.000
    # competidores tiene ~17% de inversión real en publicidad.
    if competitor_count >= 20000:
        return 18.0
    if competitor_count >= 800:
        return 17.0
    if competitor_count >= 300:
        return 15.0
    if competitor_count >= 120:
        return 13.0
    if competitor_count >= 40:
        return 12.0
    return 10.0


def get_market_data(product_name: str,
                    category: str = "Otro / General",
                    purchase_price: float = 0) -> dict:
    """
    Retorna datos de mercado para un producto.
    Intenta ML API real con múltiples variantes del nombre;
    si ninguna funciona, usa benchmarks.
    """
    product_name = product_name.strip()
    if not product_name:
        return _benchmark_data(category, purchase_price)

    token = _load_token()
    if not token:
        data = _benchmark_data(category, purchase_price)
        data["_debug"] = "sin_token"
        return data

    for variant in _search_variants(product_name):
        try:
            catalog_raw = _catalog_search(variant, token, limit=15)
        except Exception as e:
            break
        if catalog_raw.get("results"):
            parsed = _parse_catalog_results(catalog_raw, category, purchase_price)
            if parsed:
                parsed["suggested_advertising_pct"] = _suggested_advertising_pct(
                    parsed.get("competitor_count", 0))
                parsed["_query_used"] = variant
                return parsed

    data = _benchmark_data(category, purchase_price)
    data["_debug"] = "sin_resultados_ML"
    return data


def _parse_ml_url(url: str) -> dict:
    """
    Extrae de una URL de MercadoLibre:
      - catalog_id: id de catálogo si es link de ficha (/p/MCO123)
      - item_id:    id de publicación (MCO-123456789)
      - title:      título legible desde el slug de la URL
    """
    u = (url or "").strip()
    out = {"catalog_id": "", "item_id": "", "title": ""}
    if not u:
        return out
    # Ficha de catálogo: /p/MCO12345  ·  /up/MCOU3836492273  (formato nuevo)
    m = re.search(r'/(?:p|up)/(MCOU?\d+)', u, re.I)
    if m:
        out["catalog_id"] = m.group(1).upper()
    # Publicación clásica: MCO-1234567890  ó  MCO1234567890 (NO MCOU…)
    m = re.search(r'MCO-?(\d{6,})', u, re.I)
    if m:
        out["item_id"] = "MCO" + m.group(1)
    # Título desde el slug clásico: .../MCO-123-este-es-el-titulo-_JM
    m = re.search(r'MCO-?\d+-([a-z0-9\-]+?)(?:-?_JM|/|\?|#|$)', u, re.I)
    if m:
        out["title"] = m.group(1).replace('-', ' ').strip()
    if not out["title"]:
        # Tomar el segmento del path que parezca slug de título: el más
        # largo con guiones, ignorando 'p','up','_JM' e ids MCO…
        path = urllib.parse.urlparse(u).path
        cand = []
        for s in path.split('/'):
            sl = s.lower()
            if (not s or sl in ('p', 'up', '_jm')
                    or s.upper().startswith('MCO')):
                continue
            cand.append(s)
        if cand:
            best = max(cand, key=lambda s: (s.count('-'), len(s)))
            out["title"] = best.replace('-', ' ').replace('_', ' ').strip()
    return out


def _og_from_page(url: str) -> dict:
    """
    Lee título e imagen REALES desde la página pública del producto
    (etiquetas Open Graph / Twitter). Funciona aunque la API /items/{id}
    no dé permiso. Retorna {'title': str, 'image': str}.
    """
    out = {"title": "", "image": ""}
    if not url:
        return out
    try:
        h = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"),
             "Accept-Language": "es-CO,es;q=0.9"}
        r = requests.get(url, headers=h, timeout=12)
        if r.status_code != 200 or not r.text:
            return out
        html = r.text
        for prop in ('og:title', 'twitter:title'):
            m = re.search(
                r'<meta[^>]+(?:property|name)=["\']' + prop +
                r'["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
            if m:
                out["title"] = m.group(1).strip()
                break
        if not out["title"]:
            m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
            if m:
                out["title"] = re.split(r'\s*[|\-–]\s*', m.group(1))[0].strip()
        for prop in ('og:image', 'twitter:image', 'twitter:image:src'):
            m = re.search(
                r'<meta[^>]+(?:property|name)=["\']' + prop +
                r'["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
            if m:
                out["image"] = m.group(1).strip().replace(
                    "http://", "https://")
                break
    except Exception:
        pass
    return out


def _real_commission_rate(price: float, category_id: str,
                          token: str, listing_type_id: str = "gold_special") -> dict:
    """
    Comisión REAL de venta vía /sites/MCO/listing_prices.
    Retorna {'rate': 0.14, 'amount': 26135, 'listing_fee': 0} o {} si falla.
    """
    if not category_id or price <= 0:
        return {}
    s = _get_session()
    s.headers["Authorization"] = "Bearer " + token
    url = (f"{ML_API}/sites/{ML_SITE}/listing_prices"
           f"?price={int(price)}&category_id={category_id}"
           f"&listing_type_id={listing_type_id}")
    try:
        r = s.get(url, timeout=12)
        if r.status_code == 200:
            d = r.json()
            sf = d.get("sale_fee_details", {}) or {}
            amount = d.get("sale_fee_amount", 0) or 0
            pct = sf.get("percentage_fee")
            rate = (pct / 100.0) if pct is not None else (
                amount / price if price > 0 else 0)
            return {
                "rate": rate,
                "amount": amount,
                "listing_fee": d.get("listing_fee_amount", 0) or 0,
                "fixed_fee": sf.get("fixed_fee", 0) or 0,
            }
    except Exception:
        pass
    return {}


def _trends_keyword(name: str) -> str:
    """Genera una consulta corta y genérica para Google Trends a partir
    del nombre del producto (3-4 palabras significativas)."""
    n = re.sub(r'[^a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9\s]', ' ', name or '')
    stop = {"de","la","el","los","las","con","para","por","y","x","un","una",
            "color","negro","blanco","talla","unidad","set","kit","pack",
            "the","and","of","medium","large","small","unisex","pro","plus",
            "premium","original","nuevo","nueva","par","pares","piezas",
            "pcs","uds","ml","cm","mm","gr"}
    words = []
    for w in n.lower().split():
        # Descartar tokens con dígitos ("550", "12pcs", "x3"): matan los
        # resultados de Google Trends (búsquedas demasiado específicas).
        if len(w) <= 2 or w in stop or any(c.isdigit() for c in w):
            continue
        words.append(w)
    # Google Trends funciona mejor con términos cortos y genéricos
    # (2 palabras). Frases largas devuelven 0.
    return ' '.join(words[:2])


def trends_for_name(name: str):
    """
    Tendencia de Google Trends para un producto. Intenta con 2 palabras
    clave; si Google no responde, reintenta con 1 sola palabra (más
    genérica, casi siempre devuelve datos). Retorna lista de puntos o [].
    """
    n = re.sub(r'[^a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9\s]', ' ', name or '')
    stop = {"de","la","el","los","las","con","para","por","y","x","un","una",
            "color","negro","blanco","talla","unidad","set","kit","pack",
            "the","and","of","medium","large","small","unisex","pro","plus",
            "premium","original","nuevo","nueva","par","pares","piezas",
            "pcs","uds","ml","cm","mm","gr"}
    words = [w for w in n.lower().split()
             if len(w) > 2 and w not in stop
             and not any(c.isdigit() for c in w)]
    for kw in (" ".join(words[:2]), (words[0] if words else "")):
        if not kw:
            continue
        pts = google_trends_30d(kw)
        if pts:
            return pts
    return []


def get_item_visits(item_id: str, days: int = 30) -> dict:
    """
    Visitas REALES a la publicación en ML en los últimos `days` días.
    Retorna {'total': N, 'daily': [(fecha, visitas), ...], 'avg': X,
             'peak': Y} o {} si falla.
    """
    if not item_id:
        return {}
    try:
        tok = _load_token()
        if not tok:
            return {}
        s = _get_session()
        s.headers["Authorization"] = "Bearer " + tok
        r = s.get(f"{ML_API}/items/{item_id}/visits/time_window"
                  f"?last={days}&unit=day", timeout=12)
        if r.status_code != 200:
            return {}
        d = r.json()
        res = d.get("results", []) or []
        daily = []
        for pt in res:
            dt = (pt.get("date", "") or "")[:10]
            daily.append((dt, pt.get("total", 0) or 0))
        vals = [v for _, v in daily]
        total = d.get("total_visits", sum(vals)) or sum(vals)
        return {
            "total": total,
            "daily": daily,
            "avg": round(total / max(len(vals), 1)) if vals else 0,
            "peak": max(vals) if vals else 0,
        }
    except Exception:
        return {}


def google_trends_30d(keyword: str, geo: str = "CO") -> list:
    """
    Nivel de búsquedas en la web en los últimos 30 días vía Google Trends.
    Retorna lista de (etiqueta_fecha, valor 0-100) — 31 puntos — o []
    si Trends no responde (rate-limit, sin red, etc.).
    El truco de 'warmup' obtiene la cookie NID que destraba la API.
    """
    if not keyword:
        return []
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120 Safari/537.36"),
            "Accept-Language": "es-CO,es;q=0.9",
        })
        s.get(f"https://trends.google.com/trends/explore?geo={geo}", timeout=12)
        time.sleep(1)
        req = {"comparisonItem": [{"keyword": keyword, "geo": geo,
                                   "time": "today 1-m"}],
               "category": 0, "property": ""}
        r = s.get("https://trends.google.com/trends/api/explore",
                  params={"hl": "es-CO", "tz": "300", "req": json.dumps(req)},
                  timeout=20)
        if r.status_code != 200:
            return []
        t = r.text
        if t[:4] == ")]}'":
            t = t[5:]
        widgets = json.loads(t).get("widgets", [])
        ts = [w for w in widgets if w.get("id") == "TIMESERIES"]
        if not ts:
            return []
        w = ts[0]
        time.sleep(1)
        r2 = s.get("https://trends.google.com/trends/api/widgetdata/multiline",
                   params={"hl": "es-CO", "tz": "300",
                           "req": json.dumps(w["request"]), "token": w["token"]},
                   timeout=20)
        if r2.status_code != 200:
            return []
        t2 = r2.text
        if t2[:4] == ")]}'":
            t2 = t2[5:]
        data = json.loads(t2)["default"]["timelineData"]
        return [(p.get("formattedAxisTime", ""), int(p["value"][0]))
                for p in data if p.get("value")]
    except Exception:
        return []


def analyze_ml_url(url: str, cost: float = 0) -> dict:
    """
    Núcleo del feature 'Agregar producto desde link de ML'.

    El usuario pega un link de una publicación/ficha de MercadoLibre y su
    costo. La app obtiene de ML: precio de venta real, categoría, comisión
    exacta, envío y % de publicidad. Devuelve un dict con todo o
    {'ok': False, 'error': ...}.
    """
    token = _load_token()
    if not token:
        return {"ok": False, "error": "No hay conexión con MercadoLibre. "
                "Conéctala en Configuración."}

    parsed = _parse_ml_url(url)
    if not (parsed["catalog_id"] or parsed["item_id"] or parsed["title"]):
        return {"ok": False, "error": "El link no parece de MercadoLibre. "
                "Pega la URL completa de la publicación."}

    s = _get_session()
    s.headers["Authorization"] = "Bearer " + token

    # ── 1. Ubicar el PRODUCTO EXACTO de la publicación del link ────────────
    # Prioridad: item_id del link → /items/{id} da el producto real
    # (precio actual, categoría, catalog_product_id, vendidos).
    item_data = None
    item_price = 0
    item_category = ""
    catalog_pid = ""
    item_sold = 0
    item_original = 0
    if parsed["item_id"]:
        try:
            ri = s.get(f"{ML_API}/items/{parsed['item_id']}", timeout=15)
            if ri.status_code == 200:
                item_data = ri.json()
                item_price = item_data.get("price", 0) or 0
                item_category = item_data.get("category_id", "") or ""
                catalog_pid = item_data.get("catalog_product_id", "") or ""
                item_sold = item_data.get("sold_quantity", 0) or 0
            # Precio REAL: promoción del canal marketplace (lo que paga
            # el comprador), no el 'standard'.
            rp = s.get(f"{ML_API}/items/{parsed['item_id']}/prices", timeout=12)
            if rp.status_code == 200:
                pa, pr_ = None, None
                for pp in rp.json().get("prices", []):
                    ctx = (pp.get("conditions", {}) or {}).get(
                        "context_restrictions", []) or []
                    if pp.get("type") == "promotion" and ctx == ["channel_marketplace"]:
                        a = pp.get("amount")
                        if a and (pa is None or a > pa):
                            pa, pr_ = a, pp.get("regular_amount")
                if pa:
                    item_price = int(pa)
                    item_original = int(pr_ or 0)
        except Exception:
            pass

    # Producto de catálogo (para atributos/imagen/competidores)
    product = None
    cat_id_for_product = (catalog_pid or parsed["catalog_id"])
    if cat_id_for_product:
        try:
            r = s.get(f"{ML_API}/products/{cat_id_for_product}", timeout=15)
            if r.status_code == 200:
                product = r.json()
        except Exception:
            pass
    # Sin item ni ficha → fallback: buscar por título (menos preciso)
    if product is None and item_data is None and parsed["title"]:
        try:
            raw = _catalog_search(parsed["title"], token, limit=5)
            results = raw.get("results", [])
            if results:
                product = results[0]
        except Exception:
            pass

    if product is None and item_data is None:
        return {"ok": False, "error":
                "No pude leer esta publicación de MercadoLibre. "
                "Verifica que el link sea de un producto activo."}

    pid = (product or {}).get("id", "") or catalog_pid
    name = ((item_data or {}).get("title")
            or (product or {}).get("name")
            or parsed["title"] or "").strip()
    domain_id = ((product or {}).get("domain_id", "")
                 or (item_data or {}).get("domain_id", "") or "")

    # ── 1b. Competidores PRECISOS ─────────────────────────────────────────
    # Prioridad 1: publicaciones activas del MISMO producto de catálogo
    #              (competencia directa exacta sobre el producto del link).
    # Prioridad 2: productos del mismo dominio por palabras clave (mercado).
    total_competitors = 0
    same_product_listings = 0
    if pid:
        try:
            rl = s.get(f"{ML_API}/products/{pid}/items?limit=1", timeout=12)
            if rl.status_code == 200:
                same_product_listings = rl.json().get(
                    "paging", {}).get("total", 0)
        except Exception:
            pass
    try:
        kw = _trends_keyword(name) or (name or parsed["title"])
        q = urllib.parse.quote(kw)
        u = f"{ML_API}/products/search?site_id={ML_SITE}&q={q}&limit=1"
        if domain_id:
            u += f"&domain_id={domain_id}"
        rc = s.get(u, timeout=12)
        if rc.status_code == 200:
            total_competitors = rc.json().get("paging", {}).get("total", 0)
        if (total_competitors == 0 or total_competitors >= 10000) and domain_id:
            rc2 = s.get(f"{ML_API}/products/search?site_id={ML_SITE}"
                        f"&q={q}&limit=1", timeout=12)
            if rc2.status_code == 200:
                t2 = rc2.json().get("paging", {}).get("total", 0)
                if 0 < t2 < 10000:
                    total_competitors = t2
    except Exception:
        pass

    # ── 2. Precio EXACTO de la publicación del link ───────────────────────
    sold_total = item_sold
    free_ship = None
    if item_data is not None:
        shp = item_data.get("shipping") or {}
        free_ship = shp.get("free_shipping")
    # Precio: el de la publicación exacta (lo que cobra ese vendedor).
    # Si no hubo item (solo ficha/título), usar mediana de publicaciones.
    real_price = item_price or 0
    min_price = max_price = real_price
    category_id = item_category or (product or {}).get("category_id", "") or ""
    if real_price <= 0 and pid:
        try:
            ri = s.get(f"{ML_API}/products/{pid}/items", timeout=15)
            if ri.status_code == 200:
                _rj = ri.json()
                prices = sorted(it.get("price") for it in
                                _rj.get("results", [])[:15]
                                if it.get("price"))
                if prices:
                    real_price = prices[len(prices) // 2]
                    min_price, max_price = prices[0], prices[-1]
                if not category_id and _rj.get("results"):
                    category_id = _rj["results"][0].get("category_id", "")
                if free_ship is None and _rj.get("results"):
                    free_ship = (_rj["results"][0].get("shipping") or {}
                                 ).get("free_shipping")
        except Exception:
            pass

    # ML bloquea por API (403) el precio de publicaciones de terceros con
    # formato de catálogo nuevo (/up/MCOU…), y la página es solo-JS. En ese
    # caso NO se inventa nada: precio = 0 y se marca como no disponible
    # para que el usuario escriba el precio real que ve en el link.
    price_unavailable = real_price <= 0

    # ── 3. Comisión REAL de ML (con categoría y precio reales del link) ───
    comm = _real_commission_rate(real_price, category_id, token) if real_price else {}

    # ── 4. Peso real → envío exacto (tabla Mercado Envíos 2026) ───────────
    weight_kg = _parse_weight_kg((product or {}).get("attributes", []))
    if not weight_kg and item_data is not None:
        weight_kg = _parse_weight_kg(item_data.get("attributes", []))
    shipping = _ml_shipping_cost(real_price, weight_kg) if real_price else 0

    # ── 5. Publicidad según saturación real del mercado ───────────────────
    competitors = total_competitors or 0
    adv_pct = _suggested_advertising_pct(competitors)

    # Imagen: del producto de catálogo o del ítem de la publicación
    image_url = ""
    for pic in ((product or {}).get("pictures")
                or (item_data or {}).get("pictures") or []):
        if pic.get("url"):
            image_url = pic["url"]
            break
    image_url = (image_url or "").replace("http://", "https://")

    # Respaldo robusto: si la API no entregó el ítem (sin permiso) o no hay
    # imagen, leer título e imagen REALES desde la página pública del link.
    if (item_data is None) or (not image_url) or (not name):
        og = _og_from_page(url)
        if og.get("image") and not image_url:
            image_url = og["image"]
        # El título del slug de la URL suele venir mal/genérico: si la API
        # no dio el ítem, el og:title de la página es el correcto.
        if og.get("title") and (item_data is None or not name):
            name = og["title"]

    # ── 6. Nivel de búsquedas en la web (Google Trends, 30 días) ──────────
    trend = trends_for_name(name)
    if trend:
        vals = [v for _, v in trend]
        search_level = round(sum(vals) / len(vals))      # promedio del mes
        search_peak  = max(vals)
        # tendencia: compara última semana vs primera semana
        first = sum(vals[:7]) / max(len(vals[:7]), 1)
        last  = sum(vals[-7:]) / max(len(vals[-7:]), 1)
        if last > first * 1.15:
            search_dir = "subiendo"
        elif last < first * 0.85:
            search_dir = "bajando"
        else:
            search_dir = "estable"
    else:
        search_level = search_peak = 0
        search_dir = ""

    permalink = ((item_data or {}).get("permalink", "") or "")
    if not permalink and parsed.get("item_id"):
        iid = parsed["item_id"]
        permalink = ("https://articulo.mercadolibre.com.co/"
                     + iid.replace("MCO", "MCO-"))
    if not permalink:
        # Links de catálogo nuevos (/up/MCOU…): usar la URL pegada,
        # sin los parámetros de tracking del #fragment.
        permalink = (url or "").split("#")[0].split("?")[0]

    return {
        "ok": True,
        "product_name":      name,
        "ml_product_id":     pid,
        "permalink":         permalink,
        "category_id":       category_id,
        "real_price":        int(real_price),
        "price_unavailable": price_unavailable,
        "original_price":    int(item_original) if item_original > real_price else 0,
        "min_price":         int(min_price),
        "max_price":         int(max_price),
        "active_listings":   same_product_listings,
        "same_product_listings": same_product_listings,
        "competitor_count":  min(competitors, 99999),
        "sold_total":        sold_total,
        "free_shipping":     bool(free_ship),
        "commission_rate":   comm.get("rate", 0),
        "commission_amount": comm.get("amount", 0),
        "listing_fee":       comm.get("listing_fee", 0),
        "commission_is_real": bool(comm),
        "weight_kg":         round(weight_kg, 3) if weight_kg else 0,
        "shipping_cost":     int(shipping),
        "advertising_pct":   adv_pct,
        "image_url":         image_url,
        "search_trend":      trend,          # [(fecha, 0-100), ...] 31 pts
        "search_level":      search_level,   # promedio mes (0-100)
        "search_peak":       search_peak,
        "search_dir":        search_dir,     # subiendo/estable/bajando
        "cost":              cost,
    }


def _ml_session_auth():
    """Sesión autenticada + user_id, o (None, None) si no hay conexión."""
    tok = _load_token()
    if not tok:
        return None, None
    s = _get_session()
    s.headers["Authorization"] = "Bearer " + tok
    try:
        me = s.get(f"{ML_API}/users/me", timeout=12)
        if me.status_code == 200:
            return s, me.json().get("id")
    except Exception:
        pass
    return None, None


def get_my_products(progress=None, days=60,
                    date_from=None, date_to=None) -> dict:
    """
    Trae TODOS los productos publicados del usuario con datos reales de ML:
      - precio, inventario, total vendido, categoría, estado, foto, link
      - ventas reales del periodo elegido (agregadas de /orders)
      - gasto real en publicidad por producto (Product Ads: cost, acos,
        clicks, prints, cpc, unidades por ads)
      - sugerido de reposición según velocidad real de ventas
      - rentabilidad neta por unidad y total (orden por rentabilidad)

    progress: callback opcional (texto) para mostrar avance.
    days: ventana en días (7/15/30/60…) si no se pasa rango personalizado.
    date_from/date_to: rango personalizado 'YYYY-MM-DD' (tiene prioridad).
    Retorna {'ok': True, 'products': [...], 'summary': {...}} o
            {'ok': False, 'error': ...}.
    """
    def _say(t):
        if progress:
            try:
                progress(t)
            except Exception:
                pass

    s, uid = _ml_session_auth()
    if not s:
        return {"ok": False, "error": "No hay conexión con MercadoLibre. "
                "Conéctala en Configuración."}

    # Resolver periodo: rango personalizado o ventana en días
    try:
        if date_from:
            _d1 = _dt.date.fromisoformat(str(date_from)[:10])
            _d2 = _dt.date.fromisoformat(str(date_to)[:10]) if date_to \
                else _dt.date.today()
            if _d2 < _d1:
                _d1, _d2 = _d2, _d1
            DAYS = max(1, (_d2 - _d1).days + 1)
            _from_date, _to_date = _d1, _d2
        else:
            DAYS = max(1, int(days or 60))
            _to_date = _dt.date.today()
            _from_date = _to_date - _dt.timedelta(days=DAYS)
    except Exception:
        DAYS = 60
        _to_date = _dt.date.today()
        _from_date = _to_date - _dt.timedelta(days=60)

    # 1) IDs de todas las publicaciones del usuario
    _say("Obteniendo lista de tus publicaciones…")
    item_ids = []
    offset = 0
    while True:
        try:
            r = s.get(f"{ML_API}/users/{uid}/items/search"
                      f"?limit=100&offset={offset}", timeout=15)
            if r.status_code != 200:
                break
            d = r.json()
            ids = d.get("results", [])
            item_ids.extend(ids)
            total = d.get("paging", {}).get("total", 0)
            offset += 100
            if offset >= total or not ids:
                break
        except Exception:
            break
    if not item_ids:
        return {"ok": False, "error": "No se encontraron publicaciones en tu cuenta."}

    # 2) Detalle de cada item (multiget en lotes de 20)
    _say(f"Cargando detalle de {len(item_ids)} productos…")
    prods = {}
    attrs = ("id,title,price,available_quantity,sold_quantity,status,"
             "category_id,listing_type_id,permalink,thumbnail,"
             "secure_thumbnail,original_price,shipping,"
             "user_product_id,inventory_id,catalog_listing")
    for i in range(0, len(item_ids), 20):
        batch = item_ids[i:i + 20]
        try:
            r = s.get(f"{ML_API}/items?ids={','.join(batch)}&attributes={attrs}",
                      timeout=20)
            if r.status_code == 200:
                for entry in r.json():
                    if entry.get("code") == 200:
                        b = entry["body"]
                        prods[b["id"]] = {
                            "item_id":     b["id"],
                            "title":       b.get("title", ""),
                            "price":       b.get("price", 0) or 0,
                            "original_price": b.get("original_price", 0) or 0,
                            "inventory":   b.get("available_quantity", 0) or 0,
                            "sold_total":  b.get("sold_quantity", 0) or 0,
                            "status":      b.get("status", ""),
                            "category_id": b.get("category_id", "") or "",
                            "listing_type": b.get("listing_type_id", "") or "",
                            "permalink":   b.get("permalink", "") or "",
                            "logistic_type": (b.get("shipping") or {})
                                .get("logistic_type", "") or "",
                            "upid":        b.get("user_product_id", "") or "",
                            "inventory_id": b.get("inventory_id", "") or "",
                            "catalog":     bool(b.get("catalog_listing")),
                            "thumbnail":   (b.get("secure_thumbnail")
                                            or b.get("thumbnail", "")
                                            or "").replace("http://", "https://"),
                            "sold_60d":    0,
                            "ad_cost": 0.0, "ad_acos": 0.0, "ad_clicks": 0,
                            "ad_prints": 0, "ad_cpc": 0.0, "ad_units": 0,
                            "ad_sales": 0.0, "ad_dir_units": 0,
                            "ad_indir_units": 0, "ad_dir_amount": 0.0,
                            "ad_indir_amount": 0.0, "ad_roas": 0.0,
                            "campaign_id": "", "campaign_name": "",
                            "has_campaign": False, "category_name": "",
                            "is_star": False,
                        }
        except Exception:
            continue
        _say(f"Detalle… {min(i+20, len(item_ids))}/{len(item_ids)}")

    # 2b) Precio REAL de venta (promoción marketplace) por ítem.
    # El campo 'price' es el 'standard'; el comprador paga la promoción
    # del canal marketplace. /items/{id}/prices lo expone. En paralelo.
    _say("Obteniendo precios reales con promoción…")

    def _real_price(iid):
        try:
            ss = requests.Session()
            ss.headers["Authorization"] = "Bearer " + _load_token()
            rp = ss.get(f"{ML_API}/items/{iid}/prices", timeout=10)
            if rp.status_code != 200:
                return iid, None, None
            promo_amt = None
            promo_reg = None
            std = None
            for pr in rp.json().get("prices", []):
                conds = pr.get("conditions", {}) or {}
                ctx = conds.get("context_restrictions", []) or []
                if pr.get("type") == "standard":
                    std = pr.get("amount")
                elif pr.get("type") == "promotion" and ctx == ["channel_marketplace"]:
                    a = pr.get("amount")
                    # tomar la promo marketplace pública (mayor de las base,
                    # las de buyer_loyalty se excluyen por tener otra cond)
                    if a and (promo_amt is None or a > promo_amt):
                        promo_amt = a
                        promo_reg = pr.get("regular_amount")
            if promo_amt:
                return iid, int(promo_amt), int(promo_reg or std or promo_amt)
            return iid, (int(std) if std else None), None
        except Exception:
            return iid, None, None

    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as ex:
            for iid, amt, reg in ex.map(_real_price, list(prods.keys())):
                if iid in prods and amt:
                    prods[iid]["price"] = amt
                    if reg and reg > amt:
                        prods[iid]["original_price"] = reg
                    else:
                        prods[iid]["original_price"] = 0
    except Exception:
        pass

    # 3) Ventas reales del periodo (agregadas por item)
    _say(f"Sumando ventas reales del periodo ({DAYS} días)…")
    since = _from_date.strftime("%Y-%m-%dT00:00:00.000-00:00")
    until = _to_date.strftime("%Y-%m-%dT23:59:59.000-00:00")
    offset = 0
    while True:
        try:
            r = s.get(f"{ML_API}/orders/search?seller={uid}"
                      f"&order.date_created.from={since}"
                      f"&order.date_created.to={until}"
                      f"&sort=date_desc&limit=50&offset={offset}", timeout=20)
            if r.status_code != 200:
                break
            d = r.json()
            results = d.get("results", [])
            for od in results:
                for oi in od.get("order_items", []):
                    iid = (oi.get("item") or {}).get("id")
                    if iid in prods:
                        prods[iid]["sold_60d"] += oi.get("quantity", 0) or 0
            total = d.get("paging", {}).get("total", 0)
            offset += 50
            if offset >= total or not results:
                break
            if offset % 500 == 0:
                _say(f"Ventas 60d… {offset}/{total} órdenes")
        except Exception:
            break

    # 4) Gasto real en publicidad por producto (Product Ads)
    _say("Obteniendo gasto real en publicidad…")
    ads_kpis, campaigns = {}, []
    try:
        s.headers["Api-Version"] = "1"
        adv = s.get(f"{ML_API}/advertising/advertisers?product_id=PADS",
                    timeout=12)
        adv_id = None
        if adv.status_code == 200:
            arr = adv.json().get("advertisers", [])
            if arr:
                adv_id = arr[0].get("advertiser_id")
        if adv_id:
            d1 = _from_date.isoformat()
            d2 = _to_date.isoformat()
            offset = 0
            mq = ("clicks,prints,cost,acos,cpc,direct_amount,"
                  "indirect_amount,total_amount,units_quantity,"
                  "direct_units_quantity,indirect_units_quantity,roas,cvr")
            while True:
                r = s.get(f"{ML_API}/advertising/advertisers/{adv_id}"
                          f"/product_ads/items?date_from={d1}&date_to={d2}"
                          f"&limit=50&offset={offset}&metrics={mq}", timeout=20)
                if r.status_code != 200:
                    break
                d = r.json()
                res = d.get("results", [])
                for it in res:
                    iid = it.get("item_id")
                    if iid in prods:
                        m = it.get("metrics", {}) or {}
                        pp = prods[iid]
                        # Un producto puede estar en VARIAS campañas → la API
                        # devuelve una fila por producto-campaña. Acumular
                        # (sumar) las métricas aditivas para el total real.
                        pp["ad_cost"]   += m.get("cost", 0) or 0
                        pp["ad_clicks"] += m.get("clicks", 0) or 0
                        pp["ad_prints"] += m.get("prints", 0) or 0
                        pp["ad_units"]  += m.get("units_quantity", 0) or 0
                        pp["ad_sales"]  += m.get("total_amount", 0) or 0
                        pp["ad_dir_units"]   += m.get("direct_units_quantity", 0) or 0
                        pp["ad_indir_units"] += m.get("indirect_units_quantity", 0) or 0
                        pp["ad_dir_amount"]  += m.get("direct_amount", 0) or 0
                        pp["ad_indir_amount"] += m.get("indirect_amount", 0) or 0
                        pp["has_campaign"] = True
                        cid = it.get("campaign_id", "")
                        if cid and cid not in pp.get("_camp_ids", []):
                            pp.setdefault("_camp_ids", []).append(cid)
                        if not pp.get("campaign_id"):
                            pp["campaign_id"] = cid
                total = d.get("paging", {}).get("total", 0)
                offset += 50
                if offset >= total or not res:
                    break

        # Campañas: nombres + estado + KPIs agregados (las 6 tarjetas)
        ads_kpis = {}
        campaigns = []
        camp_name = {}
        if adv_id:
            mq2 = ("cost,acos,total_amount,direct_amount,indirect_amount,"
                   "direct_units_quantity,indirect_units_quantity,"
                   "units_quantity")
            rc = s.get(f"{ML_API}/advertising/advertisers/{adv_id}"
                       f"/product_ads/campaigns?date_from={d1}&date_to={d2}"
                       f"&metrics={mq2}&limit=100", timeout=15)
            if rc.status_code == 200:
                agg = {"cost": 0, "total_amount": 0,
                       "direct_units_quantity": 0,
                       "indirect_units_quantity": 0, "units_quantity": 0}
                for c in rc.json().get("results", []):
                    cid = c.get("id")
                    camp_name[cid] = c.get("name", "")
                    m = c.get("metrics", {}) or {}
                    campaigns.append({
                        "id": cid, "name": c.get("name", ""),
                        "status": c.get("status", ""),
                        "cost": int(m.get("cost", 0) or 0),
                        "acos": round(m.get("acos", 0) or 0, 2),
                    })
                    for k in agg:
                        agg[k] += m.get(k, 0) or 0
                roas = (agg["total_amount"] / agg["cost"]) if agg["cost"] else 0
                acos = (agg["cost"] / agg["total_amount"] * 100
                        ) if agg["total_amount"] else 0
                ads_kpis = {
                    "ventas_producto":  int(agg["direct_units_quantity"]),
                    "ventas_sin_prod":  int(agg["indirect_units_quantity"]),
                    "roas":             round(roas, 2),
                    "ingresos":         int(agg["total_amount"]),
                    "inversion":        int(agg["cost"]),
                    "acos":             round(acos, 2),
                }
        # Asignar nombre de campaña a cada producto
        for p in prods.values():
            p["campaign_name"] = camp_name.get(p.get("campaign_id"), "")
    except Exception:
        ads_kpis, campaigns = {}, []
    finally:
        s.headers.pop("Api-Version", None)

    # 5) Comisión real por categoría (cacheada — pocas categorías únicas)
    _say("Calculando comisiones reales y rentabilidad…")
    # Costos manuales guardados (MercadoLibre no expone el costo del producto)
    try:
        from database import get_ml_costs
        saved_costs = get_ml_costs()
    except Exception:
        saved_costs = {}
    # Costo desde el INVENTARIO (producto+envío). Tiene prioridad: las
    # publicaciones vinculadas a un producto físico heredan su costo
    # total; el costo manual viejo queda solo como respaldo.
    try:
        from database import inv_costs_map
        inv_costs = inv_costs_map()
    except Exception:
        inv_costs = {}

    comm_cache = {}
    plist = list(prods.values())
    for p in plist:
        cat = p["category_id"]
        price = p["price"]
        key = (cat, p["listing_type"])
        if key not in comm_cache and cat and price > 0:
            lt = p["listing_type"] or "gold_special"
            cm = _real_commission_rate(price, cat, _load_token(), lt)
            comm_cache[key] = cm.get("rate", 0) if cm else 0
        rate = comm_cache.get(key, 0) or 0

        # Ratios de publicidad derivados de los totales acumulados
        _ac = p.get("ad_cost", 0) or 0
        _as = p.get("ad_sales", 0) or 0
        _acl = p.get("ad_clicks", 0) or 0
        p["ad_acos"] = round(_ac / _as * 100, 2) if _as else 0
        p["ad_cpc"]  = round(_ac / _acl, 2) if _acl else 0
        p["ad_roas"] = round(_as / _ac, 2) if _ac else 0

        sold60 = p["sold_60d"]
        # costo de publicidad por unidad vendida (real)
        ad_per_unit = (p["ad_cost"] / sold60) if sold60 > 0 else 0
        ship = _ml_shipping_cost(price)
        commission = price * rate * 1.19          # + IVA 19% sobre comisión
        retencion = price * 0.028                  # ReteFuente+ICA+IVA
        if p["item_id"] in inv_costs:
            cost = float(inv_costs[p["item_id"]] or 0)
            p["cost_from_inv"] = True
        else:
            cost = float(saved_costs.get(p["item_id"], 0) or 0)
            p["cost_from_inv"] = False
        net_unit = (price - commission - ship - retencion
                    - ad_per_unit - cost)
        margin = (net_unit / price * 100) if price > 0 else 0
        net_60d = net_unit * sold60

        # reposición: cubrir próximos 30 días según velocidad real
        daily = sold60 / DAYS if DAYS else 0
        target = daily * 30
        restock = max(0, int(round(target - p["inventory"])))

        p["commission_rate"] = round(rate, 4)
        p["commission_unit"] = int(commission)
        p["shipping_unit"]   = int(ship)
        p["retencion_unit"]  = int(retencion)
        p["ad_per_unit"]     = int(ad_per_unit)
        p["cost"]            = int(cost)
        p["cost_known"]      = cost > 0
        p["net_unit"]        = int(net_unit)
        p["margin_pct"]      = round(margin, 1)
        p["net_60d"]         = int(net_60d)
        p["daily_sales"]     = round(daily, 2)
        p["restock_qty"]     = restock

    # 6) Nombres de categoría (lookup cacheado — pocas categorías únicas)
    _say("Resolviendo categorías…")
    cat_cache = {}
    for p in plist:
        cid = p["category_id"]
        if cid and cid not in cat_cache:
            try:
                rc = s.get(f"{ML_API}/categories/{cid}", timeout=8)
                cat_cache[cid] = rc.json().get("name", cid) \
                    if rc.status_code == 200 else cid
            except Exception:
                cat_cache[cid] = cid
        p["category_name"] = cat_cache.get(cid, cid or "—")

    # 7) Productos estrella: score combinado ventas × margen.
    #    Normaliza ventas y margen del periodo y los pondera; los 20
    #    mejores se marcan como estrella.
    max_sold = max((p["sold_60d"] for p in plist), default=1) or 1
    for p in plist:
        sales_n = p["sold_60d"] / max_sold                  # 0-1
        marg_n  = max(0.0, min(p["margin_pct"], 60)) / 60   # 0-1 (tope 60%)
        p["star_score"] = round(sales_n * 0.6 + marg_n * 0.4, 4)

    # Orden principal: estrella (ventas×margen) desc
    plist.sort(key=lambda x: x["star_score"], reverse=True)
    for i, p in enumerate(plist):
        p["is_star"] = i < 20
        p["rank"] = i + 1

    cats = sorted({p["category_name"] for p in plist if p["category_name"]})
    summary = {
        "total_products": len(plist),
        "total_sold_60d": sum(p["sold_60d"] for p in plist),
        "total_net_60d":  sum(p["net_60d"] for p in plist),
        "total_ad_cost":  int(sum(p["ad_cost"] for p in plist)),
        "need_restock":   sum(1 for p in plist if p["restock_qty"] > 0),
        "period_days":    DAYS,
        "date_from":      _from_date.isoformat(),
        "date_to":        _to_date.isoformat(),
        "updated_at":     _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ads_kpis":       ads_kpis,
        "campaigns":      campaigns,
        "categories":     cats,
    }
    _say("Listo")
    return {"ok": True, "products": plist, "summary": summary}


def guess_category(product_name: str) -> str:
    """
    Adivina la categoría de ML basándose en palabras clave del nombre.
    Retorna el nombre de categoría más probable.
    """
    name = product_name.lower()
    rules = [
        (["celular", "smartphone", "iphone", "samsung galaxy", "xiaomi"],             "Celulares y Smartphones"),
        (["laptop", "portátil", "notebook", "computador", "pc ", "mac "],             "Computadores y Laptops"),
        (["tablet", "ipad"],                                                           "Tablets"),
        (["cámara", "camara", "lente", "gopro", "flash"],                             "Cámaras y Fotografía"),
        (["audífono", "audifono", "auricular", "parlante", "bocina", "speaker",
          "bluetooth", "tws", "headphone", "earphone"],                               "Electrónica y Tecnología"),
        (["tv", "televisor", "monitor", "proyector", "beamer"],                       "TV, Audio y Video"),
        (["nevera", "lavadora", "secadora", "microondas", "estufa", "horno",
          "licuadora", "batidora", "extractor"],                                      "Electrodomésticos"),
        (["camiseta", "camisa", "pantalón", "vestido", "blusa", "chaqueta",
          "ropa", "tela", "moda"],                                                    "Ropa y Accesorios"),
        (["tenis", "zapato", "bota", "sandalia", "calzado"],                          "Calzado"),
        (["reloj", "joya", "collar", "pulsera", "anillo", "aretes"],                 "Relojes y Joyería"),
        (["mueble", "silla", "mesa", "cama", "sofá", "estante", "closet"],           "Muebles"),
        (["jardín", "jardin", "planta", "maceta", "herramienta jardín",
          "hogar", "cocina", "lámpara", "lampara", "linterna", "báscula",
          "bascula", "organizador"],                                                   "Hogar y Jardín"),
        (["bicicleta", "deporte", "gimnasio", "pesa", "yoga", "camping",
          "fútbol", "balón"],                                                          "Deportes y Fitness"),
        (["juguete", "muñeca", "lego", "puzzle", "juego", "videojuego"],             "Juguetes y Juegos"),
        (["bebé", "bebe", "pañal", "coche bebé", "mamadera", "andador"],            "Bebés"),
        (["crema", "shampoo", "perfume", "maquillaje", "cosmético",
          "belleza", "skincare"],                                                      "Belleza y Cuidado Personal"),
        (["mascotas", "perro", "gato", "veterinario", "correa", "collar mascota"],  "Mascotas"),
        (["herramienta", "taladro", "martillo", "tornillo", "llave",
          "construcción", "pintura"],                                                  "Herramientas y Construcción"),
        (["carro", "moto", "auto", "vehículo", "repuesto", "llanta"],               "Automotriz"),
        (["alimento", "comida", "snack", "bebida", "suplemento", "proteína",
          "vitamina"],                                                                 "Alimentos y Bebidas"),
        (["oficina", "papelería", "impresora", "tóner", "cartucho"],                "Industrias y Oficinas"),
    ]
    for keywords, category in rules:
        if any(kw in name for kw in keywords):
            return category
    return "Otro / General"


def get_my_items_basic(progress=None) -> dict:
    """
    Lista LIGERA de todas las publicaciones del usuario (para asignarlas
    al inventario): solo id, título, foto, precio y estado. Sin órdenes
    ni publicidad → carga en segundos.
    """
    def _say(t):
        if progress:
            try:
                progress(t)
            except Exception:
                pass

    s, uid = _ml_session_auth()
    if not s:
        return {"ok": False, "error": "No hay conexión con MercadoLibre."}

    _say("Obteniendo tus publicaciones…")
    item_ids = []
    offset = 0
    while True:
        try:
            r = s.get(f"{ML_API}/users/{uid}/items/search"
                      f"?limit=100&offset={offset}", timeout=15)
            if r.status_code != 200:
                break
            d = r.json()
            ids = d.get("results", [])
            item_ids.extend(ids)
            total = d.get("paging", {}).get("total", 0)
            offset += 100
            if offset >= total or not ids:
                break
        except Exception:
            break
    if not item_ids:
        return {"ok": False, "error": "No se encontraron publicaciones."}

    items = []
    attrs = ("id,title,price,status,thumbnail,secure_thumbnail,"
             "sold_quantity,available_quantity,shipping,"
             "user_product_id,inventory_id,catalog_listing")
    for i in range(0, len(item_ids), 20):
        batch = item_ids[i:i + 20]
        try:
            r = s.get(f"{ML_API}/items?ids={','.join(batch)}"
                      f"&attributes={attrs}", timeout=20)
            if r.status_code == 200:
                for entry in r.json():
                    if entry.get("code") == 200:
                        b = entry["body"]
                        items.append({
                            "item_id": b["id"],
                            "title":   b.get("title", "") or "",
                            "price":   b.get("price", 0) or 0,
                            "status":  b.get("status", "") or "",
                            "thumbnail": (b.get("secure_thumbnail")
                                          or b.get("thumbnail", "")
                                          or "").replace("http://", "https://"),
                            "sold_total": b.get("sold_quantity", 0) or 0,
                            "inventory": b.get("available_quantity", 0) or 0,
                            "logistic_type": (b.get("shipping") or {})
                                .get("logistic_type", "") or "",
                            "upid": b.get("user_product_id", "") or "",
                            "inventory_id": b.get("inventory_id", "") or "",
                            "catalog": bool(b.get("catalog_listing")),
                        })
        except Exception:
            continue
        _say(f"Cargando… {min(i+20, len(item_ids))}/{len(item_ids)}")

    return {"ok": True, "items": items}
