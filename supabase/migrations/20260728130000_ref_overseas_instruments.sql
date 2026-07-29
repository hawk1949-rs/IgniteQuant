-- Overseas instruments + domestic↔ overseas pairs for paired research / backtests.

CREATE TABLE IF NOT EXISTS public.ref_overseas_pair (
    domestic_product_id TEXT NOT NULL,
    overseas_product_id TEXT NOT NULL,
    note TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domestic_product_id, overseas_product_id)
);

COMMENT ON TABLE public.ref_overseas_pair IS
    '内盘品种与外盘对照映射（如 au↔gc）。K 线本身存 market_bar_archive.symbol=GC=F 等。';

INSERT INTO public.ref_instrument(
    product_id, exchange_id, name, multiplier, price_tick,
    default_margin_rate, currency, signal_symbol, active,
    payload_json, updated_at
) VALUES
(
    'gc', 'COMEX', 'COMEX黄金', 100, 0.1,
    NULL, 'USD', 'GC=F', TRUE,
    '{"yahoo_symbol":"GC=F","eastmoney_secid":"101.GC00Y","display_symbol":"XAUUSD/GC","venue":"overseas","note":"COMEX Gold continuous; 对照沪金 au"}'::jsonb,
    NOW()
),
(
    'si', 'COMEX', 'COMEX白银', 5000, 0.005,
    NULL, 'USD', 'SI=F', TRUE,
    '{"yahoo_symbol":"SI=F","eastmoney_secid":"101.SI00Y","display_symbol":"XAGUSD/SI","venue":"overseas","note":"COMEX Silver continuous; 对照沪银 ag"}'::jsonb,
    NOW()
),
(
    'hg', 'COMEX', 'COMEX铜', 25000, 0.0005,
    NULL, 'USD', 'HG=F', TRUE,
    '{"yahoo_symbol":"HG=F","eastmoney_secid":"101.HG00Y","display_symbol":"HG","venue":"overseas"}'::jsonb,
    NOW()
),
(
    'cl', 'NYMEX', 'NYMEX原油', 1000, 0.01,
    NULL, 'USD', 'CL=F', TRUE,
    '{"yahoo_symbol":"CL=F","eastmoney_secid":"102.CL00Y","display_symbol":"CL","venue":"overseas"}'::jsonb,
    NOW()
)
ON CONFLICT (product_id) DO UPDATE SET
    exchange_id = EXCLUDED.exchange_id,
    name = EXCLUDED.name,
    multiplier = EXCLUDED.multiplier,
    price_tick = EXCLUDED.price_tick,
    currency = EXCLUDED.currency,
    signal_symbol = EXCLUDED.signal_symbol,
    payload_json = public.ref_instrument.payload_json || EXCLUDED.payload_json,
    active = TRUE,
    updated_at = NOW();

INSERT INTO public.ref_overseas_pair(domestic_product_id, overseas_product_id, note, updated_at)
VALUES
    ('au', 'gc', 'au ↔ gc (COMEX gold)', NOW()),
    ('ag', 'si', 'ag ↔ si (COMEX silver)', NOW())
ON CONFLICT (domestic_product_id, overseas_product_id) DO UPDATE SET
    note = EXCLUDED.note,
    updated_at = NOW();
