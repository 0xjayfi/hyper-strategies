"""SQLite database initialization and query helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("consensus.db")

SCHEMA_SQL = """\
-- Trader registry (refreshed daily)
CREATE TABLE IF NOT EXISTS traders (
    address TEXT PRIMARY KEY,
    label TEXT,
    score REAL,
    style TEXT,
    cluster_id INTEGER,
    account_value_usd REAL,
    roi_7d REAL,
    roi_30d REAL,
    roi_90d REAL,
    trade_count INTEGER,
    last_scored_at TEXT,
    is_active INTEGER DEFAULT 1,
    blacklisted_until TEXT
);

-- Raw trades (append-only, deduped by tx_hash)
CREATE TABLE IF NOT EXISTS trades (
    transaction_hash TEXT PRIMARY KEY,
    trader_address TEXT,
    token_symbol TEXT,
    side TEXT,
    action TEXT,
    size REAL,
    price_usd REAL,
    value_usd REAL,
    timestamp TEXT,
    fee_usd REAL,
    closed_pnl REAL
);

CREATE INDEX IF NOT EXISTS idx_trades_trader_token
    ON trades(trader_address, token_symbol);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp
    ON trades(timestamp);

-- Consensus snapshots (for backtesting and audit trail)
CREATE TABLE IF NOT EXISTS consensus_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol TEXT,
    timestamp TEXT,
    consensus TEXT,
    long_count INTEGER,
    short_count INTEGER,
    long_volume_usd REAL,
    short_volume_usd REAL,
    long_cluster_count INTEGER,
    short_cluster_count INTEGER
);

-- Our positions (active and historical)
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol TEXT,
    side TEXT,
    entry_price_usd REAL,
    exit_price_usd REAL,
    size_usd REAL,
    leverage INTEGER,
    stop_loss_price REAL,
    opened_at TEXT,
    closed_at TEXT,
    close_reason TEXT,
    pnl_usd REAL
);
"""


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create all tables and return the connection."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
