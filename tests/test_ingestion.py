"""Unit tests for the ingestion services.

Tests cover:
- Leaderboard merge logic across 3 timeframes
- Position snapshot storage with correct side derivation
- Trade deduplication via UNIQUE constraint
- All trade fields stored correctly
"""

from __future__ import annotations

import sqlite3

import pytest
from unittest.mock import AsyncMock

from snap.database import init_db
from snap.ingestion import ingest_leaderboard, ingest_positions, ingest_trades


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary SQLite database with all tables initialised."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.close()
    return path


def _make_leaderboard_client(
    entries_7d: list[dict],
    entries_30d: list[dict],
    entries_90d: list[dict],
) -> AsyncMock:
    """Create a mock NansenClient whose get_leaderboard returns different
    data depending on the date range.

    The mock inspects the ``date_from`` argument to decide which entries to
    return: the 7d call has the most recent ``date_from``, then 30d, then 90d.
    """
    client = AsyncMock()

    call_count = 0

    async def mock_get_leaderboard(
        date_from, date_to, min_account_value=50_000, min_total_pnl=0
    ):
        nonlocal call_count
        call_count += 1
        # The function is called in order: 7d, 30d, 90d
        if call_count == 1:
            return entries_7d
        elif call_count == 2:
            return entries_30d
        else:
            return entries_90d

    client.get_leaderboard = mock_get_leaderboard
    return client


# ---------------------------------------------------------------------------
# Leaderboard tests
# ---------------------------------------------------------------------------


async def test_ingest_leaderboard_merges_timeframes(db_path):
    """Leaderboard data from 3 timeframes is merged correctly by address."""
    # Trader A appears in all 3 ranges with different ROI and PnL
    # Trader B appears only in 30d and 90d
    # Trader C appears only in 7d

    entries_7d = [
        {
            "trader_address": "0xAAA",
            "trader_address_label": "Smart Money",
            "total_pnl": 5000.0,
            "roi": 8.0,
            "account_value": 100000.0,
        },
        {
            "trader_address": "0xCCC",
            "trader_address_label": "",
            "total_pnl": 2000.0,
            "roi": 4.0,
            "account_value": 60000.0,
        },
    ]

    entries_30d = [
        {
            "trader_address": "0xAAA",
            "trader_address_label": "",
            "total_pnl": 20000.0,
            "roi": 22.0,
            "account_value": 95000.0,
        },
        {
            "trader_address": "0xBBB",
            "trader_address_label": "Fund",
            "total_pnl": 15000.0,
            "roi": 18.0,
            "account_value": 80000.0,
        },
    ]

    entries_90d = [
        {
            "trader_address": "0xAAA",
            "trader_address_label": "Smart Money",
            "total_pnl": 60000.0,
            "roi": 40.0,
            "account_value": 110000.0,
        },
        {
            "trader_address": "0xBBB",
            "trader_address_label": "",
            "total_pnl": 50000.0,
            "roi": 35.0,
            "account_value": 85000.0,
        },
    ]

    client = _make_leaderboard_client(entries_7d, entries_30d, entries_90d)

    count = await ingest_leaderboard(client, db_path)

    # 3 unique traders: 0xAAA, 0xBBB, 0xCCC
    assert count == 3

    # Verify database state
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM traders ORDER BY address"
    ).fetchall()
    conn.close()

    assert len(rows) == 3

    # Trader 0xAAA: max account_value is 110000 (from 90d),
    # label is "Smart Money" (from 7d, first non-empty)
    trader_a = dict(rows[0])
    assert trader_a["address"] == "0xAAA"
    assert trader_a["account_value"] == 110000.0
    assert trader_a["label"] == "Smart Money"

    # Trader 0xBBB: max account_value is 85000 (from 90d), label is "Fund" (from 30d)
    trader_b = dict(rows[1])
    assert trader_b["address"] == "0xBBB"
    assert trader_b["account_value"] == 85000.0
    assert trader_b["label"] == "Fund"

    # Trader 0xCCC: only appears in 7d, account_value 60000
    trader_c = dict(rows[2])
    assert trader_c["address"] == "0xCCC"
    assert trader_c["account_value"] == 60000.0
    assert trader_c["label"] == ""


