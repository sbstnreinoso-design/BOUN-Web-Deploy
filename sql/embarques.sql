-- ───────────────────────────────────────────────────────────────────────────
-- embarques + embarque_items → sección "🚢 Mercancía en camino".
-- ───────────────────────────────────────────────────────────────────────────
-- Un EMBARQUE es una compra/importación que viene en camino (China → agente de
-- carga → bodega BOUN). Agrupa varias LÍNEAS de producto que comparten la misma
-- transportadora y fechas, igual que la hoja de importación de Sebastián.
--
-- Ciclo de vida (campo embarques.estado):
--   · en_camino  → la mercancía viaja. Sus unidades se SUMAN a "En camino"
--                  (qty_transit) de cada producto del inventario, para que se
--                  vea producto por producto que viene en camino.
--   · arribado   → al marcar "Arribó": por cada línea se RESTAN sus unidades de
--                  qty_transit y se SUMAN a la bodega destino (Bogotá/Yopal);
--                  además el costo del producto se actualiza por PROMEDIO
--                  PONDERADO (costo viejo del stock físico + costo landed nuevo)
--                  y, si parte de la línea es de María José, alimenta su
--                  liquidación (owner=MARIA_JOSE + mj_qty).
--   · cancelado  → se anula; sus unidades salen de qty_transit.
--
-- Costo landed por unidad = costo_unit_china + (valor_flete / cantidad).
--   · El flete sale del CBM: cbm = (largo×ancho×alto/1.000.000) × cant_cajas (m³)
--     y, si la transportadora es "Envios DC", valor_flete = cbm × cbm_rate
--     (tarifa por defecto 1.700.000). Con otra transportadora el flete se
--     escribe a mano y no se calcula por CBM.
--
-- Idempotente. Supabase → SQL Editor → pegar → Run.
-- ───────────────────────────────────────────────────────────────────────────

create table if not exists public.embarques (
  id                     bigint generated always as identity primary key,
  nombre                 text,                              -- etiqueta libre (ej. "Importación China · Jun 2026")
  transportadora         text not null default 'Envios DC', -- "Envios DC" calcula CBM; otra = texto libre, flete manual
  usa_cbm                boolean not null default true,     -- true → flete = cbm × cbm_rate; false → flete manual
  cbm_rate               numeric not null default 1700000,  -- costo por m³ (CBM) de la transportadora
  fecha_compra           date,                              -- cuándo se compró
  fecha_entrega_agente   date,                              -- entrega al agente de carga
  eta                    date,                              -- tiempo estimado de arribo (ETA)
  estado                 text not null default 'en_camino', -- bodega_agente | en_camino | nacionalizacion | arribado | cancelado
  contenedor             text,                              -- nº de contenedor que asigna Envío DC (para rastreo)
  arribado_at            timestamptz,                       -- cuándo se marcó arribado
  notas                  text,
  created_by             text,
  created_at             timestamptz not null default now()
);

create table if not exists public.embarque_items (
  id                bigint generated always as identity primary key,
  embarque_id       bigint not null references public.embarques(id) on delete cascade,
  product_id        bigint references public.inventory_products(id) on delete set null,
  code              text,            -- snapshot del código BOUN (para mostrar)
  name              text,            -- snapshot del nombre
  thumb             text,            -- snapshot de la foto

  cantidad          numeric not null default 0,   -- unidades totales de la línea
  costo_unit_china  numeric not null default 0,   -- precio de compra por unidad (China)
  bodega_destino    text not null default 'bogota', -- bogota | yopal (a dónde llega)

  -- Caja / volumen → CBM
  caja_largo        numeric not null default 0,   -- cm
  caja_ancho        numeric not null default 0,   -- cm
  caja_alto         numeric not null default 0,   -- cm
  cantidad_cajas    numeric not null default 1,
  peso              numeric not null default 0,   -- kg (informativo)
  cbm               numeric not null default 0,   -- m³ totales de la línea
  valor_flete       numeric not null default 0,   -- flete de la línea (auto si usa_cbm; manual si no)

  -- María José (parte de la línea que es de ella)
  mj_cantidad       numeric not null default 0,
  mj_anchor         date,
  recibo            text,            -- Nº de recibo Envío DC al que corresponde la línea

  arribado          boolean not null default false,
  created_at        timestamptz not null default now()
);

create index if not exists embarque_items_emb_idx     on public.embarque_items (embarque_id);
create index if not exists embarque_items_prod_idx    on public.embarque_items (product_id);
create index if not exists embarques_estado_idx       on public.embarques (estado);
create index if not exists embarques_created_idx      on public.embarques (created_at desc);

-- ── Recibos del agente (Envío DC) ────────────────────────────────────────────
-- Cuando el agente en China (Envío DC) RECIBE el paquete, le entrega al
-- proveedor un recibo (ENCARGOS DC CHINA): con ese recibo se reporta el paquete
-- a Envío DC y se rastrea hasta que llega a la bodega. Aquí se guardan esos
-- recibos (imagen o PDF) adjuntos a cada embarque. El archivo se guarda en
-- base64 en `data` (se sirve aparte; NO se incluye en el listado para no pesar).
create table if not exists public.embarque_recibos (
  id           bigint generated always as identity primary key,
  embarque_id  bigint not null references public.embarques(id) on delete cascade,
  nombre       text,            -- nombre del archivo
  mime         text,            -- image/jpeg, application/pdf, …
  data         text,            -- contenido en base64
  size_bytes   bigint not null default 0,
  nota         text,            -- nº de recibo / referencia (ej. "0000849")
  created_by   text,
  created_at   timestamptz not null default now()
);
create index if not exists embarque_recibos_emb_idx on public.embarque_recibos (embarque_id);

-- Migración para tablas ya creadas: nº de contenedor + total de cajas/bultos.
alter table public.embarques add column if not exists contenedor  text;
alter table public.embarques add column if not exists total_cajas numeric;
alter table public.embarque_items add column if not exists recibo text;

-- Coherente con el resto del motor: RLS deshabilitado (acceso por service/anon key).
alter table public.embarques        disable row level security;
alter table public.embarque_items   disable row level security;
alter table public.embarque_recibos disable row level security;

-- Verificación rápida (opcional):
--   select estado, count(*) from embarques group by estado;
