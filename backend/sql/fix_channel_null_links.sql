-- fix_channel_null_links.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- PROBLEMA
--   El motor de sincronización de stock resuelve las publicaciones de ML con
--   _ml_active_pubs()/_compute_plan(), que consultan inventory_links filtrando
--   por SQL:  channel = 'mercadolibre'  (via _ml_only_filter()).
--   Ese filtro NO matchea filas con channel NULL. En cambio, TODOS los displays
--   (inv_get_links, _links_summary, /api/inventory/items, mapeo…) hacen
--   `channel or 'mercadolibre'`, así que una fila con channel NULL se PINTA como
--   ML activa/mapeada pero es INVISIBLE para el escaneo → nunca recibe stock.
--
--   Caso detectado (12-jul-2026): combo KRUNCHFLOW, publicación MCO2018591491
--   (product_id 100). ML ya tiene el SKU "KRUNCHFLOW" y 9 u en depósito, pero el
--   apply real dejó 0 filas / 0 escrituras para este código: su vínculo quedó
--   con channel NULL (heredado de antes de la migración multicanal).
--
-- POR QUÉ ES CORRECTO EL BACKFILL
--   Antes de la migración multicanal la tabla inventory_links era SOLO-ML, así
--   que toda fila con channel NULL es, por definición, de MercadoLibre.
--
-- CÓMO CORRER
--   Supabase → SQL Editor → pega y ejecuta. (No requiere secretos en el código;
--   lo corre el dueño desde el panel.) Idempotente: si no hay NULLs, no hace nada.
-- ─────────────────────────────────────────────────────────────────────────────

-- 1) Diagnóstico previo — cuántos vínculos ML quedaron con channel NULL:
SELECT count(*) AS links_channel_null
FROM inventory_links
WHERE channel IS NULL;

-- 2) Ver el/los afectados (incluye el combo KRUNCHFLOW / MCO2018591491):
SELECT product_id, ml_item_id, ml_title, ml_qty
FROM inventory_links
WHERE channel IS NULL
ORDER BY product_id;

-- 3) FIX — asignar 'mercadolibre' a todo vínculo heredado sin canal:
UPDATE inventory_links
SET channel = 'mercadolibre'
WHERE channel IS NULL;

-- 4) Verificación — debe devolver 0:
SELECT count(*) AS remaining_null
FROM inventory_links
WHERE channel IS NULL;

-- Tras correr esto: dispara un escaneo (Aplicar, canal MercadoLibre) desde
-- Cerebro / la sección de sincronización. El combo KRUNCHFLOW debe aparecer en
-- las filas con objetivo = armables de Bogotá (9) y quedar gestionado por el
-- motor de ahí en adelante.
