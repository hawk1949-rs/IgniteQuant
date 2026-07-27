-- IgniteQuant L3–L4: reference + research schema for Supabase Postgres
-- Project target: hawk19455@gmail.com's Project (bbolerrskvcxutovcfyj)
-- Apply via: python tools/apply_supabase_schema.py
-- Or Supabase SQL editor / `supabase db push` when linked.

CREATE TABLE IF NOT EXISTS ref_instrument (
    product_id TEXT PRIMARY KEY,
    exchange_id TEXT NOT NULL,
    name TEXT NOT NULL,
    multiplier DOUBLE PRECISION NOT NULL,
    price_tick DOUBLE PRECISION NOT NULL,
    default_margin_rate DOUBLE PRECISION,
    currency TEXT NOT NULL DEFAULT 'CNY',
    signal_symbol TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ref_contract (
    symbol TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES ref_instrument(product_id),
    listed_at TIMESTAMPTZ,
    expire_at TIMESTAMPTZ,
    delivery_month TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ref_continuous_map (
    id BIGSERIAL PRIMARY KEY,
    signal_symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    underlying_symbol TEXT NOT NULL,
    roll_reason TEXT,
    UNIQUE (signal_symbol, as_of)
);

CREATE TABLE IF NOT EXISTS ref_trading_session (
    id BIGSERIAL PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES ref_instrument(product_id),
    exchange_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    weekday_mask TEXT NOT NULL DEFAULT '1,2,3,4,5',
    open_sec INTEGER NOT NULL,
    close_sec INTEGER NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    UNIQUE (product_id, session_id)
);

CREATE TABLE IF NOT EXISTS ref_fee_schedule (
    id BIGSERIAL PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES ref_instrument(product_id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    open_fee DOUBLE PRECISION NOT NULL,
    close_fee DOUBLE PRECISION NOT NULL,
    close_today_fee DOUBLE PRECISION NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'per_lot',
    UNIQUE (product_id, valid_from)
);

CREATE TABLE IF NOT EXISTS market_bar_archive (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    bar_id TEXT NOT NULL UNIQUE,
    bar_start TIMESTAMPTZ,
    bar_end TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL DEFAULT 0,
    open_oi DOUBLE PRECISION NOT NULL DEFAULT 0,
    close_oi DOUBLE PRECISION NOT NULL DEFAULT 0,
    underlying_symbol TEXT,
    is_final BOOLEAN NOT NULL DEFAULT TRUE,
    source TEXT NOT NULL DEFAULT 'tqsdk_sim_live',
    instance_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, duration_sec, bar_end)
);

CREATE TABLE IF NOT EXISTS factor_definition (
    factor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    formula_hash TEXT,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS factor_value (
    id BIGSERIAL PRIMARY KEY,
    factor_id TEXT NOT NULL REFERENCES factor_definition(factor_id),
    symbol TEXT NOT NULL,
    observation_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    raw_value DOUBLE PRECISION,
    norm_value DOUBLE PRECISION,
    quality TEXT,
    UNIQUE (factor_id, symbol, observation_at)
);

CREATE TABLE IF NOT EXISTS label_value (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    observation_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    horizon TEXT NOT NULL,
    forward_return DOUBLE PRECISION,
    mfe DOUBLE PRECISION,
    mae DOUBLE PRECISION,
    label_version TEXT NOT NULL DEFAULT 'v1',
    UNIQUE (symbol, observation_at, horizon, label_version)
);

CREATE TABLE IF NOT EXISTS config_version (
    config_hash TEXT PRIMARY KEY,
    decision_mode TEXT,
    yaml_or_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    config_hash TEXT NOT NULL REFERENCES config_version(config_hash),
    symbol TEXT NOT NULL,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    git_sha TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS backtest_metric (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    split TEXT NOT NULL DEFAULT 'FULL',
    UNIQUE (run_id, metric_name, split)
);

CREATE INDEX IF NOT EXISTS idx_ref_continuous_signal ON ref_continuous_map (signal_symbol, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_market_bar_archive_symbol ON market_bar_archive (symbol, duration_sec, bar_end DESC);
CREATE INDEX IF NOT EXISTS idx_factor_value_lookup ON factor_value (factor_id, symbol, available_at);
CREATE INDEX IF NOT EXISTS idx_backtest_run_strategy ON backtest_run (strategy_id, created_at DESC);

-- Seed catalog instruments (idempotent)
INSERT INTO ref_instrument (product_id, exchange_id, name, multiplier, price_tick, signal_symbol, payload_json)
VALUES
    ('au', 'SHFE', '沪金', 1000, 0.02, 'KQ.m@SHFE.au', '{"open_fee_per_lot":10,"close_fee_per_lot":10,"close_today_fee_per_lot":10}'::jsonb),
    ('ag', 'SHFE', '沪银', 15, 1.0, 'KQ.m@SHFE.ag', '{"open_fee_per_lot":3,"close_fee_per_lot":3,"close_today_fee_per_lot":3}'::jsonb),
    ('rb', 'SHFE', '螺纹钢', 10, 1.0, 'KQ.m@SHFE.rb', '{"open_fee_per_lot":3,"close_fee_per_lot":3,"close_today_fee_per_lot":3}'::jsonb),
    ('fg', 'CZCE', '玻璃', 20, 1.0, 'KQ.m@CZCE.FG', '{"open_fee_per_lot":3,"close_fee_per_lot":3,"close_today_fee_per_lot":3}'::jsonb)
ON CONFLICT (product_id) DO UPDATE SET
    name = EXCLUDED.name,
    multiplier = EXCLUDED.multiplier,
    price_tick = EXCLUDED.price_tick,
    signal_symbol = EXCLUDED.signal_symbol,
    payload_json = EXCLUDED.payload_json,
    updated_at = NOW();

INSERT INTO ref_fee_schedule (product_id, valid_from, open_fee, close_fee, close_today_fee, fee_type)
VALUES
    ('au', '1970-01-01', 10, 10, 10, 'per_lot'),
    ('ag', '1970-01-01', 3, 3, 3, 'per_lot'),
    ('rb', '1970-01-01', 3, 3, 3, 'per_lot'),
    ('fg', '1970-01-01', 3, 3, 3, 'per_lot')
ON CONFLICT (product_id, valid_from) DO UPDATE SET
    open_fee = EXCLUDED.open_fee,
    close_fee = EXCLUDED.close_fee,
    close_today_fee = EXCLUDED.close_today_fee;

INSERT INTO ref_continuous_map (signal_symbol, as_of, underlying_symbol, roll_reason)
VALUES
    ('KQ.m@SHFE.au', '1970-01-01T00:00:00Z', 'KQ.m@SHFE.au', 'catalog_seed'),
    ('KQ.m@SHFE.ag', '1970-01-01T00:00:00Z', 'KQ.m@SHFE.ag', 'catalog_seed'),
    ('KQ.m@SHFE.rb', '1970-01-01T00:00:00Z', 'KQ.m@SHFE.rb', 'catalog_seed'),
    ('KQ.m@CZCE.FG', '1970-01-01T00:00:00Z', 'KQ.m@CZCE.FG', 'catalog_seed')
ON CONFLICT (signal_symbol, as_of) DO NOTHING;
