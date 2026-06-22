-- ───────────────────────────────────────────────────────────────────────────
-- denuncias → reporte vivo de la sección "Denuncias" (Brand Protection Program).
-- ───────────────────────────────────────────────────────────────────────────
-- Cada fila = una denuncia presentada en el Brand Protection Program (BPP) de
-- MercadoLibre contra un vendedor que usa la marca registrada BOUN sin
-- autorización (se cuelga de un catálogo BOUN o publica producto que exhibe la
-- marca sin haberlo fabricado el titular).
--
-- La skill "detectar-denunciar-marca" la refresca a diario (8:00 PM):
--   1) detecta infractores (catálogo Marca:BOUN con vendedor ≠ BOUN COLOMBIA),
--   2) denuncia y envía,
--   3) revisa el estado de las denuncias de días anteriores,
--   4) hace upsert de cada fila aquí (por seller_nick + catalog_id) y reporta a
--      la sección /denuncias de la web y al Cerebro.
--
-- Identidad de una denuncia = (seller_nick, catalog_id): un vendedor colgándose
-- de un catálogo BOUN = una sola fila viva (el scan hace upsert y actualiza
-- estado/fecha). El mismo vendedor en otro catálogo = otra fila.
--
-- Estados (campo `estado`):
--   · pendiente             → marcada como sospechosa, aún sin enviar.
--   · en_proceso            → denuncia enviada; ML la está evaluando ("En proceso").
--   · procedente            → ML aceptó la denuncia y dio de baja la publicación.
--   · rechazada             → ML rechazó la denuncia.
--   · publicacion_inactiva  → la publicación infractora ya no está activa (cayó).
--
-- Idempotente: se puede correr varias veces sin romper nada.
-- Supabase → SQL Editor → pegar → Run.
-- ───────────────────────────────────────────────────────────────────────────

create table if not exists public.denuncias (
  id              bigint generated always as identity primary key,

  -- ── Infractor ──
  seller_nick     text not null,                 -- nick del vendedor infractor (ej. MARIABEDUTT)
  seller_link     text,                          -- URL al perfil / historial del vendedor

  -- ── Publicación infractora ──
  pub_id          text,                          -- MCO de la publicación del infractor
  pub_title       text,
  pub_link        text,                          -- URL pública a la publicación infractora
  pub_price       numeric default 0,
  thumb           text,                          -- foto (para identificarla en la web)

  -- ── Catálogo BOUN usurpado ──
  catalog_id      text not null,                 -- MCO del catálogo (Marca: BOUN) usurpado
  catalog_title   text,
  catalog_link    text,                          -- URL a la ficha de catálogo

  -- ── Denuncia ──
  motivo          text not null default 'marca_registrada', -- marca_registrada | falsificado | uso_ilegal_marca
  tipo_infraccion text,                          -- texto exacto elegido en el BPP ("Es un producto falsificado")
  texto           text,                          -- declaración enviada al BPP (visible al vendedor)
  estado          text not null default 'en_proceso', -- ver leyenda arriba

  -- ── Fechas / ciclo de vida ──
  denunciado_at   timestamptz not null default now(),  -- cuándo se presentó
  revisado_at     timestamptz not null default now(),  -- última revisión de estado por la skill
  resuelto        boolean not null default false,      -- true cuando cae la pub o cierra el caso
  resuelto_at     timestamptz,
  historial       jsonb not null default '[]'::jsonb   -- [{fecha, estado, nota}] para la traza diaria
);

-- Una denuncia viva por (vendedor, catálogo): el scan diario hace upsert.
create unique index if not exists denuncias_seller_catalog_uidx
  on public.denuncias (seller_nick, catalog_id);

create index if not exists denuncias_estado_idx   on public.denuncias (estado);
create index if not exists denuncias_resuelto_idx on public.denuncias (resuelto);
create index if not exists denuncias_fecha_idx    on public.denuncias (denunciado_at desc);

-- Coherente con el resto del motor: RLS deshabilitado (acceso por service/anon key).
alter table public.denuncias disable row level security;

-- Verificación rápida (opcional):
--   select estado, count(*) from denuncias group by estado order by 2 desc;
