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


def _items_by_order(order_ids: list) -> dict:
    """{OrderId → [nombres de los items]} vía GetMultipleOrderItems (lotes).
    Cada OrderItem = 1 unidad, así que len(lista) = unidades de esa orden.
    """
    out = {}
    for i in range(0, len(order_ids), 25):
        chunk = order_ids[i:i + 25]
        try:
            d = _get("GetMultipleOrderItems",
                     {"OrderIdList": "[" + ",".join(chunk) + "]"})
            body = (d.get("SuccessResponse") or {}).get("Body") or {}
            for o in _as_list((body.get("Orders") or {}).get("Order")):
                items = _as_list((o.get("OrderItems") or {}).get("OrderItem"))
                out[str(o.get("OrderId"))] = [
                    (it.get("Name") or "").strip() for it in items]
        except Exception:
            pass
    return out


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
                                   "unidades": 0, "ingresos": 0.0,
                                   "_prod": {}, "roas": None, "acos": None})
            b["ordenes"] += 1
            b["ingresos"] += float(o.get("Price") or 0)
            oid = o.get("OrderId")
            if oid:
                ids.append((str(oid), ca))
        # items reales por orden (unidades + nombres para el top de productos)
        imap = _items_by_order([i for i, _ in ids])
        for oid, ca in ids:
            if ca not in by:
                continue
            names = imap.get(oid, [])
            by[ca]["unidades"] += len(names)
            for nm in names:
                if nm:
                    by[ca]["_prod"][nm] = by[ca]["_prod"].get(nm, 0) + 1
        dias = sorted(by.values(), key=lambda x: x["fecha"])
        for d in dias:
            d["ingresos"] = round(d["ingresos"], 2)
            top = sorted(d.pop("_prod").items(), key=lambda x: -x[1])[:3]
            d["top"] = [{"nombre": n, "unidades": u} for n, u in top]
        return {"ok": True, "dias": dias}
    except Exception as e:
        return {"ok": False, "error": "Falabella: %s" % str(e)[:120]}
