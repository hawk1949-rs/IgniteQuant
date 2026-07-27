-- Product tenant + publication + sim instance + trading event inbox (C architecture)
-- Research/product truth lives here; trading events land via sync from local outbox.

-- ---------------------------------------------------------------------------
-- profiles (1:1 with auth.users when Auth is enabled)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    display_name TEXT,
    handle TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, display_name)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data ->> 'display_name', split_part(NEW.email, '@', 1))
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- ---------------------------------------------------------------------------
-- strategy_publication — research / public strategy cards
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

-- ---------------------------------------------------------------------------
-- sim_instance — cockpit session registry (cloud projection of local runners)
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- trading_event_inbox — cloud landing zone for local sync_outbox
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.strategy_publication ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sim_instance ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trading_event_inbox ENABLE ROW LEVEL SECURITY;

-- profiles
DROP POLICY IF EXISTS profiles_select_own ON public.profiles;
CREATE POLICY profiles_select_own ON public.profiles
    FOR SELECT USING (auth.uid() = id);
DROP POLICY IF EXISTS profiles_update_own ON public.profiles;
CREATE POLICY profiles_update_own ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- strategy_publication
DROP POLICY IF EXISTS strategy_pub_select_public ON public.strategy_publication;
CREATE POLICY strategy_pub_select_public ON public.strategy_publication
    FOR SELECT USING (
        (visibility = 'public' AND status = 'published')
        OR owner_id = auth.uid()
    );
DROP POLICY IF EXISTS strategy_pub_insert_own ON public.strategy_publication;
CREATE POLICY strategy_pub_insert_own ON public.strategy_publication
    FOR INSERT WITH CHECK (owner_id = auth.uid());
DROP POLICY IF EXISTS strategy_pub_update_own ON public.strategy_publication;
CREATE POLICY strategy_pub_update_own ON public.strategy_publication
    FOR UPDATE USING (owner_id = auth.uid());

-- sim_instance (private cockpit)
DROP POLICY IF EXISTS sim_instance_select_own ON public.sim_instance;
CREATE POLICY sim_instance_select_own ON public.sim_instance
    FOR SELECT USING (owner_id = auth.uid());
DROP POLICY IF EXISTS sim_instance_write_own ON public.sim_instance;
CREATE POLICY sim_instance_write_own ON public.sim_instance
    FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

-- trading_event_inbox (owner read; writers use service role / postgres)
DROP POLICY IF EXISTS trading_inbox_select_own ON public.trading_event_inbox;
CREATE POLICY trading_inbox_select_own ON public.trading_event_inbox
    FOR SELECT USING (owner_id = auth.uid());

-- Seed a draft publication for Falcon (ownerless until Auth binds it)
INSERT INTO public.strategy_publication (
    strategy_id, slug, title, summary, visibility, status, symbol_id, payload_json
) VALUES (
    'falcon_v2',
    'falcon-v2-au',
    'Falcon v2 · 沪金',
    '本地天勤模拟盘策略；公开研究页展示回测与说明，座舱详情需登录。',
    'public',
    'published',
    'au',
    '{"framework":"tq","source":"ignitequant_seed"}'::jsonb
)
ON CONFLICT (slug) DO UPDATE SET
    title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    updated_at = NOW();
