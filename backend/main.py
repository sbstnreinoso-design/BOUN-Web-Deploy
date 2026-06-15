"""
BOUN Web — backend FastAPI.
Reutiliza la misma lógica de la app de escritorio (database.py, ml_scraper,
ml_fees, scoring) y los mismos datos en Supabase. Expone una API REST y
sirve el frontend carbón.
"""
import os
import time
import threading
import secrets
from datetime import datetime, timezone
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
            top = sorted(x.pop("_prod").items(),
                         key=lambda y: -y[1]["unidades"])[:3]
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


_SALES_CACHE = {}        # days -> {"ts": epoch, "data": ...}
_SALES_TTL = 10 * 60


def _build_sales(days: int, date_from: str = None, date_to: str = None) -> dict:
    ml = _ml_daily_sales(days, date_from, date_to)
    try:
        import falabella as fb
        fa = fb.daily_sales(days, date_from, date_to)
    except Exception as e:
        fa = {"ok": False, "error": "Falabella: %s" % str(e)[:120]}
    combo = {}

    _empty = lambda: {"ordenes": 0, "unidades": 0, "ingresos": 0,
                      "roas": None, "acos": None, "top": []}

    def _add(src, key):
        if src.get("ok"):
            for d in src.get("dias", []):
                b = combo.setdefault(d["fecha"], {
                    "fecha": d["fecha"], "ml": _empty(),
                    "falabella": _empty()})
                b[key] = {"ordenes": d["ordenes"], "unidades": d["unidades"],
                          "ingresos": d["ingresos"], "roas": d.get("roas"),
                          "acos": d.get("acos"), "top": d.get("top", [])}
    _add(ml, "ml")
    _add(fa, "falabella")
    dias = []
    for f in sorted(combo):
        b = combo[f]
        b["total"] = {
            "ordenes": b["ml"]["ordenes"] + b["falabella"]["ordenes"],
            "unidades": b["ml"]["unidades"] + b["falabella"]["unidades"],
            "ingresos": round(b["ml"]["ingresos"] + b["falabella"]["ingresos"], 2)}
        dias.append(b)
    return {"ok": True, "days": days, "dias": dias,
            "date_from": date_from or "", "date_to": date_to or "",
            "ml_ok": bool(ml.get("ok")), "ml_error": ml.get("error", ""),
            "fal_ok": bool(fa.get("ok")), "fal_error": fa.get("error", "")}


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
    try:
        r = _ml_request(
            "GET", "/items/%s?attributes=id,status,available_quantity,"
                   "variations,shipping" % item_id)
        if r is None:
            return JSONResponse({"ok": False, "error": "ml_not_connected"},
                                status_code=502, headers=_EXPORT_CORS)
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:300],
                                 "ml_status": r.status_code}, status_code=502,
                                headers=_EXPORT_CORS)
        item = r.json()
        status = item.get("status")
        logistic = (item.get("shipping") or {}).get("logistic_type")
        variations = item.get("variations") or []
        # Guardrails: no tocar Full, ni cerradas, ni (en v1) variaciones.
        if logistic == "fulfillment":
            return JSONResponse({"ok": False, "skip": True, "reason": "full",
                                 "item_id": item_id}, headers=_EXPORT_CORS)
        if status == "closed":
            return JSONResponse({"ok": False, "skip": True, "reason": "closed",
                                 "item_id": item_id}, headers=_EXPORT_CORS)
        if variations:
            return JSONResponse(
                {"ok": False, "skip": True, "reason": "variations",
                 "item_id": item_id,
                 "detalle": "requiere reparto por variación (fase 2)"},
                headers=_EXPORT_CORS)
        body = {"available_quantity": c}
        if dry == "1":
            return JSONResponse({"ok": True, "item_id": item_id, "cantidad": c,
                                 "status": status, "logistic": logistic,
                                 "dry_run": True, "body": body},
                                headers=_EXPORT_CORS)
        pr = _ml_request("PUT", "/items/%s" % item_id, json_body=body)
        if pr is None:
            return JSONResponse({"ok": False, "error": "ml_not_connected"},
                                status_code=502, headers=_EXPORT_CORS)
        if pr.status_code in (200, 201):
            return JSONResponse({"ok": True, "item_id": item_id, "cantidad": c,
                                 "ml_status": pr.status_code},
                                headers=_EXPORT_CORS)
        try:
            err = pr.json()
        except Exception:
            err = pr.text[:500]
        return JSONResponse({"ok": False, "error": err,
                             "ml_status": pr.status_code}, status_code=502,
                            headers=_EXPORT_CORS)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]},
                            status_code=502, headers=_EXPORT_CORS)


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


# ── Shopify OAuth (captura del Admin API token de cada tienda) ───────────────
# Instala la app "BOUN Sync Stock" en una tienda y guarda su token en Supabase
# (app_settings), sin que nadie tenga que copiar el token a mano.

_SHOP_SCOPES = ("read_products,write_products,read_inventory,write_inventory,"
                "read_orders,read_locations")
_SHOP_REDIRECT = "https://boun-web-deploy.onrender.com/shopify/callback"


def _shopify_app_creds():
    cid = (db.get_setting("shopify_api_key", "")
           or os.environ.get("SHOPIFY_API_KEY", ""))
    sec = (db.get_setting("shopify_api_secret", "")
           or os.environ.get("SHOPIFY_API_SECRET", ""))
    return cid, sec


@app.get("/shopify/install")
def shopify_install(shop: str = "", key: str = ""):
    token = os.environ.get("BOUN_EXPORT_TOKEN", "")
    if not token or key != token:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cid, _sec = _shopify_app_creds()
    if not cid:
        return JSONResponse({"error": "missing_shopify_api_key"},
                            status_code=500)
    shop = (shop or "").strip()
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
    cid, sec = _shopify_app_creds()
    params = dict(request.query_params)
    shop = params.get("shop", "")
    code = params.get("code", "")
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
