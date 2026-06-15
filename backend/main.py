"""
BOUN Web — backend FastAPI.
Reutiliza la misma lógica de la app de escritorio (database.py, ml_scraper,
ml_fees, scoring) y los mismos datos en Supabase. Expone una API REST y
sirve el frontend carbón.
"""
import os
import time
import json
import base64
import threading
import secrets
from datetime import datetime, timezone, timedelta
import hmac as _hmac
import hashlib as _hashlib
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import (FileResponse, JSONResponse, Response,
                               RedirectResponse, HTMLResponse)
from pydantic import BaseModel
from typing import Optional

import database as db

app = FastAPI(title="BOUN Análisis ML")

# ── Sesiones simples en memoria (token → user) ───────────────────────────────
_SESSIONS = {}


def _current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "No autenticado")
    tok = authorization.split(" ", 1)[1]
    u = _SESSIONS.get(tok)
    if not u:
        raise HTTPException(401, "Sesión expirada")
    return u


def _admin(user: dict = Depends(_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Solo administradores")
    return user


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class PwChangeIn(BaseModel):
    new_password: str


@app.get("/api/health")
def health():
    return {"ok": True, "users": db.users_count()}


@app.post("/api/login")
def login(data: LoginIn):
    r = db.verify_login(data.username, data.password)
    if not r.get("ok"):
        raise HTTPException(401, r.get("error", "Credenciales incorrectas"))
    tok = secrets.token_urlsafe(32)
    _SESSIONS[tok] = r["user"]
    return {"token": tok, "user": r["user"]}


@app.get("/api/admin-login")
def admin_login(k: str = ""):
    """Auto-login SOLO del administrador mediante un token secreto
    (ADMIN_AUTOLOGIN_TOKEN). Permite al creador entrar sin contraseña con un
    link marcado como favorito. Los demás usuarios siguen con login normal."""
    token = os.environ.get("ADMIN_AUTOLOGIN_TOKEN", "")
    if not token or k != token:
        raise HTTPException(401, "No autorizado")
    admins = [u for u in (db.list_users() or []) if u.get("role") == "admin"]
    if not admins:
        raise HTTPException(500, "Sin administrador")
    user = {"username": admins[0]["username"], "role": "admin",
            "must_change": False}
    tok = secrets.token_urlsafe(32)
    _SESSIONS[tok] = user
    return {"token": tok, "user": user}


@app.post("/api/logout")
def logout(user: dict = Depends(_current_user),
           authorization: str = Header(None)):
    _SESSIONS.pop(authorization.split(" ", 1)[1], None)
    return {"ok": True}


@app.post("/api/change-password")
def change_password(data: PwChangeIn, user: dict = Depends(_current_user)):
    if len(data.new_password) < 6:
        raise HTTPException(400, "Mínimo 6 caracteres")
    r = db.set_password(user["username"], data.new_password, must_change=False)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "No se pudo actualizar"))
    return {"ok": True}


# ── Colaboradores (admin) ────────────────────────────────────────────────────

class UserIn(BaseModel):
    username: str
    password: str


@app.get("/api/users")
def list_users(user: dict = Depends(_admin)):
    return db.list_users()


@app.post("/api/users")
def create_user(data: UserIn, user: dict = Depends(_admin)):
    r = db.create_user(data.username, data.password, role="colaborador",
                       must_change=True)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "No se pudo crear"))
    return {"ok": True}


@app.delete("/api/users/{username}")
def delete_user(username: str, user: dict = Depends(_admin)):
    return {"ok": db.delete_user(username)}


class ActiveIn(BaseModel):
    active: bool


@app.patch("/api/users/{username}/active")
def set_active(username: str, data: ActiveIn, user: dict = Depends(_admin)):
    return {"ok": db.set_user_active(username, data.active)}


class ResetIn(BaseModel):
    new_password: str


@app.post("/api/users/{username}/reset")
def reset_pw(username: str, data: ResetIn, user: dict = Depends(_admin)):
    r = db.set_password(username, data.new_password, must_change=True)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "No se pudo"))
    return {"ok": True}


# ── Inventario ───────────────────────────────────────────────────────────────

@app.get("/api/inventory")
def inventory(user: dict = Depends(_current_user)):
    return db.inv_list_products()


class InvProductIn(BaseModel):
    code: str
    name: str
    cost_product: float = 0
    cost_shipping: float = 0


@app.post("/api/inventory")
def inv_create(data: InvProductIn, user: dict = Depends(_current_user)):
    r = db.inv_create_product(data.code, data.name,
                              created_by=user.get("username", ""),
                              cost_product=data.cost_product,
                              cost_shipping=data.cost_shipping)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "No se pudo crear"))
    return r


class InvUpdateIn(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    cost_product: Optional[float] = None
    cost_shipping: Optional[float] = None
    qty_bogota: Optional[float] = None
    qty_yopal: Optional[float] = None
    qty_transit: Optional[float] = None


@app.patch("/api/inventory/{pid}")
def inv_update(pid: int, data: InvUpdateIn,
               user: dict = Depends(_current_user)):
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Nada que actualizar")
    # Solo el administrador puede editar el SKU/código del producto.
    if "code" in fields and user.get("role") != "admin":
        raise HTTPException(403, "Solo el administrador puede editar el SKU.")
    return {"ok": db.inv_update_product(pid, fields)}


@app.delete("/api/inventory/{pid}")
def inv_delete(pid: int, user: dict = Depends(_admin)):
    return {"ok": db.inv_delete_product(pid)}


class AssignIn(BaseModel):
    items: list   # [[item_id,title,thumb,sold,qty,logistic,price,net,
                  #   margin,roas,acos,sold60,inv_id,upid], …]


@app.post("/api/inventory/{pid}/links")
def inv_assign(pid: int, data: AssignIn, user: dict = Depends(_current_user)):
    return {"ok": db.inv_set_links(pid, data.items)}


@app.get("/api/inventory/items")
def inventory_items(user: dict = Depends(_current_user)):
    """Publicaciones de ML (ligero) para asignar, + vínculos actuales."""
    from ml_scraper import get_my_items_basic
    r = get_my_items_basic()
    links = db.inv_get_links()
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "links": links}
    return {"ok": True, "items": r["items"], "links": links}


# ── Mis Productos ────────────────────────────────────────────────────────────

# ── Caché en servidor de Mis Productos (refresco cada 20 min) ────────────────
_MP_CACHE = {}        # days -> {"ts": epoch, "data": result}
_MP_LOCK = threading.Lock()
_MP_TTL = 20 * 60     # 20 minutos


def _fetch_my_products(days):
    from ml_scraper import get_my_products
    r = get_my_products(days=days)
    if r.get("ok"):
        try:
            inv = db.inv_links_map()
            for pr in r.get("products", []):
                pr["inv_code"] = inv.get(pr.get("item_id"), "")
        except Exception:
            pass
        # refrescar también el stock/inventory_id de los vínculos del
        # inventario (igual que el refresco de la app de escritorio)
        try:
            sm = {pr.get("item_id"): (
                pr.get("inventory", 0) or 0, pr.get("logistic_type", "") or "",
                pr.get("sold_total", 0) or 0, pr.get("price", 0) or 0,
                pr.get("net_unit", 0) or 0, pr.get("margin_pct", 0) or 0,
                pr.get("ad_roas", 0) or 0, pr.get("ad_acos", 0) or 0,
                pr.get("sold_60d", 0) or 0, pr.get("inventory_id", "") or "",
                pr.get("upid", "") or "")
                for pr in r.get("products", []) if pr.get("item_id")}
            db.inv_refresh_link_stock(sm)
        except Exception:
            pass
    return r


@app.get("/api/my-products")
def my_products(days: int = 60, force: bool = False,
                user: dict = Depends(_current_user)):
    now = time.time()
    c = _MP_CACHE.get(days)
    if c and not force and (now - c["ts"]) < _MP_TTL:
        out = dict(c["data"])
        out["cache_age_min"] = int((now - c["ts"]) / 60)
        return out
    # refrescar (con lock para no duplicar trabajo en peticiones simultáneas)
    with _MP_LOCK:
        c = _MP_CACHE.get(days)
        if c and not force and (time.time() - c["ts"]) < _MP_TTL:
            out = dict(c["data"]); out["cache_age_min"] = int((time.time()-c["ts"])/60); return out
        r = _fetch_my_products(days)
        if r.get("ok"):
            _MP_CACHE[days] = {"ts": time.time(), "data": r}
        out = dict(r); out["cache_age_min"] = 0
        return out


def _mp_background_refresh():
    """Refresca el periodo de 60 días cada 20 min, en segundo plano,
    para que la página abra al instante con datos recientes."""
    while True:
        # precalentar primero el mapa de ventas de 7 días (lo usa el export)
        try:
            _sold7_map(force=True)
        except Exception:
            pass
        try:
            r = _fetch_my_products(60)
            if r.get("ok"):
                _MP_CACHE[60] = {"ts": time.time(), "data": r}
        except Exception:
            pass
        time.sleep(_MP_TTL)


@app.on_event("startup")
def _start_bg():
    t = threading.Thread(target=_mp_background_refresh, daemon=True)
    t.start()


@app.get("/api/product-trends")
def product_trends(item_id: str = "", title: str = "", days: int = 60,
                   user: dict = Depends(_current_user)):
    """Google Trends + visitas ML de UNA publicación (panel desplegable)."""
    out = {"trends": [], "visits": {}}
    try:
        from ml_scraper import trends_for_name, get_item_visits
        out["trends"] = trends_for_name(title) or []
    except Exception:
        pass
    try:
        from ml_scraper import get_item_visits
        out["visits"] = get_item_visits(item_id, days) or {}
    except Exception:
        pass
    return out


# ── Productos para comprar (catálogo guardado) ───────────────────────────────

@app.get("/api/products")
def products(user: dict = Depends(_current_user)):
    return db.get_all_products("viability_score DESC")


@app.get("/api/products/{pid}")
def product_get(pid: int, user: dict = Depends(_current_user)):
    p = db.get_product(pid)
    if not p:
        raise HTTPException(404, "No encontrado")
    return p


class ProductPatchIn(BaseModel):
    purchase_price: Optional[float] = None
    sale_price: Optional[float] = None
    shipping_cost: Optional[float] = None
    ml_commission_total: Optional[float] = None
    total_costs: Optional[float] = None
    net_profit: Optional[float] = None
    profit_margin_pct: Optional[float] = None
    viability_score: Optional[float] = None


@app.patch("/api/products/{pid}")
def product_patch(pid: int, data: ProductPatchIn,
                  user: dict = Depends(_current_user)):
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Nada que actualizar")
    db.update_product(pid, fields)
    return {"ok": True}


@app.delete("/api/products/{pid}")
def product_delete(pid: int, user: dict = Depends(_admin)):
    db.delete_product(pid)
    return {"ok": True}


# ── Agregar producto (analizar link ML) ─────────────────────────────────────

class AnalyzeIn(BaseModel):
    url: str
    cost: float = 0


@app.post("/api/analyze")
def analyze(data: AnalyzeIn, user: dict = Depends(_current_user)):
    from ml_scraper import analyze_ml_url
    r = analyze_ml_url(data.url, data.cost)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "No se pudo analizar"))
    return r


class RecalcIn(BaseModel):
    sale_price: float
    cost: float
    category: str = "Otro / General"
    commission_rate: float = 0
    advertising_pct: float = 0
    competitor_count: int = 0
    search_level: int = 0


