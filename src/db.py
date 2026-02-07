from __future__ import annotations

import aiosqlite
from pathlib import Path
from typing import Any

DB_PATH = "data/signals.db"


async def _get_db() -> aiosqlite.Connection:
    """Get a database connection with row factory set."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init() -> None:
    """Initialize the database by creating the directory and all tables."""
    # Create data directory if it doesn't exist
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await _get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS traders (
                address TEXT PRIMARY KEY,
                label TEXT,
                score REAL,
                style TEXT,
                tier TEXT,
                roi_7d REAL,
                roi_30d REAL,
                account_value REAL,
                nof_trades INTEGER,
                last_scored_at TEXT,
                blacklisted_until TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS trader_positions (
                address TEXT,
                token_symbol TEXT,
                side TEXT,
                position_value_usd REAL,
                entry_price REAL,
                last_seen_at TEXT,
                PRIMARY KEY (address, token_symbol)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS our_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                size REAL NOT NULL,
                value_usd REAL NOT NULL,
                stop_price REAL,
                trailing_stop_price REAL,
                highest_price REAL,
                lowest_price REAL,
                opened_at TEXT NOT NULL,
                source_trader TEXT,
                source_signal_id TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                close_reason TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                trader_address TEXT,
                token_symbol TEXT,
                side TEXT,
                action TEXT,
                value_usd REAL,
                position_weight REAL,
                timestamp TEXT,
                age_seconds REAL,
                slippage_check_passed INTEGER,
                trader_score REAL,
                copy_size_usd REAL,
                decision TEXT,
                created_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_trades (
                transaction_hash TEXT PRIMARY KEY,
                seen_at TEXT
            )
        """)

        await db.commit()
    finally:
        await db.close()


# ============================================================================
# TRADERS
# ============================================================================

async def upsert_trader(
    address: str,
    label: str | None,
    score: float | None,
    style: str | None,
    tier: str | None,
    roi_7d: float | None,
    roi_30d: float | None,
    account_value: float | None,
    nof_trades: int | None,
    last_scored_at: str | None,
) -> None:
    """Insert or replace a trader record."""
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT OR REPLACE INTO traders (
                address, label, score, style, tier, roi_7d, roi_30d,
                account_value, nof_trades, last_scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (address, label, score, style, tier, roi_7d, roi_30d,
             account_value, nof_trades, last_scored_at),
        )
        await db.commit()
    finally:
        await db.close()


async def get_trader(address: str) -> dict[str, Any] | None:
    """Get a trader by address."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM traders WHERE address = ?",
            (address,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_primary_traders() -> list[dict[str, Any]]:
    """Get all primary traders that are not blacklisted."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM traders
            WHERE tier = 'primary'
              AND (blacklisted_until IS NULL OR blacklisted_until < datetime('now'))
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_all_traders() -> list[dict[str, Any]]:
    """Get all traders."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM traders")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def blacklist_trader(address: str, until: str) -> None:
    """Blacklist a trader until a specific time."""
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE traders SET blacklisted_until = ? WHERE address = ?",
            (until, address),
        )
        await db.commit()
    finally:
        await db.close()


# ============================================================================
# TRADER POSITIONS
# ============================================================================

async def upsert_trader_position(
    address: str,
    token_symbol: str,
    side: str | None,
    position_value_usd: float | None,
    entry_price: float | None,
    last_seen_at: str | None,
) -> None:
    """Insert or replace a trader position record."""
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT OR REPLACE INTO trader_positions (
                address, token_symbol, side, position_value_usd,
                entry_price, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (address, token_symbol, side, position_value_usd,
             entry_price, last_seen_at),
        )
        await db.commit()
    finally:
        await db.close()


async def get_trader_positions(address: str) -> list[dict[str, Any]]:
    """Get all positions for a trader."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM trader_positions WHERE address = ?",
            (address,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


# ============================================================================
# OUR POSITIONS
# ============================================================================

async def insert_our_position(**kwargs: Any) -> int:
    """Insert a new position and return the row id."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO our_positions (
                token_symbol, side, entry_price, size, value_usd,
                stop_price, trailing_stop_price, highest_price, lowest_price,
                opened_at, source_trader, source_signal_id, status, close_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kwargs.get("token_symbol"),
                kwargs.get("side"),
                kwargs.get("entry_price"),
                kwargs.get("size"),
                kwargs.get("value_usd"),
                kwargs.get("stop_price"),
                kwargs.get("trailing_stop_price"),
                kwargs.get("highest_price"),
                kwargs.get("lowest_price"),
                kwargs.get("opened_at"),
                kwargs.get("source_trader"),
                kwargs.get("source_signal_id"),
                kwargs.get("status", "open"),
                kwargs.get("close_reason"),
            ),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_open_positions() -> list[dict[str, Any]]:
    """Get all open positions."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM our_positions WHERE status = 'open'"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def update_position(id: int, **kwargs: Any) -> None:
    """Update a position with dynamic fields."""
    if not kwargs:
        return

    db = await _get_db()
    try:
        # Build dynamic UPDATE statement
        set_clauses = []
        values = []
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)

        values.append(id)
        sql = f"UPDATE our_positions SET {', '.join(set_clauses)} WHERE id = ?"

        await db.execute(sql, values)
        await db.commit()
    finally:
        await db.close()


async def close_position(id: int, close_reason: str) -> None:
    """Close a position with a reason."""
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE our_positions SET status = 'closed', close_reason = ? WHERE id = ?",
            (close_reason, id),
        )
        await db.commit()
    finally:
        await db.close()


# ============================================================================
# SIGNALS
# ============================================================================

async def insert_signal(**kwargs: Any) -> None:
    """Insert a new signal record."""
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO signals (
                id, trader_address, token_symbol, side, action, value_usd,
                position_weight, timestamp, age_seconds, slippage_check_passed,
                trader_score, copy_size_usd, decision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kwargs.get("id"),
                kwargs.get("trader_address"),
                kwargs.get("token_symbol"),
                kwargs.get("side"),
                kwargs.get("action"),
                kwargs.get("value_usd"),
                kwargs.get("position_weight"),
                kwargs.get("timestamp"),
                kwargs.get("age_seconds"),
                kwargs.get("slippage_check_passed"),
                kwargs.get("trader_score"),
                kwargs.get("copy_size_usd"),
                kwargs.get("decision"),
                kwargs.get("created_at"),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_signal(id: str) -> dict[str, Any] | None:
    """Get a signal by id."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM signals WHERE id = ?",
            (id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


# ============================================================================
# SEEN TRADES
# ============================================================================

async def is_seen(transaction_hash: str) -> bool:
    """Check if a transaction hash has been seen."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM seen_trades WHERE transaction_hash = ?",
            (transaction_hash,),
        )
        row = await cursor.fetchone()
        return row is not None
    finally:
        await db.close()


async def mark_seen(transaction_hash: str, seen_at: str) -> None:
    """Mark a transaction hash as seen."""
    db = await _get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO seen_trades (transaction_hash, seen_at) VALUES (?, ?)",
            (transaction_hash, seen_at),
        )
        await db.commit()
    finally:
        await db.close()
