"""
Cliente mínimo de la Sellercenter API de Falabella (marketplace BOUN).
Lee credenciales SOLO de variables de entorno (no en el código):
  FALABELLA_API_USER  → User ID (correo del Seller Center)
  FALABELLA_API_KEY   → API Key
Autenticación por firma HMAC-SHA256 sobre el querystring ordenado.
Se usa para traer las ventas diarias (GetOrders + GetMultipleOrderItems).
"""
import os
import time
import hmac
import hashlib
import datetime as _dt
import xml.sax.saxutils as _su
from urllib.parse import quote

import requests

# Estados transitorios de la API de Falabella que vale la pena reintentar.
_RETRY_STATUS = {429, 500, 502, 503, 504}

BASE = "https://sellercenter-api.falabella.com"
# Colombia es UTC-5 fijo (sin horario de verano)
_CO_TZ = _dt.timezone(_dt.timedelta(hours=-5))
# Operador logístico de la cuenta (Falabella Colombia = "faco"); el stock vive
# por BusinessUnit/OperatorCode, así que ProductUpdate debe usar ese formato.
_OPERATOR = os.environ.get("FALABELLA_OPERATOR", "faco")


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


def _get(action: str, extra: dict = None, timeout: int = 30,
         retries: int = 3) -> dict:
    """GET firmado con reintentos: la API de Falabella devuelve 503/429
    transitorios. Cada intento re-firma (Timestamp fresco) y espera con backoff."""
    last = None
    for i in range(retries):
        try:
            r = requests.get(_signed_url(action, extra), timeout=timeout)
            if r.status_code in _RETRY_STATUS and i < retries - 1:
                last = "HTTP %d" % r.status_code
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            raise
    raise RuntimeError(str(last) if last else "sin respuesta")


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _post(action: str, body: str, extra: dict = None, timeout: int = 60,
          retries: int = 3) -> dict:
    """POST firmado (la firma va en el querystring; el XML va en el cuerpo).
    Reintenta los estados transitorios (503/429…) con backoff."""
    last = None
    for i in range(retries):
        try:
            r = requests.post(_signed_url(action, extra),
                              data=body.encode("utf-8"),
                              headers={"Content-Type":
                                       "text/xml; charset=utf-8"},
                              timeout=timeout)
            if r.status_code in _RETRY_STATUS and i < retries - 1:
                last = "HTTP %d" % r.status_code
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            raise
    else:
        raise RuntimeError(str(last) if last else "sin respuesta")
    d = r.json()
    if "ErrorResponse" in d:
        h = (d.get("ErrorResponse") or {}).get("Head", {}) or {}
        raise RuntimeError("%s: %s" % (h.get("ErrorCode"),
                                       h.get("ErrorMessage")))
    return d


# ── API pública para los endpoints externos (ventas/catálogo/stock) ──────────

def _all_order_items(order_ids: list) -> list:
    """Lista plana de OrderItem (cada uno = 1 unidad) de varias órdenes."""
    out = []
    for i in range(0, len(order_ids), 25):
        chunk = order_ids[i:i + 25]
        try:
            d = _get("GetMultipleOrderItems",
                     {"OrderIdList": "[" + ",".join(chunk) + "]"})
            body = (d.get("SuccessResponse") or {}).get("Body") or {}
            for o in _as_list((body.get("Orders") or {}).get("Order")):
                out.extend(_as_list((o.get("OrderItems") or {}).get("OrderItem")))
        except Exception:
            pass
    return out


def ventas_por_sku(dias: int = 1) -> dict:
    """Ventas agregadas por SKU en los últimos `dias` días."""
    since = ((_dt.datetime.now(_CO_TZ) - _dt.timedelta(days=int(dias)))
             .replace(hour=0, minute=0, second=0, microsecond=0).isoformat())
    orders = get_orders(since)
    ids = [str(o.get("OrderId")) for o in orders if o.get("OrderId")]
    items = _all_order_items(ids)
    agg = {}
    for it in items:
        sku = it.get("SellerSku") or it.get("Sku") or "??"
        row = agg.setdefault(sku, {"sku": sku, "nombre": it.get("Name", ""),
                                   "unidades": 0, "ingreso": 0.0})
        row["unidades"] += 1
        try:
            row["ingreso"] += float(it.get("ItemPrice")
                                    or it.get("PaidPrice") or 0)
        except (TypeError, ValueError):
            pass
    return {"desde": since, "ordenes": len(orders), "unidades": len(items),
            "por_sku": sorted(agg.values(), key=lambda r: -r["unidades"])}


