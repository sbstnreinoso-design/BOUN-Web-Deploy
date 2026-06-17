"""
seo_publisher.py — Motor SEO + publicador multicanal de BOUN.

Objetivo: convertir un producto (SKU) en una publicación profesional lista
para MercadoLibre (como variante de una publicación existente) y Falabella
(como producto nuevo), maximizando descubrimiento por SEO.

Diseñado para ser REUTILIZABLE: cualquier producto BOUN se publica con el
mismo flujo. La inteligencia SEO vive aquí (server-side) y la consume tanto la
página `publicador.html` como los endpoints de `main.py`.

Tres capas:
  1) KEYWORDS  — corpus de búsquedas reales de MercadoLibre Colombia con pesos,
                 normalización (sin tildes/duplicados) y stoplist de conectores.
  2) TÍTULO    — armado por relevancia descendente, sin conectores (de/para/…),
                 respetando el límite de cada canal (ML=60).
  3) PAQUETE   — ensambla título + descripción + fotos + atributos por canal.

No hace I/O de red por sí mismo (salvo el cliente Falabella ProductCreate, que
es opcional). Las fotos/descripción/precio se inyectan desde el llamador
(Shopify/inventario), así el motor es testeable offline.
"""
from __future__ import annotations

import re
import os
import unicodedata
import xml.sax.saxutils as _su
from typing import Dict, List, Optional

# ───────────────────────────── Normalización ──────────────────────────────