@app.post("/api/recalc")
def recalc(data: RecalcIn, user: dict = Depends(_current_user)):
    from ml_fees import calculate_fees
    from scoring import calculate_score
    from ml_scraper import _ml_shipping_cost
    ship = _ml_shipping_cost(data.sale_price)
    fees = calculate_fees(
        sale_price=data.sale_price, purchase_price=data.cost,
        category=data.category, listing_type="Clásica",
        shipping_cost=ship, advertising_pct=(data.advertising_pct or 0) / 100.0,
        commission_rate=(data.commission_rate or None))
    lvl = data.search_level or 0
    score = calculate_score(
        profit_margin_pct=fees["profit_margin_pct"],
        monthly_sales=int(lvl * 5), competitor_count=data.competitor_count,
        search_volume=int(lvl * 50), avg_rating=4.0)
    return {"fees": fees, "shipping": ship, "score": score}


class SaveProductIn(BaseModel):
    name: str
    category: str = "Otro / General"
    purchase_price: float = 0
    sale_price: float = 0
    ml_competitor_count: int = 0
    ml_category_commission: float = 0
    ml_monthly_sales: int = 0
    ml_search_volume: int = 0
    shipping_cost: float = 0
    advertising_pct: float = 0
    ml_commission_total: float = 0
    total_costs: float = 0
    viability_score: float = 0
    profit_margin_pct: float = 0
    net_profit: float = 0
    permalink: str = ""
    image_url: str = ""


@app.post("/api/products")
def product_create(data: SaveProductIn, user: dict = Depends(_current_user)):
    d = data.dict()
    d["pdf_filename"] = d.pop("permalink", "") or ""
    d["image_path"] = d.pop("image_url", "") or ""
    d["created_by"] = user.get("username", "")
    pid = db.insert_product(d)
    return {"ok": True, "id": pid}


# ── Configuración / estado ML ────────────────────────────────────────────────

@app.get("/api/ml-status")
def ml_status(user: dict = Depends(_current_user)):
    try:
        from ml_scraper import is_connected, get_connected_username
        return {"connected": is_connected(),
                "username": get_connected_username()}
    except Exception:
        return {"connected": False, "username": ""}


# Información de la empresa + credenciales (admin)
@app.get("/api/settings")
def get_settings(user: dict = Depends(_current_user)):
    g = db.get_setting
    return {
        "company_name": g("company_name", "BOUN"),
        "company_nit": g("company_nit", ""),
        "default_user": g("default_user", "Admin"),
        "currency": g("currency", "COP"),
        "ml_app_id": g("ml_app_id", ""),
        "ml_redirect_uri": g("ml_redirect_uri", "https://boun.com.co/oauth"),
        "has_secret": bool(g("ml_client_secret", "")),
    }


class SettingsIn(BaseModel):
    company_name: Optional[str] = None
    company_nit: Optional[str] = None
    default_user: Optional[str] = None
    currency: Optional[str] = None


@app.post("/api/settings")
def save_settings(data: SettingsIn, user: dict = Depends(_admin)):
    for k, v in data.dict().items():
        if v is not None:
            db.set_setting(k, str(v))
    return {"ok": True}


class CredsIn(BaseModel):
    ml_app_id: str = ""
    ml_client_secret: str = ""
    ml_redirect_uri: str = ""


@app.post("/api/ml/credentials")
def ml_creds(data: CredsIn, user: dict = Depends(_admin)):
    if data.ml_app_id:
        db.set_setting("ml_app_id", data.ml_app_id.strip())
    if data.ml_client_secret:
        db.set_setting("ml_client_secret", data.ml_client_secret.strip())
    if data.ml_redirect_uri:
        db.set_setting("ml_redirect_uri", data.ml_redirect_uri.strip())
    return {"ok": True}


@app.get("/api/ml/auth-url")
def ml_auth_url(user: dict = Depends(_admin)):
    import urllib.parse
    from ml_scraper import ML_AUTH_URL, OAUTH_REDIRECT_URI
    app_id = db.get_setting("ml_app_id", "").strip()
    secret = db.get_setting("ml_client_secret", "").strip()
    if not app_id or not secret:
        raise HTTPException(400, "Configura primero el APP ID y Client Secret.")
    redirect = db.get_setting("ml_redirect_uri", OAUTH_REDIRECT_URI).strip() or OAUTH_REDIRECT_URI
    url = (ML_AUTH_URL + "?response_type=code&client_id="
           + urllib.parse.quote(app_id) + "&redirect_uri="
           + urllib.parse.quote(redirect))
    return {"url": url}


class ExchangeIn(BaseModel):
    code: str


