-- ───────────────────────────────────────────────────────────────────────────
-- inventory_links → multicanal (MercadoLibre + Falabella + Shopify BOUN/KAT)
-- ───────────────────────────────────────────────────────────────────────────
-- Hasta ahora inventory_links era 100% MercadoLibre: la columna ml_item_id
-- guardaba el id de la publicación ML y era ÚNICA (el upsert usaba
-- on_conflict=ml_item_id).
--
-- Esta migración generaliza la tabla para que UN producto de inventario pueda
-- tener publicaciones asignadas en los 4 canales, distinguibles entre sí:
--   channel ∈ ('mercadolibre','falabella','shopify_boun','shopify_kat')
--
-- La columna ml_item_id pasa a ser el IDENTIFICADOR EXTERNO genérico del canal:
--   · mercadolibre → item_id  (MCO…)
--   · falabella    → SellerSku
--   · shopify_boun → gid de la variante (gid://shopify/ProductVariant/…)
--   · shopify_kat  → gid de la variante
-- (se reutilizan los demás campos ml_* como datos genéricos de la publicación)
--
-- Idempotente: se puede correr varias veces sin error.
-- Correr en el SQL Editor de Supabase ANTES de desplegar el backend nuevo.
-- ───────────────────────────────────────────────────────────────────────────

-- 1) Nueva columna de canal, con default que respeta las filas ML existentes.
ALTER TABLE inventory_links
  ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'mercadolibre';

-- 2) Backfill defensivo: cualquier fila vieja sin canal queda como ML.
UPDATE inventory_links
   SET channel = 'mercadolibre'
 WHERE channel IS NULL OR channel = '';

-- 3) Conservar la unicidad sobre ml_item_id (cero-downtime). El backend VIEJO
--    hace upsert con on_conflict=ml_item_id; si se quita ANTES de desplegar el
--    código nuevo, "Asignar publicaciones" se rompe en producción. La dejamos:
--    es inofensiva porque los ids externos no colisionan entre canales
--    (ML=MCO…, Falabella=SellerSku, Shopify=gid de variante). Si la tabla se
--    creó sin ella (BD nueva), la (re)creamos.
CREATE UNIQUE INDEX IF NOT EXISTS inventory_links_ml_item_id_key
  ON inventory_links (ml_item_id);

-- 4) Nueva unicidad compuesta (canal + id externo). PostgREST la usa como
--    destino de on_conflict=channel,ml_item_id en el código nuevo. Convive con
--    la de (3) sin problema.
CREATE UNIQUE INDEX IF NOT EXISTS inventory_links_channel_extid_uidx
  ON inventory_links (channel, ml_item_id);

-- 5) Índice de apoyo para las consultas por producto + canal (motor de sync).
CREATE INDEX IF NOT EXISTS inventory_links_product_channel_idx
  ON inventory_links (product_id, channel);

-- Verificación rápida (opcional):
--   SELECT channel, count(*) FROM inventory_links GROUP BY channel;
