"""
BOUN Web — Sección DROPSHIPPING.

Productos que NO están en las bodegas de BOUN: los tiene un proveedor externo
(hoy Derocha Store, que los consigue en el catálogo de Dropi) y él mismo los
entrega — por Mercado Envíos Flex (mensajería Derocha Express, tarifa por zona)
o llevándolos a una agencia de MercadoLibre (sin costo para BOUN).

Qué resuelve este módulo
  • Inventario del proveedor: stock leído de Dropi (token de integración) o
    cargado a mano, con un colchón de seguridad (10 % por defecto, mínimo 1 u.)
    porque el proveedor también le vende a otros. Lo PUBLICABLE es lo que el
    motor de stock reparte entre las publicaciones (ML BOUN, ML KAT, Shopify).
  • Ventas y liquidación: lee las órdenes de MercadoLibre (BOUN y KAT) de las
    publicaciones dropshipping, decide si el envío fue Flex (suma la tarifa de
    Derocha Express según la zona de entrega) o agencia ($0), y lleva el saldo
    que se le debe al proveedor menos los pagos registrados.
  • Ganadores: unidades 30 días, margen neto y reclamos por calidad → marca los
    productos que conviene traer y vender desde la bodega Bogotá; "migrar" saca
    el producto del dropshipping y el motor vuelve a usar las bodegas propias.

Persistencia sin migraciones SQL (igual que Envíos Flex): JSON en app_settings
    ds_productos   lista de productos dropshipping
    ds_ventas      {clave: venta}   clave = "acct|order_id|item_id"
    ds_pagos       lista de pagos al proveedor
    ds_cfg         configuración (proveedor, colchón, umbrales, base Dropi…)
    ds_tarifas     tarifas Flex por zona del proveedor
    ds_sync        estado de la última sincronización
    dropi_token    token de integración de Dropi (NUNCA se devuelve al cliente)

Cada producto dropshipping existe también en inventory_products con su código
(DS-…) para que el Mapeo y el motor de stock funcionen igual que con el resto;
el motor consulta `disp_for(codigo)` para saber cuánto publicar.
"""
import json
import math
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import database as db

TZ = timezone(timedelta(hours=-5))

K_PROD, K_VENTAS, K_PAGOS = "ds_productos", "ds_ventas", "ds_pagos"
K_CFG, K_TAR, K_SYNC, K_TOKEN = "ds_cfg", "ds_tarifas", "ds_sync", "dropi_token"

DEF_CFG = {
    "proveedor": "Derocha Store",
    "colchon_pct": 10,          # % del stock del proveedor que NO se publica
    "colchon_min": 1,           # mínimo de unidades reservadas
    "desde": "2026-10-15",      # inicio del dropshipping (lectura de ventas)
    "ganador_ventas30": 15,     # unidades en 30 días para ser ganador
    "ganador_margen_pct": 20,   # margen neto mínimo (%) para ser ganador
    "dropi_base": "https://api.dropi.co",
    "sync_min": 15,             # cada cuánto se relee Dropi (min) si hay token
}

# Tarifas Derocha Express (Flex). Las zonas específicas se evalúan ANTES que
# Bogotá (Usme es una localidad de Bogotá con tarifa propia).
DEF_TARIFAS = [
    {"zona": "Usme", "tarifa": 11000, "claves": ["usme"]},
    {"zona": "Soacha", "tarifa": 12000, "claves": ["soacha"]},
    {"zona": "Chía · Cajicá · Cota · Funza · Mosquera", "tarifa": 16000,
     "claves": ["chia", "cajica", "cota", "funza", "mosquera"]},
    {"zona": "Madrid", "tarifa": 18000, "claves": ["madrid"]},
    {"zona": "Bogotá", "tarifa": 8900, "claves": ["bogota"]},
]

# Catálogo inicial (hoja "PRODUCTOS DEROCHA DROPSHIPPING" + lectura de Dropi
# del 7-nov-2026). Solo se usa la primera vez que se abre la sección.
_SEED_TS = "2026-11-07T16:00:00-05:00"
SEED_PRODUCTS = [
    ("DS-SECADOR-MASCOTA", "Secador de pelo para mascotas 2 en 1", 32000,
     330523, "Tecnología Y Más", 775, "MCO4618989724"),
    ("DS-ALM-PIERNAS", "Almohada ortopédica piernas y rodillas", 26900,
     1866621, "Wopi Bodega", 100, "MCO2325507701"),
    ("DS-COJIN-GEL", "Cojín ortopédico de silicona gel para silla", 30000,
     None, "", None, "MCO4598046416"),
    ("DS-COJIN-COLUMNA", "Cojín almohada ortopédica dolor de columna", 34000,
     1220664, "Wopi Bodega", 203, "MCO4585574930"),
    ("DS-FUENTE-FLOR-2L", "Bebedero fuente de agua flor 2 L", 34600,
     2119780, "Wopi Bodega", 93, "MCO4582434408"),
    ("DS-FUENTE-25L", "Bebedero fuente de agua 2,5 L · 2 filtros", 47000,
     2104711, "Wopi Bodega", 100, "MCO4582425654"),
    ("DS-ALM-ESTIRAMIENTO", "Almohada estiramiento de espalda", 30000,
     1324337, "Wopi Bodega", 147, "MCO4587988670"),
    ("DS-ALM-CERVICAL-GEO", "Almohada cervical geométrica", 22000,
     1975653, "Wopi Bodega", 1305, "MCO4598061774"),
    ("DS-ALM-VISCO", "Almohada ortopédica viscoelástica", 45000,
     1710097, "Wopi Bodega", 105, "MCO2339174565"),
]

_LOCK = threading.RLock()
_SYNC_LOCK = threading.Lock()
_DISP_CACHE = {"ts": 0.0, "map": {}}
_ITEMS_CACHE = {"ts": 0.0, "set": set()}
_UID = {}           # acct → seller id de ML
_HOOKS = {"ml_request": None, "propagate": None}


# ── Utilidades ───────────────────────────────────────────────────────────────

def _now():
    return datetime.now(TZ)


def _iso(dt=None):
    return (dt or _now()).strftime("%Y-%m-%dT%H:%M:%S%z")


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore")
    return s.decode().lower().strip()