async def test_ingest_leaderboard_updates_existing_traders(db_path):
    """Running ingest_leaderboard twice updates (replaces) existing rows."""
    entries_7d_v1 = [
        {
            "trader_address": "0xAAA",
            "trader_address_label": "",
            "total_pnl": 1000.0,
            "roi": 5.0,
            "account_value": 50000.0,
        }
    ]
    client_v1 = _make_leaderboard_client(entries_7d_v1, [], [])
    await ingest_leaderboard(client_v1, db_path)

    # Second run with higher account_value
    entries_7d_v2 = [
        {
            "trader_address": "0xAAA",
            "trader_address_label": "Whale",
            "total_pnl": 10000.0,
            "roi": 15.0,
            "account_value": 200000.0,
        }
    ]
    client_v2 = _make_leaderboard_client(entries_7d_v2, [], [])
    await ingest_leaderboard(client_v2, db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM traders WHERE address = '0xAAA'").fetchall()
    conn.close()

    # Still only 1 row (upsert, not duplicate)
    assert len(rows) == 1
    assert rows[0]["account_value"] == 200000.0
    assert rows[0]["label"] == "Whale"


# ---------------------------------------------------------------------------
# Positions tests
# ---------------------------------------------------------------------------


async def test_ingest_positions_stores_snapshots(db_path):
    """Position data is correctly stored in position_snapshots table."""
    # First insert the trader into the traders table (FK requirement)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xTRADER1", "Test Trader", 500000.0),
    )
    conn.commit()
    conn.close()

    mock_response = {
        "asset_positions": [
            {
                "position": {
                    "token_symbol": "BTC",
                    "entry_price_usd": "45000.0",
                    "leverage_type": "isolated",
                    "leverage_value": 5,
                    "liquidation_price_usd": "38000.0",
                    "margin_used_usd": "9000.0",
                    "position_value_usd": "45000.0",
                    "size": "1.0",
                    "unrealized_pnl_usd": "2000.0",
                },
                "position_type": "oneWay",
            },
            {
                "position": {
                    "token_symbol": "ETH",
                    "entry_price_usd": "3000.0",
                    "leverage_type": "cross",
                    "leverage_value": 3,
                    "liquidation_price_usd": "5000.0",
                    "margin_used_usd": "10000.0",
                    "position_value_usd": "30000.0",
                    "size": "-10.0",
                    "unrealized_pnl_usd": "-800.0",
                },
                "position_type": "oneWay",
            },
        ],
        "margin_summary_account_value_usd": "500000.0",
        "timestamp": 1700000000000,
    }

    client = AsyncMock()
    client.get_perp_positions = AsyncMock(return_value=mock_response)

    count = await ingest_positions(
        client, db_path, ["0xTRADER1"], snapshot_batch="batch-uuid-001"
    )

    assert count == 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM position_snapshots ORDER BY token_symbol"
    ).fetchall()
    conn.close()

    assert len(rows) == 2

    btc = dict(rows[0])
    assert btc["snapshot_batch"] == "batch-uuid-001"
    assert btc["address"] == "0xTRADER1"
    assert btc["token_symbol"] == "BTC"
    assert btc["side"] == "Long"
    assert btc["size"] == 1.0
    assert btc["entry_price"] == 45000.0
    assert btc["position_value_usd"] == 45000.0
    assert btc["leverage_value"] == 5.0
    assert btc["leverage_type"] == "isolated"
    assert btc["account_value"] == 500000.0

    eth = dict(rows[1])
    assert eth["token_symbol"] == "ETH"
    assert eth["side"] == "Short"
    assert eth["size"] == 10.0  # abs(-10.0)
    assert eth["unrealized_pnl"] == -800.0


