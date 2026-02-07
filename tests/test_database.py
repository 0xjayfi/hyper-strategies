"""Unit tests for the database module.

Tests cover:
- All 9 tables are created by init_db
- init_db is idempotent (safe to call multiple times)
- WAL journal mode is configured
- Foreign key enforcement is enabled
- get_connection configures Row factory
"""

from __future__ import annotations

import sqlite3

import pytest

from snap.database import init_db, get_connection

# The 9 expected tables from the spec
EXPECTED_TABLES = {
    "traders",
    "trader_scores",
    "position_snapshots",
    "trade_history",
    "target_allocations",
    "orders",
    "our_positions",
    "pnl_ledger",
    "system_state",
}


def _get_table_names(conn: sqlite3.Connection) -> set[str]:
    """Return a set of user table names in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in cursor.fetchall()}


def test_init_db_creates_all_tables(tmp_path):
    """init_db creates all 9 tables defined in the schema."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    table_names = _get_table_names(conn)
    conn.close()

    assert table_names == EXPECTED_TABLES


def test_init_db_idempotent(tmp_path):
    """Calling init_db twice on the same database does not raise errors."""
    db_path = str(tmp_path / "test.db")

    conn1 = init_db(db_path)
    tables1 = _get_table_names(conn1)
    conn1.close()

    # Second call should be a no-op
    conn2 = init_db(db_path)
    tables2 = _get_table_names(conn2)
    conn2.close()

    assert tables1 == tables2 == EXPECTED_TABLES


def test_wal_mode(tmp_path):
    """WAL journal mode is set by get_connection."""
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)

    result = conn.execute("PRAGMA journal_mode;").fetchone()
    conn.close()

    # sqlite3.Row returns a Row object; index 0 is the journal_mode value
    assert result[0] == "wal"


def test_foreign_keys_enabled(tmp_path):
    """Foreign key enforcement is enabled by get_connection."""
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)

    result = conn.execute("PRAGMA foreign_keys;").fetchone()
    conn.close()

    assert result[0] == 1


def test_row_factory_set(tmp_path):
    """get_connection sets row_factory to sqlite3.Row for dict-like access."""
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)

    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_init_db_creates_indexes(tmp_path):
    """init_db creates the expected indexes."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    )
    index_names = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "idx_scores_eligible" in index_names
    assert "idx_snap_batch" in index_names


def test_traders_table_schema(tmp_path):
    """The traders table has the expected columns."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    cursor = conn.execute("PRAGMA table_info(traders);")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    expected_columns = {
        "address",
        "label",
        "account_value",
        "first_seen_at",
        "blacklisted",
        "blacklist_reason",
        "blacklist_until",
        "updated_at",
    }
    assert columns == expected_columns


def test_position_snapshots_table_schema(tmp_path):
    """The position_snapshots table has the expected columns."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    cursor = conn.execute("PRAGMA table_info(position_snapshots);")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    expected_columns = {
        "id",
        "snapshot_batch",
        "address",
        "token_symbol",
        "side",
        "size",
        "entry_price",
        "mark_price",
        "position_value_usd",
        "leverage_value",
        "leverage_type",
        "liquidation_price",
        "unrealized_pnl",
        "margin_used",
        "account_value",
        "captured_at",
    }
    assert columns == expected_columns


def test_trade_history_unique_constraint(tmp_path):
    """The trade_history table enforces uniqueness on (address, token_symbol, timestamp, action)."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    # First insert the trader (FK requirement)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xTEST", "", 100000.0),
    )

    # Insert a trade
    conn.execute(
        """INSERT INTO trade_history
           (address, token_symbol, action, side, size, price, value_usd,
            closed_pnl, fee_usd, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("0xTEST", "BTC", "Open", "Long", 0.1, 45000.0, 4500.0, 0.0, 1.0,
         "2025-10-01T12:00:00"),
    )
    conn.commit()

    # Duplicate insert should fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO trade_history
               (address, token_symbol, action, side, size, price, value_usd,
                closed_pnl, fee_usd, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("0xTEST", "BTC", "Open", "Long", 0.1, 45000.0, 4500.0, 0.0, 1.0,
             "2025-10-01T12:00:00"),
        )

    conn.close()


def test_memory_database():
    """init_db works with an in-memory database."""
    conn = init_db(":memory:")
    table_names = _get_table_names(conn)
    conn.close()

    assert table_names == EXPECTED_TABLES
