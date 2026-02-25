"""SQLite database schema creation and connection management.

Implements all 9 tables from Section 3 of the specification, adapted for
SQLite (INTEGER PRIMARY KEY AUTOINCREMENT instead of SERIAL, CURRENT_TIMESTAMP
instead of NOW(), TEXT for booleans stored as 0/1).

Supports a two-database architecture:
- **Data DB**: ``traders``, ``trade_history``, ``position_snapshots`` —
  collected market data, shared across strategies.
- **Strategy DB**: ``trader_scores``, ``target_allocations``, ``orders``,
  ``our_positions``, ``pnl_ledger``, ``system_state`` —
  per-strategy scoring, portfolio, and execution state.

Public API:
    get_connection(db_path)    - Returns a sqlite3.Connection with WAL mode.
    init_db(db_path)           - Creates all tables and indexes (single-DB mode).
    init_data_db(db_path)      - Creates only data tables + migrations.
    init_strategy_db(db_path)  - Creates only strategy tables + migrations.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# SQL statements for all 9 tables
# ---------------------------------------------------------------------------

_CREATE_TRADERS = """
CREATE TABLE IF NOT EXISTS traders (
    address             TEXT PRIMARY KEY,
    label               TEXT,
    account_value       REAL,
    roi_7d              REAL,
    roi_30d             REAL,
    roi_90d             REAL,
    pnl_7d              REAL,
    pnl_30d             REAL,
    pnl_90d             REAL,
    first_seen_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    blacklisted         INTEGER DEFAULT 0,
    blacklist_reason    TEXT,
    blacklist_until     TEXT,
    updated_at          TEXT
);
"""

_CREATE_TRADER_SCORES = """
CREATE TABLE IF NOT EXISTS trader_scores (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    address                 TEXT NOT NULL,
    scored_at               TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- raw metrics
    roi_7d                  REAL,
    roi_30d                 REAL,
    roi_90d                 REAL,
    pnl_7d                  REAL,
    pnl_30d                 REAL,
    pnl_90d                 REAL,
    win_rate                REAL,
    profit_factor           REAL,
    pseudo_sharpe           REAL,
    trade_count             INTEGER,
    avg_hold_hours          REAL,
    trades_per_day          REAL,
    style                   TEXT,
    -- normalized components
    normalized_roi          REAL,
    normalized_sharpe       REAL,
    normalized_win_rate     REAL,
    consistency_score       REAL,
    smart_money_bonus       REAL,
    risk_mgmt_score         REAL,
    -- multipliers
    style_multiplier        REAL,
    recency_decay           REAL,
    -- final
    composite_score         REAL,
    -- eligibility
    passes_tier1            INTEGER,
    passes_consistency      INTEGER,
    passes_quality          INTEGER,
    is_eligible             INTEGER,
    fail_reason             TEXT
);
"""

_CREATE_TRADER_SCORES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_scores_eligible
    ON trader_scores(is_eligible, composite_score DESC);
"""

_CREATE_POSITION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS position_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_batch      TEXT NOT NULL,
    address             TEXT NOT NULL REFERENCES traders(address),
    token_symbol        TEXT NOT NULL,
    side                TEXT NOT NULL,
    size                REAL,
    entry_price         REAL,
    mark_price          REAL,
    position_value_usd  REAL,
    leverage_value      REAL,
    leverage_type       TEXT,
    liquidation_price   REAL,
    unrealized_pnl      REAL,
    margin_used         REAL,
    account_value       REAL,
    captured_at         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_POSITION_SNAPSHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_snap_batch ON position_snapshots(snapshot_batch);