async def test_ingest_positions_determines_side(db_path):
    """Positive size yields 'Long', negative size yields 'Short'."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xSIDETEST", "", 100000.0),
    )
    conn.commit()
    conn.close()

    mock_response = {
        "asset_positions": [
            {
                "position": {
                    "token_symbol": "SOL",
                    "entry_price_usd": "150.0",
                    "leverage_type": "cross",
                    "leverage_value": 2,
                    "liquidation_price_usd": "100.0",
                    "margin_used_usd": "1500.0",
                    "position_value_usd": "3000.0",
                    "size": "20.0",
                    "unrealized_pnl_usd": "100.0",
                },
                "position_type": "oneWay",
            },
            {
                "position": {
                    "token_symbol": "HYPE",
                    "entry_price_usd": "10.0",
                    "leverage_type": "isolated",
                    "leverage_value": 3,
                    "liquidation_price_usd": "15.0",
                    "margin_used_usd": "500.0",
                    "position_value_usd": "1500.0",
                    "size": "-150.0",
                    "unrealized_pnl_usd": "-50.0",
                },
                "position_type": "oneWay",
            },
        ],
        "margin_summary_account_value_usd": "100000.0",
    }

    client = AsyncMock()
    client.get_perp_positions = AsyncMock(return_value=mock_response)

    await ingest_positions(
        client, db_path, ["0xSIDETEST"], snapshot_batch="side-test-batch"
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT token_symbol, side, size FROM position_snapshots ORDER BY token_symbol"
    ).fetchall()
    conn.close()

    hype = dict(rows[0])
    assert hype["token_symbol"] == "HYPE"
    assert hype["side"] == "Short"
    assert hype["size"] == 150.0

    sol = dict(rows[1])
    assert sol["token_symbol"] == "SOL"
    assert sol["side"] == "Long"
    assert sol["size"] == 20.0


async def test_ingest_positions_computes_mark_price(db_path):
    """Mark price is computed as position_value_usd / abs(size)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xMARK", "", 50000.0),
    )
    conn.commit()
    conn.close()

    mock_response = {
        "asset_positions": [
            {
                "position": {
                    "token_symbol": "BTC",
                    "entry_price_usd": "45000.0",
                    "leverage_type": "cross",
                    "leverage_value": 1,
                    "liquidation_price_usd": "30000.0",
                    "margin_used_usd": "50000.0",
                    "position_value_usd": "50000.0",
                    "size": "1.0",
                    "unrealized_pnl_usd": "5000.0",
                },
                "position_type": "oneWay",
            },
        ],
        "margin_summary_account_value_usd": "50000.0",
    }

    client = AsyncMock()
    client.get_perp_positions = AsyncMock(return_value=mock_response)

    await ingest_positions(
        client, db_path, ["0xMARK"], snapshot_batch="mark-batch"
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT mark_price FROM position_snapshots WHERE token_symbol='BTC'"
    ).fetchone()
    conn.close()

    # mark_price = 50000.0 / 1.0 = 50000.0
    assert row["mark_price"] == pytest.approx(50000.0)


# ---------------------------------------------------------------------------
# Trades tests
# ---------------------------------------------------------------------------


async def test_ingest_trades_stores_all_fields(db_path):
    """All trade fields are stored correctly in the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xTRADER1", "", 100000.0),
    )
    conn.commit()
    conn.close()

    mock_trades = [
        {
            "action": "Open",
            "closed_pnl": 0,
            "fee_usd": 2.5,
            "price": 45000.0,
            "side": "Long",
            "size": 0.1,
            "timestamp": "2025-10-01T12:00:00.000000",
            "token_symbol": "BTC",
            "value_usd": 4500.0,
        },
        {
            "action": "Close",
            "closed_pnl": 500.0,
            "fee_usd": 3.0,
            "price": 50000.0,
            "side": "Long",
            "size": 0.1,
            "timestamp": "2025-10-05T14:30:00.000000",
            "token_symbol": "BTC",
            "value_usd": 5000.0,
        },
    ]

    client = AsyncMock()
    client.get_perp_trades = AsyncMock(return_value=mock_trades)

    count = await ingest_trades(
        client, db_path, ["0xTRADER1"], date_from="2025-09-01", date_to="2025-10-10"
    )

    assert count == 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM trade_history ORDER BY timestamp"
    ).fetchall()
    conn.close()

    assert len(rows) == 2

    open_trade = dict(rows[0])
    assert open_trade["address"] == "0xTRADER1"
    assert open_trade["token_symbol"] == "BTC"
    assert open_trade["action"] == "Open"
    assert open_trade["side"] == "Long"
    assert open_trade["size"] == 0.1
    assert open_trade["price"] == 45000.0
    assert open_trade["value_usd"] == 4500.0
    assert open_trade["closed_pnl"] == 0
    assert open_trade["fee_usd"] == 2.5
    assert open_trade["timestamp"] == "2025-10-01T12:00:00.000000"

    close_trade = dict(rows[1])
    assert close_trade["action"] == "Close"
    assert close_trade["closed_pnl"] == 500.0
    assert close_trade["fee_usd"] == 3.0
    assert close_trade["price"] == 50000.0


async def test_ingest_trades_deduplicates(db_path):
    """Inserting the same trades twice produces no duplicates."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xDEDUP", "", 100000.0),
    )
    conn.commit()
    conn.close()

    mock_trades = [
        {
            "action": "Open",
            "closed_pnl": 0,
            "fee_usd": 1.0,
            "price": 3000.0,
            "side": "Short",
            "size": 5.0,
            "timestamp": "2025-10-01T10:00:00.000000",
            "token_symbol": "ETH",
            "value_usd": 15000.0,
        },
        {
            "action": "Add",
            "closed_pnl": 0,
            "fee_usd": 0.5,
            "price": 2900.0,
            "side": "Short",
            "size": 2.0,
            "timestamp": "2025-10-02T11:00:00.000000",
            "token_symbol": "ETH",
            "value_usd": 5800.0,
        },
    ]

    client = AsyncMock()
    client.get_perp_trades = AsyncMock(return_value=mock_trades)

    # First ingestion
    count1 = await ingest_trades(
        client, db_path, ["0xDEDUP"], date_from="2025-09-01", date_to="2025-10-10"
    )
    assert count1 == 2

    # Second ingestion with the same trades
    count2 = await ingest_trades(
        client, db_path, ["0xDEDUP"], date_from="2025-09-01", date_to="2025-10-10"
    )
    assert count2 == 0  # No new trades inserted

    # Verify no duplicates in database
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT COUNT(*) FROM trade_history").fetchone()
    conn.close()
    assert row[0] == 2


