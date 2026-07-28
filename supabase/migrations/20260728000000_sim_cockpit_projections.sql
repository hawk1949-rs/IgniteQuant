-- Sim cockpit cloud read projections (C architecture: local write → cloud read)
-- Populated by local outbox push (cloud_sync) and optional backfill CLI.

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

ALTER TABLE public.sim_decision_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sim_intent_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sim_fill_projection ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sim_decision_select_own ON public.sim_decision_projection;
CREATE POLICY sim_decision_select_own ON public.sim_decision_projection
    FOR SELECT USING (owner_id = auth.uid() OR owner_id IS NULL);

DROP POLICY IF EXISTS sim_intent_select_own ON public.sim_intent_projection;
CREATE POLICY sim_intent_select_own ON public.sim_intent_projection
    FOR SELECT USING (owner_id = auth.uid() OR owner_id IS NULL);

DROP POLICY IF EXISTS sim_fill_select_own ON public.sim_fill_projection;
CREATE POLICY sim_fill_select_own ON public.sim_fill_projection
    FOR SELECT USING (owner_id = auth.uid() OR owner_id IS NULL);
