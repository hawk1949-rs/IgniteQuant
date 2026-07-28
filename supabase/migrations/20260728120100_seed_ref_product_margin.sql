-- Seed product margin rates from user spreadsheet (2026-07-28).
-- Idempotent upsert; also syncs ref_instrument.default_margin_rate when product exists.

INSERT INTO public.ref_product_margin(
  exchange_id, product_id, margin_rate_pct, margin_rate, source, as_of, notes
) VALUES
('SHFE', 'ad', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'ag', 19.0, 0.19, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'al', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'ao', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'au', 16.0, 0.16, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'br', 14.0, 0.14, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'bu', 14.0, 0.14, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'cu', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'fu', 22.0, 0.22, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'hc', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'ni', 10.0, 0.1, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'op', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'pb', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'rb', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'ru', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'sn', 13.0, 0.13, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'sp', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'ss', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'wr', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('SHFE', 'zn', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('INE', 'bc', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('INE', 'ec', 22.0, 0.22, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('INE', 'lu', 22.0, 0.22, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('INE', 'nr', 9.0, 0.09, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('INE', 'sc', 22.0, 0.22, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('GFEX', 'lc', 15.0, 0.15, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('GFEX', 'pd', 19.0, 0.19, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('GFEX', 'ps', 13.0, 0.13, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('GFEX', 'pt', 19.0, 0.19, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('GFEX', 'si', 10.0, 0.1, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'a', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'b', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'bb', 15.0, 0.15, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'bz', 8.0, 0.08, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'c', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'cs', 6.0, 0.06, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'eb', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'eg', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'fb', 10.0, 0.1, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'i', 11.0, 0.11, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'j', 20.0, 0.2, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'jd', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'jm', 12.0, 0.12, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'l', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'lg', 8.0, 0.08, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'lh', 8.0, 0.08, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'm', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'p', 8.0, 0.08, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'pg', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'pp', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'rr', 6.0, 0.06, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'v', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct'),
('DCE', 'y', 7.0, 0.07, 'user_xls_2026-07-28', DATE '2026-07-28', 'spec_margin_pct')
ON CONFLICT (exchange_id, product_id) DO UPDATE SET
  margin_rate_pct = EXCLUDED.margin_rate_pct,
  margin_rate = EXCLUDED.margin_rate,
  source = EXCLUDED.source,
  as_of = EXCLUDED.as_of,
  notes = EXCLUDED.notes,
  updated_at = NOW();

UPDATE public.ref_instrument ri
SET default_margin_rate = m.margin_rate,
    updated_at = NOW()
FROM public.ref_product_margin m
WHERE ri.product_id = m.product_id
  AND UPPER(ri.exchange_id) = UPPER(m.exchange_id);
