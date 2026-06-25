-- ───────────────────────────────────────────────────────────────────────────
-- María José — Liquidación de productos propios de María José.
-- ───────────────────────────────────────────────────────────────────────────
-- María José tiene productos propios publicados dentro de las cuentas BOUN
-- (MercadoLibre, Falabella, Shopify). De las ventas totales hay que separar lo
-- que corresponde a SUS productos, descontar todos los costos reales de venta
-- (comisión + IVA + retención, envío/Full y publicidad) y saber CUÁNTO se le
-- debe y CUÁNDO cada plataforma libera ese dinero, para poder pagárselo.
--
-- Tres piezas:
--   1) inventory_products.owner  → marca qué productos son de María José.
--   2) mj_ventas                 → una fila por ítem vendido de sus productos,
--                                   con el desglose de costos y la fecha de
--                                   liberación del dinero por plataforma.
--   3) mj_abonos                 → pagos/abonos hechos a María José (restan del
--                                   saldo). El saldo a pagar = Σ neto − Σ abonos.
--
-- Idempotente: se puede correr varias veces sin romper nada.
-- Supabase → SQL Editor → pegar → Run.
-- ───────────────────────────────────────────────────────────────────────────

-- 1) ── Marca de propietario en el inventario ────────────────────────────────
-- 'BOUN' (por defecto) | 'MARIA_JOSE'. Se marca desde la web (sección
-- Inventario → toggle "Producto de María José").
alter table public.inventory_products
  add column if not exists owner text not null default 'BOUN';

create index if not exists inventory_products_owner_idx
  on public.inventory_products (owner);


-- 2) ── Ventas atribuibles a María José (ledger por ítem) ─────────────────────
-- Una fila = un ítem vendido de un producto de María José en una orden.
-- Identidad = (plataforma, order_id, item_id): el sync diario hace upsert y
-- actualiza estado de liberación / costos sin duplicar.
create table if not exists public.mj_ventas (
  id              bigint generated always as identity primary key,

  -- ── Origen de la venta ──
  plataforma      text not null,                 -- mercadolibre | falabella | shopify_boun | shopify_kat
  order_id        text not null,                 -- id de la orden en la plataforma
  item_id         text,                          -- id de la publicación / line item (ML item, Falabella SKU, Shopify line)
  product_id      bigint,                        -- inventory_products.id (producto BOUN de María José)
  codigo          text,                          -- código/SKU BOUN del producto
  nombre          text,                          -- título de la publicación
  thumb           text,                          -- foto del producto (para identificarlo en la web)
  unidades        numeric not null default 0,

  -- ── Fecha ──
  fecha_venta     date not null,                 -- fecha de la venta en hora Colombia (-05:00)

  -- ── Dinero (todo en COP) ──
  precio_venta    numeric not null default 0,    -- precio bruto cobrado al comprador (lo que vendió)
  descuentos      numeric not null default 0,    -- descuentos/cupones aplicados a la venta
  comision        numeric not null default 0,    -- comisión real de la plataforma (sale_fee de ML, incl. su IVA)
  retencion       numeric not null default 0,    -- retención en la fuente (2.8%)
  costo_envio     numeric not null default 0,    -- costo de envío / Full que asume el vendedor
  costo_publicidad numeric not null default 0,   -- publicidad real atribuida a este ítem (Product Ads)
  neto_mj         numeric not null default 0,    -- LO QUE SE LE DEBE = precio_venta − comision − retencion − envio − publicidad

  -- ── Métricas de pauta (informativas, a nivel de la venta/ítem) ──
  roas            numeric,                       -- ingresos por ads / gasto
  acos            numeric,                       -- gasto / ingresos (%)

  -- ── Liberación del dinero por la plataforma ──
  release_date    date,                          -- cuándo la plataforma libera el dinero (money_release_date en ML)
  liberado        boolean not null default false,-- true cuando ya pasó la fecha de liberación
  estado_pago     text not null default 'pendiente', -- pendiente | liberado (estado de liberación de la plataforma)

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Una fila viva por (plataforma, orden, ítem): el sync hace upsert.
create unique index if not exists mj_ventas_uidx
  on public.mj_ventas (plataforma, order_id, item_id);

create index if not exists mj_ventas_fecha_idx     on public.mj_ventas (fecha_venta desc);
create index if not exists mj_ventas_release_idx   on public.mj_ventas (release_date);
create index if not exists mj_ventas_liberado_idx  on public.mj_ventas (liberado);
create index if not exists mj_ventas_plataforma_idx on public.mj_ventas (plataforma);


-- 3) ── Abonos / pagos hechos a María José ───────────────────────────────────
-- Cada fila resta del saldo. saldo_a_pagar = Σ neto_mj − Σ abonos.monto
create table if not exists public.mj_abonos (
  id          bigint generated always as identity primary key,
  fecha       date not null default (now() at time zone 'America/Bogota')::date,
  monto       numeric not null,                  -- monto abonado (COP)
  metodo      text default '',                   -- transferencia | efectivo | nequi | …
  nota        text default '',
  created_by  text default '',
  created_at  timestamptz not null default now()
);

create index if not exists mj_abonos_fecha_idx on public.mj_abonos (fecha desc);


-- Coherente con el resto del motor: RLS deshabilitado (acceso por service/anon key).
alter table public.mj_ventas disable row level security;
alter table public.mj_abonos disable row level security;

-- Verificación rápida (opcional):
--   select plataforma, count(*), sum(neto_mj) from mj_ventas group by 1;
--   select coalesce(sum(neto_mj),0) total_neto from mj_ventas;
--   select coalesce(sum(monto),0)   total_abonos from mj_abonos;