@app.post("/api/ml/exchange")
def ml_exchange(data: ExchangeIn, user: dict = Depends(_admin)):
    import time as _t
    from ml_scraper import (_extract_code, _get_session, get_ml_username,
                            ML_API, OAUTH_REDIRECT_URI)
    app_id = db.get_setting("ml_app_id", "").strip()
    secret = db.get_setting("ml_client_secret", "").strip()
    redirect = db.get_setting("ml_redirect_uri", OAUTH_REDIRECT_URI).strip() or OAUTH_REDIRECT_URI
    code = _extract_code(data.code)
    if not code:
        raise HTTPException(400, "Código inválido. Copia solo el código de la URL.")
    try:
        sx = _get_session()
        r = sx.post(ML_API + "/oauth/token", data={
            "grant_type": "authorization_code", "client_id": app_id,
            "client_secret": secret, "code": code, "redirect_uri": redirect},
            headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    except Exception as e:
        raise HTTPException(400, "Error de red: %s" % e)
    if r.status_code != 200:
        raise HTTPException(400, "Error al obtener token: %s" % r.text[:200])
    td = r.json()
    db.set_setting("ml_access_token", td.get("access_token", ""))
    db.set_setting("ml_refresh_token", td.get("refresh_token", ""))
    db.set_setting("ml_token_ts", str(_t.time()))
    db.set_setting("ml_user_id", str(td.get("user_id", "")))
    uname = get_ml_username(td.get("access_token", ""), str(td.get("user_id", "")))
    db.set_setting("ml_username", uname)
    return {"ok": True, "username": uname}


@app.post("/api/ml/disconnect")
def ml_disconnect(user: dict = Depends(_admin)):
    for k in ("ml_access_token", "ml_refresh_token", "ml_username",
              "ml_user_id", "ml_token_ts"):
        db.set_setting(k, "")
    return {"ok": True}


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats(user: dict = Depends(_current_user)):
    return db.get_stats()


# ── Ventas diarias (MercadoLibre + Falabella + total) ────────────────────────

def _ml_ads_daily(date_list: list) -> dict:
    """{fecha → {roas, acos}} de Product Ads de ML, consultando día por día
    (en paralelo). ROAS = ingresos por ads / gasto; ACOS = gasto / ingresos.
    """
    out = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from ml_scraper import _ml_session_auth, ML_API
        s, uid = _ml_session_auth()
        if not s:
            return out
        s.headers["Api-Version"] = "1"
        adv = s.get(f"{ML_API}/advertising/advertisers?product_id=PADS",
                    timeout=12)
        adv_id = None
        if adv.status_code == 200:
            arr = adv.json().get("advertisers", [])
            if arr:
                adv_id = arr[0].get("advertiser_id")
        if not adv_id:
            return out

        def _one(day):
            cost = rev = 0.0
            try:
                r = s.get(f"{ML_API}/advertising/advertisers/{adv_id}"
                          f"/product_ads/campaigns?date_from={day}&date_to={day}"
                          f"&metrics=cost,total_amount&limit=100", timeout=15)
                if r.status_code == 200:
                    for c in r.json().get("results", []):
                        m = c.get("metrics", {}) or {}
                        cost += m.get("cost", 0) or 0
                        rev += m.get("total_amount", 0) or 0
            except Exception:
                pass
            roas = round(rev / cost, 2) if cost > 0 else None
            acos = round(cost / rev * 100, 1) if rev > 0 else None
            return day, {"roas": roas, "acos": acos}

        with ThreadPoolExecutor(max_workers=8) as ex:
            for day, v in ex.map(_one, date_list):
                out[day] = v
    except Exception:
        pass
    return out


def _ml_thumbs(s, item_ids: list) -> dict:
    """{item_id → miniatura https} vía multiget de /items."""
    out = {}
    from ml_scraper import ML_API
    for i in range(0, len(item_ids), 20):
        ch = [x for x in item_ids[i:i + 20] if x]
        if not ch:
            continue
        try:
            r = s.get(f"{ML_API}/items?ids={','.join(ch)}"
                      f"&attributes=id,secure_thumbnail,thumbnail", timeout=15)
            if r.status_code == 200:
                for e in r.json():
                    bd = e.get("body", {}) or {}
                    u = bd.get("secure_thumbnail") or bd.get("thumbnail") or ""
                    if u.startswith("http://"):
                        u = "https://" + u[7:]
                    if bd.get("id"):
                        out[bd["id"]] = u
        except Exception:
            pass
    return out


def _ml_daily_sales(days: int = 14, date_from: str = None,
                    date_to: str = None) -> dict:
    """Ventas diarias de ML por fecha {ordenes, unidades, ingresos}.

    Rango personalizado date_from/date_to ('YYYY-MM-DD') si se pasan;
    si no, los últimos `days` días.
    """
    try:
        import datetime as _dt
        from ml_scraper import _ml_session_auth, ML_API
        s, uid = _ml_session_auth()
        if not s:
            return {"ok": False, "error": "MercadoLibre sin conexión"}
        co = _dt.timezone(_dt.timedelta(hours=-5))
        d_from = d_to = None
        if date_from:
            d1 = _dt.date.fromisoformat(date_from[:10])
            d2 = (_dt.date.fromisoformat(date_to[:10]) if date_to
                  else _dt.datetime.now(co).date())
            if d2 < d1:
                d1, d2 = d2, d1
            d_from, d_to = d1.isoformat(), d2.isoformat()
            from_d = _dt.datetime.combine(d1, _dt.time(0, 0, 0), co)
            to_d = _dt.datetime.combine(d2, _dt.time(23, 59, 59), co)
        else:
            to_d = _dt.datetime.now(co)
            from_d = (to_d - _dt.timedelta(days=days)).replace(
                hour=0, minute=0, second=0, microsecond=0)
        since = from_d.strftime("%Y-%m-%dT%H:%M:%S.000-05:00")
        until = to_d.strftime("%Y-%m-%dT%H:%M:%S.000-05:00")
        by, offset = {}, 0
        while True:
            r = s.get(f"{ML_API}/orders/search?seller={uid}"
                      f"&order.date_created.from={since}"
                      f"&order.date_created.to={until}"
                      f"&sort=date_desc&limit=50&offset={offset}", timeout=20)
            if r.status_code != 200:
                break
            d = r.json()
            results = d.get("results", [])
            for od in results:
                fecha = (od.get("date_created") or "")[:10]
                if not fecha:
                    continue
                if d_from and (fecha < d_from or fecha > d_to):
                    continue
                b = by.setdefault(fecha, {"fecha": fecha, "ordenes": 0,
                                          "unidades": 0, "ingresos": 0.0,
                                          "_prod": {}, "roas": None,
                                          "acos": None})
                b["ordenes"] += 1
                b["ingresos"] += float(od.get("total_amount") or 0)
                for oi in od.get("order_items", []):
                    q = int(oi.get("quantity") or 0)
                    b["unidades"] += q
                    it = oi.get("item") or {}
                    iid = it.get("id")
                    nm = (it.get("title") or "").strip()
                    if iid:
                        e = b["_prod"].setdefault(
                            iid, {"nombre": nm, "unidades": 0})
                        e["unidades"] += q
                        if nm and not e["nombre"]:
                            e["nombre"] = nm
            total = d.get("paging", {}).get("total", 0)
            offset += 50
            if offset >= total or not results:
                break
        dias = sorted(by.values(), key=lambda x: x["fecha"])
        all_ids = set()
        for x in dias:
            x["ingresos"] = round(x["ingresos"], 2)
            # TODOS los productos del día, ordenados por unidades (top primero).
            top = sorted(x.pop("_prod").items(),
                         key=lambda y: -y[1]["unidades"])
            x["top"] = [{"item_id": iid, "nombre": v["nombre"],
                         "unidades": v["unidades"]} for iid, v in top]
            for t in x["top"]:
                all_ids.add(t["item_id"])
        # miniaturas de los productos top
        thumbs = _ml_thumbs(s, list(all_ids)) if all_ids else {}
        for x in dias:
            for t in x["top"]:
                t["img"] = thumbs.get(t.pop("item_id"), "")
        # ROAS/ACOS por día desde Product Ads (si hay publicidad activa)
        try:
            ads = _ml_ads_daily([x["fecha"] for x in dias])
            for x in dias:
                a = ads.get(x["fecha"])
                if a:
                    x["roas"] = a.get("roas")
                    x["acos"] = a.get("acos")
        except Exception:
            pass
        return {"ok": True, "dias": dias}
    except Exception as e:
        return {"ok": False, "error": "MercadoLibre: %s" % str(e)[:120]}


def _shopify_orders(shop: str, token: str, since_iso: str,
                    until_iso: str) -> list:
    """Órdenes de una tienda Shopify en el rango (paginado por Link header)."""
    import requests as _rq
    import re as _re
    out = []
    url = "https://%s/admin/api/2025-01/orders.json" % shop
    params = {"status": "any", "created_at_min": since_iso,
              "created_at_max": until_iso, "limit": 250,
              "fields": "created_at,total_price,line_items,financial_status"}
    headers = {"X-Shopify-Access-Token": token}
    for _ in range(15):
        r = _rq.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            raise Exception("HTTP %d" % r.status_code)
        out.extend(r.json().get("orders", []) or [])
        nxt = None
        for part in (r.headers.get("Link", "") or "").split(","):
            if 'rel="next"' in part:
                m = _re.search(r"<([^>]+)>", part)
                if m:
                    nxt = m.group(1)
        if not nxt:
            break
        url, params = nxt, None   # la URL "next" ya trae page_info+limit
    return out


def _shopify_product_images(shop: str, token: str, product_ids) -> dict:
    """{str(product_id): url_imagen destacada} para productos Shopify.
    Las órdenes no traen la imagen, así que se consulta /products.json?ids=."""
    import requests as _rq
    out = {}
    ids = [str(p) for p in product_ids if p]
    if not ids:
        return out
    headers = {"X-Shopify-Access-Token": token}
    url = "https://%s/admin/api/2025-01/products.json" % shop
    for i in range(0, len(ids), 250):
        chunk = ids[i:i + 250]
        try:
            r = _rq.get(url, params={"ids": ",".join(chunk),
                                     "fields": "id,image", "limit": 250},
                        headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            for p in r.json().get("products", []) or []:
                src = (p.get("image") or {}).get("src") or ""
                if src:
                    out[str(p.get("id"))] = src
        except Exception:
            continue
    return out


def _shopify_daily_sales(days: int = 14, date_from: str = None,
                         date_to: str = None) -> dict:
    """Ventas diarias combinadas de las tiendas Shopify (BOUN + KAT)."""
    import datetime as _dt
    co = _dt.timezone(_dt.timedelta(hours=-5))
    d_from = d_to = None
    if date_from:
        d1 = _dt.date.fromisoformat(date_from[:10])
        d2 = (_dt.date.fromisoformat(date_to[:10]) if date_to
              else _dt.datetime.now(co).date())
        if d2 < d1:
            d1, d2 = d2, d1
        d_from, d_to = d1.isoformat(), d2.isoformat()
        from_d = _dt.datetime.combine(d1, _dt.time(0, 0, 0), co)
        to_d = _dt.datetime.combine(d2, _dt.time(23, 59, 59), co)
    else:
        to_d = _dt.datetime.now(co)
        from_d = (to_d - _dt.timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0)
    since_iso, until_iso = from_d.isoformat(), to_d.isoformat()
    by, ok_any, errors, store_imgs = {}, False, [], {}
    for ckey, shop in _SHOPIFY_SHOPS.items():
        tok = db.get_setting("shopify_token::%s" % shop, "")
        if not tok:
            continue
        try:
            orders = _shopify_orders(shop, tok, since_iso, until_iso)
            ok_any = True
        except Exception as e:
            errors.append("%s: %s" % (ckey.replace("shopify_", ""),
                                      str(e)[:80]))
            continue
        tienda = ckey.replace("shopify_", "").upper()
        pids = set()
        for od in orders:
            ca = od.get("created_at") or ""
            try:
                dt = _dt.datetime.fromisoformat(
                    ca.replace("Z", "+00:00")).astimezone(co)
            except Exception:
                continue
            fecha = dt.strftime("%Y-%m-%d")
            if d_from and (fecha < d_from or fecha > d_to):
                continue
            b = by.setdefault(fecha, {"fecha": fecha, "ordenes": 0,
                                      "unidades": 0, "ingresos": 0.0,
                                      "_prod": {}, "roas": None, "acos": None})
            b["ordenes"] += 1
            b["ingresos"] += float(od.get("total_price") or 0)
            for li in od.get("line_items", []):
                q = int(li.get("quantity") or 0)
                b["unidades"] += q
                nm = (li.get("title") or "").strip()
                pid = li.get("product_id")
                if pid:
                    pids.add(pid)
                k = "%s|%s" % (tienda, li.get("sku") or nm or pid)
                e = b["_prod"].setdefault(
                    k, {"nombre": "[%s] %s" % (tienda, nm), "unidades": 0,
                        "pid": pid, "tienda": tienda})
                e["unidades"] += q
        # Imágenes de los productos vendidos de esta tienda.
        try:
            store_imgs[tienda] = _shopify_product_images(shop, tok, pids)
        except Exception:
            store_imgs[tienda] = {}
    dias = sorted(by.values(), key=lambda x: x["fecha"])
    for d in dias:
        d["ingresos"] = round(d["ingresos"], 2)
        top = sorted(d.pop("_prod").values(), key=lambda v: -v["unidades"])
        d["top"] = [{"nombre": t["nombre"], "unidades": t["unidades"],
                     "img": store_imgs.get(t.get("tienda"), {}).get(
                         str(t.get("pid")), "")} for t in top]
    if not ok_any:
        return {"ok": False,
                "error": "Shopify: " + ("; ".join(errors) or "sin tiendas")}
    return {"ok": True, "dias": dias}


_SALES_CACHE = {}        # days -> {"ts": epoch, "data": ...}
_SALES_TTL = 10 * 60
_FAL_LAST_GOOD = {}      # rango -> {"ts": epoch, "dias": [...]} última lectura ok


def _build_sales(days: int, date_from: str = None, date_to: str = None) -> dict:
    ml = _ml_daily_sales(days, date_from, date_to)
    try:
        import falabella as fb
        fa = fb.daily_sales(days, date_from, date_to)
    except Exception as e:
        fa = {"ok": False, "error": "Falabella: %s" % str(e)[:120]}
    try:
        sh = _shopify_daily_sales(days, date_from, date_to)
    except Exception as e:
        sh = {"ok": False, "error": "Shopify: %s" % str(e)[:120]}
    # Degradación elegante: si Falabella cae (503), mostrar la última lectura
    # buena de ese mismo rango marcada como "stale", en vez de quedar vacío.
    _fal_key = "%s|%s|%s" % (days, date_from or "", date_to or "")
    fal_ok = bool(fa.get("ok"))
    fal_error = fa.get("error", "")
    fal_stale, fal_as_of = False, 0
    if fal_ok:
        _FAL_LAST_GOOD[_fal_key] = {"ts": time.time(),
                                    "dias": fa.get("dias", [])}
    else:
        lg = _FAL_LAST_GOOD.get(_fal_key)
        if lg:
            fa = {"ok": True, "dias": lg["dias"]}
            fal_stale = True
            fal_as_of = int((time.time() - lg["ts"]) / 60)
    combo = {}

    _empty = lambda: {"ordenes": 0, "unidades": 0, "ingresos": 0,
                      "roas": None, "acos": None, "top": []}

    def _add(src, key):
        if src.get("ok"):
            for d in src.get("dias", []):
                b = combo.setdefault(d["fecha"], {
                    "fecha": d["fecha"], "ml": _empty(),
                    "falabella": _empty(), "shopify": _empty()})
                b[key] = {"ordenes": d["ordenes"], "unidades": d["unidades"],
                          "ingresos": d["ingresos"], "roas": d.get("roas"),
                          "acos": d.get("acos"), "top": d.get("top", [])}
    _add(ml, "ml")
    _add(fa, "falabella")
    _add(sh, "shopify")
    dias = []
    for f in sorted(combo):
        b = combo[f]
        b.setdefault("shopify", _empty())
        b["total"] = {
            "ordenes": b["ml"]["ordenes"] + b["falabella"]["ordenes"]
            + b["shopify"]["ordenes"],
            "unidades": b["ml"]["unidades"] + b["falabella"]["unidades"]
            + b["shopify"]["unidades"],
            "ingresos": round(b["ml"]["ingresos"] + b["falabella"]["ingresos"]
                              + b["shopify"]["ingresos"], 2)}
        dias.append(b)
    return {"ok": True, "days": days, "dias": dias,
            "date_from": date_from or "", "date_to": date_to or "",
            "ml_ok": bool(ml.get("ok")), "ml_error": ml.get("error", ""),
            "fal_ok": fal_ok, "fal_error": fal_error,
            "fal_stale": fal_stale, "fal_as_of": fal_as_of,
            "shop_ok": bool(sh.get("ok")), "shop_error": sh.get("error", "")}


@app.get("/api/sales")
def sales(days: int = 14, date_from: str = "", date_to: str = "",
          force: bool = False, user: dict = Depends(_current_user)):
    now = time.time()
    key = ("range:%s:%s" % (date_from, date_to)) if date_from else ("days:%d" % days)
    c = _SALES_CACHE.get(key)
    if c and not force and (now - c["ts"]) < _SALES_TTL:
        out = dict(c["data"]); out["cache_age_min"] = int((now - c["ts"]) / 60)
        return out
    data = _build_sales(days, date_from or None, date_to or None)
    _SALES_CACHE[key] = {"ts": time.time(), "data": data}
    out = dict(data); out["cache_age_min"] = 0
    return out


# ── Exportación de inventario (solo lectura, protegida por token) ─────────────
# Ruta PÚBLICA (sin sesión de usuario) pensada para que un agente externo lea
# el inventario en tiempo real pasando solo una URL con ?key=...  No toca el
# login ni las demás rutas: es puramente aditiva.

# Caché del nº de ventas por publicación en los últimos 7 días.  Se obtiene de
# ML con get_my_products(days=7) (el campo sold_60d ahí trae el conteo de la
# ventana pedida) y NO se escribe en la base, para no pisar el dato de 60 días.
_SOLD7_CACHE = {"ts": 0.0, "map": {}}
_SOLD7_TTL = 20 * 60


def _sold7_map(force: bool = False) -> dict:
    """item_id → unidades vendidas en los últimos 7 días (cacheado 20 min).

    Consulta SOLO el endpoint de órdenes de ML (ligero), no el scrape pesado
    de get_my_products — así es rápido y fiable en Render free.
    """
    now = time.time()
    if (not force and _SOLD7_CACHE["map"]
            and (now - _SOLD7_CACHE["ts"]) < _SOLD7_TTL):
        return _SOLD7_CACHE["map"]
    try:
        import datetime as _dt
        from ml_scraper import _ml_session_auth, ML_API
        s, uid = _ml_session_auth()
        if not s:
            return _SOLD7_CACHE["map"]
        to_d = _dt.date.today()
        from_d = to_d - _dt.timedelta(days=7)
        since = from_d.strftime("%Y-%m-%dT00:00:00.000-00:00")
        until = to_d.strftime("%Y-%m-%dT23:59:59.000-00:00")
        m = {}
        offset = 0
        while True:
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
                    if iid:
                        m[iid] = m.get(iid, 0) + (oi.get("quantity", 0) or 0)
            total = d.get("paging", {}).get("total", 0)
            offset += 50
            if offset >= total or not results:
                break
        _SOLD7_CACHE["ts"] = now
        _SOLD7_CACHE["map"] = m
    except Exception:
        pass
    return _SOLD7_CACHE["map"]


_EXPORT_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "no-store",
}


def _img_full(thumb: str) -> str:
    """Sube la miniatura de ML a resolución original (-I.jpg → -O.jpg)."""
    t = thumb or ""
    for s in ("-I.jpg", "-I.webp", "-I.png"):
        if t.endswith(s):
            return t[: -len(s)] + s.replace("-I", "-O")
    return t


def _permalink_from_mco(mco: str) -> str:
    """Reconstruye un permalink usable desde el id de publicación (MCO…)."""
    mco = (mco or "").strip()
    if mco.startswith("MCO") and mco[3:].isdigit():
        return "https://articulo.mercadolibre.com.co/MCO-" + mco[3:]
    return ""


@app.options("/api/export/inventario.json")
def export_inventario_preflight():
    return Response(status_code=204, headers=_EXPORT_CORS)


@app.get("/api/export/inventario.json")
def export_inventario(key: str = ""):
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)

    prods = db.inv_list_products()
    # ventas 7 días: SOLO lectura de caché (no bloquear la petición con un
    # fetch a ML). El refresco en segundo plano la mantiene caliente.
    s7 = _SOLD7_CACHE["map"]
    # ¿ya se calculó al menos una vez? Si sí, una publicación que no aparece
    # en el mapa = 0 ventas reales; si aún no, vendidos_7d = null.
    s7_warm = _SOLD7_CACHE["ts"] > 0
    productos = []
    for p in prods:
        pubs = []
        for l in p.get("links", []):
            mco = l.get("ml_item_id") or ""
            thumb = l.get("ml_thumb") or ""
            imagenes = [_img_full(thumb)] if thumb else []
            roas_v = float(l.get("ml_roas") or 0)
            pub = {
                "mco": mco,
                "titulo": l.get("ml_title") or "",
                "permalink": _permalink_from_mco(mco),
                # Estadísticas de ventas por publicación (para rankear)
                "vendidos_60d": int(l.get("ml_sold60") or 0),
                "vendidos_7d": (s7.get(mco, 0) if s7_warm else None),
                "roas": (round(roas_v, 2) if roas_v > 0 else None),
                "imagenes": imagenes,
            }
            # Marca de stock compartido (A, B, …) si la app la detectó
            if l.get("share_group"):
                pub["comparte_stock_grupo"] = l["share_group"]
            if l.get("ml_logistic"):
                pub["logistica"] = l["ml_logistic"]
            pubs.append(pub)

        mg = float(p.get("avg_margin") or 0)
        ro = float(p.get("avg_roas") or 0)
        ac = float(p.get("avg_acos") or 0)
        productos.append({
            "codigo": p.get("code") or "",
            "nombre": p.get("name") or "",
            # La app no tiene un campo dedicado de SKU Falabella: se toma del
            # campo "Notas" del producto (queda vacío si no se ha llenado).
            "sku_falabella": (p.get("notes") or "").strip(),
            "bodega_bogota": int(p.get("qty_bogota") or 0),
            "bodega_yopal": int(p.get("qty_yopal") or 0),
            "ml_full": int(p.get("qty_full") or 0),
            "en_camino": int(p.get("qty_transit") or 0),
            "vendidos_60d": int(p.get("sold60_total") or 0),
            "margen": (f"{mg:.1f}%" if mg else "—"),
            "roas": (f"{ro:.2f}x" if ro else "—"),
            "acos": (f"{ac:.1f}%" if ac else "—"),
            # La app no calcula un sugerido de compra para el inventario.
            "sugerido_compra": None,
            "publicaciones": pubs,
        })

    out = {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(productos),
        "productos": productos,
    }
    return JSONResponse(out, headers=_EXPORT_CORS)


