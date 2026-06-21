"""
Capa de datos BOUN — Supabase (nube, compartida por el equipo) con
respaldo local SQLite para uso offline.

• Lecturas/escrituras van a Supabase → todos los compañeros ven los
  mismos datos en tiempo real.
• Si no hay internet, se usa la copia local SQLite (espejo).
• Cada escritura exitosa en la nube también se replica localmente.
"""
import sqlite3
import os
import re
import json
import threading
import hashlib
import secrets
from datetime import datetime

import requests

from config import (DB_DIR, DB_PATH, PDF_DIR, IMG_DIR,
                     SUPABASE_URL, SUPABASE_KEY)

# Columnas que existen en la tabla products de Supabase (para filtrar
# claves que el espejo local pueda tener de más).
_PROD_COLS = {
    "id", "name", "category", "supplier_name", "purchase_price",
    "sale_price", "listing_type", "ml_monthly_sales", "ml_search_volume",
    "ml_competitor_count", "ml_avg_rating", "ml_category_commission",
    "shipping_cost", "advertising_pct", "import_tax_pct", "other_costs",
    "ml_commission_total", "total_costs", "net_profit", "profit_margin_pct",
    "viability_score", "pdf_filename", "image_path", "notes",
    "created_at", "updated_at", "created_by",
}

_SB = f"{SUPABASE_URL}/rest/v1"
_HDR = {
    "apikey": SUPABASE_KEY,
    "Authorization": "Bearer " + SUPABASE_KEY,
    "Content-Type": "application/json",
}
_TIMEOUT = 10
_lock = threading.Lock()


def _ensure_dirs():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Helpers Supabase ──────────────────────────────────────────────────────────

