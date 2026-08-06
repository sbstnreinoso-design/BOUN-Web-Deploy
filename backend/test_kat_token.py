"""Pruebas de la capa de token de la cuenta KAT (ml_scraper).

Simula la API de ML y la tabla settings para cubrir los modos de fallo que
sacaban el canal KAT del escaneo. Sin red y sin base de datos reales.
"""
import sys, types, time, threading

# ── Stubs de dependencias pesadas antes de importar ml_scraper ───────────────
SETTINGS = {}

db_stub = types.ModuleType("database")
db_stub.get_setting = lambda k, d="": SETTINGS.get(k, d)
def _set(k, v): SETTINGS[k] = v
db_stub.set_setting = _set
sys.modules["database"] = db_stub

CALLS = {"refresh": 0, "me": 0, "refresh_bodies": []}
SCRIPT = {}          # comportamiento programable por test


class FakeResp:
    def __init__(self, code, payload=None, text=""):
        self.status_code = code
        self._payload = payload if payload is not None else {}
        self.text = text or ""
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.headers = {}
    def post(self, url, data=None, headers=None, timeout=None):
        CALLS["refresh"] += 1
        CALLS["refresh_bodies"].append(dict(data or {}))
        return SCRIPT["refresh"](data or {})
    def get(self, url, timeout=None, headers=None):
        if url.endswith("/users/me"):
            CALLS["me"] += 1
            return SCRIPT["me"](self.headers.get("Authorization", ""))
        raise AssertionError("GET inesperado: " + url)
    def request(self, *a, **k):
        raise AssertionError("no usado")


import ml_scraper as M
M._get_session = lambda: FakeSession()
M.time.sleep = lambda s: None          # sin esperas reales en los tests


def reset(settings=None, refresh=None, me=None):
    SETTINGS.clear()
    SETTINGS.update(settings or {})
    CALLS.update({"refresh": 0, "me": 0})
    CALLS["refresh_bodies"] = []
    SCRIPT["refresh"] = refresh or (lambda d: FakeResp(400, text="invalid_grant"))
    SCRIPT["me"] = me or (lambda auth: FakeResp(401, text="invalid token"))
    # limpiar cachés en proceso
    M._KAT_TOK_CACHE.update({"token": "", "ts": 0.0})
    M._KAT_VERIFIED.update({"token": "", "uid": None, "ts": 0.0})
    M._KAT_ERR_CACHE["msg"] = None


def base_settings(**kw):
    s = {"ml_kat_access_token": "TOK_VIEJO",
         "ml_kat_refresh_token": "REF_1",
         "ml_kat_token_ts": str(time.time()),
         "ml_app_id": "APP", "ml_client_secret": "SECRET"}
    s.update(kw)
    return s


def refresh_ok(nuevo="TOK_NUEVO", nuevo_ref="REF_2"):
    def _r(d):
        return FakeResp(200, {"access_token": nuevo, "refresh_token": nuevo_ref})
    return _r


def me_acepta(*tokens):
    ok = {"Bearer " + t for t in tokens}
    def _m(auth):
        return FakeResp(200, {"id": 536057274}) if auth in ok else FakeResp(401, text="invalid token")
    return _m


FALLOS = []
def check(nombre, cond, extra=""):
    print(("  OK   " if cond else "  FALLA") + " · " + nombre + (" — " + extra if extra and not cond else ""))
    if not cond:
        FALLOS.append(nombre)


print("\n=== 1. Token vigente y válido → NO refresca, entra directo ===")
reset(base_settings(), refresh_ok(), me_acepta("TOK_VIEJO"))
s, uid = M._ml_kat_session_auth()
check("entra a KAT", s is not None and uid == 536057274)
check("no refrescó de más", CALLS["refresh"] == 0, "refresh=%d" % CALLS["refresh"])

print("\n=== 2. CAUSA RAÍZ: token vigente por TTL pero ML lo rechaza (401) ===")
print("     Antes: se rendía y el canal KAT quedaba fuera del escaneo.")
reset(base_settings(), refresh_ok(), me_acepta("TOK_NUEVO"))
s, uid = M._ml_kat_session_auth()
check("se recupera solo refrescando", s is not None and uid == 536057274)
check("refrescó exactamente 1 vez", CALLS["refresh"] == 1, "refresh=%d" % CALLS["refresh"])
check("no dejó error pendiente", M.get_kat_auth_error() == "", M.get_kat_auth_error())