# ── API Falabella (ventas / catálogo / stock) — protegida por token ──────────
# Mismas reglas que el export: pública (sin sesión), ?key= vs BOUN_EXPORT_TOKEN,
# CORS abierto, no-store. Pensada para un agente externo sin internet abierto.

def _falabella_guard(key: str):
    """Devuelve una JSONResponse de error si no pasa auth/credenciales; si todo
    bien, devuelve None."""
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)
    import falabella as fb
    if not fb.is_connected():
        return JSONResponse({"error": "missing_falabella_credentials"},
                            status_code=500, headers=_EXPORT_CORS)
    return None


@app.options("/api/falabella/ventas")
@app.options("/api/falabella/productos")
@app.options("/api/falabella/set-stock")
def falabella_preflight():
    return Response(status_code=204, headers=_EXPORT_CORS)


@app.get("/api/falabella/ventas")
def falabella_ventas(key: str = "", dias: int = 1):
    g = _falabella_guard(key)
    if g:
        return g
    import falabella as fb
    try:
        return JSONResponse(fb.ventas_por_sku(dias), headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502,
                            headers=_EXPORT_CORS)


@app.get("/api/falabella/productos")
def falabella_productos(key: str = ""):
    g = _falabella_guard(key)
    if g:
        return g
    import falabella as fb
    try:
        return JSONResponse(fb.get_products_list(), headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502,
                            headers=_EXPORT_CORS)


@app.get("/api/falabella/set-stock")
def falabella_set_stock(key: str = "", sku: str = "", cantidad: str = "",
                        dry: str = ""):
    g = _falabella_guard(key)
    if g:
        return g
    if not sku:
        return JSONResponse({"error": "bad_request"}, status_code=400,
                            headers=_EXPORT_CORS)
    try:
        c = int(cantidad)
        if c < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return JSONResponse({"error": "bad_request"}, status_code=400,
                            headers=_EXPORT_CORS)
    import falabella as fb
    try:
        if dry == "1":
            return JSONResponse(fb.set_stock(sku, c, dry=True),
                                headers=_EXPORT_CORS)
        res = fb.set_stock(sku, c, dry=False)
        return JSONResponse({"ok": True, "sku": sku, "cantidad": c,
                             "respuesta": res}, headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]},
                            status_code=502, headers=_EXPORT_CORS)


# ── API MercadoLibre (leer/fijar SELLER_SKU) — protegida por token ───────────
# Reutiliza el token de ML del backend (mismo que /api/inventory). El access
# token NUNCA se devuelve. Refresca y reintenta una vez si ML responde 401.

def _ml_guard(key: str):
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)
    from ml_scraper import is_connected
    if not is_connected():
        return JSONResponse({"error": "ml_not_connected"}, status_code=500,
                            headers=_EXPORT_CORS)
    return None


def _ml_request(method: str, path: str, json_body=None, timeout: int = 20):
    """Petición a la API de ML con el token del backend; si responde 401,
    refresca el token y reintenta una vez. Devuelve el Response o None."""
    from ml_scraper import _ml_session_auth, _try_refresh, ML_API
    s, _uid = _ml_session_auth()
    if not s:
        return None
    url = ML_API + path
    r = s.request(method, url, json=json_body, timeout=timeout)
    if r.status_code == 401:
        tok = _try_refresh()
        if tok:
            s.headers["Authorization"] = "Bearer " + tok
            r = s.request(method, url, json=json_body, timeout=timeout)
    return r


def _seller_sku(attrs) -> Optional[str]:
    for a in (attrs or []):
        if a.get("id") == "SELLER_SKU":
            return a.get("value_name")
    return None


@app.options("/api/ml/item")
@app.options("/api/ml/set-sku")
def ml_sku_preflight():
    return Response(status_code=204, headers=_EXPORT_CORS)


@app.get("/api/ml/item")
def ml_item(key: str = "", item_id: str = ""):
    g = _ml_guard(key)
    if g:
        return g
    if not item_id:
        return JSONResponse({"ok": False, "error": "bad_request"},
                            status_code=400, headers=_EXPORT_CORS)
    try:
        r = _ml_request("GET", "/items/%s" % item_id)
        if r is None:
            return JSONResponse({"ok": False, "error": "ml_not_connected"},
                                status_code=502, headers=_EXPORT_CORS)
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:200],
                                 "ml_status": r.status_code}, status_code=502,
                                headers=_EXPORT_CORS)
        d = r.json()
        out = {"ok": True, "item_id": item_id,
               "seller_sku": _seller_sku(d.get("attributes")),
               "variations": [
                   {"id": v.get("id"),
                    "seller_sku": (v.get("seller_custom_field")
                                   or _seller_sku(v.get("attributes")))}
                   for v in (d.get("variations") or [])]}
        return JSONResponse(out, headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]},
                            status_code=502, headers=_EXPORT_CORS)


@app.get("/api/ml/set-sku")
def ml_set_sku(key: str = "", item_id: str = "", sku: str = "", dry: str = ""):
    g = _ml_guard(key)
    if g:
        return g
    if not item_id or not sku:
        return JSONResponse({"ok": False, "error": "bad_request"},
                            status_code=400, headers=_EXPORT_CORS)
    try:
        import json as _json
        # leer el ítem: estado, catálogo y variaciones
        r = _ml_request("GET", "/items/%s" % item_id)
        if r is None:
            return JSONResponse({"ok": False, "error": "ml_not_connected"},
                                status_code=502, headers=_EXPORT_CORS)
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:300],
                                 "ml_status": r.status_code}, status_code=502,
                                headers=_EXPORT_CORS)
        item = r.json()
        status = item.get("status")
        catalog = bool(item.get("catalog_listing"))
        variations = item.get("variations") or []
        # Publicaciones CERRADAS: ML no las deja modificar y no necesitan SKU.
        if status == "closed":
            return JSONResponse({"ok": False, "skip": True, "reason": "closed",
                                 "item_id": item_id, "status": status,
                                 "catalog_listing": catalog},
                                headers=_EXPORT_CORS)
        # Con variaciones → el SKU por variación va en seller_custom_field
        # (las variaciones no usan el atributo SELLER_SKU). Se envían TODAS.
        if variations:
            body = {"variations": [
                {"id": v.get("id"), "seller_custom_field": sku}
                for v in variations]}
            applied = "variations"
        else:
            body = {"attributes": [{"id": "SELLER_SKU", "value_name": sku}]}
            applied = "item"
        if dry == "1":
            return JSONResponse({"ok": True, "item_id": item_id, "set": sku,
                                 "applied_to": applied, "status": status,
                                 "catalog_listing": catalog, "dry_run": True,
                                 "body": body}, headers=_EXPORT_CORS)
        pr = _ml_request("PUT", "/items/%s" % item_id, json_body=body)
        if pr is None:
            return JSONResponse({"ok": False, "error": "ml_not_connected"},
                                status_code=502, headers=_EXPORT_CORS)
        if pr.status_code in (200, 201):
            return JSONResponse({"ok": True, "item_id": item_id, "set": sku,
                                 "applied_to": applied,
                                 "ml_status": pr.status_code},
                                headers=_EXPORT_CORS)
        # error: devolver el error CRUDO de ML (cause/code/message)
        try:
            err = pr.json()
        except Exception:
            err = pr.text[:500]
        txt = _json.dumps(err) if isinstance(err, (dict, list)) else str(err)
        # no modificable (catálogo/cerrada) → skip, no es un error real
        if "not_modifiable" in txt or "catalog_listing" in txt:
            return JSONResponse({"ok": False, "skip": True,
                                 "reason": "closed/catalog", "item_id": item_id,
                                 "ml_status": pr.status_code, "error": err},
                                headers=_EXPORT_CORS)
        return JSONResponse({"ok": False, "error": err,
                             "ml_status": pr.status_code}, status_code=502,
                            headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]},
                            status_code=502, headers=_EXPORT_CORS)


