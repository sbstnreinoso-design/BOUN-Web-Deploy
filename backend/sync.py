"""
Motor de sincronización de stock (Fase 1 — cálculo y reparto, modo DRY-RUN).

- Mapeo Falabella (SellerSku ↔ código BOUN) embebido desde el CSV de referencia.
- Reparto del disponible entre las publicaciones activas de cada canal:
  floor(disponible / nº_activas) y el resto a la de más ventas.

NO escribe en ningún canal: solo calcula el "plan". La propagación real (ML
set-stock, Falabella set-stock, Shopify) se conecta después de validar.
"""

# SellerSku_Falabella, SKU_Falabella_ID, Codigo_BOUN  (del CSV 2026-06-14)
_FAL_CSV = """\
003,120800212,CNCT-OTG-NARANJA
085,120464532,FND-AIRTAG-MASCOTA-BLANCA
087,120674683,FND-AIRTAG-MASCOTA-ROSA
091,120699365,FND-AIRTAG-MASCOTA-ROSA
094,120699823,FND-AIRTAG-MASCOTA-ROJA
095,120778882,FND-AIRTAG-MASCOTA-AZUL
840,132424454,CLLR-GATO-NEGRO
850,132424416,CLLR-GATO-ROSA
860,132424143,CLLR-GATO-AZUL
870,132424559,CG 034 - ROJO
880,132423604,CLLR-GATO-MORADO
890,132424341,CLLR-GATO-AMARILLO
027,139003376,COR-SILI-ZAPATOS-BLANCO
028,139003375,COR-SILI-ZAPATOS-NEGRO
308,132425754,MNG-PRTOECCION-BLANCA
2322,150849980,MNG-PRTOECCION-BLANCA
234342,150849851,MNG-PRTOECCION-NEGRA
45433,153577013,BOLSO-PUMA-TB-NEGRO
432422,153577012,BOLSO-PUMA-TB-NEGRO
3453,150850927,TAR-RFID-NEGRO
142,120210710,PLA 028
176,132933613,MA 013
0811,139003963,GD 018 GRIS
5454,151573167,GD 017 ROSADO
36556,150731616,PW025
2343,150850218,PP012
53445,150916595,MD 016- NEGRO
3424,150916670,GSC 026
4344,150918498,BLC 027
7899,150815194,PA 003-ARSENISCA
1420,139050545,PA005
454,150664614,PA004-BLANCO-NEGRO
206,139052728,GF021
545454,150922894,GF021
5666,151379698,KAT ASTRO
1231231,153571868,KATCOSMOS
777,154898576,KATLUNA
0997,154900568,KATKRUNCH
143,120211709,SET 011
3233,150849623,SET 011
192,139063244,GP022-CAMUFLADO
193,139063243,GP022-BEIGE
194,139063242,GP023-NEGRO
334,122065550,PF 015
43433,150918973,BALACLAVA-MOTO-NEGRA
125,139048445,PA 014- AZUL
PAAZUL-DORMIR,154952963,PA 014- AZUL
4323,151379342,PA 030 - PLATA
4545,151379292,PA 030 - PLATA
23332,151379475,PA 030 - VERDE
7878,151378964,PA 030 - ORO-ROSA
199,120800539,PA006-NEGRO
198,120248677,PA 014- AZUL
1460,139050537,PA006-NEGRO
PAOO2-CONCIERTOS,154953045,PA001BAG-NEGRO-EST-BOUN
4343,150665456,PA001BAG-NEGRO-EST-BOUN
110011,153096079,PA001BAG-NEGRO-EST-BOUN
311,122065764,PA005
138,122065301,PA-ESP-120
105,139046587,PA-ESP-120
270,132932246,PA007
4020,132933501,PA007
4234,150692787,PA007
333,150663292,PA003-NEGRO
8373838,150717582,PA003-NEGRO
336,150664525,PA001BAG-NEGRO
3356,150664310,PA-SILVER
335,150663529,PA008
110012,153097566,PA008
54454,150731341,PA009
898,151576978,PA 031 NEGRO MATE
4544,151575488,PA 031 ARSENISCA EDGE
SLEEP24-NEGRO,154950120,PA002
3566,150691070,PA-BEBES-AQUA
"""


def _norm(c: str) -> str:
    """Normaliza un código: colapsa espacios múltiples y recorta, para que
    'CG  034 - ROJO' (inventario) cruce con 'CG 034 - ROJO' (CSV)."""
    return " ".join((c or "").split())


def _build_fal_map():
    m = {}
    for line in _FAL_CSV.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        seller_sku, fal_id, codigo = parts[0], parts[1], _norm(parts[2])
        m.setdefault(codigo, []).append({"seller_sku": seller_sku,
                                         "fal_id": fal_id})
    return m


# {codigo_boun (normalizado): [{seller_sku, fal_id}, …]}
FAL_MAP = _build_fal_map()


def falabella_skus(codigo_boun: str) -> list:
    return FAL_MAP.get(_norm(codigo_boun), [])


def reparto(disponible: int, pubs: list) -> dict:
    """Reparte `disponible` entre publicaciones activas.
    pubs: [{"key": <id>, "ventas": <int>}, …]
    Devuelve {key: cantidad}. floor(disp/n) a todas, el resto a la de más
    ventas. Si disponible <= 0 → 0 a todas.
    """
    n = len(pubs)
    if n == 0:
        return {}
    if disponible <= 0:
        return {p["key"]: 0 for p in pubs}
    base = disponible // n
    resto = disponible - base * n
    out = {p["key"]: base for p in pubs}
    if resto > 0:
        # el resto va a la(s) de más ventas
        orden = sorted(pubs, key=lambda p: -(p.get("ventas") or 0))
        for i in range(resto):
            out[orden[i % n]["key"]] += 1
    return out
