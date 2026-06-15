-- Columnas extra para la sección "Pendientes de bodega".
-- Idempotente: se puede correr varias veces sin romper nada.
-- Supabase → SQL Editor → pegar → Run.

alter table cola_bodega add column if not exists canal           text;
alter table cola_bodega add column if not exists order_id        text;
alter table cola_bodega add column if not exists nombre          text;
alter table cola_bodega add column if not exists bodega_asignada text;
alter table cola_bodega add column if not exists auto            boolean default false;
alter table cola_bodega add column if not exists confirmado_at   timestamptz;
alter table cola_bodega add column if not exists created_at      timestamptz default now();