def _sb_get(path):
    try:
        r = requests.get(f"{_SB}/{path}", headers=_HDR, timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── Detección de capacidad: ¿ya existe la columna `channel` en
# inventory_links? (migración sql/inventory_links_multicanal.sql) ──────────────
# Permite desplegar el backend ANTES o DESPUÉS de correr el SQL sin romper nada:
# mientras la columna no exista, todo opera en modo "solo MercadoLibre" (legacy)
# y la función multicanal se activa SOLA en cuanto la migración corre.
import time as _time
_CHCAP = {"ok": None, "ts": 0.0}


def channel_supported() -> bool:
    c = _CHCAP
    if c["ok"] is True:
        return True
    # Reprobar si es desconocido o si la última prueba (negativa) ya tiene >60s.
    if c["ok"] is None or (_time.time() - c["ts"]) > 60:
        probe = _sb_get("inventory_links?select=channel&limit=1")
        c["ts"] = _time.time()
        c["ok"] = probe is not None
    return bool(c["ok"])


def _ml_only_filter() -> str:
    """Prefijo de filtro para acotar a MercadoLibre cuando la columna existe.
    Antes de la migración devuelve '' (todas las filas ya son ML)."""
    return "channel=eq.mercadolibre&" if channel_supported() else ""


def _sb_post(table, payload, upsert=False):
    h = dict(_HDR)
    h["Prefer"] = ("resolution=merge-duplicates,return=representation"
                   if upsert else "return=representation")
    try:
        r = requests.post(f"{_SB}/{table}", headers=h,
                          data=json.dumps(payload), timeout=_TIMEOUT)
        if r.status_code in (200, 201):
            j = r.json()
            return j[0] if isinstance(j, list) and j else j
    except Exception:
        pass
    return None


def _sb_patch(table, flt, payload):
    h = dict(_HDR)
    h["Prefer"] = "return=representation"
    try:
        r = requests.patch(f"{_SB}/{table}?{flt}", headers=h,
                           data=json.dumps(payload), timeout=_TIMEOUT)
        return r.status_code in (200, 204)
    except Exception:
        return False


def _sb_delete(table, flt):
    try:
        r = requests.delete(f"{_SB}/{table}?{flt}", headers=_HDR,
                            timeout=_TIMEOUT)
        return r.status_code in (200, 204)
    except Exception:
        return False


def _online():
    try:
        r = requests.get(f"{_SB}/app_settings?select=key&limit=1",
                         headers=_HDR, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ── Esquema local (espejo offline) ────────────────────────────────────────────

def init_db():
    _ensure_dirs()
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL, category TEXT DEFAULT 'Otro / General',
            supplier_name TEXT, purchase_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0, listing_type TEXT DEFAULT 'Clásica',
            ml_monthly_sales INTEGER DEFAULT 0, ml_search_volume INTEGER DEFAULT 0,
            ml_competitor_count INTEGER DEFAULT 0, ml_avg_rating REAL DEFAULT 0,
            ml_category_commission REAL DEFAULT 0, shipping_cost REAL DEFAULT 0,
            advertising_pct REAL DEFAULT 0, import_tax_pct REAL DEFAULT 0,
            other_costs REAL DEFAULT 0, ml_commission_total REAL DEFAULT 0,
            total_costs REAL DEFAULT 0, net_profit REAL DEFAULT 0,
            profit_margin_pct REAL DEFAULT 0, viability_score REAL DEFAULT 0,
            pdf_filename TEXT, image_path TEXT, notes TEXT,
            created_at TEXT, updated_at TEXT, created_by TEXT DEFAULT 'admin'
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS ml_costs (
            item_id TEXT PRIMARY KEY, cost REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)")]
        if "image_path" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN image_path TEXT")
    # Migración única: subir productos locales a la nube si la nube está
    # vacía y aún no se migró desde esta máquina.
    try:
        _migrate_local_to_cloud()
    except Exception:
        pass
    # Sube credenciales/token ML locales a la nube si faltan (sana la
    # conexión compartida sin reconectar manualmente).
    try:
        _heal_settings_to_cloud()
    except Exception:
        pass


def _meta_get(k):
    with get_conn() as c:
        r = c.execute("SELECT value FROM _meta WHERE key=?", (k,)).fetchone()
        return r["value"] if r else ""


def _meta_set(k, v):
    with get_conn() as c:
        c.execute("INSERT INTO _meta(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def _migrate_local_to_cloud():
    if _meta_get("cloud_migrated") == "1":
        return
    cloud = _sb_get("products?select=id&limit=1")
    if cloud is None:           # sin internet, intentar luego
        return
    if len(cloud) == 0:
        with get_conn() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM products")]
        for row in rows:
            row.pop("id", None)
            payload = {k: v for k, v in row.items() if k in _PROD_COLS}
            _sb_post("products", payload)
        with get_conn() as c:
            costs = [dict(r) for r in c.execute("SELECT * FROM ml_costs")]
        for cst in costs:
            _sb_post("ml_costs", cst, upsert=True)
    _meta_set("cloud_migrated", "1")


def _heal_settings_to_cloud():
    """
    Sube a la nube las claves de configuración locales (credenciales y
    token de MercadoLibre de la versión anterior) que aún NO existan en
    la nube. Así la conexión ML se comparte sin reconectar manualmente.
    Se ejecuta en cada arranque (es barato: pocas claves) y nunca
    sobrescribe valores ya presentes en la nube.
    """
    try:
        with get_conn() as c:
            local = {r["key"]: r["value"] for r in
                     c.execute("SELECT key,value FROM settings")}
        if not local:
            return
        cloud_rows = _sb_get("app_settings?select=key")
        if cloud_rows is None:          # sin internet
            return
        cloud_keys = {r["key"] for r in cloud_rows}
        for k, v in local.items():
            if k not in cloud_keys and v not in (None, ""):
                _sb_post("app_settings", {"key": k, "value": v}, upsert=True)
    except Exception:
        pass


def _mirror_products(rows):
    """Reemplaza el espejo local con las filas de la nube."""
    try:
        with get_conn() as c:
            c.execute("DELETE FROM products")
            for r in rows:
                d = {k: r.get(k) for k in _PROD_COLS if k in r}
                cols = ",".join(d.keys())
                ph = ",".join(["?"] * len(d))
                c.execute(f"INSERT INTO products ({cols}) VALUES ({ph})",
                          list(d.values()))
    except Exception:
        pass


# ── PRODUCTS ──────────────────────────────────────────────────────────────────

def _ord(order_by):
    parts = (order_by or "viability_score DESC").split()
    col = parts[0]
    d = "desc" if len(parts) > 1 and parts[1].upper() == "DESC" else "asc"
    return f"{col}.{d}"


def insert_product(data: dict) -> int:
    data = {k: v for k, v in data.items() if k in _PROD_COLS}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data.setdefault("created_at", now)
    data["updated_at"] = now
    row = _sb_post("products", data)
    if row and row.get("id"):
        pid = row["id"]
        try:
            with get_conn() as c:
                d = {k: row.get(k) for k in _PROD_COLS if k in row}
                cols = ",".join(d.keys()); ph = ",".join(["?"] * len(d))
                c.execute(f"INSERT OR REPLACE INTO products ({cols}) "
                          f"VALUES ({ph})", list(d.values()))
        except Exception:
            pass
        return pid
    # Offline: guardar local con id temporal negativo
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO products ({','.join(data.keys())}) "
            f"VALUES ({','.join(['?']*len(data))})", list(data.values()))
        return cur.lastrowid


def update_product(pid: int, data: dict):
    data = {k: v for k, v in data.items() if k in _PROD_COLS}
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _sb_patch("products", f"id=eq.{pid}", data)
    try:
        with get_conn() as conn:
            sets = ",".join(f"{k}=?" for k in data)
            conn.execute(f"UPDATE products SET {sets} WHERE id=?",
                         list(data.values()) + [pid])
    except Exception:
        pass


def delete_product(pid: int):
    _sb_delete("products", f"id=eq.{pid}")
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM products WHERE id=?", (pid,))
    except Exception:
        pass


def get_product(pid: int):
    rows = _sb_get(f"products?id=eq.{pid}&select=*")
    if rows is not None:
        return rows[0] if rows else None
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None


def get_all_products(order_by="viability_score DESC") -> list:
    rows = _sb_get(f"products?select=*&order={_ord(order_by)}")
    if rows is not None:
        _mirror_products(rows)
        return rows
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM products ORDER BY {order_by}")]


def get_top_products(n=5) -> list:
    rows = _sb_get(f"products?select=*&order=viability_score.desc&limit={n}")
    if rows is not None:
        return rows
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM products ORDER BY viability_score DESC LIMIT ?",
            (n,))]


