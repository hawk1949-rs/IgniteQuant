-- IgniteQuant cloud schema for Aliyun RDS PostgreSQL (no Supabase Auth / RLS).
-- Apply: PYTHONPATH=src python tools/apply_rds_schema.py

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- profiles (standalone; no auth.users FK)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY,
    display_name TEXT,
    handle TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- L3–L4 reference + research
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ref_instrument (
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

CREATE TABLE IF NOT EXISTS public.ref_contract (
    symbol TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES public.ref_instrument(product_id),
    listed_at TIMESTAMPTZ,
    expire_at TIMESTAMPTZ,
    delivery_month TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.ref_continuous_map (
    id BIGSERIAL PRIMARY KEY,
    signal_symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    underlying_symbol TEXT NOT NULL,
    roll_reason TEXT,
    UNIQUE (signal_symbol, as_of)
);

CREATE TABLE IF NOT EXISTS public.ref_trading_session (
    id BIGSERIAL PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES public.ref_instrument(product_id),
    exchange_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    weekday_mask TEXT NOT NULL DEFAULT '1,2,3,4,5',
    open_sec INTEGER NOT NULL,
    close_sec INTEGER NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    UNIQUE (product_id, session_id)
);

CREATE TABLE IF NOT EXISTS public.ref_fee_schedule (
    id BIGSERIAL PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES public.ref_instrument(product_id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    open_fee DOUBLE PRECISION NOT NULL,
    close_fee DOUBLE PRECISION NOT NULL,
    close_today_fee DOUBLE PRECISION NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'per_lot',
    UNIQUE (product_id, valid_from)
);

CREATE TABLE IF NOT EXISTS public.market_bar_archive (
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

CREATE TABLE IF NOT EXISTS public.factor_definition (
    factor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    formula_hash TEXT,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.factor_value (
    id BIGSERIAL PRIMARY KEY,
    factor_id TEXT NOT NULL REFERENCES public.factor_definition(factor_id),
    symbol TEXT NOT NULL,
    observation_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    raw_value DOUBLE PRECISION,
    norm_value DOUBLE PRECISION,
    quality TEXT,
    UNIQUE (factor_id, symbol, observation_at)
);

CREATE TABLE IF NOT EXISTS public.label_value (
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

CREATE TABLE IF NOT EXISTS public.config_version (
    config_hash TEXT PRIMARY KEY,
    decision_mode TEXT,
    yaml_or_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.backtest_run (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    config_hash TEXT NOT NULL REFERENCES public.config_version(config_hash),
    symbol TEXT NOT NULL,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    git_sha TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.backtest_metric (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES public.backtest_run(run_id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    split TEXT NOT NULL DEFAULT 'FULL',
    UNIQUE (run_id, metric_name, split)
);

CREATE INDEX IF NOT EXISTS idx_ref_continuous_signal
    ON public.ref_continuous_map (signal_symbol, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_market_bar_archive_symbol
    ON public.market_bar_archive (symbol, duration_sec, bar_end DESC);
CREATE INDEX IF NOT EXISTS idx_factor_value_lookup
    ON public.factor_value (factor_id, symbol, available_at);
CREATE INDEX IF NOT EXISTS idx_backtest_run_strategy
    ON public.backtest_run (strategy_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Product tenant + sim projections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.strategy_publication (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES public.profiles (id) ON DELETE SET NULL,
    strategy_id TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT,
    visibility TEXT NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('private', 'unlisted', 'public')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published', 'archived')),
    config_hash TEXT,
    symbol_id TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_publication_visibility
    ON public.strategy_publication (visibility, status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_publication_owner
    ON public.strategy_publication (owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.sim_instance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES public.profiles (id) ON DELETE CASCADE,
    instance_key TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol_id TEXT NOT NULL,
    framework TEXT NOT NULL DEFAULT 'tq',
    status TEXT NOT NULL DEFAULT 'idle'
        CHECK (status IN ('idle', 'running', 'stale', 'stopped', 'error')),
    runtime_state TEXT,
    publication_id UUID REFERENCES public.strategy_publication (id) ON DELETE SET NULL,
    last_heartbeat_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    local_db_hint TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instance_key)
);

CREATE INDEX IF NOT EXISTS idx_sim_instance_owner_status
    ON public.sim_instance (owner_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.trading_event_inbox (
    id BIGSERIAL PRIMARY KEY,
    owner_id UUID REFERENCES public.profiles (id) ON DELETE SET NULL,
    instance_key TEXT NOT NULL,
    local_outbox_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    UNIQUE (instance_key, local_outbox_id)
);

CREATE INDEX IF NOT EXISTS idx_trading_event_inbox_pending
    ON public.trading_event_inbox (instance_key, received_at)
    WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_trading_event_inbox_type
    ON public.trading_event_inbox (event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.sim_decision_projection (
    id BIGSERIAL PRIMARY KEY,
    owner_id UUID REFERENCES public.profiles (id) ON DELETE SET NULL,
    instance_key TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    bar_id TEXT,
    symbol TEXT,
    applied_action TEXT,
    target_before INTEGER,
    target_after INTEGER,
    legacy_signal INTEGER,
    regime TEXT,
    factor_quality TEXT,
    factor_values_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    score_parts_json JSONB,
    risk_action TEXT,
    requested_position INTEGER,
    approved_position INTEGER,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instance_key, decision_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_decision_proj_instance_time
    ON public.sim_decision_projection (instance_key, occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.sim_intent_projection (
    id BIGSERIAL PRIMARY KEY,
    owner_id UUID REFERENCES public.profiles (id) ON DELETE SET NULL,
    instance_key TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    decision_id TEXT,
    symbol TEXT,
    current_position INTEGER,
    desired_position INTEGER,
    urgency TEXT,
    status TEXT,
    side TEXT,
    qty INTEGER,
    idempotency_key TEXT,
    reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instance_key, intent_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_intent_proj_instance_time
    ON public.sim_intent_projection (instance_key, occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.sim_fill_projection (
    id BIGSERIAL PRIMARY KEY,
    owner_id UUID REFERENCES public.profiles (id) ON DELETE SET NULL,
    instance_key TEXT NOT NULL,
    fill_id TEXT NOT NULL,
    intent_id TEXT,
    symbol TEXT,
    price DOUBLE PRECISION,
    qty INTEGER,
    fee DOUBLE PRECISION DEFAULT 0,
    side TEXT,
    trade_time TIMESTAMPTZ,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instance_key, fill_id)
);

CREATE INDEX IF NOT EXISTS idx_sim_fill_proj_instance_time
    ON public.sim_fill_projection (instance_key, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- Margin + overseas
-- ---------------------------------------------------------------------------
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

CREATE TABLE IF NOT EXISTS public.ref_overseas_pair (
    domestic_product_id TEXT NOT NULL,
    overseas_product_id TEXT NOT NULL,
    note TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domestic_product_id, overseas_product_id)
);

CREATE TABLE IF NOT EXISTS public.schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.schema_meta(key, value)
VALUES ('ignitequant_rds_schema', '001')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
