-- ───────────────────────────────────────────────────────────────────────────
-- mapeo_pendientes → reporte vivo de la sección "Mapeo".
-- ───────────────────────────────────────────────────────────────────────────
-- Cada fila = una publicación viva (ML / Falabella / Shopify BOUN / KAT) que
-- NO está correctamente mapeada a un SKU del inventario BOUN (la fuente de
-- verdad). La skill "mapeo de sku" la refresca a diario (8:00 PM) y la sección
-- /mapeo de la web la muestra con foto + link + desplegable para asociarla a un
-- producto. Al asociarla (o cuando deja de estar pendiente) se marca resuelta.
--
-- Motivos:
--   · sin_mapear   → la publicación no tiene vínculo en inventory_links.
--   · mal_mapeado  → tiene vínculo, pero el SKU declarado en el canal NO coincide
--                    con el código del producto al que está vinculada (SKU cruzado).
--
-- Idempotente: se puede correr varias veces sin romper nada.
-- Supabase → SQL Editor → pegar → Run.
-- ───────────────────────────────────────────────────────────────────────────

create table if not exists public.mapeo_pendientes (
  id            bigint generated always as identity primary key,
  channel       text not null,                 -- mercadolibre | falabella | shopify_boun | shopify_kat
  ext_id        text not null,                 -- item_id ML / SellerSku Falabella / variant gid Shopify
  title         text,
  thumb         text,                           -- foto de la publicación (para identificarla)
  link          text,                           -- URL a la publicación (cuando el canal lo permite)
  sku_canal     text,                           -- SKU declarado en el canal (si lo hay)
  qty           integer default 0,
  price         numeric default 0,
  motivo        text not null default 'sin_mapear',  -- sin_mapear | mal_mapeado
  sugerido_code text,                            -- mejor código BOUN sugerido (match por SKU), si lo hay
  detalle       text,
  detectado_at  timestamptz not null default now(),
  visto_at      timestamptz not null default now(),  -- última corrida que aún la vio pendiente
  resuelto      boolean not null default false,
  resuelto_at   timestamptz,
  resuelto_code text                            -- código BOUN al que se asoció al resolverla
);

-- Una publicación = una sola fila viva por canal (el scan hace upsert).
create unique index if not exists mapeo_pendientes_channel_ext_uidx
  on public.mapeo_pendientes (channel, ext_id);

create index if not exists mapeo_pendientes_resuelto_idx
  on public.mapeo_pendientes (resuelto);

-- Coherente con el resto del motor: RLS deshabilitado (acceso por service/anon key).
alter table public.mapeo_pendientes disable row level security;

-- Verificación rápida (opcional):
--   select motivo, count(*) from mapeo_pendientes where resuelto=false group by motivo;