def get_stats() -> dict:
    rows = _sb_get("products?select=viability_score,profit_margin_pct,"
                   "ml_monthly_sales")
    if rows is None:
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT viability_score,profit_margin_pct,ml_monthly_sales "
                "FROM products")]
    if not rows:
        return {"total": 0, "avg_score": 0, "best_margin": 0,
                "avg_margin": 0, "total_sales_potential": 0,
                "high_score_count": 0}
    vs = [r.get("viability_score") or 0 for r in rows]
    pm = [r.get("profit_margin_pct") or 0 for r in rows]
    ms = [r.get("ml_monthly_sales") or 0 for r in rows]
    n = len(rows)
    return {
        "total": n,
        "avg_score": round(sum(vs) / n, 1) if n else 0,
        "best_margin": round(max(pm), 1) if pm else 0,
        "avg_margin": round(sum(pm) / n, 1) if n else 0,
        "total_sales_potential": sum(ms),
        "high_score_count": sum(1 for v in vs if v >= 8),
    }


# ── SETTINGS (compartidos: incl. token ML del equipo) ─────────────────────────

def get_setting(key: str, default="") -> str:
    rows = _sb_get(f"app_settings?key=eq.{key}&select=value")
    if rows is not None:
        if rows:
            try:
                with get_conn() as c:
                    c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                              "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (key, rows[0]["value"]))
            except Exception:
                pass
            return rows[0]["value"]
        return default
    with get_conn() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key=?",
                          (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key: str, value: str):
    _sb_post("app_settings", {"key": key, "value": value}, upsert=True)
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))
    except Exception:
        pass


# ── COSTOS MANUALES DE PRODUCTOS ML ───────────────────────────────────────────

def get_ml_costs() -> dict:
    rows = _sb_get("ml_costs?select=item_id,cost")
    if rows is not None:
        try:
            with get_conn() as c:
                for r in rows:
                    c.execute("INSERT INTO ml_costs(item_id,cost) VALUES(?,?) "
                              "ON CONFLICT(item_id) DO UPDATE SET cost=excluded.cost",
                              (r["item_id"], r.get("cost") or 0))
        except Exception:
            pass
        return {r["item_id"]: (r.get("cost") or 0) for r in rows}
    with get_conn() as conn:
        return {r["item_id"]: (r["cost"] or 0) for r in
                conn.execute("SELECT item_id,cost FROM ml_costs")}


def set_ml_cost(item_id: str, cost: float):
    _sb_post("ml_costs", {"item_id": item_id, "cost": float(cost or 0)},
             upsert=True)
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO ml_costs(item_id,cost) VALUES(?,?) "
                         "ON CONFLICT(item_id) DO UPDATE SET cost=excluded.cost",
                         (item_id, float(cost or 0)))
    except Exception:
        pass


# ── USUARIOS / AUTENTICACIÓN ──────────────────────────────────────────────────

def _hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"),
        120_000).hex()


