"""
Cliente mínimo de la Sellercenter API de Falabella (marketplace BOUN).
Lee credenciales SOLO de variables de entorno (no en el código):
  FALABELLA_API_USER  → User ID (correo del Seller Center)
  FALABELLA_API_KEY   → API Key
Autenticación por firma HMAC-SHA256 sobre el querystring ordenado.
Se usa para traer las ventas diarias (GetOrders + GetMultipleOrderItems).
"""
import os
import hmac
import hashlib
import datetime as _dt
from urllib.parse import quote

import requests

BASE = "https://sellercenter-api.falabella.com"
# Colombia es UTC-5 fijo (sin horario de verano)
_CO_TZ = _dt.timezone(_dt.timedelta(hours=-5))


def _creds():
    return (os.environ.get("FALABELLA_API_USER", "").strip(),
            os.environ.get("FALABELLA_API_KEY", "").strip())


def is_connected() -> bool:
    u, k = _creds()
    return bool(u and k)


def _signed_url(action: str, extra: dict = None) -> str:
    user, key = _creds()
    p = {"UserID": user, "Version": "1.0", "Action": action, "Format": "JSON",
         "Timestamp": _dt.datetime.now(_dt.timezone.utc)
                         .replace(microsecond=0).isoformat()}
    if extra:
        p.update(extra)
    q = "&".join(f"{quote(k2, safe='')}={quote(str(p[k2]), safe='')}"
                 for k2 in sorted(p))
    sig = hmac.new(key.encode(), q.encode(), hashlib.sha256).hexdigest()
    return f"{BASE}/?{q}&Signature={sig}"


def _get(action: str, extra: dict = None, timeout: int = 30) -> dict:
    r = requests.get(_signed_url(action, extra), timeout=timeout)
    r.raise_for_status()
    return r.json()


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def get_orders(created_after_iso: str, created_before_iso: str = None,
               limit: int = 100) -> list:
    """Todas las órdenes creadas en un rango de fechas (paginado)."""
    orders, offset = [], 0
    while True:
        params = {"CreatedAfter": created_after_iso,
                  "Limit": str(limit), "Offset": str(offset),
                  "SortBy": "created_at", "SortDirection": "DESC"}
        if created_before_iso:
            params["CreatedBefore"] = created_before_iso
        d = _get("GetOrders", params)
        body = (d.get("SuccessResponse") or {}).get("Body") or {}
        oo = _as_list((body.get("Orders") or {}).get("Order"))
        orders.extend(oo)
        if len(oo) < limit:
            break
        offset += limit
        if offset > 5000:
            break
    return orders


def _units_by_order(order_ids: list) -> dict:
    """{OrderId → nº de unidades} vía GetMultipleOrderItems (en lotes)."""
    units = {}
    for i in range(0, len(order_ids), 25):
        chunk = order_ids[i:i + 25]
        try:
            d = _get("GetMultipleOrderItems",
                     {"OrderIdList": "[" + ",".join(chunk) + "]"})
            body = (d.get("SuccessResponse") or {}).get("Body") or {}
            for o in _as_list((body.get("Orders") or {}).get("Order")):
                items = _as_list((o.get("OrderItems") or {}).get("OrderItem"))
                units[str(o.get("OrderId"))] = len(items)
        except Exception:
            pass
    return units


def daily_sales(days: int = 14, date_from: str = None,
                date_to: str = None) -> dict:
    """Ventas diarias de Falabella: por fecha {ordenes, unidades, ingresos}.

    Agrupa por la fecha local (Colombia) en que se creó la orden.
    Usa rango personalizado date_from/date_to ('YYYY-MM-DD') si se pasan;
    de lo contrario, los últimos `days` días.
    """
    if not is_connected():
        return {"ok": False, "error": "Falabella API sin credenciales"}
    try:
        before = None
        d_from = d_to = None
        if date_from:
            d1 = _dt.date.fromisoformat(date_from[:10])
            d2 = (_dt.date.fromisoformat(date_to[:10]) if date_to
                  else _dt.datetime.now(_CO_TZ).date())
            if d2 < d1:
                d1, d2 = d2, d1
            d_from, d_to = d1.isoformat(), d2.isoformat()
            since = _dt.datetime.combine(
                d1, _dt.time(0, 0, 0), _CO_TZ).isoformat()
            before = _dt.datetime.combine(
                d2, _dt.time(23, 59, 59), _CO_TZ).isoformat()
        else:
            since = ((_dt.datetime.now(_CO_TZ) - _dt.timedelta(days=days))
                     .replace(hour=0, minute=0, second=0,
                              microsecond=0).isoformat())
        orders = get_orders(since, before)
        by = {}
        ids = []
        for o in orders:
            ca = (o.get("CreatedAt") or "")[:10]   # 'YYYY-MM-DD' (hora seller)
            if not ca:
                continue
            if d_from and (ca < d_from or ca > d_to):
                continue
            b = by.setdefault(ca, {"fecha": ca, "ordenes": 0,
                                   "unidades": 0, "ingresos": 0.0})
            b["ordenes"] += 1
            b["ingresos"] += float(o.get("Price") or 0)
            oid = o.get("OrderId")
            if oid:
                ids.append((str(oid), ca))
        # unidades reales por orden
        umap = _units_by_order([i for i, _ in ids])
        for oid, ca in ids:
            if ca in by:
                by[ca]["unidades"] += umap.get(oid, 0)
        dias = sorted(by.values(), key=lambda x: x["fecha"])
        for d in dias:
            d["ingresos"] = round(d["ingresos"], 2)
        return {"ok": True, "dias": dias}
    except Exception as e:
        return {"ok": False, "error": "Falabella: %s" % str(e)[:120]}
