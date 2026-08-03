-- D1 schema mirroring alpha_engine/db.py + alpha_engine/ops.py (SQLite dialect, D1-compatible)

CREATE TABLE IF NOT EXISTS positions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    token_id TEXT,
    question TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    stake_usdc REAL NOT NULL,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    last_price REAL,
    last_marked_at TEXT,
    exit_price REAL,
    closed_at TEXT,
    pnl_usdc REAL,
    resolution TEXT,
    category TEXT,
    event_key TEXT,
    peak_price REAL,
    edge_gone_count INTEGER DEFAULT 0,
    entry_fee_usdc REAL DEFAULT 0,
    exit_fee_usdc REAL DEFAULT 0,
    strategy_version TEXT,
    campaign_id TEXT,
    mfe_pct REAL DEFAULT 0,
    mae_pct REAL DEFAULT 0,
    peak_value_usdc REAL,
    trough_value_usdc REAL,
    entry_reason TEXT,
    close_detail_json TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_open_market
    ON positions(market_id) WHERE status='OPEN';
CREATE INDEX IF NOT EXISTS ix_positions_status_event ON positions(status,event_key);
CREATE INDEX IF NOT EXISTS ix_positions_status_category ON positions(status,category);

CREATE TABLE IF NOT EXISTS snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT,
    captured_at TEXT,
    question TEXT,
    yes_price REAL,
    no_price REAL,
    bid REAL,
    ask REAL,
    spread REAL,
    liquidity REAL,
    volume REAL,
    volume_24h REAL,
    rank_score REAL,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_market_time ON snapshots(market_id,captured_at);

CREATE TABLE IF NOT EXISTS analyses(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT,
    created_at TEXT,
    side TEXT,
    fair_probability REAL,
    market_probability REAL,
    gross_edge REAL,
    net_edge REAL,
    confidence REAL,
    critic_risk REAL,
    score REAL,
    stake_usdc REAL,
    decision TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_analysis_market_time ON analyses(market_id,created_at);

CREATE TABLE IF NOT EXISTS cycles(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    markets_seen INTEGER,
    eligible INTEGER,
    analysed INTEGER,
    opened INTEGER,
    error TEXT
);

CREATE TABLE IF NOT EXISTS decision_ledger(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    cycle_id INTEGER,
    market_id TEXT,
    position_id INTEGER,
    action TEXT NOT NULL,
    reason TEXT,
    strategy_version TEXT,
    campaign_id TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_ledger_time ON decision_ledger(created_at);
CREATE INDEX IF NOT EXISTS ix_ledger_market ON decision_ledger(market_id,created_at);

CREATE TABLE IF NOT EXISTS entry_confirmations(
    market_id TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    confirmations INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_edge REAL,
    last_confidence REAL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS service_health(
    component TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error TEXT,
    paused_until TEXT
);

CREATE TABLE IF NOT EXISTS campaigns(
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    strategy_version TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS maintenance_runs(
    name TEXT PRIMARY KEY,
    last_run_at TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS equity_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    equity REAL NOT NULL,
    total_pnl REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    exposure REAL NOT NULL,
    open_positions INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_equity_history_time ON equity_history(captured_at);