def users_count() -> int:
    """Nº de usuarios. -1 si no hay conexión (no se puede determinar)."""
    rows = _sb_get("users?select=username")
    if rows is None:
        return -1
    return len(rows)


def list_users() -> list:
    rows = _sb_get("users?select=username,role,active,must_change,created_at"
                    "&order=created_at.asc")
    return rows if rows is not None else []


def create_user(username: str, password: str, role: str = "colaborador",
                 must_change: bool = True) -> dict:
    username = (username or "").strip().lower()
    if not username or not password:
        return {"ok": False, "error": "Usuario y contraseña requeridos."}
    if users_count() == -1:
        return {"ok": False, "error": "Sin conexión. Revisa tu internet."}
    exists = _sb_get(f"users?username=eq.{username}&select=username")
    if exists:
        return {"ok": False, "error": "Ese usuario ya existe."}
    salt = secrets.token_hex(16)
    row = _sb_post("users", {
        "username": username, "salt": salt,
        "pass_hash": _hash_pw(password, salt),
        "role": role, "active": True, "must_change": must_change,
    })
    if row is None:
        return {"ok": False, "error": "No se pudo crear el usuario."}
    return {"ok": True}


def verify_login(username: str, password: str) -> dict:
    username = (username or "").strip().lower()
    rows = _sb_get(f"users?username=eq.{username}&select=*")
    if rows is None:
        return {"ok": False, "error": "Sin conexión a internet."}
    if not rows:
        return {"ok": False, "error": "Usuario o contraseña incorrectos."}
    u = rows[0]
    if not u.get("active", True):
        return {"ok": False, "error": "Tu cuenta está desactivada. "
                "Contacta al administrador."}
    if _hash_pw(password, u["salt"]) != u["pass_hash"]:
        return {"ok": False, "error": "Usuario o contraseña incorrectos."}
    return {"ok": True, "user": {
        "username": u["username"], "role": u.get("role", "colaborador"),
        "must_change": bool(u.get("must_change", False))}}


def set_password(username: str, new_password: str,
                 must_change: bool = False) -> dict:
    username = (username or "").strip().lower()
    if not new_password:
        return {"ok": False, "error": "La contraseña no puede estar vacía."}
    salt = secrets.token_hex(16)
    ok = _sb_patch("users", f"username=eq.{username}", {
        "salt": salt, "pass_hash": _hash_pw(new_password, salt),
        "must_change": must_change})
    return {"ok": ok} if ok else {"ok": False,
                                   "error": "No se pudo actualizar."}


def remember_session(username: str):
    """Recuerda al usuario en ESTA Mac (local, no en la nube)."""
    _meta_set("session_user", (username or "").strip().lower())


def forget_session():
    _meta_set("session_user", "")


def get_remembered_user() -> dict:
    """
    Si hay un usuario recordado en esta Mac y sigue activo en la nube,
    devuelve su dict {'username','role','must_change'}. Si no, None.
    """
    uname = _meta_get("session_user")
    if not uname:
        return None
    rows = _sb_get(f"users?username=eq.{uname}&select=*")
    if not rows:                       # sin conexión o usuario eliminado
        return None
    u = rows[0]
    if not u.get("active", True):
        forget_session()
        return None
    return {"username": u["username"],
            "role": u.get("role", "colaborador"),
            "must_change": bool(u.get("must_change", False))}


def delete_user(username: str) -> bool:
    return _sb_delete("users", f"username=eq.{(username or '').strip().lower()}")


def set_user_active(username: str, active: bool) -> bool:
    return _sb_patch("users", f"username=eq.{(username or '').strip().lower()}",
                     {"active": bool(active)})


# ── INVENTARIO (productos físicos ↔ publicaciones ML) ─────────────────────────