async def test_ingest_trades_default_dates(db_path):
    """When no dates are provided, defaults to last 90 days."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xDATES", "", 50000.0),
    )
    conn.commit()
    conn.close()

    client = AsyncMock()
    client.get_perp_trades = AsyncMock(return_value=[])

    await ingest_trades(client, db_path, ["0xDATES"])

    # Verify the client was called once with date strings
    client.get_perp_trades.assert_called_once()
    call_kwargs = client.get_perp_trades.call_args
    # The positional args include address, date_from, date_to
    assert call_kwargs.kwargs.get("address") == "0xDATES"
    # date_from and date_to should be valid YYYY-MM-DD strings
    date_from = call_kwargs.kwargs.get("date_from")
    date_to = call_kwargs.kwargs.get("date_to")
    assert len(date_from) == 10  # YYYY-MM-DD
    assert len(date_to) == 10


async def test_ingest_trades_multiple_addresses(db_path):
    """Trades are fetched and stored for multiple addresses."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xADDR1", "", 100000.0),
    )
    conn.execute(
        "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
        ("0xADDR2", "", 80000.0),
    )
    conn.commit()
    conn.close()

    trades_addr1 = [
        {
            "action": "Open",
            "closed_pnl": 0,
            "fee_usd": 1.0,
            "price": 45000.0,
            "side": "Long",
            "size": 0.1,
            "timestamp": "2025-10-01T12:00:00.000000",
            "token_symbol": "BTC",
            "value_usd": 4500.0,
        },
    ]

    trades_addr2 = [
        {
            "action": "Open",
            "closed_pnl": 0,
            "fee_usd": 0.5,
            "price": 150.0,
            "side": "Short",
            "size": 100.0,
            "timestamp": "2025-10-01T08:00:00.000000",
            "token_symbol": "SOL",
            "value_usd": 15000.0,
        },
        {
            "action": "Close",
            "closed_pnl": 1000.0,
            "fee_usd": 0.5,
            "price": 140.0,
            "side": "Short",
            "size": 100.0,
            "timestamp": "2025-10-03T16:00:00.000000",
            "token_symbol": "SOL",
            "value_usd": 14000.0,
        },
    ]

    async def mock_get_trades(address, date_from, date_to):
        if address == "0xADDR1":
            return trades_addr1
        return trades_addr2

    client = AsyncMock()
    client.get_perp_trades = mock_get_trades

    count = await ingest_trades(
        client,
        db_path,
        ["0xADDR1", "0xADDR2"],
        date_from="2025-09-01",
        date_to="2025-10-10",
    )

    assert count == 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    addr1_rows = conn.execute(
        "SELECT * FROM trade_history WHERE address='0xADDR1'"
    ).fetchall()
    addr2_rows = conn.execute(
        "SELECT * FROM trade_history WHERE address='0xADDR2'"
    ).fetchall()
    conn.close()

    assert len(addr1_rows) == 1
    assert len(addr2_rows) == 2