print("\n=== 3. Access token vacío pero con refresh_token → recuperable ===")
reset(base_settings(ml_kat_access_token=""), refresh_ok(), me_acepta("TOK_NUEVO"))
s, uid = M._ml_kat_session_auth()
check("recupera el token en vez de rendirse", s is not None and uid == 536057274)

print("\n=== 4. Token vencido por TTL → refresca proactivamente ===")
reset(base_settings(ml_kat_token_ts=str(time.time() - M.TOKEN_TTL - 10)),
      refresh_ok(), me_acepta("TOK_NUEVO"))
s, uid = M._ml_kat_session_auth()
check("refresca antes de usarlo", s is not None and CALLS["refresh"] == 1)

print("\n=== 5. Hipo de red en el refresh (2 fallos y luego OK) → reintenta ===")
intentos = {"n": 0}
def refresh_flaky(d):
    intentos["n"] += 1
    if intentos["n"] < 3:
        raise Exception("connection reset")
    return FakeResp(200, {"access_token": "TOK_NUEVO", "refresh_token": "REF_2"})
reset(base_settings(ml_kat_access_token=""), refresh_flaky, me_acepta("TOK_NUEVO"))
s, uid = M._ml_kat_session_auth()
check("sobrevive al hipo de red", s is not None, "intentos=%d" % intentos["n"])

print("\n=== 6. ML 503 en el refresh → reintenta; si insiste, error claro ===")
reset(base_settings(ml_kat_access_token=""), lambda d: FakeResp(503, text="upstream"), me_acepta("X"))
s, uid = M._ml_kat_session_auth()
check("no entra (correcto)", s is None)
check("reintentó 3 veces", CALLS["refresh"] == 3, "refresh=%d" % CALLS["refresh"])
check("deja motivo legible", "No se pudo refrescar" in M.get_kat_auth_error(), M.get_kat_auth_error())

print("\n=== 7. invalid_grant (autorización revocada) → terminal, sin reintentos ===")
reset(base_settings(ml_kat_access_token=""),
      lambda d: FakeResp(400, text='{"error":"invalid_grant"}'), me_acepta("X"))
s, uid = M._ml_kat_session_auth()
check("no entra", s is None)
check("NO reintenta en vano", CALLS["refresh"] == 1, "refresh=%d" % CALLS["refresh"])
check("pide reconexión explícita", "reconectarla" in M.get_kat_auth_error(), M.get_kat_auth_error())

print("\n=== 8. Carrera: 2 escaneos refrescan a la vez (refresh de UN SOLO USO) ===")
print("     Antes: el segundo quemaba el refresh_token y perdía el canal.")
usados = set()
lock_r = threading.Lock()
def refresh_un_solo_uso(d):
    ref = d.get("refresh_token")
    with lock_r:
        if ref in usados:
            return FakeResp(400, text='{"error":"invalid_grant"}')
        usados.add(ref)
    return FakeResp(200, {"access_token": "TOK_NUEVO", "refresh_token": "REF_2"})
reset(base_settings(ml_kat_access_token=""), refresh_un_solo_uso, me_acepta("TOK_NUEVO"))
res = []
def worker():
    res.append(M._ml_kat_session_auth()[1])
hilos = [threading.Thread(target=worker) for _ in range(2)]
[h.start() for h in hilos]; [h.join() for h in hilos]
check("los DOS escaneos entran", res.count(536057274) == 2, "resultados=%r" % res)
check("solo se consumió 1 refresh_token", CALLS["refresh"] == 1, "refresh=%d" % CALLS["refresh"])

print("\n=== 9. Caché: N peticiones seguidas no disparan N veces /users/me ===")
reset(base_settings(), refresh_ok(), me_acepta("TOK_VIEJO"))
for _ in range(50):
    M._ml_kat_session_auth()
check("un solo /users/me para 50 llamadas", CALLS["me"] == 1, "me=%d" % CALLS["me"])