def inv_list_products() -> list:
    """Productos del inventario con sus publicaciones vinculadas, el
    conteo y la foto de la publicación MÁS VENDIDA (para identificar)."""
    prods = _sb_get("inventory_products?select=*&order=code.asc") or []
    _ch = "channel," if channel_supported() else ""
    links = _sb_get("inventory_links?select=product_id,%sml_item_id,"
                    "ml_title,ml_thumb,ml_sold,ml_qty,ml_logistic,"
                    "ml_price,ml_net,ml_margin,ml_roas,ml_acos,"
                    "ml_sold60,ml_inventory_id,ml_upid" % _ch) or []
    by_prod = {}
    for l in links:
        # Normaliza el canal (filas viejas pueden venir sin él).
        l["channel"] = l.get("channel") or "mercadolibre"
        by_prod.setdefault(l.get("product_id"), []).append(l)
    for p in prods:
        ls = sorted(by_prod.get(p["id"], []),
                    key=lambda x: -(x.get("ml_sold") or 0))
        p["links"] = ls
        p["n_links"] = len(ls)
        # Conteo por canal (para la meta de la tarjeta).
        p["n_by_channel"] = {}
        for l in ls:
            c = l.get("channel") or "mercadolibre"
            p["n_by_channel"][c] = p["n_by_channel"].get(c, 0) + 1
        p["thumb"] = next((l.get("ml_thumb") for l in ls
                           if l.get("ml_thumb")), "")
        # Marcar GRUPOS de publicaciones que COMPARTEN stock en ML
        # (mismo user_product_id / inventory_id). Se les asigna una
        # letra A,B,… para mostrarlo en la app y NO duplicar el stock.
        import string as _string
        from collections import defaultdict as _dd
        _g = _dd(list)
        for l in ls:
            k = (l.get("ml_upid") or l.get("ml_inventory_id") or "")
            if k:
                _g[k].append(l)
        _letter = 0
        for k, members in _g.items():
            if len(members) > 1:
                lt = _string.ascii_uppercase[_letter % 26]
                _letter += 1
                for l in members:
                    l["share_group"] = lt
        # Bodega ML Full = stock de publicaciones Full, contando UNA sola
        # vez por inventory_id (publicaciones que comparten stock no se
        # suman dos veces).
        _seen = {}
        for l in ls:
            if l.get("ml_logistic") == "fulfillment":
                key = (l.get("ml_inventory_id") or l.get("ml_upid")
                       or l.get("ml_item_id"))
                if key not in _seen:
                    _seen[key] = float(l.get("ml_qty") or 0)
        p["qty_full"] = int(sum(_seen.values()))
        # Valoración: promedios de precio y neto/u de sus publicaciones
        _pr = [float(l.get("ml_price") or 0) for l in ls
               if (l.get("ml_price") or 0) > 0]
        _nt = [float(l.get("ml_net") or 0) for l in ls
               if (l.get("ml_price") or 0) > 0]
        p["avg_price"] = (sum(_pr) / len(_pr)) if _pr else 0
        p["avg_net"] = (sum(_nt) / len(_nt)) if _nt else 0
        _mg = [float(l.get("ml_margin") or 0) for l in ls
               if (l.get("ml_price") or 0) > 0]
        p["avg_margin"] = (sum(_mg) / len(_mg)) if _mg else 0
        # ROAS/ACOS: promediar SOLO publicaciones con publicidad activa
        _ro = [float(l.get("ml_roas") or 0) for l in ls
               if (l.get("ml_roas") or 0) > 0]
        _ac = [float(l.get("ml_acos") or 0) for l in ls
               if (l.get("ml_acos") or 0) > 0]
        p["avg_roas"] = (sum(_ro) / len(_ro)) if _ro else 0
        p["avg_acos"] = (sum(_ac) / len(_ac)) if _ac else 0
        # Ventas reales de los últimos 60 días (todas sus publicaciones)
        p["sold60_total"] = int(sum(float(l.get("ml_sold60") or 0)
                                    for l in ls))
    return prods


def inv_next_code() -> str:
    """Siguiente código sugerido: SKU001, SKU002, … (mayor numérico + 1,
    acepta códigos viejos sin prefijo)."""
    prods = _sb_get("inventory_products?select=code") or []
    mx = 0
    for p in prods:
        m = re.search(r"(\d+)\s*$", (p.get("code") or "").strip())
        if m:
            mx = max(mx, int(m.group(1)))
    return f"SKU{mx + 1:03d}"


def inv_create_product(code: str, name: str, created_by: str = "",
                       cost_product: float = 0,
                       cost_shipping: float = 0) -> dict:
    code = (code or "").strip()
    name = (name or "").strip()
    if not code or not name:
        return {"ok": False, "error": "Código y nombre son obligatorios."}
    exists = _sb_get(f"inventory_products?code=eq.{code}&select=id")
    if exists:
        return {"ok": False, "error": f"El código {code} ya existe."}
    row = _sb_post("inventory_products", {
        "code": code, "name": name, "created_by": created_by or "",
        "cost_product": float(cost_product or 0),
        "cost_shipping": float(cost_shipping or 0)})
    if row is None:
        return {"ok": False, "error": "No se pudo crear (revisa internet)."}
    return {"ok": True, "id": row.get("id")}