"""

_CREATE_TRADE_HISTORY = """
CREATE TABLE IF NOT EXISTS trade_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    address             TEXT NOT NULL REFERENCES traders(address),
    token_symbol        TEXT,
    action              TEXT,
    side                TEXT,
    size                REAL,
    price               REAL,
    value_usd           REAL,
    closed_pnl          REAL,
    fee_usd             REAL,
    timestamp           TEXT,
    fetched_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(address, token_symbol, timestamp, action)
);
"""

_CREATE_TARGET_ALLOCATIONS = """
CREATE TABLE IF NOT EXISTS target_allocations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rebalance_id        TEXT NOT NULL,
    token_symbol        TEXT NOT NULL,
    side                TEXT NOT NULL,
    raw_weight          REAL,
    capped_weight       REAL,
    target_usd          REAL,
    target_size         REAL,
    computed_at         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rebalance_id        TEXT,
    token_symbol        TEXT NOT NULL,
    side                TEXT NOT NULL,
    order_type          TEXT NOT NULL,
    intended_usd        REAL,
    intended_size       REAL,
    limit_price         REAL,
    stop_price          REAL,
    status              TEXT DEFAULT 'PENDING',
    hl_order_id         TEXT,
    created_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    sent_at             TEXT,
    filled_at           TEXT,
    filled_size         REAL,
    filled_avg_price    REAL,
    filled_usd          REAL,
    slippage_bps        REAL,
    fee_usd             REAL,
    error_msg           TEXT
);
"""

_CREATE_OUR_POSITIONS = """
CREATE TABLE IF NOT EXISTS our_positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol        TEXT NOT NULL UNIQUE,
    side                TEXT NOT NULL,
    size                REAL,
    entry_price         REAL,
    current_price       REAL,
    position_usd        REAL,
    unrealized_pnl      REAL,
    stop_loss_price     REAL,
    trailing_stop_price REAL,
    trailing_high       REAL,
    opened_at           TEXT,
    max_close_at        TEXT,
    leverage            REAL DEFAULT 5.0,
    updated_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_PNL_LEDGER = """
CREATE TABLE IF NOT EXISTS pnl_ledger (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol        TEXT,
    side                TEXT,
    entry_price         REAL,
    exit_price          REAL,
    size                REAL,
    realized_pnl        REAL,
    fees_total          REAL,
    hold_hours          REAL,
    exit_reason         TEXT,
    closed_at           TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_SYSTEM_STATE = """