@app.options("/api/ml/set-stock")
def ml_set_stock_preflight():
    return Response(status_code=204, headers=_EXPORT_CORS)


def _ml_set_stock_one(item_id: str, cantidad: int, dry: bool = False,
                      max_delta=None) -> dict:
    """Fija available_quantity de UNA publicación ML al valor ABSOLUTO `cantidad`.
    Devuelve un dict plano (lo usan el endpoint y el motor de propagación).

    Seguridad:
    - Salta Full, cerradas y catálogo (skip, no error).
    - Escritura absoluta → idempotente: reaplicar el mismo plan no descuadra.
    - `max_delta`: si |nuevo-actual| supera el tope, NO escribe (skip=delta_guard).
    - Snapshot del stock `actual` para auditoría y reversión.
    """
    try:
        c = int(cantidad)
        if c < 0:
            return {"ok": False, "error": "bad_request", "item_id": item_id}
        r = _ml_request(
            "GET", "/items/%s?attributes=id,status,available_quantity,"
                   "variations,shipping,catalog_listing" % item_id)
        if r is None:
            return {"ok": False, "error": "ml_not_connected", "item_id": item_id}
        if r.status_code != 200:
            return {"ok": False, "error": r.text[:300],
                    "ml_status": r.status_code, "item_id": item_id}
        item = r.json()
        status = item.get("status")
        logistic = (item.get("shipping") or {}).get("logistic_type")
        variations = item.get("variations") or []
        # Guardrails: no tocar Full ni cerradas/catálogo (no contar como error).
        if logistic == "fulfillment":
            return {"ok": False, "skip": True, "reason": "full",
                    "item_id": item_id}
        if status == "closed" or item.get("catalog_listing") is True:
            return {"ok": False, "skip": True, "reason": "closed/catalog",
                    "item_id": item_id}
        # Con variaciones → fija available_quantity en CADA variación (mismo N
        # por defecto). Sin variaciones → en el ítem. `actual` = snapshot previo.
        if variations:
            applied_to = "variations"
            actual = sum(int(v.get("available_quantity") or 0)
                         for v in variations)
            body = {"variations": [{"id": v.get("id"), "available_quantity": c}
                                   for v in variations if v.get("id")]}
        else:
            applied_to = "item"
            actual = int(item.get("available_quantity") or 0)
            body = {"available_quantity": c}
        # Guardia de salto: evita escrituras desproporcionadas por un cálculo raro.
        if max_delta is not None and abs(c - actual) > max_delta:
            return {"ok": False, "skip": True, "reason": "delta_guard",
                    "item_id": item_id, "actual": actual, "target": c,
                    "max_delta": max_delta, "applied_to": applied_to}
        if dry:
            return {"ok": True, "dry_run": True, "item_id": item_id, "set": c,
                    "actual": actual, "applied_to": applied_to,
                    "status": status, "logistic": logistic, "body": body}
        pr = _ml_request("PUT", "/items/%s" % item_id, json_body=body)
        if pr is None:
            return {"ok": False, "error": "ml_not_connected", "item_id": item_id}
        if pr.status_code in (200, 201):
            return {"ok": True, "item_id": item_id, "set": c, "actual": actual,
                    "applied_to": applied_to, "ml_status": pr.status_code}
        txt = (pr.text or "").lower()
        if "not_modifiable" in txt or "catalog_listing" in txt:
            return {"ok": False, "skip": True, "reason": "closed/catalog",
                    "item_id": item_id}
        try:
            err = pr.json()
        except Exception:
            err = pr.text[:500]
        return {"ok": False, "error": err, "ml_status": pr.status_code,
                "item_id": item_id}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "item_id": item_id}


@app.get("/api/ml/set-stock")
def ml_set_stock(key: str = "", item_id: str = "", cantidad: str = "",
                 dry: str = ""):
    """Fija available_quantity de una publicación ML (no toca Full ni cerradas).
    dry=1 devuelve el body sin enviar."""
    g = _ml_guard(key)
    if g:
        return g
    if not item_id:
        return JSONResponse({"ok": False, "error": "bad_request"},
                            status_code=400, headers=_EXPORT_CORS)
    try:
        c = int(cantidad)
        if c < 0:
            raise ValueError()
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "bad_request"},
                            status_code=400, headers=_EXPORT_CORS)
    res = _ml_set_stock_one(item_id, c, dry=(dry == "1"))
    code = 200 if (res.get("ok") or res.get("skip")) else 502
    return JSONResponse(res, status_code=code, headers=_EXPORT_CORS)


# ── Motor de sincronización — helpers de canales + pipeline (DRY-RUN) ────────

_SHOPIFY_SHOPS = {"shopify_boun": "uapngf-er.myshopify.com",
                  "shopify_kat": "2kp2p9-qu.myshopify.com"}


def _shopify_variants_by_sku(shop: str, sku: str) -> list:
    """Variantes activas de una tienda Shopify con ese SKU (= código BOUN)."""
    tok = db.get_setting("shopify_token::%s" % shop, "")
    if not tok:
        return []
    q = ('query($q:String!){productVariants(first:20,query:$q){edges{node{'
         'id sku inventoryQuantity product{status} inventoryItem{id}}}}}')
    try:
        import requests as _rq
        r = _rq.post("https://%s/admin/api/2025-01/graphql.json" % shop,
                     json={"query": q, "variables": {"q": "sku:%s" % sku}},
                     headers={"X-Shopify-Access-Token": tok}, timeout=15)
        if r.status_code != 200:
            return []
        edges = (((r.json().get("data") or {}).get("productVariants") or {})
                 .get("edges") or [])
        out = []
        for e in edges:
            n = e.get("node") or {}
            if (n.get("product") or {}).get("status") == "ACTIVE":
                out.append({"key": n.get("id"), "ventas": 0,
                            "actual": n.get("inventoryQuantity"),
                            "inv_item": (n.get("inventoryItem") or {}).get("id")})
        return out
    except Exception:
        return []


_SHOP_LOC = {}


def _shopify_location_id(shop: str, tok: str):
    """Primera location activa de la tienda (cacheada). Necesaria para fijar
    inventario con inventorySetQuantities."""
    if shop in _SHOP_LOC:
        return _SHOP_LOC[shop]
    if not tok:
        return None
    q = "query{locations(first:10){edges{node{id name isActive}}}}"
    try:
        import requests as _rq
        r = _rq.post("https://%s/admin/api/2025-01/graphql.json" % shop,
                     json={"query": q},
                     headers={"X-Shopify-Access-Token": tok}, timeout=15)
        if r.status_code != 200:
            return None
        edges = (((r.json().get("data") or {}).get("locations") or {})
                 .get("edges") or [])
        for e in edges:
            n = e.get("node") or {}
            if n.get("isActive"):
                _SHOP_LOC[shop] = n.get("id")
                return _SHOP_LOC[shop]
    except Exception:
        pass
    return None


def _shopify_set_inventory(shop: str, tok: str, inv_item: str, location: str,
                           cantidad: int, actual=None, dry: bool = False,
                           max_delta=None) -> dict:
    """Fija el inventario 'available' (valor ABSOLUTO → idempotente) de un
    inventoryItem en una location, vía inventorySetQuantities. Respeta max_delta."""
    c = int(cantidad)
    if max_delta is not None and actual is not None and abs(c - actual) > max_delta:
        return {"ok": False, "skip": True, "reason": "delta_guard",
                "inv_item": inv_item, "actual": actual, "target": c,
                "max_delta": max_delta}
    if dry:
        return {"ok": True, "dry_run": True, "shop": shop, "inv_item": inv_item,
                "actual": actual, "set": c}
    m = ("mutation($input:InventorySetQuantitiesInput!){"
         "inventorySetQuantities(input:$input){userErrors{field message}}}")
    variables = {"input": {"name": "available", "reason": "correction",
                           "ignoreCompareQuantity": True,
                           "quantities": [{"inventoryItemId": inv_item,
                                           "locationId": location,
                                           "quantity": c}]}}
    try:
        import requests as _rq
        r = _rq.post("https://%s/admin/api/2025-01/graphql.json" % shop,
                     json={"query": m, "variables": variables},
                     headers={"X-Shopify-Access-Token": tok}, timeout=20)
        if r.status_code != 200:
            return {"ok": False, "error": r.text[:200], "http": r.status_code,
                    "inv_item": inv_item}
        data = (r.json().get("data") or {}).get("inventorySetQuantities") or {}
        errs = data.get("userErrors") or []
        if errs:
            return {"ok": False, "error": errs, "inv_item": inv_item}
        return {"ok": True, "shop": shop, "inv_item": inv_item, "actual": actual,
                "set": c}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "inv_item": inv_item}


def _ml_active_pubs(product_id: int) -> tuple:
    """(activas[{key,ventas}], excluidas[]) de ML para un producto (no-Full)."""
    links = db._sb_get("inventory_links?product_id=eq.%d&select=ml_item_id,"
                       "ml_sold60,ml_logistic" % product_id) or []
    activas, excl = [], []
    for l in links:
        iid = l.get("ml_item_id")
        if not iid:
            continue
        r = _ml_request("GET", "/items/%s?attributes=id,status,shipping" % iid)
        st = lg = None
        if r is not None and r.status_code == 200:
            jd = r.json(); st = jd.get("status")
            lg = (jd.get("shipping") or {}).get("logistic_type")
        if lg == "fulfillment":
            excl.append({"item_id": iid, "motivo": "full"})
        elif st != "active":
            excl.append({"item_id": iid, "motivo": st or "?"})
        else:
            activas.append({"key": iid, "ventas": int(l.get("ml_sold60") or 0)})
    return activas, excl


def _compute_plan(codigo: str, disponible: int) -> dict:
    """Reparto del disponible entre publicaciones activas de los 4 canales."""
    import sync as _sync
    out = {}
    prows = db._sb_get("inventory_products?code=eq.%s&select=id"
                       % _q_(codigo)) or []
    pid = prows[0]["id"] if prows else None
    # MercadoLibre
    if pid:
        ml_act, ml_excl = _ml_active_pubs(pid)
        out["mercadolibre"] = {"reparto": _sync.reparto(disponible, ml_act),
                               "excluidas": ml_excl}
    else:
        out["mercadolibre"] = {"reparto": {}, "excluidas": []}
    # Falabella (SKUs del CSV)
    fal = _sync.falabella_skus(codigo)
    out["falabella"] = {"reparto": _sync.reparto(
        disponible, [{"key": f["seller_sku"], "ventas": 0} for f in fal])}
    # Shopify ×2
    for ckey, shop in _SHOPIFY_SHOPS.items():
        vs = _shopify_variants_by_sku(shop, codigo)
        out[ckey] = {"reparto": _sync.reparto(disponible, vs),
                     "variantes": len(vs)}
    return out


def _q_(v):
    import urllib.parse as _u
    return _u.quote(str(v), safe="")


def _pending_cola(codigo: str) -> int:
    rows = db._sb_get("cola_bodega?codigo_boun=eq.%s&estado=eq.pendiente&"
                      "select=cantidad" % _q_(codigo)) or []
    return sum(int(r.get("cantidad") or 0) for r in rows)


def _sync_apply_channels() -> set:
    """Lista blanca de canales habilitados para ESCRITURA real. Separada de
    `sync_enabled` (que solo controla la ingesta de ventas). Vacío = nadie
    escribe → DRY-RUN puro. Ej.: setting `sync_apply_channels='mercadolibre'`.
    Kill-switch = vaciar el setting. Acepta coma o punto y coma."""
    raw = (db.get_setting("sync_apply_channels", "")
           or os.environ.get("SYNC_APPLY_CHANNELS", ""))
    return {c.strip() for c in raw.replace(";", ",").split(",") if c.strip()}


