"""SQLite schema for Phase 4+ persistence (大框架 §8.3, data-architecture blueprint).

SCHEMA_VERSION bumps require an entry in MIGRATIONS. Fresh databases apply BASE_DDL
(which already includes the latest shape); upgrades apply only the missing versions
via ``migrate()`` in sqlite.py (including safe ADD COLUMN helpers).
"""

from __future__ import annotations

SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Base DDL — full latest shape for new databases
# ---------------------------------------------------------------------------

BASE_DDL = """
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
    bar_end_at TEXT,
    factor_snapshot_id TEXT,
    signal_id TEXT,
    target_id TEXT,
    risk_decision_id TEXT,
    config_hash TEXT,
    model_version TEXT,
    reason_codes_json TEXT,
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
    side TEXT,
    offset TEXT,
    qty INTEGER,
    broker_order_id TEXT,
    updated_at TEXT,
    terminal_at TEXT,
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
    broker_order_id TEXT,
    broker_trade_id TEXT,
    multiplier REAL,
    realized_pnl REAL,
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
    created_at TEXT NOT NULL,
    long_today INTEGER NOT NULL DEFAULT 0,
    long_yesterday INTEGER NOT NULL DEFAULT 0,
    short_today INTEGER NOT NULL DEFAULT 0,
    short_yesterday INTEGER NOT NULL DEFAULT 0,
    avg_entry_price REAL,
    unrealized_pnl REAL NOT NULL DEFAULT 0
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
    created_at TEXT NOT NULL,
    realized_pnl_today REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    strategy_drawdown_pct REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recon_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    matched INTEGER NOT NULL,
    runtime_state TEXT NOT NULL,
    mismatches_json TEXT NOT NULL,
    broker_json TEXT NOT NULL,
    local_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    severity TEXT,
    resolved_at TEXT
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

CREATE TABLE IF NOT EXISTS broker_order_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    local_order_id TEXT,
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    offset TEXT,
    status TEXT NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    remaining_qty INTEGER NOT NULL DEFAULT 0,
    avg_price REAL,
    message TEXT,
    event_time TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, event_id)
);

CREATE TABLE IF NOT EXISTS heartbeat_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    quote_as_of TEXT,
    last_price REAL,
    confirmed_net INTEGER,
    current_target INTEGER,
    pending_desired INTEGER,
    runtime_state TEXT,
    session_open INTEGER,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_health (
    instance_id TEXT PRIMARY KEY,
    last_heartbeat_at TEXT,
    last_bar_at TEXT,
    last_quote_at TEXT,
    unknown_order_count INTEGER NOT NULL DEFAULT 0,
    kill_switch_active INTEGER NOT NULL DEFAULT 0,
    persistence_healthy INTEGER NOT NULL DEFAULT 1,
    runtime_state TEXT NOT NULL DEFAULT 'IDLE',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_snapshot (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    factor_snapshot_id TEXT NOT NULL,
    bar_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    data_as_of TEXT NOT NULL,
    regime TEXT NOT NULL,
    quality TEXT NOT NULL,
    factor_version TEXT NOT NULL,
    values_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, factor_snapshot_id)
);

CREATE TABLE IF NOT EXISTS signal_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    factor_snapshot_id TEXT NOT NULL,
    action TEXT NOT NULL,
    direction INTEGER NOT NULL,
    alpha REAL NOT NULL,
    strength REAL NOT NULL,
    confidence REAL NOT NULL,
    legacy_signal INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, signal_id)
);

CREATE TABLE IF NOT EXISTS target_position_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    current_position INTEGER NOT NULL,
    desired_position INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    planned_stop_price REAL,
    stop_distance REAL,
    sizing_method TEXT NOT NULL,
    requested_risk TEXT NOT NULL,
    config_version TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, target_id)
);

CREATE TABLE IF NOT EXISTS signal_state (
    instance_id TEXT PRIMARY KEY,
    previous_alpha REAL,
    consecutive_long_bars INTEGER NOT NULL DEFAULT 0,
    consecutive_short_bars INTEGER NOT NULL DEFAULT 0,
    previous_action TEXT,
    last_signal_id TEXT,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS market_bar (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    bar_id TEXT NOT NULL,
    bar_start TEXT,
    bar_end TEXT NOT NULL,
    available_at TEXT,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL DEFAULT 0,
    open_oi REAL NOT NULL DEFAULT 0,
    close_oi REAL NOT NULL DEFAULT 0,
    underlying_symbol TEXT,
    is_final INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'tqsdk_sim_live',
    instance_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(symbol, duration_sec, bar_end),
    UNIQUE(bar_id)
);

CREATE TABLE IF NOT EXISTS market_quote_l1 (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    last REAL,
    bid1 REAL,
    ask1 REAL,
    bid_vol1 INTEGER,
    ask_vol1 INTEGER,
    spread_ticks REAL,
    upper_locked INTEGER NOT NULL DEFAULT 0,
    lower_locked INTEGER NOT NULL DEFAULT 0,
    instance_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_instrument (
    product_id TEXT PRIMARY KEY,
    exchange_id TEXT NOT NULL,
    name TEXT NOT NULL,
    multiplier REAL NOT NULL,
    price_tick REAL NOT NULL,
    default_margin_rate REAL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    signal_symbol TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_contract (
    symbol TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    listed_at TEXT,
    expire_at TEXT,
    delivery_month TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_continuous_map (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    roll_reason TEXT,
    UNIQUE(signal_symbol, as_of)
);

CREATE TABLE IF NOT EXISTS ref_trading_session (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    exchange_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    weekday_mask TEXT NOT NULL DEFAULT '1,2,3,4,5',
    open_sec INTEGER NOT NULL,
    close_sec INTEGER NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    UNIQUE(product_id, session_id)
);

CREATE TABLE IF NOT EXISTS ref_fee_schedule (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    open_fee REAL NOT NULL,
    close_fee REAL NOT NULL,
    close_today_fee REAL NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'per_lot',
    UNIQUE(product_id, valid_from)
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    status TEXT NOT NULL,
    git_sha TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS backtest_metric (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    split TEXT NOT NULL DEFAULT 'FULL',
    UNIQUE(run_id, metric_name, split)
);

CREATE TABLE IF NOT EXISTS config_version (
    config_hash TEXT PRIMARY KEY,
    decision_mode TEXT,
    yaml_or_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_definition (
    factor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    formula_hash TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    owner TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_instance ON decision_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_intent_instance ON order_intent_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_fill_instance ON trade_fill_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_audit_instance ON audit_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_recon_instance ON recon_event(instance_id, seq);
CREATE INDEX IF NOT EXISTS idx_broker_order_intent ON broker_order_event(instance_id, intent_id, event_time);
CREATE INDEX IF NOT EXISTS idx_heartbeat_instance ON heartbeat_event(instance_id, as_of);
CREATE INDEX IF NOT EXISTS idx_factor_snapshot_bar ON factor_snapshot(instance_id, bar_id);
CREATE INDEX IF NOT EXISTS idx_signal_factor ON signal_event(instance_id, factor_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_target_signal ON target_position_event(instance_id, signal_id);
CREATE INDEX IF NOT EXISTS idx_market_bar_symbol ON market_bar(symbol, duration_sec, bar_end);
CREATE INDEX IF NOT EXISTS idx_market_quote_symbol ON market_quote_l1(symbol, as_of);
"""