def inv_update_product(pid: int, fields: dict) -> bool:
    fields = {k: v for k, v in fields.items()
              if k in ("code", "name", "notes",
                       "cost_product", "cost_shipping",
                       "qty_bogota", "qty_yopal", "qty_transit")}
    if not fields:
        return False
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _sb_patch("inventory_products", f"id=eq.{pid}", fields)


def inv_delete_product(pid: int) -> bool:
    # on delete cascade borra también sus vínculos
    return _sb_delete("inventory_products", f"id=eq.{pid}")


_INV_LINK_COLS = ("ml_item_id,ml_title,ml_thumb,ml_sold,ml_qty,ml_logistic,"
                  "ml_price,ml_net,ml_margin,ml_roas,ml_acos,"
                  "ml_sold60,ml_inventory_id,ml_upid")


def inv_get_links() -> list:
    """Todos los vínculos de TODOS los canales:
    [{product_id, channel, ml_item_id, ml_title, ml_thumb, ml_sold}, …].
    channel ∈ mercadolibre|falabella|shopify_boun|shopify_kat.
    Pre-migración (sin columna channel) devuelve solo ML con channel inferido."""
    ch = "channel," if channel_supported() else ""
    rows = _sb_get("inventory_links?select=product_id,%sml_item_id,"
                   "ml_title,ml_thumb,ml_sold,ml_qty,ml_logistic,"
                   "ml_price,ml_net,ml_margin,ml_roas,ml_acos,"
                   "ml_sold60,ml_inventory_id,ml_upid" % ch) or []
    for r in rows:
        if not r.get("channel"):
            r["channel"] = "mercadolibre"
    return rows


def inv_links_map() -> dict:
    """ml_item_id → code, SÓLO MercadoLibre (chip en Mis Productos)."""
    prods = _sb_get("inventory_products?select=id,code") or []
    codes = {p["id"]: p.get("code", "") for p in prods}
    links = _sb_get("inventory_links?%sselect=product_id,ml_item_id"
                    % _ml_only_filter()) or []
    return {l["ml_item_id"]: codes.get(l["product_id"], "")
            for l in links if l.get("ml_item_id")}


def inv_refresh_link_stock(stock_map: dict) -> int:
    """
    Actualiza ml_qty/ml_logistic/ml_sold de los vínculos con datos
    frescos de ML. stock_map = {item_id: (qty, logistic, sold)}.
    Solo escribe los que cambiaron. Devuelve nº de actualizados.
    SÓLO toca vínculos de MercadoLibre (los demás canales no usan este mapa).
    """
    links = _sb_get("inventory_links?%sselect=id,ml_item_id,ml_qty,"
                    "ml_logistic,ml_sold,ml_price,ml_net,ml_margin,"
                    "ml_roas,ml_acos,ml_sold60,ml_inventory_id,ml_upid"
                    % _ml_only_filter()) or []
    n = 0
    for l in links:
        iid = l.get("ml_item_id")
        if iid not in stock_map:
            continue
        vals = stock_map[iid]
        qty, logistic, sold = vals[0], vals[1], vals[2]
        price = vals[3] if len(vals) > 3 else l.get("ml_price") or 0
        net = vals[4] if len(vals) > 4 else l.get("ml_net") or 0
        margin = vals[5] if len(vals) > 5 else l.get("ml_margin") or 0
        roas = vals[6] if len(vals) > 6 else l.get("ml_roas") or 0
        acos = vals[7] if len(vals) > 7 else l.get("ml_acos") or 0
        sold60 = vals[8] if len(vals) > 8 else l.get("ml_sold60") or 0
        # Conservar inventory_id/upid existentes si el dato fresco viene
        # vacío (un caché viejo sin estos campos NO debe borrarlos).
        _ni = vals[9] if len(vals) > 9 else ""
        _nu = vals[10] if len(vals) > 10 else ""
        inv_id = _ni or (l.get("ml_inventory_id") or "")
        upid = _nu or (l.get("ml_upid") or "")
        if (float(l.get("ml_qty") or 0) == float(qty or 0)
                and (l.get("ml_logistic") or "") == (logistic or "")
                and float(l.get("ml_sold") or 0) == float(sold or 0)
                and float(l.get("ml_price") or 0) == float(price or 0)
                and float(l.get("ml_net") or 0) == float(net or 0)
                and float(l.get("ml_margin") or 0) == float(margin or 0)
                and float(l.get("ml_roas") or 0) == float(roas or 0)
                and float(l.get("ml_acos") or 0) == float(acos or 0)
                and float(l.get("ml_sold60") or 0) == float(sold60 or 0)
                and (l.get("ml_inventory_id") or "") == (inv_id or "")
                and (l.get("ml_upid") or "") == (upid or "")):
            continue
        if _sb_patch("inventory_links", f"id=eq.{l['id']}",
                     {"ml_qty": qty or 0, "ml_logistic": logistic or "",
                      "ml_sold": sold or 0, "ml_price": price or 0,
                      "ml_net": net or 0, "ml_margin": margin or 0,
                      "ml_roas": roas or 0, "ml_acos": acos or 0,
                      "ml_sold60": sold60 or 0,
                      "ml_inventory_id": inv_id or "",
                      "ml_upid": upid or ""}):
            n += 1
    return n