def _get(key, default):
    raw = db.get_setting(key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _put(key, value):
    db.set_setting(key, json.dumps(value, ensure_ascii=False))


def _int(x, d=0):
    try:
        return int(round(float(x)))
    except Exception:
        return d


def get_cfg() -> dict:
    c = dict(DEF_CFG)
    c.update(_get(K_CFG, {}) or {})
    return c


def get_tarifas() -> list:
    t = _get(K_TAR, None)
    return t if isinstance(t, list) and t else [dict(x) for x in DEF_TARIFAS]


def get_productos() -> list:
    with _LOCK:
        prods = _get(K_PROD, None)
        if prods is None:
            prods = [{
                "sku": sku, "nombre": nom, "costo": costo,
                "dropi_id": did, "proveedor_dropi": prov,
                "link_dropi": ("https://app.dropi.co/dashboard/product-details/%s/x"
                               % did) if did else "",
                "stock_proveedor": st, "stock_ts": _SEED_TS if st is not None else "",
                "stock_fuente": "manual" if st is not None else "",
                "stock_error": "" if did else "Falta el link del producto en Dropi",
                "colchon_pct": None, "estado": "activo",
                "ml_items": [{"acct": "boun", "item_id": mco}],
                "reclamos_calidad": 0, "notas": "",
                "creado": _SEED_TS, "costos_hist": [],
            } for sku, nom, costo, did, prov, st, mco in SEED_PRODUCTS]
            _put(K_PROD, prods)
        return prods


def _save_productos(prods):
    with _LOCK:
        _put(K_PROD, prods)
    _DISP_CACHE["ts"] = 0.0
    _ITEMS_CACHE["ts"] = 0.0


def _find(prods, sku):
    sku = (sku or "").strip().upper()
    for p in prods:
        if (p.get("sku") or "").upper() == sku:
            return p
    return None


def publicable(p: dict, cfg: dict = None) -> int:
    """Unidades que se pueden publicar: stock del proveedor menos el colchón
    (pct con mínimo de unidades). 0 si el producto no está activo o no hay
    lectura de stock."""
    cfg = cfg or get_cfg()
    if p.get("estado") != "activo":
        return 0
    st = p.get("stock_proveedor")
    if st is None:
        return 0
    st = max(0, _int(st))
    pct = p.get("colchon_pct")
    pct = float(cfg.get("colchon_pct", 10) if pct in (None, "") else pct)
    reserva = max(int(math.ceil(st * pct / 100.0)), _int(cfg.get("colchon_min", 1)))
    return max(0, st - reserva)


def disp_for(codigo: str):
    """Para el motor de stock: disponible de un código dropshipping, o None si
    el código no es dropshipping (o ya migró a bodega propia)."""
    now = time.time()
    if now - _DISP_CACHE["ts"] > 30:
        try:
            cfg = get_cfg()
            m = {}
            for p in get_productos():
                if p.get("estado") in ("activo", "pausado"):
                    m[(p.get("sku") or "").upper()] = publicable(p, cfg)
            _DISP_CACHE.update({"ts": now, "map": m})
        except Exception:
            pass
    return _DISP_CACHE["map"].get((codigo or "").strip().upper())


def is_ds_item(item_id: str = "", seller_sku: str = "") -> bool:
    """¿La publicación/SKU de una orden es dropshipping? (para excluirla de la
    cuenta de Unilogix: esos envíos Flex los entrega el proveedor)."""
    if (seller_sku or "").strip().upper().startswith("DS-"):
        return True
    iid = (item_id or "").strip().upper()
    if not iid:
        return False
    now = time.time()
    if now - _ITEMS_CACHE["ts"] > 60:
        try:
            _ITEMS_CACHE.update({"ts": now, "set": set(_item_map(get_productos()))})
        except Exception:
            pass
    return iid in _ITEMS_CACHE["set"]


def on_sale(codigo: str, cantidad: int):
    """El motor registró una venta de un código dropshipping: baja el espejo
    local del stock del proveedor hasta la siguiente lectura de Dropi (así no
    se sobrevende en el intervalo). Devuelve el nuevo disponible."""
    with _LOCK:
        prods = get_productos()
        p = _find(prods, codigo)
        if not p:
            return None
        if p.get("stock_proveedor") is not None:
            p["stock_proveedor"] = max(0, _int(p["stock_proveedor"]) - int(cantidad))
        _save_productos(prods)
        return publicable(p)


# ── Zonas / tarifas Flex del proveedor ───────────────────────────────────────

def zona_flex(state: str, city: str, muni: str, tarifas: list = None):
    """(zona, tarifa) de un envío Flex según la dirección de entrega, o
    (texto, None) si cae fuera de las zonas acordadas."""
    tarifas = tarifas or get_tarifas()
    st = _norm(state)
    blob = " %s | %s " % (_norm(muni), _norm(city))
    full = blob + " | " + st
    if "cundinamarca" not in full and "bogota" not in full:
        return (city or muni or state or "Sin dirección"), None
    # primero las zonas específicas, Bogotá al final
    orden = sorted(tarifas, key=lambda t: "bogota" in [_norm(c) for c in t.get("claves") or []])
    for t in orden:
        for k in t.get("claves") or []:
            k = _norm(k)
            if not k:
                continue
            hay = full if k == "bogota" else blob
            if re.search(r"\b%s\b" % re.escape(k), hay):
                return t.get("zona") or k.title(), _int(t.get("tarifa"))
    return (muni or city or state), None


# ── Dropi ────────────────────────────────────────────────────────────────────

def _find_key(obj, keys, depth=0):
    if depth > 4:
        return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            r = _find_key(v, keys, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj[:5]:
            r = _find_key(v, keys, depth + 1)
            if r is not None:
                return r
    return None


def _parse_dropi_product(data):
    """Saca stock total, precio proveedor y nombre de la respuesta de Dropi
    (tolerante a las distintas versiones de su API)."""
    obj = data
    if isinstance(data, dict):
        for k in ("objects", "data", "product", "result"):
            if isinstance(data.get(k), (dict, list)):
                obj = data[k]
                break
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    if not isinstance(obj, dict):
        return None
    stock = None
    wh = obj.get("warehouse_product") or obj.get("warehouses") or obj.get("warehouse_products")
    if isinstance(wh, list) and wh:
        vals = [_int(w.get("stock"), None) for w in wh if isinstance(w, dict)]
        vals = [v for v in vals if v is not None]
        if vals:
            stock = sum(vals)
    if stock is None:
        for k in ("stock", "total_stock", "stock_total", "quantity"):
            if k in obj:
                v = _int(obj.get(k), None)
                if v is not None:
                    stock = v
                    break
    if stock is None:
        v = _find_key(obj, ["stock", "total_stock"])
        stock = _int(v, None) if v is not None else None
    if stock is None:
        return None
    precio = _find_key(obj, ["sale_price", "suggested_supplier_price", "price"])
    return {"stock": stock, "precio": _int(precio, 0) or None,
            "nombre": (obj.get("name") or "")[:120],
            "proveedor": _dropi_proveedor(obj),
            "sugerido": _int(obj.get("suggested_price"), 0) or None,
            "sku_dropi": str(obj.get("sku") or "")[:60]}


def _dropi_proveedor(obj: dict) -> str:
    """Nombre del proveedor (bodega) que publica el producto en Dropi."""
    for k in ("user", "supplier", "provider", "owner"):
        u = obj.get(k)
        if isinstance(u, dict):
            for kk in ("store_name", "name", "business_name", "full_name"):
                v = u.get(kk)
                if v and isinstance(v, str):
                    nm = v.strip()
                    sur = (u.get("surname") or "").strip() if kk == "name" else ""
                    return (nm + (" " + sur if sur else ""))[:80]
    wh = obj.get("warehouse_product") or []
    if isinstance(wh, list):
        for w in wh:
            ww = (w or {}).get("warehouse") if isinstance(w, dict) else None
            if isinstance(ww, dict) and ww.get("name"):
                return str(ww["name"])[:80]
    for k in ("supplier_name", "store_name", "provider_name"):
        if obj.get(k):
            return str(obj[k])[:80]
    return ""


def dropi_id_from(texto: str) -> str:
    """Saca el ID del producto de un link de Dropi (…/product-details/1866621/…)
    o acepta el número suelto."""
    t = (texto or "").strip()
    m = re.search(r"product-details/(\d+)", t) or re.search(r"[?&](?:id|product_id)=(\d+)", t) \
        or re.search(r"/products?/(\d+)", t) or re.fullmatch(r"\s*(\d{3,})\s*", t)
    return m.group(1) if m else ""


def ml_item_from(texto: str) -> str:
    """Saca el ID de publicación (MCO…) de un link de MercadoLibre."""
    t = (texto or "").strip().upper()
    # Link de catálogo (/p/MCO…): la publicación real viene en item_id / wid.
    m = re.search(r"(?:ITEM_ID(?:%3A|:|=)|WID=)MCO-?(\d{6,})", t)
    if m:
        return "MCO" + m.group(1)
    m = re.search(r"MCO-?(\d{6,})", t)
    if m:
        return "MCO" + m.group(1)
    m = re.fullmatch(r"\s*(\d{6,})\s*", t)
    return ("MCO" + m.group(1)) if m else ""


_DROPI_COMBO = {}   # combinación base/cabecera/ruta que ya funcionó


def _jwt_claims(token: str) -> dict:
    import base64, json as _j
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        c = _j.loads(base64.urlsafe_b64decode(p))
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _dropi_combos(token: str, base: str):
    """Dropi solo acepta el token de integración en api.dropi.co/integrations
    con la cabecera `dropi-integration-key` y — en tokens tipo WooCommerce —
    con cabeceras estilo WordPress (User-Agent con la URL de la tienda del
    token + Referer/Origin), como las manda el plugin Dropify. Se prueban
    pocas combinaciones para no disparar el límite de peticiones de Dropi."""
    c = _jwt_claims(token)
    tienda = str(c.get("integration_url") or c.get("url") or
                 "https://boun-web-deploy.onrender.com").strip() or "https://boun-web-deploy.onrender.com"
    if not tienda.startswith("http"):
        tienda = "https://" + tienda
    wp = {"User-Agent": "WordPress/6.6; %s" % tienda, "Referer": tienda,
          "Origin": tienda.rstrip("/")}
    plana = {"User-Agent": "BOUN-Inventario/1.0"}
    b = "https://api.dropi.co/integrations"
    out = []
    for extra, tag in ((wp, "wordpress"), (plana, "plana")):
        for hname in ("dropi-integration-key", "dropi-integracion-key"):
            for ruta in ("/products/%s", "/products/v2/%s"):
                out.append((b, hname, token, ruta, extra, tag))
    return out


def _clean_token(t: str) -> str:
    t = (t or "").strip().strip('"').strip("'").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return "".join(t.split())   # sin saltos de línea ni espacios internos


def token_info(t: str) -> dict:
    """Diagnóstico NO secreto del token: largo, forma JWT y claims públicos."""
    import base64, json as _j
    t = _clean_token(t)
    info = {"largo": len(t), "partes": len(t.split("."))}
    try:
        p = t.split(".")[1]
        p += "=" * (-len(p) % 4)
        c = _j.loads(base64.urlsafe_b64decode(p))
        info.update({k: c.get(k) for k in ("aud", "sub", "iss", "exp", "integration_url", "ip_url") if k in c})
        info["claims"] = sorted(c.keys())
    except Exception:
        info["jwt"] = "no decodifica (¿copiado incompleto?)"
    return info


def dropi_fetch(dropi_id, token: str, base: str, debug: bool = False) -> dict:
    """Lee un producto de Dropi con el token de integración. Usa la
    combinación que ya funcionó; si no hay, prueba las conocidas."""
    token = _clean_token(token)
    combos = _dropi_combos(token, base)
    k = _DROPI_COMBO.get("key")
    if k:
        combos = [c for c in combos if (c[1], c[3], c[5]) == k] + \
                 [c for c in combos if (c[1], c[3], c[5]) != k]
    err, log = "sin respuesta", []
    for (b, hname, hval, ruta, extra, tag) in combos:
        url = b + (ruta % dropi_id)
        hdrs = {hname: hval, "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8"}
        hdrs.update(extra)
        try:
            r = requests.get(url, headers=hdrs, timeout=12)
            code = r.status_code
        except Exception as e:
            code, r = "ERR", None
            err = "conexión: %s" % str(e)[:80]
        msg = ""
        if r is not None:
            try:
                j = r.json()
                msg = str(j.get("message") or j.get("status") or "")[:120] if isinstance(j, dict) else ""
            except Exception:
                msg = r.text[:120]
        log.append("%s · %s %s → %s %s" % (tag, hname, url.replace(str(dropi_id), "{id}"), code, msg))
        if r is None:
            continue
        if code == 429 or "exceeded the allowed" in msg.lower():
            err = "Dropi limitó las peticiones (espera unos minutos)"
            break
        if code in (401, 403) or "access denied" in msg.lower():
            err = "Dropi rechazó el token (%s%s)" % (code, (": " + msg) if msg else "")
            continue
        if code != 200:
            if err.startswith("sin respuesta"):
                err = "Dropi respondió %s %s" % (code, msg)
            continue
        try:
            parsed = _parse_dropi_product(r.json())
        except Exception:
            parsed = None
        if parsed:
            _DROPI_COMBO["key"] = (hname, ruta, tag)
            parsed.update({"ok": True, "ruta": url.replace(str(dropi_id), "{id}"),
                           "cabecera": "%s (%s)" % (hname, tag)})
            if debug:
                parsed["intentos"] = log
            return parsed
        err = "respuesta sin stock"
        if debug:
            log.append("   cuerpo: %s" % r.text[:200])
    out = {"ok": False, "error": err}
    if debug:
        out["intentos"] = log
    return out


def sync_stock() -> dict:
    token = db.get_setting(K_TOKEN, "")
    if not token:
        return {"ok": False, "error": "Falta el token de Dropi", "leidos": 0}
    cfg = get_cfg()
    prods = get_productos()
    leidos, errores, cambios = 0, 0, []
    for p in prods:
        if p.get("estado") == "migrado" or not p.get("dropi_id"):
            continue
        antes = publicable(p, cfg)
        r = dropi_fetch(p["dropi_id"], token, cfg.get("dropi_base"))
        if r.get("ok"):
            leidos += 1
            p["stock_proveedor"] = int(r["stock"])
            p["stock_ts"] = _iso()
            p["stock_fuente"] = "dropi"
            p["stock_error"] = ""
            if r.get("precio"):
                p["precio_dropi"] = r["precio"]
            if r.get("proveedor"):
                p["proveedor_dropi"] = r["proveedor"]   # el proveedor real según Dropi
            if publicable(p, cfg) != antes:
                cambios.append(p["sku"])
        else:
            errores += 1
            p["stock_error"] = r.get("error") or "error"
            if leidos == 0 and "rechazó el token" in (r.get("error") or ""):
                break   # token inválido: no insistir con los demás productos
    _save_productos(prods)
    _propagar_cambios(cambios)
    return {"ok": errores == 0, "leidos": leidos, "errores": errores,
            "cambios": cambios}


def _propagar_cambios(skus):
    fn = _HOOKS.get("propagate")
    if not fn:
        return
    cfg = get_cfg()
    prods = get_productos()
    for sku in skus:
        p = _find(prods, sku)
        if p:
            try:
                fn(sku, publicable(p, cfg))
            except Exception:
                pass


# ── Ventas desde MercadoLibre ────────────────────────────────────────────────

def _ml(path, acct):
    fn = _HOOKS.get("ml_request")
    if not fn:
        return None
    try:
        r = fn("GET", path, acct=acct)
    except Exception:
        return None
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def _uid(acct):
    if acct not in _UID:
        me = _ml("/users/me", acct)
        if me and me.get("id"):
            _UID[acct] = str(me["id"])
    return _UID.get(acct)


_EST_ENVIO = {
    "delivered": "entregada", "shipped": "en camino",
    "ready_to_ship": "por despachar", "handling": "por despachar",
    "pending": "por despachar", "not_delivered": "no entregada",
    "returned": "devuelta", "cancelled": "cancelada",
}


def _item_map(prods):
    m = {}
    for p in prods:
        for it in p.get("ml_items") or []:
            iid = (it.get("item_id") or "").strip().upper()
            if iid:
                m[iid] = p["sku"]
    return m


def _venta_from(acct, order, oi, sku, prods, tarifas, ventas_prev):
    item = oi.get("item") or {}
    iid = (item.get("id") or "").upper()
    key = "%s|%s|%s" % (acct, order.get("id"), iid)
    prev = ventas_prev.get(key) or {}
    qty = _int(oi.get("quantity"), 1)
    unit = float(oi.get("unit_price") or 0)
    fee = float(oi.get("sale_fee") or 0)
    sh = order.get("shipping") or {}
    sid = str(sh.get("id") or "")
    shipment = _ml("/shipments/%s" % sid, acct) if sid else None
    shipment = shipment or {}
    lt = sh.get("logistic_type") or shipment.get("logistic_type") or ""
    ra = shipment.get("receiver_address") or {}
    state = (ra.get("state") or {}).get("name", "")
    city = (ra.get("city") or {}).get("name", "")
    muni = (ra.get("municipality") or {}).get("name", "")
    barrio = (ra.get("neighborhood") or {}).get("name", "")
    es_flex = lt == "self_service"
    if es_flex:
        zona, tarifa = zona_flex(state, city, muni, tarifas)
        envio = "flex"
    elif lt == "fulfillment":
        zona, tarifa, envio = (city or state), 0, "full"
    else:
        zona, tarifa, envio = (city or muni or state), 0, "agencia"
    # Costo de envío que ML le cobra a BOUN (para el neto estimado).
    cost_ml = prev.get("envio_ml")
    if cost_ml is None and sid:
        c = _ml("/shipments/%s/costs" % sid, acct) or {}
        snd = c.get("senders") or []
        cost_ml = float((snd[0] or {}).get("cost") or 0) if snd else 0.0
    cost_ml = float(cost_ml or 0)
    ship_status = shipment.get("status") or ""
    if (order.get("status") or "") == "cancelled":
        estado = "cancelada"
    else:
        estado = _EST_ENVIO.get(ship_status, ship_status or "por despachar")
        sub = (shipment.get("substatus") or "").lower()
        if ship_status in ("ready_to_ship", "handling") and sub in (
                "dropped_off", "in_hub", "picked_up", "in_transit", "on_route",
                "out_for_delivery", "soon_deliver", "authorized_by_carrier",
                "in_packing_list", "packed", "in_warehouse", "received_by_carrier"):
            estado = "en camino"     # ya lo entregaron a la agencia / transportadora
    p = _find(prods, sku) or {}
    costo_u = prev.get("costo_u")
    if costo_u is None:
        costo_u = _int(p.get("costo"), 0)
    created = order.get("date_created") or ""
    try:
        fecha = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(TZ)
        fecha_s = fecha.strftime("%Y-%m-%d %H:%M")
    except Exception:
        fecha_s = created[:16].replace("T", " ")
    bruto = unit * qty
    neto = bruto - fee * qty - cost_ml
    v = {
        "key": key, "acct": acct, "order_id": str(order.get("id")),
        "pack": str(order.get("pack_id") or ""), "ship": sid,
        "item_id": iid, "sku": sku, "titulo": (item.get("title") or "")[:90],
        "fecha": fecha_s, "qty": qty, "precio_u": unit, "bruto": bruto,
        "comision": round(fee * qty), "envio_ml": round(cost_ml),
        "neto_ml": round(neto),
        "envio": envio, "logistic": lt, "zona": zona, "barrio": barrio,
        "localidad": muni,
        "ciudad": city, "depto": state,
        "tarifa_flex": tarifa, "estado": estado, "envio_status": "%s/%s" % (ship_status, (shipment.get("substatus") or "")),
        "comprador": ((order.get("buyer") or {}).get("nickname") or "")[:40],
        "costo_u": costo_u,
        # campos manuales que la sincronización NUNCA pisa
        "excluir": prev.get("excluir", False),
        "envio_override": prev.get("envio_override"),
        "nota": prev.get("nota", ""),
        "leido": _iso(),
    }
    return v


def calc_venta(v: dict) -> dict:
    """Completa una venta con lo que se le debe al proveedor y la utilidad."""
    v = dict(v)
    envio_prov = v.get("envio_override")
    if envio_prov in (None, ""):
        envio_prov = v.get("tarifa_flex") if v.get("envio") == "flex" else 0
        if v.get("tarifa_no_cobra"):
            envio_prov = 0
    sin_tarifa = v.get("envio") == "flex" and envio_prov is None \
        and v.get("envio_override") in (None, "")
    envio_prov = _int(envio_prov, 0)
    cancel_sin_envio = v.get("estado") == "cancelada" and \
        v.get("logistic") != "fulfillment"
    producto = _int(v.get("costo_u"), 0) * _int(v.get("qty"), 1)
    if v.get("excluir") or cancel_sin_envio:
        debe = 0
    else:
        debe = producto + envio_prov
    v["envio_proveedor"] = envio_prov
    v["costo_producto"] = producto
    v["debe"] = debe
    v["sin_tarifa"] = bool(sin_tarifa)
    v["utilidad"] = (0 if (v.get("excluir") or v.get("estado") == "cancelada")
                     else _int(v.get("neto_ml")) - debe)
    v["cuenta"] = not (v.get("excluir") or v.get("estado") == "cancelada")
    return v


def sync_ventas() -> dict:
    cfg = get_cfg()
    prods = get_productos()
    tarifas = get_tarifas()
    imap = _item_map(prods)
    with _LOCK:
        ventas = _get(K_VENTAS, {}) or {}
    estado = _get(K_SYNC, {}) or {}
    try:
        desde = datetime.fromisoformat(cfg.get("desde") or DEF_CFG["desde"]).replace(tzinfo=TZ)
    except Exception:
        desde = datetime.fromisoformat(DEF_CFG["desde"]).replace(tzinfo=TZ)
    # Incremental: relee desde 3 días antes de la última lectura completa.
    last = estado.get("ventas_hasta")
    if last:
        try:
            desde = max(desde, datetime.fromisoformat(last) - timedelta(days=3))
        except Exception:
            pass
    now = _now()
    fmt = "%Y-%m-%dT%H:%M:%S.000-05:00"
    nuevas, errores, vistos = 0, [], set()
    for acct in ("boun", "kat"):
        uid = _uid(acct)
        if not uid:
            errores.append("sin conexión ML %s" % acct.upper())
            continue
        offset = 0
        while True:
            d = _ml("/orders/search?seller=%s&order.date_created.from=%s"
                    "&order.date_created.to=%s&sort=date_asc&limit=50&offset=%d"
                    % (uid, desde.strftime(fmt), now.strftime(fmt), offset), acct)
            if d is None:
                errores.append("orders/search %s" % acct.upper())
                break
            res = d.get("results") or []
            for od in res:
                for oi in od.get("order_items") or []:
                    item = oi.get("item") or {}
                    iid = (item.get("id") or "").upper()
                    ssku = (item.get("seller_sku") or "").strip().upper()
                    sku = imap.get(iid) or (ssku if ssku.startswith("DS-") and _find(prods, ssku) else None)
                    if not sku:
                        continue
                    v = _venta_from(acct, od, oi, sku, prods, tarifas, ventas)
                    if v["key"] not in ventas:
                        nuevas += 1
                    ventas[v["key"]] = v
                    vistos.add(v["key"])
            offset += 50
            if not res or offset >= (d.get("paging") or {}).get("total", 0):
                break
    # Refresca ventas viejas que aún no terminan (fuera de la ventana leída).
    for k, v in list(ventas.items()):
        if k in vistos or v.get("estado") in ("entregada", "cancelada", "devuelta"):
            continue
        od = _ml("/orders/%s" % v["order_id"], v.get("acct") or "boun")
        if not od:
            continue
        for oi in od.get("order_items") or []:
            if ((oi.get("item") or {}).get("id") or "").upper() == v.get("item_id"):
                ventas[k] = _venta_from(v.get("acct") or "boun", od, oi, v["sku"],
                                        prods, tarifas, ventas)
    # Un envío Flex con varias órdenes (pack) se le paga al proveedor UNA vez.
    por_envio = {}
    for k in sorted(ventas):
        v = ventas[k]
        v.pop("tarifa_no_cobra", None)
        if v.get("envio") == "flex" and v.get("ship"):
            if v["ship"] in por_envio:
                v["tarifa_no_cobra"] = True
            else:
                por_envio[v["ship"]] = k
    with _LOCK:
        _put(K_VENTAS, ventas)
    estado.update({"ventas_ts": _iso(), "ventas_hasta": now.isoformat(),
                   "ventas_error": "; ".join(errores)[:200]})
    _put(K_SYNC, estado)
    return {"ok": not errores, "nuevas": nuevas, "total": len(ventas),
            "errores": errores}


# ── Inventario central (para Mapeo y motor de stock) ─────────────────────────

def ensure_inventory(p: dict) -> dict:
    """Crea (si falta) el producto DS-… en inventory_products y vincula sus
    publicaciones para que el motor de stock y el Mapeo lo reconozcan."""
    from urllib.parse import quote
    sku = p["sku"]
    rows = db._sb_get("inventory_products?code=eq.%s&select=id,name,cost_product"
                      % quote(sku, safe="")) or []
    if rows:
        pid = rows[0]["id"]
        if _int(rows[0].get("cost_product")) != _int(p.get("costo")):
            db.inv_update_product(pid, {"cost_product": float(p.get("costo") or 0)})
    else:
        r = db.inv_create_product(sku, p.get("nombre") or sku, "dropshipping",
                                  cost_product=float(p.get("costo") or 0))
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        pid = r.get("id")
        if pid:
            db.inv_update_product(pid, {"owner": "dropshipping",
                                        "notes": "Dropshipping · %s" % get_cfg()["proveedor"]})
    links = 0
    for it in p.get("ml_items") or []:
        iid = (it.get("item_id") or "").strip().upper()
        if not iid or not pid:
            continue
        ch = "mercadolibre_kat" if it.get("acct") == "kat" else "mercadolibre"
        if db.inv_link_add(pid, ch, iid, {"title": p.get("nombre") or ""}):
            links += 1
    return {"ok": True, "pid": pid, "links": links}


# ── Resumen / KPIs / ganadores ───────────────────────────────────────────────

def _parse_fecha(s):
    try:
        return datetime.strptime((s or "")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except Exception:
        return None


def resumen() -> dict:
    cfg = get_cfg()
    prods = get_productos()
    tarifas = get_tarifas()
    ventas = [calc_venta(v) for v in (_get(K_VENTAS, {}) or {}).values()]
    ventas.sort(key=lambda v: v.get("fecha") or "", reverse=True)
    pagos = _get(K_PAGOS, []) or []
    sync = _get(K_SYNC, {}) or {}
    total_debe = sum(v["debe"] for v in ventas)
    pagado = sum(_int(p.get("monto")) for p in pagos)
    hace30 = _now() - timedelta(days=30)
    hace7 = _now() - timedelta(days=7)

    by_sku = {}
    for v in ventas:
        s = by_sku.setdefault(v["sku"], {"u30": 0, "u7": 0, "uall": 0, "v30": 0,
                                         "bruto30": 0, "util30": 0, "utilall": 0,
                                         "cancel30": 0, "ultima": ""})
        f = _parse_fecha(v.get("fecha"))
        if v["cuenta"]:
            s["uall"] += v["qty"]
            s["utilall"] += v["utilidad"]
        if v.get("fecha", "") > s["ultima"]:
            s["ultima"] = v.get("fecha", "")
        if f and f >= hace30:
            if v["cuenta"]:
                s["u30"] += v["qty"]
                s["v30"] += 1
                s["bruto30"] += v["bruto"]
                s["util30"] += v["utilidad"]
            elif v.get("estado") == "cancelada":
                s["cancel30"] += 1
        if f and f >= hace7 and v["cuenta"]:
            s["u7"] += v["qty"]

    meta_u = _int(cfg.get("ganador_ventas30"), 15)
    meta_m = float(cfg.get("ganador_margen_pct") or 20)
    out_prods, ganadores = [], []
    for p in prods:
        s = by_sku.get(p["sku"], {"u30": 0, "u7": 0, "uall": 0, "v30": 0,
                                  "bruto30": 0, "util30": 0, "utilall": 0,
                                  "cancel30": 0, "ultima": ""})
        margen = (s["util30"] / s["bruto30"] * 100.0) if s["bruto30"] else None
        reclamos = _int(p.get("reclamos_calidad"))
        ok_u = s["u30"] >= meta_u
        ok_m = margen is not None and margen >= meta_m
        ok_r = reclamos == 0
        q = dict(p)
        q.update({
            "publicable": publicable(p, cfg),
            "colchon_efectivo": (p.get("colchon_pct") if p.get("colchon_pct") not in (None, "")
                                 else cfg["colchon_pct"]),
            "ventas30": s["u30"], "ventas7": s["u7"], "ventas_total": s["uall"],
            "util30": s["util30"], "util_total": s["utilall"],
            "margen30": round(margen, 1) if margen is not None else None,
            "cancel30": s["cancel30"], "ultima_venta": s["ultima"],
            "criterios": {"ventas": ok_u, "margen": ok_m, "reclamos": ok_r},
            "ganador": ok_u and ok_m and ok_r and p.get("estado") != "migrado",
            "dias_cobertura": (round(publicable(p, cfg) / (s["u30"] / 30.0))
                               if s["u30"] else None),
        })
        q.pop("costos_hist", None)
        out_prods.append(q)
        if q["ganador"]:
            ganadores.append(p["sku"])

    activos = [q for q in out_prods if q.get("estado") == "activo"]
    v30 = [v for v in ventas if v["cuenta"] and (_parse_fecha(v.get("fecha")) or hace30) >= hace30]
    return {
        "cfg": cfg, "tarifas": tarifas,
        "has_token": bool(db.get_setting(K_TOKEN, "")),
        "productos": out_prods, "ventas": ventas, "pagos": pagos,
        "sync": sync, "syncing": _SYNC_LOCK.locked(),
        "ganadores": ganadores,
        "kpis": {
            "saldo": total_debe - pagado, "total_debe": total_debe,
            "pagado": pagado,
            "stock_total": sum(_int(q.get("stock_proveedor")) for q in activos),
            "publicable_total": sum(q["publicable"] for q in activos),
            "activos": len(activos), "productos": len(out_prods),
            "unid30": sum(v["qty"] for v in v30),
            "ventas30": len(v30),
            "util30": sum(v["utilidad"] for v in v30),
            "bruto30": sum(v["bruto"] for v in v30),
            "sin_tarifa": sum(1 for v in ventas if v["sin_tarifa"] and v["cuenta"]),
            "por_despachar": sum(1 for v in ventas if v.get("estado") == "por despachar"),
            "sin_stock": sum(1 for q in activos if q["publicable"] <= 0),
        },
    }


def alertas_count() -> int:
    try:
        r = resumen()
        k = r["kpis"]
        return int(k["sin_tarifa"] + k["sin_stock"])
    except Exception:
        return 0


def run_sync(stock=True, ventas=True) -> dict:
    """Sincronización completa (con candado para no correr dos a la vez)."""
    if not _SYNC_LOCK.acquire(blocking=False):
        return {"ok": False, "busy": True}
    out = {}
    try:
        for p in get_productos():
            if p.get("estado") != "migrado":
                try:
                    ensure_inventory(p)
                except Exception:
                    pass
        if stock:
            out["stock"] = sync_stock()
        if ventas:
            out["ventas"] = sync_ventas()
        st = _get(K_SYNC, {}) or {}
        st["ultimo"] = _iso()
        if stock:
            st["stock_ts"] = _iso()
            st["stock_error"] = "" if (out["stock"].get("ok")) else \
                (out["stock"].get("error") or "%s error(es)" % out["stock"].get("errores"))
        _put(K_SYNC, st)
    finally:
        _SYNC_LOCK.release()
    return out


def _loop():
    time.sleep(90)
    while True:
        try:
            cfg = get_cfg()
            if db.get_setting(K_TOKEN, ""):
                run_sync(stock=True, ventas=True)
            else:
                run_sync(stock=False, ventas=True)
            time.sleep(max(5, _int(cfg.get("sync_min"), 15)) * 60)
        except Exception:
            time.sleep(600)


# ── API ──────────────────────────────────────────────────────────────────────

class MlItemIn(BaseModel):
    acct: str = "boun"
    item_id: str


class ProductoIn(BaseModel):
    sku: str
    nombre: str
    costo: float = 0
    dropi_id: Optional[str] = None
    proveedor_dropi: Optional[str] = ""
    link_dropi: Optional[str] = ""
    colchon_pct: Optional[float] = None
    ml_items: List[MlItemIn] = []
    notas: Optional[str] = ""


class ProductoPatch(BaseModel):
    nombre: Optional[str] = None
    costo: Optional[float] = None
    dropi_id: Optional[str] = None
    proveedor_dropi: Optional[str] = None
    link_dropi: Optional[str] = None
    colchon_pct: Optional[float] = None
    quitar_colchon_propio: Optional[bool] = None
    ml_items: Optional[List[MlItemIn]] = None
    notas: Optional[str] = None
    estado: Optional[str] = None
    reclamos_calidad: Optional[int] = None


class StockIn(BaseModel):
    stock: int


class VentaPatch(BaseModel):
    excluir: Optional[bool] = None
    envio_override: Optional[float] = None
    quitar_override: Optional[bool] = None
    nota: Optional[str] = None


class PagoIn(BaseModel):
    monto: float
    fecha: Optional[str] = ""
    nota: Optional[str] = ""


class TarifaIn(BaseModel):
    zona: str
    tarifa: float
    claves: List[str] = []


class CfgIn(BaseModel):
    proveedor: Optional[str] = None
    colchon_pct: Optional[float] = None
    colchon_min: Optional[int] = None
    desde: Optional[str] = None
    ganador_ventas30: Optional[int] = None
    ganador_margen_pct: Optional[float] = None
    dropi_base: Optional[str] = None
    sync_min: Optional[int] = None
    tarifas: Optional[List[TarifaIn]] = None
    dropi_token: Optional[str] = None
    borrar_token: Optional[bool] = None


def _clean_items(items):
    out, seen = [], set()
    for it in items or []:
        d = it if isinstance(it, dict) else it.dict()
        iid = re.sub(r"[^A-Z0-9]", "", (d.get("item_id") or "").upper())
        if not iid:
            continue
        if not iid.startswith("MCO"):
            iid = "MCO" + iid
        acct = "kat" if d.get("acct") == "kat" else "boun"
        if (acct, iid) in seen:
            continue
        seen.add((acct, iid))
        out.append({"acct": acct, "item_id": iid})
    return out


def build_router(current_user, admin, ml_request, propagate) -> APIRouter:
    _HOOKS["ml_request"] = ml_request
    _HOOKS["propagate"] = propagate
    r = APIRouter()

    @r.get("/api/dropship")
    def ds_get(user: dict = Depends(current_user)):
        return resumen()

    @r.get("/api/dropship/count")
    def ds_count(user: dict = Depends(current_user)):
        return {"count": alertas_count()}

    @r.post("/api/dropship/sync")
    def ds_sync(stock: bool = True, ventas: bool = True,
                user: dict = Depends(current_user)):
        if _SYNC_LOCK.locked():
            return {"ok": True, "busy": True}
        threading.Thread(target=run_sync, kwargs={"stock": stock, "ventas": ventas},
                         daemon=True).start()
        return {"ok": True, "started": True}

    @r.post("/api/dropship/leer-dropi")
    def ds_leer_dropi(data: dict, user: dict = Depends(admin)):
        pid = dropi_id_from(str(data.get("link") or ""))
        if not pid:
            raise HTTPException(400, "No encontré el ID en ese link. Debe verse como …/product-details/1866621/…")
        token = db.get_setting(K_TOKEN, "")
        dup = next((p["sku"] for p in get_productos() if str(p.get("dropi_id") or "") == pid), None)
        out = {"ok": True, "dropi_id": pid, "ya_existe": dup,
               "link": "https://app.dropi.co/dashboard/product-details/%s/x" % pid}
        if not token:
            out.update({"leido": False, "error": "Falta el token de Dropi"})
            return out
        res = dropi_fetch(pid, token, get_cfg().get("dropi_base"))
        if not res.get("ok"):
            out.update({"leido": False, "error": res.get("error")})
            return out
        out.update({"leido": True, "nombre": res.get("nombre"), "stock": res.get("stock"),
                    "precio": res.get("precio"), "sugerido": res.get("sugerido"),
                    "proveedor": res.get("proveedor"), "sku_dropi": res.get("sku_dropi")})
        return out

    @r.post("/api/dropship/leer-ml")
    def ds_leer_ml(data: dict, user: dict = Depends(admin)):
        iid = ml_item_from(str(data.get("link") or ""))
        if not iid:
            raise HTTPException(400, "No encontré el código MCO en ese link.")
        acc_pref = data.get("acct")
        orden = [acc_pref] if acc_pref in ("boun", "kat") else []
        orden += [a for a in ("boun", "kat") if a not in orden]
        me = {}
        for acct in orden:
            try:
                me[acct] = (_ml("/users/me", acct) or {}).get("id")
            except Exception:
                me[acct] = None
        it = _ml("/items/%s" % iid, orden[0]) or {}
        if not it.get("id"):
            return {"ok": True, "item_id": iid, "leido": False,
                    "error": "MercadoLibre no devolvió la publicación %s" % iid}
        acct = next((a for a, uid in me.items() if uid and str(uid) == str(it.get("seller_id"))), None)
        ssku = ""
        for a in it.get("attributes") or []:
            if a.get("id") == "SELLER_SKU":
                ssku = a.get("value_name") or ""
        dup = next((p["sku"] for p in get_productos()
                    for x in (p.get("ml_items") or []) if x.get("item_id") == iid), None)
        return {"ok": True, "leido": True, "item_id": iid, "acct": acct,
                "ajena": acct is None, "titulo": it.get("title"), "precio": it.get("price"),
                "estado": it.get("status"), "seller_sku": ssku, "ya_en": dup,
                "foto": (it.get("thumbnail") or "").replace("http://", "https://")}

    @r.post("/api/dropship/productos")
    def ds_crear(data: ProductoIn, user: dict = Depends(admin)):
        sku = re.sub(r"\s+", "-", data.sku.strip().upper())
        if not sku.startswith("DS-"):
            sku = "DS-" + sku
        prods = get_productos()
        if _find(prods, sku):
            raise HTTPException(400, "El SKU %s ya existe en dropshipping." % sku)
        p = {"sku": sku, "nombre": data.nombre.strip(), "costo": _int(data.costo),
             "dropi_id": (str(data.dropi_id).strip() or None) if data.dropi_id else None,
             "proveedor_dropi": data.proveedor_dropi or "",
             "link_dropi": data.link_dropi or "",
             "stock_proveedor": None, "stock_ts": "", "stock_fuente": "",
             "stock_error": "", "colchon_pct": data.colchon_pct,
             "estado": "activo", "ml_items": _clean_items(data.ml_items),
             "reclamos_calidad": 0, "notas": data.notas or "",
             "creado": _iso(), "creado_por": user.get("username", ""),
             "costos_hist": []}
        if p["dropi_id"] and not p["link_dropi"]:
            p["link_dropi"] = "https://app.dropi.co/dashboard/product-details/%s/x" % p["dropi_id"]
        prods.append(p)
        _save_productos(prods)
        inv = ensure_inventory(p)
        return {"ok": True, "sku": sku, "inventario": inv}

    @r.patch("/api/dropship/productos/{sku}")
    def ds_editar(sku: str, data: ProductoPatch, user: dict = Depends(admin)):
        prods = get_productos()
        p = _find(prods, sku)
        if not p:
            raise HTTPException(404, "No existe %s" % sku)
        d = data.dict(exclude_unset=True)
        if "costo" in d and _int(d["costo"]) != _int(p.get("costo")):
            p.setdefault("costos_hist", []).append(
                {"fecha": _iso(), "antes": p.get("costo"), "despues": _int(d["costo"]),
                 "por": user.get("username", "")})
            p["costo"] = _int(d["costo"])
        for k in ("nombre", "proveedor_dropi", "link_dropi", "notas"):
            if k in d and d[k] is not None:
                p[k] = d[k]
        if "dropi_id" in d:
            p["dropi_id"] = (str(d["dropi_id"]).strip() or None) if d["dropi_id"] else None
            if p["dropi_id"]:
                p["link_dropi"] = p.get("link_dropi") or \
                    "https://app.dropi.co/dashboard/product-details/%s/x" % p["dropi_id"]
                if p.get("stock_error", "").startswith("Falta el link"):
                    p["stock_error"] = ""
        if d.get("quitar_colchon_propio"):
            p["colchon_pct"] = None
        elif "colchon_pct" in d and d["colchon_pct"] is not None:
            p["colchon_pct"] = max(0.0, min(90.0, float(d["colchon_pct"])))
        if "reclamos_calidad" in d and d["reclamos_calidad"] is not None:
            p["reclamos_calidad"] = max(0, int(d["reclamos_calidad"]))
        if d.get("estado") in ("activo", "pausado"):
            p["estado"] = d["estado"]
        if "ml_items" in d and d["ml_items"] is not None:
            p["ml_items"] = _clean_items(d["ml_items"])
        _save_productos(prods)
        inv = ensure_inventory(p) if p.get("estado") != "migrado" else None
        _propagar_cambios([p["sku"]])
        return {"ok": True, "inventario": inv}

    @r.post("/api/dropship/productos/{sku}/stock")
    def ds_stock_manual(sku: str, data: StockIn, user: dict = Depends(current_user)):
        prods = get_productos()
        p = _find(prods, sku)
        if not p:
            raise HTTPException(404, "No existe %s" % sku)
        p["stock_proveedor"] = max(0, int(data.stock))
        p["stock_ts"] = _iso()
        p["stock_fuente"] = "manual"
        p["stock_por"] = user.get("username", "")
        _save_productos(prods)
        _propagar_cambios([p["sku"]])
        return {"ok": True, "publicable": publicable(p)}

    @r.post("/api/dropship/productos/{sku}/migrar")
    def ds_migrar(sku: str, user: dict = Depends(admin)):
        prods = get_productos()
        p = _find(prods, sku)
        if not p:
            raise HTTPException(404, "No existe %s" % sku)
        p["estado"] = "migrado"
        p["migrado_ts"] = _iso()
        p["migrado_por"] = user.get("username", "")
        _save_productos(prods)
        return {"ok": True}

    @r.post("/api/dropship/productos/{sku}/reactivar")
    def ds_reactivar(sku: str, user: dict = Depends(admin)):
        prods = get_productos()
        p = _find(prods, sku)
        if not p:
            raise HTTPException(404, "No existe %s" % sku)
        p["estado"] = "activo"
        p.pop("migrado_ts", None)
        _save_productos(prods)
        ensure_inventory(p)
        _propagar_cambios([p["sku"]])
        return {"ok": True}

    @r.delete("/api/dropship/productos/{sku}")
    def ds_borrar(sku: str, user: dict = Depends(admin)):
        prods = get_productos()
        p = _find(prods, sku)
        if not p:
            raise HTTPException(404, "No existe %s" % sku)
        prods.remove(p)
        _save_productos(prods)
        return {"ok": True}

    @r.patch("/api/dropship/ventas/{key:path}")
    def ds_venta(key: str, data: VentaPatch, user: dict = Depends(admin)):
        with _LOCK:
            ventas = _get(K_VENTAS, {}) or {}
            v = ventas.get(key)
            if not v:
                raise HTTPException(404, "Venta no encontrada")
            d = data.dict(exclude_unset=True)
            if d.get("quitar_override"):
                v["envio_override"] = None
            elif "envio_override" in d and d["envio_override"] is not None:
                v["envio_override"] = max(0, _int(d["envio_override"]))
            if "excluir" in d and d["excluir"] is not None:
                v["excluir"] = bool(d["excluir"])
            if "nota" in d and d["nota"] is not None:
                v["nota"] = d["nota"][:200]
            ventas[key] = v
            _put(K_VENTAS, ventas)
        return {"ok": True, "venta": calc_venta(v)}

    @r.post("/api/dropship/pagos")
    def ds_pago(data: PagoIn, user: dict = Depends(admin)):
        if data.monto <= 0:
            raise HTTPException(400, "El monto debe ser mayor a 0")
        with _LOCK:
            pagos = _get(K_PAGOS, []) or []
            pagos.append({"id": secrets.token_hex(6), "monto": _int(data.monto),
                          "fecha": (data.fecha or _now().strftime("%Y-%m-%d"))[:10],
                          "nota": (data.nota or "")[:200],
                          "created_by": user.get("username", ""),
                          "created_at": _iso()})
            _put(K_PAGOS, pagos)
        return {"ok": True}

    @r.delete("/api/dropship/pagos/{pid}")
    def ds_pago_borrar(pid: str, user: dict = Depends(admin)):
        with _LOCK:
            pagos = [p for p in (_get(K_PAGOS, []) or []) if p.get("id") != pid]
            _put(K_PAGOS, pagos)
        return {"ok": True}

    @r.post("/api/dropship/config")
    def ds_config(data: CfgIn, user: dict = Depends(admin)):
        d = data.dict(exclude_unset=True)
        cfg = _get(K_CFG, {}) or {}
        for k in ("proveedor", "colchon_pct", "colchon_min", "desde",
                  "ganador_ventas30", "ganador_margen_pct", "dropi_base", "sync_min"):
            if k in d and d[k] is not None:
                cfg[k] = d[k]
        if "colchon_pct" in cfg:
            cfg["colchon_pct"] = max(0.0, min(90.0, float(cfg["colchon_pct"])))
        _put(K_CFG, cfg)
        if d.get("tarifas") is not None:
            tars = []
            for t in d["tarifas"]:
                claves = [_norm(c) for c in (t.get("claves") or []) if _norm(c)]
                if t.get("zona") and claves:
                    tars.append({"zona": t["zona"].strip(), "tarifa": _int(t.get("tarifa")),
                                 "claves": claves})
            if tars:
                _put(K_TAR, tars)
        if d.get("borrar_token"):
            db.set_setting(K_TOKEN, "")
        elif d.get("dropi_token"):
            tk = _clean_token(d["dropi_token"])
            if len(tk) < 100 or "jwt" in token_info(tk):
                raise HTTPException(400, "Ese no parece el token de Dropi (tiene %d caracteres). En Dropi → Mis Integraciones usa el botón «Copiar» y pégalo aquí." % len(tk))
            db.set_setting(K_TOKEN, tk)
        _DISP_CACHE["ts"] = 0.0
        return {"ok": True}

    @r.post("/api/dropship/probar-dropi")
    def ds_probar(user: dict = Depends(admin)):
        token = db.get_setting(K_TOKEN, "")
        if not token:
            return {"ok": False, "error": "Primero guarda el token de Dropi."}
        p = next((x for x in get_productos() if x.get("dropi_id")), None)
        if not p:
            return {"ok": False, "error": "Ningún producto tiene ID de Dropi."}
        res = dropi_fetch(p["dropi_id"], token, get_cfg().get("dropi_base"), debug=True)
        res["sku"] = p["sku"]
        res["token_info"] = token_info(token)
        return res

    threading.Thread(target=_loop, daemon=True).start()
    return r