def _bu_field(prod: dict, field: str):
    bu = _as_list((prod.get("BusinessUnits") or {}).get("BusinessUnit"))
    return bu[0].get(field) if bu else None


def get_products_list(limit: int = 100) -> list:
    """Catálogo: SellerSku, Name, Quantity(stock), Price, Status.
    El stock/precio/estado vive en BusinessUnits → se extrae de ahí.
    """
    out, off = [], 0
    while True:
        d = _get("GetProducts", {"Limit": str(limit), "Offset": str(off)})
        body = (d.get("SuccessResponse") or {}).get("Body") or {}
        page = _as_list((body.get("Products") or {}).get("Product"))
        for x in page:
            out.append({
                "SellerSku": x.get("SellerSku"),
                "Name": x.get("Name"),
                "Quantity": x.get("Quantity") or _bu_field(x, "Stock"),
                "Price": x.get("Price") or _bu_field(x, "Price"),
                "Status": x.get("Status") or _bu_field(x, "Status"),
            })
        if len(page) < limit:
            break
        off += limit
        if off > 3000:
            break
    return out


def set_stock(seller_sku, cantidad, dry: bool = False) -> dict:
    """Actualiza el stock de un SKU (ProductUpdate) por BusinessUnit/Operator.
    dry=True devuelve el XML sin enviar nada.
    """
    cantidad = int(cantidad)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><Request><Product>'
           '<SellerSku>%s</SellerSku>'
           '<BusinessUnits><BusinessUnit>'
           '<OperatorCode>%s</OperatorCode>'
           '<Stock>%d</Stock>'
           '</BusinessUnit></BusinessUnits>'
           '</Product></Request>'
           % (_su.escape(str(seller_sku)), _OPERATOR, cantidad))
    if dry:
        return {"dry_run": True, "sku": seller_sku, "cantidad": cantidad,
                "xml": xml}
    return _post("ProductUpdate", xml)


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
    """{OrderId → [(nombre, sku), …]} vía GetMultipleOrderItems (lotes).
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
                    ((it.get("Name") or "").strip(), str(it.get("Sku") or ""))
                    for it in items]
        except Exception:
            pass
    return out


def _product_images() -> dict:
    """{SellerSku → URL de imagen principal} del catálogo Falabella."""
    out, offset = {}, 0
    while True:
        try:
            d = _get("GetProducts", {"Limit": "100", "Offset": str(offset)})
        except Exception:
            break
        body = (d.get("SuccessResponse") or {}).get("Body") or {}
        prods = _as_list((body.get("Products") or {}).get("Product"))
        for p in prods:
            sku = str(p.get("SellerSku") or "")
            img = p.get("MainImage") or ""
            if not img:
                imgs = _as_list((p.get("Images") or {}).get("Image"))
                img = imgs[0] if imgs else ""
            if sku:
                out[sku] = img
        if len(prods) < 100:
            break
        offset += 100
        if offset > 3000:
            break
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
        # items reales por orden (unidades + nombre/sku para el top)
        imap = _items_by_order([i for i, _ in ids])
        for oid, ca in ids:
            if ca not in by:
                continue
            items = imap.get(oid, [])
            by[ca]["unidades"] += len(items)
            for nm, sku in items:
                key = sku or nm
                if not key:
                    continue
                e = by[ca]["_prod"].setdefault(
                    key, {"nombre": nm, "sku": sku, "unidades": 0})
                e["unidades"] += 1
                if nm and not e["nombre"]:
                    e["nombre"] = nm
        imgs = _product_images() if ids else {}
        dias = sorted(by.values(), key=lambda x: x["fecha"])
        for d in dias:
            d["ingresos"] = round(d["ingresos"], 2)
            # TODOS los productos del día, ordenados por unidades (top primero).
            top = sorted(d.pop("_prod").values(),
                         key=lambda v: -v["unidades"])
            d["top"] = [{"nombre": t["nombre"], "unidades": t["unidades"],
                         "img": imgs.get(t.get("sku") or "", "")} for t in top]
        return {"ok": True, "dias": dias}
    except Exception as e:
        return {"ok": False, "error": "Falabella: %s" % str(e)[:120]}