def inv_costs_map() -> dict:
    """ml_item_id → costo TOTAL (producto + envío) de su producto de
    inventario. Es el costo que hereda cada publicación vinculada."""
    prods = _sb_get("inventory_products?select=id,cost_product,"
                    "cost_shipping") or []
    totals = {p["id"]: float(p.get("cost_product") or 0)
              + float(p.get("cost_shipping") or 0) for p in prods}
    links = _sb_get("inventory_links?%sselect=product_id,ml_item_id"
                    % _ml_only_filter()) or []
    return {l["ml_item_id"]: totals.get(l["product_id"], 0)
            for l in links if l.get("ml_item_id")}


VALID_CHANNELS = ("mercadolibre", "falabella", "shopify_boun", "shopify_kat")


def inv_link_add(pid: int, channel: str, ext_id: str, meta: dict = None) -> bool:
    """Asocia UNA sola publicación a un producto SIN tocar los demás vínculos.

    A diferencia de inv_set_links (que reemplaza todos los vínculos del producto
    en los canales administrados), esto hace un upsert puntual: si la publicación
    estaba en otro producto del mismo canal, on_conflict=channel,ml_item_id la
    mueve a este. Lo usa la sección "Mapeo" para resolver un pendiente a la vez.
    """
    meta = meta or {}
    channel = channel if channel in VALID_CHANNELS else "mercadolibre"
    ext_id = (ext_id or "").strip()
    if not ext_id:
        return False
    payload = {
        "product_id": pid, "ml_item_id": ext_id,
        "ml_title": (meta.get("title") or "")[:200],
        "ml_thumb": meta.get("thumb") or "",
        "ml_sold": meta.get("sold") or 0,
        "ml_qty": meta.get("qty") or 0,
        "ml_logistic": meta.get("logistic") or "",
        "ml_price": meta.get("price") or 0,
        "ml_net": meta.get("net") or 0,
        "ml_margin": meta.get("margin") or 0,
        "ml_roas": meta.get("roas") or 0,
        "ml_acos": meta.get("acos") or 0,
        "ml_sold60": meta.get("sold60") or 0,
        "ml_inventory_id": meta.get("inv_id") or "",
        "ml_upid": meta.get("upid") or "",
    }
    if channel_supported():
        payload["channel"] = channel
        conflict = "on_conflict=channel,ml_item_id"
    else:
        # Pre-migración (tabla solo-ML): solo se pueden asociar publicaciones ML.
        if channel != "mercadolibre":
            return False
        conflict = "on_conflict=ml_item_id"
    row = _sb_post("inventory_links?%s" % conflict, payload, upsert=True)
    return row is not None


def inv_link_delete(channel: str, ext_id: str) -> bool:
    """Borra UN vínculo por (canal, id externo). Lo usa la sección Mapeo para
    quitar vínculos huérfanos (apuntan a una publicación que ya no existe)."""
    import urllib.parse as _u
    ext_id = (ext_id or "").strip()
    if not ext_id:
        return False
    flt = "ml_item_id=eq.%s" % _u.quote(ext_id, safe="")
    if channel_supported():
        flt += "&channel=eq.%s" % _u.quote(channel or "mercadolibre", safe="")
    return _sb_delete("inventory_links", flt)