print("\n=== 10. force_refresh ignora la caché (tras un 401 a mitad de corrida) ===")
reset(base_settings(), refresh_ok(), me_acepta("TOK_VIEJO", "TOK_NUEVO"))
M._ml_kat_session_auth()
antes = CALLS["refresh"]
s, uid = M._ml_kat_session_auth(force_refresh=True)
check("fuerza token nuevo", s is not None and CALLS["refresh"] == antes + 1)

print("\n=== 11. Cuenta nunca autorizada → ausencia esperada, NO error ===")
reset({"ml_app_id": "APP", "ml_client_secret": "SECRET"}, refresh_ok(), me_acepta("X"))
s, uid = M._ml_kat_session_auth()
check("no entra", s is None)
check("kat_is_authorized() = False", M.kat_is_authorized() is False)
check("no inventa un error", M.get_kat_auth_error() == "", M.get_kat_auth_error())

print("\n=== 12. Cuenta autorizada se distingue de nunca autorizada ===")
reset(base_settings(), refresh_ok(), me_acepta("TOK_VIEJO"))
check("kat_is_authorized() = True", M.kat_is_authorized() is True)

print("\n=== 13. get_my_items_basic: 401 a mitad del listado → reautentica ===")
print("     150 publicaciones = 2 páginas; el token muere tras la 1ª.")
TOTAL_PUBS = 150
estado = {"paginas_con_token_viejo": 0}
class SessListado(FakeSession):
    def get(self, url, timeout=None, headers=None):
        auth = self.headers.get("Authorization", "")
        if url.endswith("/users/me"):
            CALLS["me"] += 1
            return (FakeResp(200, {"id": 7})
                    if auth in ("Bearer TOK_VIEJO", "Bearer TOK_NUEVO")
                    else FakeResp(401))
        if "/items/search" in url:
            off = int(url.split("offset=")[1])
            # El token viejo sirve para la 1ª página y luego lo revocan.
            if auth == "Bearer TOK_VIEJO":
                if estado["paginas_con_token_viejo"] >= 1:
                    return FakeResp(401, text="expired")
                estado["paginas_con_token_viejo"] += 1
            ids = ["MCO%d" % (off + i)
                   for i in range(min(100, max(0, TOTAL_PUBS - off)))]
            return FakeResp(200, {"results": ids,
                                  "paging": {"total": TOTAL_PUBS}})
        if "/items?ids=" in url:
            ids = url.split("ids=")[1].split("&")[0].split(",")
            return FakeResp(200, [{"code": 200, "body": {"id": i, "title": "t",
                                   "seller_custom_field": "BOUN-1"}} for i in ids])
        return FakeResp(404)
reset(base_settings(), refresh_ok(), None)
M._get_session = lambda: SessListado()
r = M.get_my_items_basic(acct="kat")
M._get_session = lambda: FakeSession()
check("lista COMPLETA pese al 401 a mitad", r.get("ok") and len(r.get("items", [])) == TOTAL_PUBS,
      "ok=%r n=%d err=%r" % (r.get("ok"), len(r.get("items", []) or []), r.get("error")))
check("refrescó para recuperarse", CALLS["refresh"] == 1, "refresh=%d" % CALLS["refresh"])

print("\n=== 14. Fallo de lectura NO se confunde con 'catálogo vacío' ===")
class SessCaida(FakeSession):
    def get(self, url, timeout=None, headers=None):
        if url.endswith("/users/me"):
            return FakeResp(200, {"id": 7})
        return FakeResp(500, text="boom")
reset(base_settings(), refresh_ok(), None)
M._get_session = lambda: SessCaida()
r = M.get_my_items_basic(acct="kat")
M._get_session = lambda: FakeSession()
check("reporta el fallo real", (not r.get("ok")) and "HTTP 500" in (r.get("error") or ""),
      "error=%r" % r.get("error"))
check("marca auth_error para que el canal salga caído", r.get("auth_error") is True)

print("\n" + "=" * 62)
if FALLOS:
    print("FALLARON %d prueba(s): %s" % (len(FALLOS), ", ".join(FALLOS)))
    sys.exit(1)
print("TODAS LAS PRUEBAS PASARON")
