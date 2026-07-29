-- Cockpit login users (Aliyun RDS; no Supabase Auth).
-- Passwords are stored as PBKDF2 hashes via tools/seed_cockpit_users.py

CREATE TABLE IF NOT EXISTS public.cockpit_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cockpit_users_active
    ON public.cockpit_users (is_active)
    WHERE is_active = TRUE;