def inv_set_links(pid: int, items: list, channels: list = None) -> bool:
    """
    Define las publicaciones de un producto en uno o varios canales.

    items = [[ext_id, title, thumb, sold, qty, logistic, price, net,
              margin, roas, acos, sold60, inv_id, upid, channel], …]
    El campo `channel` (índice 14) identifica el canal de cada publicación
    (mercadolibre | falabella | shopify_boun | shopify_kat). Si falta, se
    asume mercadolibre (retrocompatibilidad con el formato viejo).

    `channels` = lista de canales que el diálogo ACTUALMENTE administra. Sólo
    se REEMPLAZAN los vínculos de esos canales para este producto; los canales
    que no se incluyan (p. ej. porque su API no respondió al abrir el diálogo)
    se conservan intactos. Si es None se deducen de los items enviados.

    Una publicación pertenece a UN solo producto dentro de su canal: si estaba
    en otro, el upsert (on_conflict=channel,ml_item_id) la mueve a este.
    """
    def _ch(it):
        c = it[14] if len(it) > 14 else "mercadolibre"
        return c if c in VALID_CHANNELS else "mercadolibre"

    has_ch = channel_supported()

    if not has_ch:
        # Pre-migración: la tabla aún es solo-ML. Conservamos el
        # comportamiento viejo (borrar todo el producto y reescribir SOLO las
        # publicaciones de MercadoLibre). Las de Falabella/Shopify se ignoran
        # hasta que corra la migración (entonces ya se podrán guardar).
        _sb_delete("inventory_links", f"product_id=eq.{pid}")
        ok = True
        for it in items:
            if _ch(it) != "mercadolibre":
                continue
            iid, title = it[0], it[1]
            row = _sb_post("inventory_links?on_conflict=ml_item_id", {
                "product_id": pid, "ml_item_id": iid,
                "ml_title": (title or "")[:200],
                "ml_thumb": (it[2] if len(it) > 2 else "") or "",
                "ml_sold": (it[3] if len(it) > 3 else 0) or 0,
                "ml_qty": (it[4] if len(it) > 4 else 0) or 0,
                "ml_logistic": (it[5] if len(it) > 5 else "") or "",
                "ml_price": (it[6] if len(it) > 6 else 0) or 0,
                "ml_net": (it[7] if len(it) > 7 else 0) or 0,
                "ml_margin": (it[8] if len(it) > 8 else 0) or 0,
                "ml_roas": (it[9] if len(it) > 9 else 0) or 0,
                "ml_acos": (it[10] if len(it) > 10 else 0) or 0,
                "ml_sold60": (it[11] if len(it) > 11 else 0) or 0,
                "ml_inventory_id": (it[12] if len(it) > 12 else "") or "",
                "ml_upid": (it[13] if len(it) > 13 else "") or ""},
                upsert=True)
            if row is None:
                ok = False
        return ok

    # Canales a reemplazar: los declarados, o los presentes en los items.
    repl = set(c for c in (channels or []) if c in VALID_CHANNELS)
    if not repl:
        repl = set(_ch(it) for it in items)
    # Borra SÓLO los vínculos de este producto en los canales administrados.
    for c in repl:
        _sb_delete("inventory_links", f"product_id=eq.{pid}&channel=eq.{c}")

    ok = True
    for it in items:
        ch = _ch(it)
        iid, title = it[0], it[1]
        thumb = it[2] if len(it) > 2 else ""
        sold = it[3] if len(it) > 3 else 0
        qty = it[4] if len(it) > 4 else 0
        logistic = it[5] if len(it) > 5 else ""
        price = it[6] if len(it) > 6 else 0
        net = it[7] if len(it) > 7 else 0
        margin = it[8] if len(it) > 8 else 0
        roas = it[9] if len(it) > 9 else 0
        acos = it[10] if len(it) > 10 else 0
        sold60 = it[11] if len(it) > 11 else 0
        inv_id = it[12] if len(it) > 12 else ""
        upid = it[13] if len(it) > 13 else ""
        # on_conflict=channel,ml_item_id → si la publicación estaba en otro
        # producto (mismo canal), el upsert la mueve a este.
        row = _sb_post("inventory_links?on_conflict=channel,ml_item_id", {
            "product_id": pid, "channel": ch, "ml_item_id": iid,
            "ml_title": (title or "")[:200],
            "ml_thumb": thumb or "", "ml_sold": sold or 0,
            "ml_qty": qty or 0, "ml_logistic": logistic or "",
            "ml_price": price or 0, "ml_net": net or 0,
            "ml_margin": margin or 0, "ml_roas": roas or 0,
            "ml_acos": acos or 0, "ml_sold60": sold60 or 0,
            "ml_inventory_id": inv_id or "", "ml_upid": upid or ""},
            upsert=True)
        if row is None:
            ok = False
    return ok
