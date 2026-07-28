-- Product margin rates (品种保证金比例) — authoritative for cockpit / sizing display.
-- Values are percent (e.g. 16 = 16%) and fraction (0.16). Source: user spreadsheet.

CREATE TABLE IF NOT EXISTS public.ref_product_margin (
    exchange_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    margin_rate_pct DOUBLE PRECISION NOT NULL
        CHECK (margin_rate_pct > 0 AND margin_rate_pct <= 100),
    margin_rate DOUBLE PRECISION NOT NULL
        CHECK (margin_rate > 0 AND margin_rate <= 1),
    source TEXT NOT NULL DEFAULT 'manual',
    as_of DATE,
    notes TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_ref_product_margin_product
    ON public.ref_product_margin (product_id);

COMMENT ON TABLE public.ref_product_margin IS
    '品种保证金比例（百分比）。座舱保证金/风险度按本表计算，不采信天勤模拟账户风险度。';

COMMENT ON COLUMN public.ref_product_margin.margin_rate_pct IS
    '保证金比例百分比，例如 16 表示 16%';

COMMENT ON COLUMN public.ref_product_margin.margin_rate IS
    '保证金比例小数，例如 0.16';
