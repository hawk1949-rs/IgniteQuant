"""SQLite schema for Phase 4 persistence (大框架 §8.3 精简子集)."""

from __future__ import annotations

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_state (
    instance_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT 'local',
    symbol TEXT NOT NULL DEFAULT '',
    runtime_state TEXT NOT NULL DEFAULT 'IDLE',
    payload_json TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    bar_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    applied_action TEXT NOT NULL,
    target_before INTEGER NOT NULL,
    target_after INTEGER NOT NULL,
    legacy_signal INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, decision_id)
);

CREATE TABLE IF NOT EXISTS risk_decision_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    risk_decision_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    requested_position INTEGER NOT NULL,
    approved_position INTEGER NOT NULL,
    rule_hits_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, risk_decision_id)
);

CREATE TABLE IF NOT EXISTS order_intent_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    current_position INTEGER NOT NULL,
    desired_position INTEGER NOT NULL,
    urgency TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, intent_id),
    UNIQUE(instance_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS trade_fill_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    fill_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    side TEXT NOT NULL,
    trade_time TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, fill_id)
);

CREATE TABLE IF NOT EXISTS position_snapshot_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    net_position INTEGER NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_snapshot_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    equity REAL NOT NULL,
    available REAL NOT NULL,
    margin REAL NOT NULL,
    margin_ratio REAL NOT NULL,
    as_of TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recon_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    matched INTEGER NOT NULL,
    runtime_state TEXT NOT NULL,
    mismatches_json TEXT NOT NULL,
    broker_json TEXT NOT NULL,
    local_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_decision_instance ON decision_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_intent_instance ON order_intent_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_fill_instance ON trade_fill_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_audit_instance ON audit_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_recon_instance ON recon_event(instance_id, seq);
"""
