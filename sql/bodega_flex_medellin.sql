-- Bodega "Flex Medellín" para BOUN.
-- Contador de stock propio de la bodega Flex de Medellín (envíos Flex ML).
-- Idempotente: se puede correr varias veces sin romper nada.
-- Supabase → SQL Editor → pegar → Run.

alter table inventory_products
  add column if not exists qty_flex_med numeric default 0;

-- (opcional) dejar en 0 las filas existentes que quedaran en null.
update inventory_products set qty_flex_med = 0 where qty_flex_med is null;