# Back-compat alias used by older imports / docs
DDL = BASE_DDL

# Columns to ADD when upgrading from SCHEMA_VERSION 1 → 2
V2_ADD_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "decision_event": [
        ("bar_end_at", "TEXT"),
        ("factor_snapshot_id", "TEXT"),
        ("signal_id", "TEXT"),
        ("target_id", "TEXT"),
        ("risk_decision_id", "TEXT"),
        ("config_hash", "TEXT"),
        ("model_version", "TEXT"),
        ("reason_codes_json", "TEXT"),
    ],
    "order_intent_event": [
        ("side", "TEXT"),
        ("offset", "TEXT"),
        ("qty", "INTEGER"),
        ("broker_order_id", "TEXT"),
        ("updated_at", "TEXT"),
        ("terminal_at", "TEXT"),
    ],
    "trade_fill_event": [
        ("broker_order_id", "TEXT"),
        ("broker_trade_id", "TEXT"),
        ("multiplier", "REAL"),
        ("realized_pnl", "REAL"),
    ],
    "position_snapshot_event": [
        ("long_today", "INTEGER NOT NULL DEFAULT 0"),
        ("long_yesterday", "INTEGER NOT NULL DEFAULT 0"),
        ("short_today", "INTEGER NOT NULL DEFAULT 0"),
        ("short_yesterday", "INTEGER NOT NULL DEFAULT 0"),
        ("avg_entry_price", "REAL"),
        ("unrealized_pnl", "REAL NOT NULL DEFAULT 0"),
    ],
    "account_snapshot_event": [
        ("realized_pnl_today", "REAL NOT NULL DEFAULT 0"),
        ("unrealized_pnl", "REAL NOT NULL DEFAULT 0"),
        ("strategy_drawdown_pct", "REAL NOT NULL DEFAULT 0"),
    ],
    "recon_event": [
        ("severity", "TEXT"),
        ("resolved_at", "TEXT"),
    ],
}

# New tables introduced at version 2 (CREATE IF NOT EXISTS is idempotent)
V2_NEW_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS broker_order_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    local_order_id TEXT,
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    offset TEXT,
    status TEXT NOT NULL,
    filled_qty INTEGER NOT NULL DEFAULT 0,
    remaining_qty INTEGER NOT NULL DEFAULT 0,
    avg_price REAL,
    message TEXT,
    event_time TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, event_id)
);

