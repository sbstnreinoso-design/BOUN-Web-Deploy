-- Auditoría de la propagación real de stock a canales (motor de sync).
-- Cada fila = una escritura intentada por _apply_plan() hacia un canal.
-- Best-effort: si esta tabla no existe, el motor igual funciona (el INSERT
-- falla en silencio). Crear cuando quieras conservar el historial/reversión.
--
-- Ejecutar en el editor SQL de Supabase (proyecto fqugzvviokyixpsdsnfg).

create table if not exists public.sync_aplicacion (
  id          bigint generated always as identity primary key,
  creado_at   timestamptz not null default now(),
  codigo_boun text,
  canal       text,                 -- 'mercadolibre' | 'falabella' | 'shopify_*'
  ref         text,                 -- item_id ML / seller_sku Falabella / variant id
  order_id    text,
  actual      integer,              -- snapshot del stock ANTES de escribir
  objetivo    integer,              -- valor absoluto que se escribió
  ok          boolean,
  detalle     text                  -- motivo del skip o error, si lo hubo
);

create index if not exists idx_sync_aplicacion_codigo on public.sync_aplicacion (codigo_boun);
create index if not exists idx_sync_aplicacion_creado on public.sync_aplicacion (creado_at desc);

-- Coherente con el resto del motor: RLS deshabilitado (acceso por service/anon key).
alter table public.sync_aplicacion disable row level security;