# Conectores y palabras vacías que NO deben ir en un título SEO de marketplace.
# El usuario lo pidió explícito: "sin conectores como de, para, etc."
STOPWORDS = {
    "de", "del", "para", "por", "con", "sin", "los", "las", "el", "la", "un",
    "una", "unos", "unas", "y", "o", "u", "e", "a", "al", "en", "que", "su",
    "sus", "lo", "se", "es", "tu", "mi", "este", "esta", "como", "mas", "muy",
    "the", "of", "for", "and", "to", "with",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    """minúsculas, sin tildes, sin signos — para comparar/deduplicar."""
    s = _strip_accents((s or "").lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> List[str]:
    return [t for t in _norm(s).split(" ") if t]


def _is_connector(tok: str) -> bool:
    return _norm(tok) in STOPWORDS


# ───────────────────────────── Corpus SEO ─────────────────────────────────
# Pesos derivados de las búsquedas canónicas reales de MercadoLibre Colombia
# (URLs /listado.mercadolibre.com.co/<consulta>) + categorías Falabella.
# Cuanto más alto el peso, más demanda/relevancia. Se mantiene por "familia"
# de producto BOUN para que el motor escale a las 5 líneas.

# Frases núcleo por línea (intención de búsqueda dominante en CO).
FAMILY_PHRASES: Dict[str, List[tuple]] = {
    # (frase, peso)  — peso ~ volumen/relevancia relativa
    "sleep": [
        ("tapones oidos dormir", 100),
        ("protector auditivo dormir", 95),
        ("tapones auditivos dormir", 92),
        ("tapones para los oidos", 80),
        ("protectores auditivos", 78),
        ("tapa oidos dormir", 70),
        ("tapones oidos silicona", 68),
        ("protectores auditivos silicona", 66),
        ("tapones antirruido", 60),
        ("tapones aislantes ruido", 55),
        ("tapones reutilizables", 50),
    ],
    "moto": [
        ("tapones oidos moto", 100),
        ("protectores auditivos moto", 92),
        ("tapones oidos viento", 78),
        ("tapones antirruido moto", 75),
        ("protector auditivo motociclista", 70),
        ("tapones oidos silicona", 60),
        ("tapones reutilizables", 48),
    ],
    "music": [
        ("tapones oidos musicos", 100),
        ("protectores auditivos conciertos", 90),
        ("tapones oidos fiesta", 80),
        ("tapones alta fidelidad", 75),
        ("protector auditivo musica", 70),
        ("tapones reutilizables silicona", 55),
    ],
    "swim": [
        ("tapones oidos natacion", 100),
        ("tapones oidos agua", 92),
        ("protectores auditivos natacion", 85),
        ("tapones impermeables oidos", 78),
        ("tapones silicona natacion", 70),
        ("tapones oidos piscina", 65),
    ],
    "industrial": [
        ("protectores auditivos industriales", 100),
        ("tapones oidos industriales", 95),
        ("proteccion auditiva trabajo", 85),
        ("tapones seguridad industrial", 80),
        ("tapones oidos 40db", 70),
        ("protector auditivo epp", 60),
    ],
}

# Modificadores transversales que suben relevancia/CTR (se añaden si caben).
MODIFIERS = [
    ("silicona", 45),
    ("reutilizables", 42),
    ("antirruido", 40),
    ("comodos", 30),
    ("hipoalergenicos", 28),
    ("estuche", 25),
    ("premium", 22),
]

# Atributos de ficha técnica por línea (para ML/Falabella).
FAMILY_SPECS: Dict[str, Dict[str, str]] = {
    "sleep":      {"atenuacion": "24 dB", "uso": "Dormir", "material": "Silicona de grado médico"},
    "moto":       {"atenuacion": "23 dB", "uso": "Motociclismo", "material": "Silicona de grado médico"},
    "music":      {"atenuacion": "13/23/45 dB (3 filtros)", "uso": "Música y conciertos", "material": "Silicona de grado médico"},
    "swim":       {"atenuacion": "Impermeable", "uso": "Natación", "material": "Silicona de grado médico"},
    "industrial": {"atenuacion": "40 dB (SNR 30, EN-352)", "uso": "Industrial", "material": "Silicona de grado médico"},
}


# ───────────────────────────── Motor de título ────────────────────────────

# ─────────── Detección de línea + análisis de referencia (competencia) ──────

_FAMILY_RULES = [
    ("swim", ["natacion", "agua", "piscina", "nadar", "impermeable", "buceo"]),
    ("moto", ["moto", "motociclista", "viento", "casco", "motociclismo"]),
    ("music", ["musico", "concierto", "fiesta", "fidelidad", "dj", "musica", "festival"]),
    ("industrial", ["industrial", "trabajo", "obra", "epp", "seguridad", "taller"]),
    ("sleep", ["dormir", "sueno", "noche", "insomnio", "descanso", "roncar"]),
]


def detect_family(text: str) -> str:
    """Deduce la línea BOUN a partir del texto de referencia (o SKU)."""
    t = _norm(text)
    for fam, kws in _FAMILY_RULES:
        if any(k in t for k in kws):
            return fam
    return "sleep"


def analyze_reference(text: str, family: Optional[str] = None) -> Dict:
    """Genera el ranking de keywords A PARTIR de una publicación de referencia
    (URL o título de la competencia pegado), mezclado con el corpus de la línea.

    - Las frases del corpus que comparten palabras con la referencia suben.
    - Los bigramas nuevos de la referencia entran como candidatos (posición = peso).
    Así el SEO sale de la competencia real, no de una lista fija.
    """
    fam = family or detect_family(text)
    base = dict(FAMILY_PHRASES.get(fam, FAMILY_PHRASES["sleep"]))
    # Ignora specs numéricas de la competencia (p. ej. 32db): la atenuación la
    # manda SIEMPRE nuestra ficha, no la del aviso de referencia.
    def _is_spec_num(t):
        return bool(re.fullmatch(r"\d+", t) or re.fullmatch(r"\d+db", t) or t == "db")
    ref_toks = [t for t in _tokens(text)
                if not _is_connector(t) and len(t) > 1 and not _is_spec_num(t)]
    ref_stems = {_stem(t) for t in ref_toks}
    ranked: Dict[str, tuple] = {}
    for p, w in base.items():
        overlap = sum(1 for t in _tokens(p) if _stem(t) in ref_stems)
        ranked[_norm(p)] = (p, w + overlap * 12)
    # bigramas de la referencia que no estén ya cubiertos
    for i in range(len(ref_toks) - 1):
        bg = ref_toks[i] + " " + ref_toks[i + 1]
        n = _norm(bg)
        if n not in ranked:
            ranked[n] = (bg, 46 - min(i, 20))
    out = [{"kw": p, "peso": w, "tokens": _tokens(p)} for p, w in ranked.values()]
    out.sort(key=lambda r: -r["peso"])
    return {"family": fam, "keywords": out}


def rank_keywords(family: str, extra_terms: Optional[List[str]] = None) -> List[Dict]:
    """Devuelve keywords ordenadas por relevancia (peso desc), normalizadas y
    sin duplicar. Cada item: {kw, peso, tokens}."""
    fam = (family or "sleep").lower().strip()
    phrases = list(FAMILY_PHRASES.get(fam, FAMILY_PHRASES["sleep"]))
    for t in (extra_terms or []):
        phrases.append((t, 35))
    ranked, seen = [], set()
    for phrase, w in sorted(phrases, key=lambda x: -x[1]):
        n = _norm(phrase)
        if not n or n in seen:
            continue
        seen.add(n)
        ranked.append({"kw": phrase, "peso": w, "tokens": _tokens(phrase)})
    return ranked


# Raíces/sinónimos para deduplicar tokens morfológicamente equivalentes
# (auditivo/auditivos → auditiv) y evitar repeticiones feas en el título.
_STEM_MAP = {
    "auditivo": "auditiv", "auditivos": "auditiv", "auditiva": "auditiv",
    "protector": "protector", "protectores": "protector",
    "tapon": "tapon", "tapones": "tapon",
    "oido": "oid", "oidos": "oid",
    "tapa": "tapa", "tapaoidos": "oid",
    "reutilizable": "reutiliz", "reutilizables": "reutiliz",
    "comodo": "comod", "comodos": "comod",
}


def _stem(tok: str) -> str:
    n = _norm(tok)
    if n in _STEM_MAP:
        return _STEM_MAP[n]
    if n.endswith("es") and len(n) > 4:
        return n[:-2]
    if n.endswith("s") and len(n) > 3:
        return n[:-1]
    return n


def _title_case_seg(seg: str) -> str:
    out = []
    for tok in seg.split(" "):
        m = re.fullmatch(r"(\d+)\s*db", _norm(tok))
        if m:
            out.append(f"{m.group(1)}dB")
        elif _norm(tok).isdigit():
            out.append(tok)
        else:
            out.append(tok.capitalize())
    return _reaccent(" ".join(out))


def build_title(family: str, *, color: str = "", brand: str = "BOUN",
                max_len: int = 60, include_brand: bool = True,
                lead: str = "primary", color_first: bool = False,
                extra_terms: Optional[List[str]] = None,
                ranked: Optional[List[Dict]] = None) -> Dict:
    """Construye el título SEO óptimo ENSAMBLANDO SEGMENTOS COHERENTES por
    relevancia descendente, SIN conectores (de/para/los…) y SIN repetir raíces.

    A diferencia de un llenado token-a-token, aquí cada bloque es una unidad con
    sentido (frase núcleo, material, beneficio, spec, color, marca), lo que
    produce títulos limpios y profesionales que caben en `max_len`.

    `ranked` permite pasar un ranking propio (p. ej. de `analyze_reference`).
    """
    if ranked is None:
        ranked = rank_keywords(family, extra_terms)
    specs = FAMILY_SPECS.get((family or "sleep").lower(), FAMILY_SPECS["sleep"])

    # frase núcleo primaria (la #1) y una secundaria con cabeza distinta
    def _clean_phrase(p):
        toks = [t for t in _tokens(p) if not _is_connector(t)]
        return toks
    primary = _clean_phrase(ranked[0]["kw"]) if ranked else []
    secondary = []
    for kw in ranked[1:]:
        toks = _clean_phrase(kw["kw"])
        if toks and _stem(toks[0]) != _stem(primary[0] if primary else ""):
            secondary = toks
            break
    lead_toks = secondary if (lead == "secondary" and secondary) else primary

    # spec de atenuación como segmento corto (24 dB → 24dB)
    att = specs.get("atenuacion", "")
    m = re.search(r"(\d+)\s*db", _norm(att))
    spec_seg = f"{m.group(1)}db" if m else ""

    # cola: modificadores de mayor a menor relevancia para CTR + spec + color
    tail = ["silicona", "reutilizables", "antirruido"]
    if spec_seg:
        tail.append(spec_seg)
    tail += ["comodos", "hipoalergenicos", "estuche"]

    # construir lista priorizada de SEGMENTOS (cada uno = lista de tokens)
    segments: List[List[str]] = []
    if lead_toks:
        segments.append(lead_toks)
    # color justo tras la cabeza si se pide diferenciación por variante
    if color_first and color:
        segments.append([color])
    # primero los modificadores fuertes (material, beneficio, spec) → títulos
    # limpios y de alta conversión; la segunda cabeza va después si sobra espacio
    for t in tail:
        segments.append([t])
    # segunda cabeza para ampliar cobertura SEO (si no es la que ya lideró)
    other_head = primary if lead_toks is secondary else secondary
    if other_head:
        segments.append(other_head)
    if color:
        segments.append([color])
    if include_brand and brand:
        segments.append([brand])

    # ensamblar: agregar tokens nuevos (por raíz) de cada segmento si caben
    used_stems = set()
    display_segs: List[str] = []

    def _cur_len(extra_seg=""):
        parts = display_segs + ([extra_seg] if extra_seg else [])
        return len(" ".join(parts))

    for seg in segments:
        new_toks = [t for t in seg
                    if _stem(t) not in used_stems and not _is_connector(t)]
        if not new_toks:
            continue
        seg_txt = _title_case_seg(" ".join(new_toks))
        # marca siempre en mayúscula
        if include_brand and len(new_toks) == 1 and _norm(new_toks[0]) == _norm(brand):
            seg_txt = brand.upper()
        sep = " " if display_segs else ""
        if _cur_len() + len(sep) + len(seg_txt) > max_len:
            continue
        display_segs.append(seg_txt)
        for t in new_toks:
            used_stems.add(_stem(t))

    title = " ".join(display_segs)
    return {
        "titulo": title,
        "largo": len(title),
        "max_len": max_len,
        "tokens": sorted(used_stems),
        "keywords_rank": ranked,
        "sin_conectores": True,
    }


_REACCENT = {
    "Oidos": "Oídos", "Musica": "Música", "Musicos": "Músicos",
    "Comodos": "Cómodos", "Natacion": "Natación", "Hipoalergenicos": "Hipoalergénicos",
    "Proteccion": "Protección",
}


def _reaccent(title: str) -> str:
    out = []
    for w in title.split(" "):
        out.append(_REACCENT.get(w, w))
    return " ".join(out)


def title_variants(family: str, *, color: str = "", brand: str = "BOUN",
                   max_len: int = 60,
                   ranked: Optional[List[Dict]] = None) -> List[str]:
    """3 variantes de título para que el humano elija (A/B testing).
    Si se pasa `ranked` (p. ej. de analyze_reference), se usa ese ranking."""
    # A) máxima cobertura SEO (sin marca ni color → más keywords)
    a = build_title(family, color="", brand=brand, max_len=max_len,
                    include_brand=False, ranked=ranked)["titulo"]
    # B) con color de la variante temprano (diferenciación)
    b = build_title(family, color=color, brand=brand, max_len=max_len,
                    include_brand=False, color_first=bool(color), ranked=ranked)["titulo"]
    # C) liderada por la cabeza secundaria (otra entrada de búsqueda)
    c = build_title(family, color=color, brand=brand, max_len=max_len,
                    include_brand=False, lead="secondary", ranked=ranked)["titulo"]
    out, seen = [], set()
    for t in (a, b, c):
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_long_title(family: str, *, color: str = "", brand: str = "BOUN",
                     max_len: int = 200,
                     ranked: Optional[List[Dict]] = None) -> Dict:
    """Título largo (catálogo / ficha): empaqueta TODAS las keywords relevantes
    por orden de peso, sin conectores ni raíces repetidas, hasta `max_len`."""
    if ranked is None:
        ranked = rank_keywords(family)
    specs = FAMILY_SPECS.get((family or "sleep").lower(), FAMILY_SPECS["sleep"])
    used, disp = set(), []
    # cabeza: la frase #1 completa
    head = [t for t in (ranked[0]["tokens"] if ranked else []) if not _is_connector(t)]
    for t in head:
        if _stem(t) not in used:
            used.add(_stem(t)); disp.append(t)
    # color y marca temprano
    extras = ([color] if color else []) + ["silicona", "reutilizables",
              "antirruido", "hipoalergenicos", "comodos", "estuche"]
    m = re.search(r"(\d+)\s*db", _norm(specs.get("atenuacion", "")))
    if m:
        extras.insert(3, f"{m.group(1)}db")
    pool = []
    for kw in ranked:
        pool += kw["tokens"]
    pool += extras
    if brand:
        pool.append(brand)
    for tok in pool:
        n = _norm(tok)
        if not n or _is_connector(n) or _stem(tok) in used:
            continue
        cand = disp + [tok]
        if len(_title_case_seg(" ".join(cand))) > max_len:
            continue
        used.add(_stem(tok)); disp.append(tok)
    title = _title_case_seg(" ".join(disp))
    if brand and _norm(brand) in {_norm(d) for d in disp}:
        title = re.sub(rf"\b{re.escape(brand)}\b", brand.upper(), title, flags=re.I)
    return {"titulo": title, "largo": len(title), "max_len": max_len}


def build_features(family: str, *, color: str = "") -> List[str]:
    """Lista de características (bullets) para la sección bajo la ficha técnica."""
    fam = (family or "sleep").lower()
    specs = FAMILY_SPECS.get(fam, FAMILY_SPECS["sleep"])
    base = [
        f"Atenuación de ruido {specs['atenuacion']}",
        f"{specs['material']}: suave e hipoalergénica",
        "Reutilizables y lavables (no son desechables)",
        "Ajuste ergonómico sin presión en el canal auditivo",
        "Cómodos para uso prolongado, incluso de lado",
        "Incluyen estuche compacto de transporte",
        "Libres de látex",
    ]
    extra = {
        "sleep": ["Bloquean ronquidos, tráfico y vecinos para dormir mejor",
                  "Ideales para sueño ligero, turnos nocturnos y viajes"],
        "moto": ["Reducen la fatiga auditiva por viento a alta velocidad",
                 "Compatibles con casco integral"],
        "music": ["Filtros que bajan el volumen sin distorsionar la música",
                  "Para músicos, conciertos, DJ y festivales"],
        "swim": ["Sellan el oído contra el agua",
                 "Para natación, ducha y deportes acuáticos"],
        "industrial": ["Cumplen referencia de seguridad industrial (EN-352)",
                       "Para obra, planta y entornos de alto ruido"],
    }.get(fam, [])
    if color:
        base.append(f"Color {color.capitalize()}")
    return extra + base


# ───────────────────────────── Descripción ────────────────────────────────

# Buenas prácticas de fotos de MercadoLibre (para la sección de fotos).
ML_PHOTO_RULES = [
    "Foto principal con fondo blanco puro (#FFFFFF), solo el producto",
    "Resolución mínima 1200×1200 px (habilita el zoom)",
    "El producto debe ocupar ~70% del encuadre, centrado",
    "Sin texto, logos ni marcas de agua sobre la imagen",
    "Mínimo 8 fotos: ángulos, detalle, escala y producto en uso",
    "Fotos secundarias pueden tener contexto/lifestyle",
    "Formato JPG/PNG, cuadrada (1:1), buena iluminación",
]


def build_description(family: str, *, color: str = "", price: int = 0,
                      ranked: Optional[List[Dict]] = None) -> str:
    """Descripción larga y rica en keywords, en voz BOUN (tuteo, beneficio
    primero). Teje las keywords relevantes de forma natural para SEO sin caer en
    relleno. No usa el HTML/CSS del landing; redacta limpio para ML/Falabella.
    """
    fam = (family or "sleep").lower()
    specs = FAMILY_SPECS.get(fam, FAMILY_SPECS["sleep"])
    color_txt = f" en color {color.capitalize()}" if color else ""
    benefit = {
        "sleep": "Duerme profundo sin que el ruido te despierte.",
        "moto": "Rueda sin que el viento y el motor te agoten el oído.",
        "music": "Disfruta la música nítida, a un volumen seguro.",
        "swim": "Nada con los oídos protegidos del agua.",
        "industrial": "Trabaja protegido del ruido, todo el turno.",
    }.get(fam, "Protege tus oídos con comodidad real.")
    # frase de keywords (las más relevantes, como sinónimos de búsqueda)
    kws = ranked or rank_keywords(fam)
    syn = []
    for k in kws[:6]:
        s = k["kw"].strip()
        if s and s.lower() not in [x.lower() for x in syn]:
            syn.append(s)
    syn_line = (", ".join(syn[:5])).rstrip(".")
    feats = build_features(fam, color=color)
    bullets = "\n".join(f"✔ {f}" for f in feats)
    return (
        f"{benefit}\n\n"
        f"Los protectores auditivos BOUN{color_txt} están fabricados en "
        f"{specs['material'].lower()}: suave, hipoalergénica, sin látex y "
        f"reutilizable. Se ajustan al canal auditivo sin presión y se sienten "
        f"cómodos durante horas, ideales para {specs['uso'].lower()}. "
        f"Bloquean el ruido con una atenuación de {specs['atenuacion']}, "
        f"manteniendo tu oído seguro y descansado.\n\n"
        f"También conocidos como: {syn_line}.\n\n"
        f"CARACTERÍSTICAS\n{bullets}\n\n"
        f"FICHA TÉCNICA\n"
        f"• Atenuación: {specs['atenuacion']}\n"
        f"• Uso: {specs['uso']}\n"
        f"• Material: {specs['material']}\n"
        f"• Color: {color or '—'}\n"
        f"• Reutilizables: Sí · Estuche incluido: Sí\n\n"
        f"¿POR QUÉ BOUN?\n"
        f"BOUN es una marca colombiana de protección auditiva premium. "
        f"Tienda Oficial y MercadoLíder, con miles de clientes y excelente "
        f"calificación. Compra con garantía, factura y envío a todo el país.\n\n"
        f"Haz tu pedido hoy y protege tus oídos con la comodidad que mereces."
    )


# ───────────────────────────── Paquete final ──────────────────────────────

def build_package(*, sku: str, family: str, color: str = "",
                  price: int = 0, list_price: int = 0,
                  photos: Optional[List[str]] = None,
                  ml_parent_ids: Optional[List[str]] = None,
                  brand: str = "BOUN") -> Dict:
    """Ensambla el paquete completo de publicación para los dos canales.

    Devuelve un dict listo para previsualizar y para alimentar a los
    publicadores (`publish_falabella`, guía ML).
    """
    photos = [p for p in (photos or []) if p]
    titles = title_variants(family, color=color, brand=brand, max_len=60)
    ranked = rank_keywords(family)
    specs = FAMILY_SPECS.get((family or "sleep").lower(), FAMILY_SPECS["sleep"])
    desc = build_description(family, color=color, price=price)
    # tags ML (hasta ~6 keywords sueltas relevantes, sin conectores)
    tag_pool: List[str] = []
    for kw in ranked:
        for tok in kw["tokens"]:
            if not _is_connector(tok) and tok not in tag_pool:
                tag_pool.append(tok)
    tags = tag_pool[:8]
    return {
        "sku": sku,
        "familia": family,
        "color": color,
        "marca": brand,
        "precio": price,
        "precio_lista": list_price,
        "titulo_recomendado": titles[0] if titles else "",
        "titulos_alternativos": titles[1:],
        "descripcion": desc,
        "fotos": photos,
        "atributos": specs,
        "tags": tags,
        "keywords_rank": ranked,
        "ml": {
            "parent_ids": ml_parent_ids or [],
            "modo": "variante",
            "titulo_max": 60,
        },
        "falabella": {
            "modo": "producto_nuevo",
            "seller_sku": sku,
            "categoria_sugerida": "Protección Auditiva",
        },
    }


# ───────────────── Cliente Falabella · ProductCreate (opcional) ────────────
# Reusa la firma HMAC del módulo falabella.py si está disponible.

def publish_falabella(pkg: Dict, *, category_id: str,
                      brand: str = "BOUN", dry: bool = True) -> Dict:
    """Crea el producto en Falabella vía ProductCreate (Sellercenter API).

    dry=True devuelve el XML que se enviaría SIN publicar (para revisión).
    Requiere FALABELLA_API_USER / FALABELLA_API_KEY en el entorno cuando dry=False.
    """
    sku = pkg["sku"]
    title = pkg["titulo_recomendado"]
    desc_html = "<p>" + _su.escape(pkg["descripcion"]).replace("\n", "<br/>") + "</p>"
    price = int(pkg.get("precio") or 0)
    specs = pkg.get("atributos", {})
    imgs = pkg.get("fotos", [])
    img_xml = "".join("<Image>%s</Image>" % _su.escape(u) for u in imgs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><Request><Product>'
        f"<SellerSku>{_su.escape(sku)}</SellerSku>"
        f"<Name>{_su.escape(title)}</Name>"
        f"<Brand>{_su.escape(brand)}</Brand>"
        f"<Description>{desc_html}</Description>"
        f"<PrimaryCategory>{_su.escape(str(category_id))}</PrimaryCategory>"
        f"<Price>{price}</Price>"
        "<ProductData>"
        f"<Atenuacion>{_su.escape(specs.get('atenuacion',''))}</Atenuacion>"
        f"<Material>{_su.escape(specs.get('material',''))}</Material>"
        "</ProductData>"
        f"<Images>{img_xml}</Images>"
        "</Product></Request>"
    )
    if dry:
        return {"dry_run": True, "sku": sku, "categoria": category_id, "xml": xml}
    # publicación real: usa el _post firmado de falabella.py
    try:
        from . import falabella as _fb  # type: ignore
    except Exception:
        import falabella as _fb  # type: ignore
    return _fb._post("ProductCreate", xml)