def _sync_apply_max_delta():
    """Tope de salto absoluto por publicación (guardia anti-cálculo-raro).
    setting `sync_apply_max_delta` o env SYNC_APPLY_MAX_DELTA. 0/vacío = sin tope."""
    try:
        v = int(db.get_setting("sync_apply_max_delta", "")
                or os.environ.get("SYNC_APPLY_MAX_DELTA", "") or "0")
        return v if v > 0 else None
    except Exception:
        return None


def _apply_plan(codigo: str, plan: dict, order_id: str = "",
                dry: bool = False, force=None) -> dict:
    """Aplica el plan de reparto SOLO a los canales en la lista blanca
    (`_sync_apply_channels`), o a `force` si se pasa (para previsualizar).

    - Hoy implementa MercadoLibre (escritor probado, valor absoluto =
      idempotente). Falabella/Shopify quedan listos para sumarse después.
    - Cada escritura se audita best-effort en la tabla `sync_aplicacion`
      (si no existe aún, `_sb_post` falla en silencio y no rompe el flujo).
    - `dry=True` calcula y devuelve lo que escribiría, sin enviar nada.
    """
    permitidos = set(force) if force else _sync_apply_channels()
    max_delta = _sync_apply_max_delta()
    out = {"permitidos": sorted(permitidos), "dry": dry, "canales": {}}
    if not permitidos:
        return out  # nadie habilitado → no escribe (DRY-RUN puro)
    # ── MercadoLibre ──────────────────────────────────────────────────────────
    if "mercadolibre" in permitidos:
        ml_res = []
        reparto = (plan.get("mercadolibre", {}) or {}).get("reparto", {}) or {}
        for item_id, cant in reparto.items():
            r = _ml_set_stock_one(str(item_id), int(cant), dry=dry,
                                  max_delta=max_delta)
            ml_res.append(r)
            if not dry:
                _safe(db._sb_post, "sync_aplicacion", {
                    "codigo_boun": codigo, "canal": "mercadolibre",
                    "ref": str(item_id), "order_id": str(order_id),
                    "actual": r.get("actual"), "objetivo": r.get("set"),
                    "ok": bool(r.get("ok")),
                    "detalle": str(r.get("reason") or r.get("error") or "")[:200]})
        out["canales"]["mercadolibre"] = ml_res
    # ── Falabella ─────────────────────────────────────────────────────────────
    # fb.set_stock fija el valor absoluto (ProductUpdate) y _post ya reintenta los
    # 503/429 con backoff. No hay snapshot barato del stock actual → sin delta_guard.
    if "falabella" in permitidos:
        import falabella as fb
        fal_res = []
        reparto = (plan.get("falabella", {}) or {}).get("reparto", {}) or {}
        for sku, cant in reparto.items():
            try:
                if dry:
                    r = {"ok": True, "dry_run": True, "sku": sku, "set": int(cant)}
                else:
                    resp = fb.set_stock(sku, int(cant), dry=False)
                    r = {"ok": True, "sku": sku, "set": int(cant), "respuesta": resp}
            except Exception as e:
                r = {"ok": False, "sku": sku, "set": int(cant),
                     "error": str(e)[:200]}
            fal_res.append(r)
            if not dry:
                _safe(db._sb_post, "sync_aplicacion", {
                    "codigo_boun": codigo, "canal": "falabella", "ref": str(sku),
                    "order_id": str(order_id), "actual": None,
                    "objetivo": int(cant), "ok": bool(r.get("ok")),
                    "detalle": str(r.get("error") or "")[:200]})
        out["canales"]["falabella"] = fal_res
    # ── Shopify (BOUN y/o KAT) ────────────────────────────────────────────────
    for ckey in ("shopify_boun", "shopify_kat"):
        if ckey not in permitidos:
            continue
        shop = _SHOPIFY_SHOPS[ckey]
        tok = db.get_setting("shopify_token::%s" % shop, "")
        loc = _shopify_location_id(shop, tok)
        vmap = {v["key"]: v for v in _shopify_variants_by_sku(shop, codigo)}
        sh_res = []
        reparto = (plan.get(ckey, {}) or {}).get("reparto", {}) or {}
        for vid, cant in reparto.items():
            v = vmap.get(vid) or {}
            inv = v.get("inv_item")
            if not inv or not loc:
                r = {"ok": False, "skip": True,
                     "reason": "sin_inv_item_o_location", "ref": vid}
            else:
                r = _shopify_set_inventory(shop, tok, inv, loc, int(cant),
                                           actual=v.get("actual"), dry=dry,
                                           max_delta=max_delta)
                r["ref"] = vid
            sh_res.append(r)
            if not dry:
                _safe(db._sb_post, "sync_aplicacion", {
                    "codigo_boun": codigo, "canal": ckey, "ref": str(vid),
                    "order_id": str(order_id), "actual": v.get("actual"),
                    "objetivo": int(cant), "ok": bool(r.get("ok")),
                    "detalle": str(r.get("reason") or r.get("error") or "")[:200]})
        out["canales"][ckey] = sh_res
    return out


