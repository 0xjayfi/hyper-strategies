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

from snap.database import init_data_db, init_db, init_strategy_db, get_connection

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
    "ml_feature_snapshots",
    "ml_models",
}

EXPECTED_DATA_TABLES = {
    "traders",
    "trade_history",
    "position_snapshots",
}

EXPECTED_STRATEGY_TABLES = {
    "trader_scores",
    "target_allocations",
    "orders",
    "our_positions",
    "pnl_ledger",
    "system_state",
    "ml_feature_snapshots",
    "ml_models",
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
        "roi_7d",
        "roi_30d",
        "roi_90d",
        "pnl_7d",
        "pnl_30d",
        "pnl_90d",
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


def test_our_positions_has_leverage_column(tmp_path):
    """The our_positions table has a leverage column with default 5.0."""
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)

    cursor = conn.execute("PRAGMA table_info(our_positions);")
    columns = {row[1]: row for row in cursor.fetchall()}
    conn.close()

    assert "leverage" in columns
    # Column info: (cid, name, type, notnull, dflt_value, pk)
    lev_col = columns["leverage"]
    assert lev_col[2] == "REAL"  # type
    assert lev_col[4] == "5.0"  # default value


# ===========================================================================
# Two-Database Architecture Tests
# ===========================================================================


def test_init_data_db_creates_only_data_tables(tmp_path):
    """init_data_db creates only data tables (traders, trade_history, position_snapshots)."""
    db_path = str(tmp_path / "data.db")
    conn = init_data_db(db_path)

    table_names = _get_table_names(conn)
    conn.close()

    assert table_names == EXPECTED_DATA_TABLES


def test_init_strategy_db_creates_only_strategy_tables(tmp_path):
    """init_strategy_db creates only strategy tables."""
    db_path = str(tmp_path / "strategy.db")
    conn = init_strategy_db(db_path)

    table_names = _get_table_names(conn)
    conn.close()

    assert table_names == EXPECTED_STRATEGY_TABLES


def test_init_data_db_idempotent(tmp_path):
    """Calling init_data_db twice is safe."""
    db_path = str(tmp_path / "data.db")
    conn1 = init_data_db(db_path)
    tables1 = _get_table_names(conn1)
    conn1.close()

    conn2 = init_data_db(db_path)
    tables2 = _get_table_names(conn2)
    conn2.close()

    assert tables1 == tables2 == EXPECTED_DATA_TABLES


def test_init_strategy_db_idempotent(tmp_path):
    """Calling init_strategy_db twice is safe."""
    db_path = str(tmp_path / "strategy.db")
    conn1 = init_strategy_db(db_path)
    tables1 = _get_table_names(conn1)
    conn1.close()

    conn2 = init_strategy_db(db_path)
    tables2 = _get_table_names(conn2)
    conn2.close()

    assert tables1 == tables2 == EXPECTED_STRATEGY_TABLES


def test_data_and_strategy_tables_are_disjoint():
    """Data and strategy table sets have no overlap."""
    assert EXPECTED_DATA_TABLES & EXPECTED_STRATEGY_TABLES == set()


def test_data_plus_strategy_equals_all():
    """Data tables + strategy tables = all tables."""
    assert EXPECTED_DATA_TABLES | EXPECTED_STRATEGY_TABLES == EXPECTED_TABLES


def test_init_data_db_in_memory():
    """init_data_db works with in-memory database."""
    conn = init_data_db(":memory:")
    tables = _get_table_names(conn)
    conn.close()
    assert tables == EXPECTED_DATA_TABLES


def test_init_strategy_db_in_memory():
    """init_strategy_db works with in-memory database."""
    conn = init_strategy_db(":memory:")
    tables = _get_table_names(conn)
    conn.close()
    assert tables == EXPECTED_STRATEGY_TABLES


def test_strategy_db_has_leverage_column(tmp_path):
    """init_strategy_db creates our_positions with leverage column."""
    db_path = str(tmp_path / "strategy.db")
    conn = init_strategy_db(db_path)

    cursor = conn.execute("PRAGMA table_info(our_positions);")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    assert "leverage" in columns


def test_trader_scores_no_fk_constraint(tmp_path):
    """trader_scores address column has no FK to traders (cross-DB safe)."""
    db_path = str(tmp_path / "strategy.db")
    conn = init_strategy_db(db_path)

    # Should be able to insert a score without a corresponding traders row
    conn.execute(
        """INSERT INTO trader_scores (address, composite_score, is_eligible)
           VALUES (?, ?, ?)""",
        ("0xNONEXISTENT", 0.5, 1),
    )
    conn.commit()

    row = conn.execute(
        "SELECT address FROM trader_scores WHERE address = ?",
        ("0xNONEXISTENT",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "0xNONEXISTENT"