CREATE TABLE IF NOT EXISTS heartbeat_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    quote_as_of TEXT,
    last_price REAL,
    confirmed_net INTEGER,
    current_target INTEGER,
    pending_desired INTEGER,
    runtime_state TEXT,
    session_open INTEGER,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_health (
    instance_id TEXT PRIMARY KEY,
    last_heartbeat_at TEXT,
    last_bar_at TEXT,
    last_quote_at TEXT,
    unknown_order_count INTEGER NOT NULL DEFAULT 0,
    kill_switch_active INTEGER NOT NULL DEFAULT 0,
    persistence_healthy INTEGER NOT NULL DEFAULT 1,
    runtime_state TEXT NOT NULL DEFAULT 'IDLE',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_snapshot (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    factor_snapshot_id TEXT NOT NULL,
    bar_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    data_as_of TEXT NOT NULL,
    regime TEXT NOT NULL,
    quality TEXT NOT NULL,
    factor_version TEXT NOT NULL,
    values_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, factor_snapshot_id)
);

CREATE TABLE IF NOT EXISTS signal_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    factor_snapshot_id TEXT NOT NULL,
    action TEXT NOT NULL,
    direction INTEGER NOT NULL,
    alpha REAL NOT NULL,
    strength REAL NOT NULL,
    confidence REAL NOT NULL,
    legacy_signal INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, signal_id)
);

CREATE TABLE IF NOT EXISTS target_position_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    current_position INTEGER NOT NULL,
    desired_position INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    planned_stop_price REAL,
    stop_distance REAL,
    sizing_method TEXT NOT NULL,
    requested_risk TEXT NOT NULL,
    config_version TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(instance_id, target_id)
);

CREATE TABLE IF NOT EXISTS signal_state (
    instance_id TEXT PRIMARY KEY,
    previous_alpha REAL,
    consecutive_long_bars INTEGER NOT NULL DEFAULT 0,
    consecutive_short_bars INTEGER NOT NULL DEFAULT 0,
    previous_action TEXT,
    last_signal_id TEXT,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS market_bar (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    bar_id TEXT NOT NULL,
    bar_start TEXT,
    bar_end TEXT NOT NULL,
    available_at TEXT,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL DEFAULT 0,
    open_oi REAL NOT NULL DEFAULT 0,
    close_oi REAL NOT NULL DEFAULT 0,
    underlying_symbol TEXT,
    is_final INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'tqsdk_sim_live',
    instance_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(symbol, duration_sec, bar_end),
    UNIQUE(bar_id)
);

CREATE TABLE IF NOT EXISTS market_quote_l1 (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    last REAL,
    bid1 REAL,
    ask1 REAL,
    bid_vol1 INTEGER,
    ask_vol1 INTEGER,
    spread_ticks REAL,
    upper_locked INTEGER NOT NULL DEFAULT 0,
    lower_locked INTEGER NOT NULL DEFAULT 0,
    instance_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_instrument (
    product_id TEXT PRIMARY KEY,
    exchange_id TEXT NOT NULL,
    name TEXT NOT NULL,
    multiplier REAL NOT NULL,
    price_tick REAL NOT NULL,
    default_margin_rate REAL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    signal_symbol TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_contract (
    symbol TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    listed_at TEXT,
    expire_at TEXT,
    delivery_month TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_continuous_map (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    roll_reason TEXT,
    UNIQUE(signal_symbol, as_of)
);

CREATE TABLE IF NOT EXISTS ref_trading_session (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    exchange_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    weekday_mask TEXT NOT NULL DEFAULT '1,2,3,4,5',
    open_sec INTEGER NOT NULL,
    close_sec INTEGER NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    UNIQUE(product_id, session_id)
);

CREATE TABLE IF NOT EXISTS ref_fee_schedule (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    open_fee REAL NOT NULL,
    close_fee REAL NOT NULL,
    close_today_fee REAL NOT NULL,
    fee_type TEXT NOT NULL DEFAULT 'per_lot',
    UNIQUE(product_id, valid_from)
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    status TEXT NOT NULL,
    git_sha TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS backtest_metric (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    split TEXT NOT NULL DEFAULT 'FULL',
    UNIQUE(run_id, metric_name, split)
);

CREATE TABLE IF NOT EXISTS config_version (
    config_hash TEXT PRIMARY KEY,
    decision_mode TEXT,
    yaml_or_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_definition (
    factor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    formula_hash TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    owner TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_broker_order_intent ON broker_order_event(instance_id, intent_id, event_time);
CREATE INDEX IF NOT EXISTS idx_heartbeat_instance ON heartbeat_event(instance_id, as_of);
CREATE INDEX IF NOT EXISTS idx_factor_snapshot_bar ON factor_snapshot(instance_id, bar_id);
CREATE INDEX IF NOT EXISTS idx_signal_factor ON signal_event(instance_id, factor_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_target_signal ON target_position_event(instance_id, signal_id);
CREATE INDEX IF NOT EXISTS idx_market_bar_symbol ON market_bar(symbol, duration_sec, bar_end);
CREATE INDEX IF NOT EXISTS idx_market_quote_symbol ON market_quote_l1(symbol, as_of);
"""