def _process_sale(canal: str, order_id: str, items: list,
                  payload=None) -> dict:
    """Pipeline (DRY-RUN): idempotencia → descuento central (cola_bodega) →
    recalcula disponible → plan de reparto a los 4 canales. NO escribe en
    los canales. items = [(codigo_boun, cantidad), …]."""
    import datetime as _dt
    ev = db._sb_get("evento_venta?canal=eq.%s&order_id=eq.%s&select=id,estado"
                    % (_q_(canal), _q_(order_id))) or []
    # idempotencia: si ya está procesado o en curso, no volver a descontar
    if ev and ev[0].get("estado") in ("procesado", "procesando"):
        return {"ok": True, "idempotente": True, "canal": canal,
                "order_id": order_id, "estado": ev[0].get("estado")}
    if not ev:
        db._sb_post("evento_venta", {"canal": canal, "order_id": str(order_id),
                                     "estado": "procesando", "payload": payload})
    else:
        db._sb_patch("evento_venta", "canal=eq.%s&order_id=eq.%s"
                     % (_q_(canal), _q_(order_id)), {"estado": "procesando"})
    resultados = []
    for raw in items:
        # items: (codigo, cantidad) o (codigo, cantidad, es_full). es_full=True
        # cuando el canal informa que el envío salió de Full (ML logistic_type
        # =fulfillment); None = desconocido → se decide por stock de bodega.
        codigo, cantidad = raw[0], int(raw[1])
        es_full = raw[2] if len(raw) >= 3 else None
        prows = db._sb_get("inventory_products?code=eq.%s&select=id,code,name,"
                           "qty_bogota,qty_yopal" % _q_(codigo)) or []
        if not prows:
            resultados.append({"codigo": codigo, "skip": True,
                               "motivo": "no_en_inventario_central"})
            continue
        p = prows[0]
        pid = p["id"]
        bog = int(p.get("qty_bogota") or 0)
        yop = int(p.get("qty_yopal") or 0)
        # Registro de la venta (descuento del total). Audita el origen del evento.
        mov = db._sb_post("movimiento_stock", {
            "codigo_boun": codigo, "delta": -cantidad,
            "motivo": "venta_%s%s" % (canal, "_full" if es_full else ""),
            "canal": canal, "order_id": str(order_id)})
        cola = {"movimiento_id": (mov or {}).get("id"), "codigo_boun": codigo,
                "nombre": p.get("name"), "cantidad": cantidad,
                "canal": canal, "order_id": str(order_id)}
        # ── Asignación de bodega ──────────────────────────────────────────────
        if es_full is True:
            # El canal confirma Full: el envío salió de la bodega de ML, no de la
            # nuestra → no descuenta bodega propia.
            cola.update({"estado": "full"})
            db._sb_post("cola_bodega", cola)
            asignado = "full"
        elif bog > 0 and yop > 0:
            # Ambas bodegas con stock → ambiguo, lo confirma una persona.
            cola.update({"estado": "pendiente"})
            db._sb_post("cola_bodega", cola)
            asignado = "pendiente"
        elif bog > 0:
            # Solo Bogotá tiene stock → deducción: salió de ahí.
            bog = max(0, bog - cantidad)
            db._sb_patch("inventory_products", "id=eq.%d" % pid,
                         {"qty_bogota": bog})
            db._sb_post("movimiento_stock", {
                "codigo_boun": codigo, "delta": -cantidad,
                "motivo": "asignacion_bodega_bogota", "canal": canal,
                "order_id": str(order_id)})
            cola.update({"estado": "confirmado", "bodega_asignada": "bogota",
                         "auto": True})
            db._sb_post("cola_bodega", cola)
            asignado = "bogota(auto)"
        elif yop > 0:
            # Solo Yopal tiene stock.
            yop = max(0, yop - cantidad)
            db._sb_patch("inventory_products", "id=eq.%d" % pid,
                         {"qty_yopal": yop})
            db._sb_post("movimiento_stock", {
                "codigo_boun": codigo, "delta": -cantidad,
                "motivo": "asignacion_bodega_yopal", "canal": canal,
                "order_id": str(order_id)})
            cola.update({"estado": "confirmado", "bodega_asignada": "yopal",
                         "auto": True})
            db._sb_post("cola_bodega", cola)
            asignado = "yopal(auto)"
        else:
            # Sin stock en ninguna bodega y el canal NO confirmó Full → puede ser
            # Full (con logística sin marcar) o sobreventa. Lo dejamos pendiente
            # para que una persona lo revise (puede marcarlo Full con el botón).
            cola.update({"estado": "pendiente"})
            db._sb_post("cola_bodega", cola)
            asignado = "pendiente(sin stock)"
        disp = max(0, bog + yop - _pending_cola(codigo))
        plan = _compute_plan(codigo, disp)
        # Propagación a canales: escribe SOLO los canales de la lista blanca
        # (_sync_apply_channels). Si está vacía, sigue siendo DRY-RUN.
        aplicado = _apply_plan(codigo, plan, order_id=order_id)
        resultados.append({"codigo": codigo, "cantidad": cantidad,
                           "es_full": bool(es_full), "bodega": asignado,
                           "disponible_tras_venta": disp,
                           "plan": plan, "aplicado": aplicado})
    db._sb_patch("evento_venta", "canal=eq.%s&order_id=eq.%s"
                 % (_q_(canal), _q_(order_id)),
                 {"estado": "procesado",
                  "procesado_at": _dt.datetime.now(
                      _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return {"ok": True, "dry_run": not bool(_sync_apply_channels()),
            "canal": canal, "order_id": order_id, "resultados": resultados}


def _sync_enabled() -> bool:
    """Interruptor maestro de la ingestión automática (poller + webhooks).
    Apagado por defecto: el motor queda desplegado pero no procesa ventas reales
    hasta activarlo (setting sync_enabled=1). /api/sync/simular siempre funciona."""
    return (db.get_setting("sync_enabled", "") == "1"
            or os.environ.get("SYNC_ENABLED", "") == "1")


def _ml_code_for_item(item_id: str) -> str:
    """código BOUN de una publicación ML (vía inventory_links → product code)."""
    links = db._sb_get("inventory_links?ml_item_id=eq.%s&select=product_id"
                       % _q_(item_id)) or []
    if not links:
        return ""
    p = db._sb_get("inventory_products?id=eq.%d&select=code"
                   % links[0]["product_id"]) or []
    return p[0]["code"] if p else ""


def _ml_item_full(item_id: str) -> bool:
    """¿La publicación ML vendida es Full? Usa el logistic_type guardado en
    inventory_links (=fulfillment). Si no hay dato, asume que NO (la lógica de
    bodega decide)."""
    links = db._sb_get("inventory_links?ml_item_id=eq.%s&select=ml_logistic"
                       % _q_(item_id)) or []
    return bool(links) and (links[0].get("ml_logistic") == "fulfillment")


def _process_async(canal, order_id, items, payload=None):
    threading.Thread(target=lambda: _safe(_process_sale, canal, order_id,
                                          items, payload), daemon=True).start()


def _safe(fn, *a, **k):
    try:
        fn(*a, **k)
    except Exception:
        pass


# ── Webhooks (responden 200 rápido; el pipeline corre en hilo) ───────────────

@app.post("/webhooks/shopify/{tienda}")
async def webhook_shopify(tienda: str, request: Request):
    shop = _SHOPIFY_SHOPS.get("shopify_%s" % tienda)
    if not shop:
        return Response(status_code=404)
    _cid, sec = _shopify_app_creds(shop)
    raw = await request.body()
    given = request.headers.get("x-shopify-hmac-sha256", "")
    calc = base64.b64encode(
        _hmac.new(sec.encode(), raw, _hashlib.sha256).digest()).decode()
    if not (sec and given and _hmac.compare_digest(calc, given)):
        return Response(status_code=401)
    try:
        data = json.loads(raw or b"{}")
        oid = str(data.get("id") or data.get("order_id") or "")
        items = [((li.get("sku") or "").strip(), int(li.get("quantity") or 0))
                 for li in data.get("line_items", [])
                 if (li.get("sku") or "").strip() and li.get("quantity")]
        if oid and items and _sync_enabled():
            _process_async("shopify_%s" % tienda, oid, items,
                           {"webhook": "shopify"})
    except Exception:
        pass
    return Response(status_code=200)


@app.post("/webhooks/mercadolibre")
async def webhook_ml(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    resource = data.get("resource", "") or ""
    # solo órdenes
    if "/orders/" in resource and _sync_enabled():
        oid = resource.rstrip("/").split("/")[-1]

        def _work():
            r = _ml_request("GET", "/orders/%s" % oid)
            if not r or r.status_code != 200:
                return
            agg = {}
            for oi in r.json().get("order_items", []):
                iid = (oi.get("item") or {}).get("id")
                qty = int(oi.get("quantity") or 0)
                code = _ml_code_for_item(iid) if iid else ""
                if code and qty:
                    k = (code, _ml_item_full(iid))
                    agg[k] = agg.get(k, 0) + qty
            items = [(c, q, f) for (c, f), q in agg.items()]
            if items:
                _safe(_process_sale, "ml", oid, items, {"webhook": "ml"})
        threading.Thread(target=_work, daemon=True).start()
    return Response(status_code=200)


# ── Poller Falabella (cada SYNC_FALABELLA_POLL_SEC) ──────────────────────────

def _falabella_poll_once():
    """Procesa SOLO órdenes Falabella nuevas (posteriores al watermark), para no
    reprocesar ventas históricas ya manejadas a mano. Avanza el watermark."""
    import falabella as fb
    import sync as _sync
    if not _sync_enabled() or not fb.is_connected():
        return
    co = timezone(timedelta(hours=-5))
    wm = db.get_setting("sync_falabella_since", "")
    if not wm:
        # primera activación: marca "desde ahora", no reprocesa el histórico
        db.set_setting("sync_falabella_since",
                       datetime.now(co).strftime("%Y-%m-%d %H:%M:%S"))
        return
    try:
        since_dt = (datetime.strptime(wm, "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=co) - timedelta(days=1))
    except Exception:
        since_dt = datetime.now(co) - timedelta(days=1)
    orders = fb.get_orders(since_dt.isoformat())
    nuevas = [o for o in orders if (o.get("CreatedAt", "") > wm)
              and o.get("OrderId")]
    if not nuevas:
        return
    items_map = fb._items_by_order([str(o["OrderId"]) for o in nuevas])
    newest = wm
    for o in nuevas:
        oid = str(o["OrderId"]); ca = o.get("CreatedAt", "")
        newest = max(newest, ca)
        ev = db._sb_get("evento_venta?canal=eq.falabella&order_id=eq.%s&"
                        "select=estado" % _q_(oid)) or []
        if ev and ev[0].get("estado") == "procesado":
            continue
        agg = {}
        for nm, sku in items_map.get(oid, []):
            code = _sync.FAL_SKU_TO_BOUN.get(sku)
            if code:
                agg[code] = agg.get(code, 0) + 1
        if agg:
            _safe(_process_sale, "falabella", oid, list(agg.items()),
                  {"poller": "falabella", "created": ca})
    if newest > wm:
        db.set_setting("sync_falabella_since", newest)


def _falabella_poller():
    sec = int(os.environ.get("SYNC_FALABELLA_POLL_SEC", "180") or 180)
    while True:
        _safe(_falabella_poll_once)
        time.sleep(max(60, sec))


def _ml_poll_once():
    """Procesa SOLO órdenes ML nuevas (posteriores al watermark). Reemplaza al
    webhook (que requiere configurar callback tras 2FA en el panel ML)."""
    import sync as _sync
    if not _sync_enabled():
        return
    from ml_scraper import _ml_session_auth, ML_API
    s, uid = _ml_session_auth()
    if not s:
        return
    co = timezone(timedelta(hours=-5))
    fmt = "%Y-%m-%dT%H:%M:%S.000-05:00"
    wm = db.get_setting("sync_ml_since", "")
    if not wm:
        db.set_setting("sync_ml_since", datetime.now(co).strftime(fmt))
        return
    try:
        base = (datetime.strptime(wm[:19], "%Y-%m-%dT%H:%M:%S")
                .replace(tzinfo=co) - timedelta(hours=2))
    except Exception:
        base = datetime.now(co) - timedelta(hours=2)
    since = base.strftime(fmt)
    until = datetime.now(co).strftime(fmt)
    newest = wm
    offset = 0
    while True:
        r = s.get("%s/orders/search?seller=%s&order.date_created.from=%s"
                  "&order.date_created.to=%s&sort=date_desc&limit=50&offset=%d"
                  % (ML_API, uid, since, until, offset), timeout=20)
        if r.status_code != 200:
            break
        d = r.json()
        results = d.get("results", [])
        for od in results:
            dc = od.get("date_created", "")
            if dc <= wm:
                continue
            newest = max(newest, dc)
            oid = str(od.get("id"))
            ev = db._sb_get("evento_venta?canal=eq.ml&order_id=eq.%s&"
                            "select=estado" % _q_(oid)) or []
            if ev and ev[0].get("estado") in ("procesado", "procesando"):
                continue
            agg = {}
            for oi in od.get("order_items", []):
                iid = (oi.get("item") or {}).get("id")
                qty = int(oi.get("quantity") or 0)
                code = _ml_code_for_item(iid) if iid else ""
                if code and qty:
                    k = (code, _ml_item_full(iid))
                    agg[k] = agg.get(k, 0) + qty
            if agg:
                items = [(c, q, f) for (c, f), q in agg.items()]
                _safe(_process_sale, "ml", oid, items,
                      {"poller": "ml", "created": dc})
        total = d.get("paging", {}).get("total", 0)
        offset += 50
        if offset >= total or not results:
            break
    if newest > wm:
        db.set_setting("sync_ml_since", newest)


def _poller_loop():
    sec = int(os.environ.get("SYNC_FALABELLA_POLL_SEC", "180") or 180)
    sec = max(60, sec)
    while True:
        _safe(_falabella_poll_once)
        _safe(_ml_poll_once)
        time.sleep(sec)


@app.on_event("startup")
def _start_poller():
    threading.Thread(target=_poller_loop, daemon=True).start()


@app.get("/api/sync/simular")
def sync_simular(key: str = "", canal: str = "test", order_id: str = "",
                 codigo: str = "", cantidad: int = 1, full: str = ""):
    """Simula una venta y corre el pipeline (DRY-RUN) para probar end-to-end.
    full=1 marca la venta como Full (no descuenta bodega)."""
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)
    if not codigo or not order_id:
        return JSONResponse({"error": "bad_request",
                             "hint": "codigo y order_id requeridos"},
                            status_code=400, headers=_EXPORT_CORS)
    try:
        es_full = True if full == "1" else None
        res = _process_sale(canal, order_id,
                            [(codigo, int(cantidad), es_full)],
                            payload={"simulado": True})
        return JSONResponse(res, headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502,
                            headers=_EXPORT_CORS)


# ── Motor de sincronización — PREVIEW de escritura (no envía nada) ────────────

@app.options("/api/sync/apply-preview")
def sync_apply_preview_preflight():
    return Response(status_code=204, headers=_EXPORT_CORS)


@app.get("/api/sync/apply-preview")
def sync_apply_preview(key: str = "", codigo: str = "", vendidos: int = 0,
                       canal: str = "mercadolibre"):
    """Muestra EXACTAMENTE lo que el motor escribiría en un canal para `codigo`
    (snapshot actual → objetivo por publicación), SIN enviar nada. Úsalo antes de
    poblar `sync_apply_channels`. Por defecto previsualiza MercadoLibre."""
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)
    if not codigo:
        return JSONResponse({"error": "bad_request"}, status_code=400,
                            headers=_EXPORT_CORS)
    try:
        prows = db._sb_get("inventory_products?code=eq.%s&select=qty_bogota,"
                           "qty_yopal" % _q_(codigo)) or []
        if not prows:
            return JSONResponse({"error": "codigo_no_encontrado",
                                 "codigo": codigo}, status_code=404,
                                headers=_EXPORT_CORS)
        bog = int(prows[0].get("qty_bogota") or 0)
        yop = int(prows[0].get("qty_yopal") or 0)
        disp = max(0, bog + yop - _pending_cola(codigo) - int(vendidos or 0))
        plan = _compute_plan(codigo, disp)
        prev = _apply_plan(codigo, plan, dry=True, force={canal})
        return JSONResponse({"ok": True, "codigo": codigo, "disponible": disp,
                             "plan": plan, "preview": prev,
                             "nota": "dry-run: no se escribió nada"},
                            headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502,
                            headers=_EXPORT_CORS)


# ── Motor de sincronización — PLAN en DRY-RUN (no escribe en ningún canal) ────

@app.options("/api/sync/plan")
def sync_plan_preflight():
    return Response(status_code=204, headers=_EXPORT_CORS)


@app.get("/api/sync/plan")
def sync_plan(key: str = "", codigo: str = "", vendidos: int = 0):
    """Calcula el disponible de un código BOUN y cómo se repartiría entre las
    publicaciones activas de cada canal, simulando una venta de `vendidos`.
    NO escribe nada. Sirve para validar la lógica antes de activar la propagación.
    """
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)
    if not codigo:
        return JSONResponse({"error": "bad_request"}, status_code=400,
                            headers=_EXPORT_CORS)
    try:
        from urllib.parse import quote as _q
        import sync as _sync
        prows = db._sb_get(
            "inventory_products?code=eq.%s&select=id,code,name,qty_bogota,"
            "qty_yopal,qty_transit" % _q(codigo, safe="")) or []
        if not prows:
            return JSONResponse({"error": "codigo_no_encontrado",
                                 "codigo": codigo}, status_code=404,
                                headers=_EXPORT_CORS)
        p = prows[0]
        bog = int(p.get("qty_bogota") or 0)
        yop = int(p.get("qty_yopal") or 0)
        disponible = max(0, bog + yop - int(vendidos or 0))

        # ── MercadoLibre: publicaciones activas no-Full del código ──
        links = db._sb_get(
            "inventory_links?product_id=eq.%d&select=ml_item_id,ml_sold60,"
            "ml_logistic" % p["id"]) or []
        ml_pubs, ml_excluidas = [], []
        for l in links:
            iid = l.get("ml_item_id")
            if not iid:
                continue
            r = _ml_request("GET", "/items/%s?attributes=id,status,shipping"
                                   % iid)
            st = lg = None
            if r is not None and r.status_code == 200:
                jd = r.json(); st = jd.get("status")
                lg = (jd.get("shipping") or {}).get("logistic_type")
            if lg == "fulfillment":
                ml_excluidas.append({"item_id": iid, "motivo": "full"})
            elif st != "active":
                ml_excluidas.append({"item_id": iid, "motivo": st or "?"})
            else:
                ml_pubs.append({"key": iid,
                                "ventas": int(l.get("ml_sold60") or 0)})
        ml_reparto = _sync.reparto(disponible, ml_pubs)

        # ── Falabella: SKUs mapeados del código (desde el CSV) ──
        fal = _sync.falabella_skus(codigo)
        fal_pubs = [{"key": f["seller_sku"], "ventas": 0} for f in fal]
        fal_reparto = _sync.reparto(disponible, fal_pubs)

        out = {
            "codigo": codigo, "producto": p.get("name"),
            "stock": {"bogota": bog, "yopal": yop,
                      "transit": int(p.get("qty_transit") or 0)},
            "vendidos_simulado": int(vendidos or 0),
            "disponible_vendible": disponible,
            "canales": {
                "mercadolibre": {"activas": list(ml_reparto.keys()),
                                 "reparto": ml_reparto,
                                 "excluidas": ml_excluidas},
                "falabella": {"skus": [f["seller_sku"] for f in fal],
                              "reparto": fal_reparto,
                              "mapeado_en_csv": bool(fal)},
                "shopify_boun": {"pendiente": "credenciales_tienda"},
                "shopify_kat": {"pendiente": "credenciales_tienda"},
            },
            "dry_run": True,
            "nota": "Cálculo sin escribir en canales (Fase 1).",
        }
        return JSONResponse(out, headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502,
                            headers=_EXPORT_CORS)


# ── Pendientes de bodega (¿de qué bodega salió cada venta?) ──────────────────
# El disponible TOTAL ya se descontó en la venta; esto solo cuadra de cuál
# bodega salió. Los casos de una sola bodega con stock se auto-asignan en el
# motor; aquí quedan únicamente los ambiguos (ambas bodegas con stock).

class ConfirmBodegaIn(BaseModel):
    bodega: str


def _stock_map(codigos: list) -> dict:
    """{codigo: {name, qty_bogota, qty_yopal, img}} para una lista de códigos.
    La foto sale del thumb de ML (inventory_links.ml_thumb, subido a alta
    resolución) y, si no hay, de image_path cuando es una URL pública."""
    out = {}
    cods = [c for c in dict.fromkeys(codigos) if c]
    if not cods:
        return out
    # Una consulta por código con filtro code=eq.<código> (patrón probado del
    # motor). OJO: inventory_products NO tiene image_path → pedirla rompía TODO
    # el select (400). La foto sale de inventory_links.ml_thumb.
    for c in cods:
        rows = db._sb_get("inventory_products?code=eq.%s&select=id,code,name,"
                          "qty_bogota,qty_yopal&limit=1" % _q_(c)) or []
        if not rows:
            continue
        r = rows[0]
        img = ""
        links = db._sb_get("inventory_links?product_id=eq.%d&select=ml_thumb"
                           "&limit=10" % r.get("id")) or []
        for l in links:
            thumb = l.get("ml_thumb") or ""
            if thumb:
                img = _img_full(thumb)
                break
        out[c] = {"name": r.get("name"),
                  "qty_bogota": int(r.get("qty_bogota") or 0),
                  "qty_yopal": int(r.get("qty_yopal") or 0),
                  "img": img}
    return out


@app.get("/api/cola-bodega")
def cola_bodega_list(user: dict = Depends(_current_user)):
    rows = db._sb_get("cola_bodega?estado=eq.pendiente&select=id,codigo_boun,"
                      "nombre,cantidad,canal,order_id,created_at&"
                      "order=created_at.asc") or []
    sm = _stock_map([r.get("codigo_boun") for r in rows])
    out = []
    for r in rows:
        s = sm.get(r.get("codigo_boun"), {})
        out.append({
            "id": r.get("id"), "codigo_boun": r.get("codigo_boun"),
            "nombre": r.get("nombre") or s.get("name") or "",
            "cantidad": int(r.get("cantidad") or 0), "canal": r.get("canal"),
            "order_id": r.get("order_id"), "created_at": r.get("created_at"),
            "img": s.get("img", ""),
            "stock_bogota": s.get("qty_bogota", 0),
            "stock_yopal": s.get("qty_yopal", 0)})
    return {"pendientes": out, "total": len(out)}


@app.get("/api/cola-bodega/count")
def cola_bodega_count(user: dict = Depends(_current_user)):
    rows = db._sb_get("cola_bodega?estado=eq.pendiente&select=id") or []
    return {"count": len(rows)}


@app.post("/api/cola-bodega/{cid}/confirmar")
def cola_bodega_confirmar(cid: int, data: ConfirmBodegaIn,
                          user: dict = Depends(_current_user)):
    bodega = (data.bodega or "").strip().lower()
    if bodega not in ("bogota", "yopal"):
        raise HTTPException(400, "bodega debe ser 'bogota' o 'yopal'")
    rows = db._sb_get("cola_bodega?id=eq.%d&select=id,codigo_boun,cantidad,"
                      "estado,canal,order_id" % cid) or []
    if not rows:
        raise HTTPException(404, "Pendiente no encontrado")
    c = rows[0]
    if c.get("estado") != "pendiente":
        raise HTTPException(409, "Ese pendiente ya fue procesado")
    prows = db._sb_get("inventory_products?code=eq.%s&select=id,name,qty_bogota,"
                       "qty_yopal" % _q_(c["codigo_boun"])) or []
    if not prows:
        raise HTTPException(404, "Producto no está en el inventario central")
    p = prows[0]
    col = "qty_bogota" if bodega == "bogota" else "qty_yopal"
    actual = int(p.get(col) or 0)
    cant = int(c.get("cantidad") or 0)
    if actual < cant:
        nb = "Bogotá" if bodega == "bogota" else "Yopal"
        otra = "Yopal" if bodega == "bogota" else "Bogotá"
        raise HTTPException(400, "%s solo tiene %d; ¿salió de %s?"
                            % (nb, actual, otra))
    nuevo = actual - cant
    db._sb_patch("inventory_products", "id=eq.%d" % p["id"], {col: nuevo})
    db._sb_post("movimiento_stock", {
        "codigo_boun": c["codigo_boun"], "delta": -cant,
        "motivo": "asignacion_bodega_%s" % bodega, "canal": c.get("canal"),
        "order_id": c.get("order_id")})
    db._sb_patch("cola_bodega", "id=eq.%d" % cid, {
        "estado": "confirmado", "bodega_asignada": bodega,
        "confirmado_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")})
    return {"ok": True, "id": cid, "bodega": bodega, "saldo_nuevo": nuevo}


@app.post("/api/cola-bodega/{cid}/full")
def cola_bodega_full(cid: int, user: dict = Depends(_current_user)):
    rows = db._sb_get("cola_bodega?id=eq.%d&select=id,estado" % cid) or []
    if not rows:
        raise HTTPException(404, "Pendiente no encontrado")
    if rows[0].get("estado") != "pendiente":
        raise HTTPException(409, "Ese pendiente ya fue procesado")
    db._sb_patch("cola_bodega", "id=eq.%d" % cid, {
        "estado": "full", "confirmado_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")})
    return {"ok": True, "id": cid, "estado": "full"}


# ── Shopify OAuth (captura del Admin API token de cada tienda) ───────────────
# Instala la app "BOUN Sync Stock" en una tienda y guarda su token en Supabase
# (app_settings), sin que nadie tenga que copiar el token a mano.

_SHOP_SCOPES = ("read_products,write_products,read_inventory,write_inventory,"
                "read_orders,read_locations")
_SHOP_REDIRECT = "https://boun-web-deploy.onrender.com/shopify/callback"


def _shopify_app_creds(shop: str = ""):
    """Credenciales de la app Shopify. Por-tienda (shopify_api_key::{shop}) si
    existen, si no las globales (la app de BOUN). KAT está en otra organización
    y usa su propia app (creds por-tienda)."""
    cid = db.get_setting("shopify_api_key::%s" % shop, "") if shop else ""
    sec = db.get_setting("shopify_api_secret::%s" % shop, "") if shop else ""
    if not cid:
        cid = (db.get_setting("shopify_api_key", "")
               or os.environ.get("SHOPIFY_API_KEY", ""))
    if not sec:
        sec = (db.get_setting("shopify_api_secret", "")
               or os.environ.get("SHOPIFY_API_SECRET", ""))
    return cid, sec


@app.get("/shopify/install")
def shopify_install(shop: str = "", key: str = ""):
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    shop = (shop or "").strip()
    cid, _sec = _shopify_app_creds(shop)
    if not cid:
        return JSONResponse({"error": "missing_shopify_api_key"},
                            status_code=500)
    if not shop.endswith(".myshopify.com"):
        return JSONResponse({"error": "bad_shop",
                             "hint": "usa el dominio .myshopify.com"},
                            status_code=400)
    import urllib.parse as _u
    url = ("https://%s/admin/oauth/authorize?client_id=%s&scope=%s"
           "&redirect_uri=%s&state=boun" % (
               shop, cid, _SHOP_SCOPES, _u.quote(_SHOP_REDIRECT, safe="")))
    return RedirectResponse(url)


@app.get("/shopify/callback")
async def shopify_callback(request: Request):
    params = dict(request.query_params)
    shop = params.get("shop", "")
    code = params.get("code", "")
    cid, sec = _shopify_app_creds(shop)
    given_hmac = params.get("hmac", "")
    if not (cid and sec and shop and code):
        return HTMLResponse("<h3>Falta configuración o parámetros.</h3>",
                            status_code=400)
    # Verificar HMAC del callback
    msg = "&".join("%s=%s" % (k, params[k]) for k in sorted(params)
                   if k not in ("hmac", "signature"))
    calc = _hmac.new(sec.encode(), msg.encode(), _hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(calc, given_hmac):
        return HTMLResponse("<h3>HMAC inválido.</h3>", status_code=401)
    # Intercambiar code por access_token
    try:
        import requests as _rq
        r = _rq.post("https://%s/admin/oauth/access_token" % shop,
                     json={"client_id": cid, "client_secret": sec,
                           "code": code}, timeout=20)
        if r.status_code != 200:
            return HTMLResponse("<h3>Error al obtener token: %s</h3>"
                                % r.text[:200], status_code=502)
        tok = r.json().get("access_token", "")
        db.set_setting("shopify_token::%s" % shop, tok)
        # Guardar también el location principal
        try:
            lr = _rq.get("https://%s/admin/api/2025-01/locations.json" % shop,
                         headers={"X-Shopify-Access-Token": tok}, timeout=15)
            locs = lr.json().get("locations", []) if lr.status_code == 200 else []
            if locs:
                db.set_setting("shopify_location::%s" % shop,
                               str(locs[0].get("id")))
        except Exception:
            pass
        return HTMLResponse(
            "<h2>✅ Tienda conectada: %s</h2>"
            "<p>El token quedó guardado de forma segura. Ya puedes cerrar "
            "esta pestaña.</p>" % shop)
    except Exception as e:
        return HTMLResponse("<h3>Error: %s</h3>" % str(e)[:200],
                            status_code=502)


@app.get("/shopify/status")
def shopify_status(key: str = ""):
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers=_EXPORT_CORS)
    rows = db._sb_get("app_settings?key=like.shopify_*&select=key,value") or []
    out = {}
    for r in rows:
        k = r.get("key", "")
        out[k] = "***" if ("token" in k or "secret" in k) else r.get("value")
    return JSONResponse({"configurado": out}, headers=_EXPORT_CORS)


# ── Frontend estático ────────────────────────────────────────────────────────

_FRONT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


@app.get("/")
def index():
    return FileResponse(os.path.join(_FRONT, "index.html"))


app.mount("/", StaticFiles(directory=_FRONT), name="static")