CREATE TABLE IF NOT EXISTS system_state (
    key                 TEXT PRIMARY KEY,
    value               TEXT,
    updated_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_ML_FEATURE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS ml_feature_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    address                 TEXT    NOT NULL,
    snapshot_date           TEXT    NOT NULL,
    roi_7d                  REAL,
    roi_30d                 REAL,
    roi_90d                 REAL,
    pnl_7d                  REAL,
    pnl_30d                 REAL,
    pnl_90d                 REAL,
    win_rate                REAL,
    profit_factor           REAL,
    pseudo_sharpe           REAL,
    trade_count             INTEGER,
    avg_hold_hours          REAL,
    trades_per_day          REAL,
    consistency_score       REAL,
    smart_money_bonus       REAL,
    risk_mgmt_score         REAL,
    recency_decay           REAL,
    position_concentration  REAL,
    num_open_positions      INTEGER,
    avg_leverage            REAL,
    pnl_volatility_7d      REAL,
    market_correlation      REAL,
    days_since_last_trade   REAL,
    max_drawdown_30d        REAL,
    forward_pnl_7d          REAL,
    created_at              TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_ML_MODELS = """
CREATE TABLE IF NOT EXISTS ml_models (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    version                 INTEGER NOT NULL,
    trained_at              TEXT    NOT NULL,
    train_rmse              REAL,
    val_rmse                REAL,
    test_rmse               REAL,
    top15_backtest_pnl      REAL,
    feature_importances     TEXT,
    model_path              TEXT,
    is_active               INTEGER DEFAULT 0
);
"""

# ---------------------------------------------------------------------------
# Grouped DDL: Data DB vs Strategy DB
# ---------------------------------------------------------------------------

_DATA_STATEMENTS: list[str] = [
    _CREATE_TRADERS,
    _CREATE_TRADE_HISTORY,
    _CREATE_POSITION_SNAPSHOTS,
    _CREATE_POSITION_SNAPSHOTS_INDEX,
]

_STRATEGY_STATEMENTS: list[str] = [
    _CREATE_TRADER_SCORES,
    _CREATE_TRADER_SCORES_INDEX,
    _CREATE_TARGET_ALLOCATIONS,
    _CREATE_ORDERS,
    _CREATE_OUR_POSITIONS,
    _CREATE_PNL_LEDGER,
    _CREATE_SYSTEM_STATE,
    _CREATE_ML_FEATURE_SNAPSHOTS,
    _CREATE_ML_MODELS,
]

# Ordered list of all DDL statements (single-DB compat)
_ALL_STATEMENTS: list[str] = _DATA_STATEMENTS + _STRATEGY_STATEMENTS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) a SQLite database and configure it for our workload.

    Settings applied:
    - WAL journal mode for concurrent readers.
    - Foreign keys enforced.
    - Row factory set to sqlite3.Row for dict-like access.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file.  Use `":memory:"` for
        an ephemeral in-memory database (useful in tests).

    Returns
    -------
    sqlite3.Connection
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create all tables and indexes, returning the open connection.

    This function is idempotent: calling it multiple times on the same
    database is safe because every statement uses ``IF NOT EXISTS``.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file, or `":memory:"`.

    Returns
    -------
    sqlite3.Connection
        The connection with all tables created, ready for use.
    """
    conn = get_connection(db_path)
    with conn:
        for stmt in _ALL_STATEMENTS:
            conn.execute(stmt)
        _migrate_our_positions(conn)
        _migrate_traders(conn)
    return conn


def init_data_db(db_path: str | Path) -> sqlite3.Connection:
    """Create only the data tables (traders, trade_history, position_snapshots).

    Use this when running the two-database architecture where collected
    market data lives in a separate database from strategy state.

    Parameters
    ----------
    db_path:
        Filesystem path to the data database file, or `":memory:"`.

    Returns
    -------
    sqlite3.Connection
    """
    conn = get_connection(db_path)
    with conn:
        for stmt in _DATA_STATEMENTS:
            conn.execute(stmt)
        _migrate_traders(conn)
    return conn


def init_strategy_db(db_path: str | Path) -> sqlite3.Connection:
    """Create only the strategy tables (scores, allocations, orders, etc.).

    Use this when running the two-database architecture where per-strategy
    state lives in a separate database from collected market data.

    Parameters
    ----------
    db_path:
        Filesystem path to the strategy database file, or `":memory:"`.

    Returns
    -------
    sqlite3.Connection
    """
    conn = get_connection(db_path)
    with conn:
        for stmt in _STRATEGY_STATEMENTS:
            conn.execute(stmt)
        _migrate_our_positions(conn)
    return conn


# ---------------------------------------------------------------------------
# Internal migration helpers
# ---------------------------------------------------------------------------


def _migrate_our_positions(conn: sqlite3.Connection) -> None:
    """Add leverage column to our_positions if missing (pre-TUI DBs)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(our_positions)").fetchall()}
    if "leverage" not in cols:
        conn.execute("ALTER TABLE our_positions ADD COLUMN leverage REAL DEFAULT 5.0")


def _migrate_traders(conn: sqlite3.Connection) -> None:
    """Add roi/pnl columns to traders if missing (pre-collector DBs)."""
    trader_cols = {r[1] for r in conn.execute("PRAGMA table_info(traders)").fetchall()}
    for col in ("roi_7d", "roi_30d", "roi_90d", "pnl_7d", "pnl_30d", "pnl_90d"):
        if col not in trader_cols:
            conn.execute(f"ALTER TABLE traders ADD COLUMN {col} REAL")
