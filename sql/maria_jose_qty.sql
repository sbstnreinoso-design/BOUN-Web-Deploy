-- ───────────────────────────────────────────────────────────────────────────
-- María José — Cupo de unidades por producto (productos compartidos MJ / BOUN).
-- ───────────────────────────────────────────────────────────────────────────
-- Algunos productos son de María José Y de BOUN: María vende PRIMERO sus
-- unidades disponibles y, cuando se agotan, las siguientes ventas son de BOUN.
-- Por eso al marcar un producto como de María José se indica CUÁNTAS unidades
-- son de ella. El motor le atribuye sus ventas (en orden cronológico desde la
-- marca) hasta completar ese cupo; al agotarse, el producto se DESMARCA solo.
--
--   · mj_qty       → unidades de María José.  0 / null = TODAS (sin tope).
--   · mj_anchor    → fecha desde la que cuentan sus ventas (cuándo se marcó).
--   · mj_consumed  → unidades suyas ya vendidas (lo actualiza el motor).
--
-- Idempotente. Supabase → SQL Editor → pegar → Run.
-- ───────────────────────────────────────────────────────────────────────────

alter table public.inventory_products
  add column if not exists mj_qty      numeric,
  add column if not exists mj_anchor   date,
  add column if not exists mj_consumed numeric not null default 0;
