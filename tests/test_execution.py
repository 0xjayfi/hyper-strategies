"""Tests for the execution engine (Phase 4).

Covers:
1. Order type selection (MARKET vs LIMIT)
2. Slippage calculation and limit price computation
3. Stop-loss and trailing-stop price calculators
4. PaperTradeClient simulated fills
5. Fill polling loop
6. Full execute_rebalance integration with paper-trade mode
"""

from __future__ import annotations

import asyncio

import pytest

from snap.config import (
    MAX_POSITION_DURATION_HOURS,
    SLIPPAGE_BPS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.database import get_connection, init_db
from snap.execution import (
    HyperliquidClient,
    PaperTradeClient,
    compute_initial_trailing_stop,
    compute_limit_price,
    compute_stop_loss_price,
    execute_rebalance,
    get_slippage_bps,
    poll_for_fill,
    select_order_type,
)
from snap.portfolio import RebalanceAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action(
    token: str = "BTC",
    side: str = "Long",
    action: str = "OPEN",
    delta_usd: float = 10_000.0,
    current_usd: float = 0.0,
    target_usd: float = 10_000.0,
    mark_price: float = 50_000.0,
) -> RebalanceAction:
    """Build a RebalanceAction for testing."""
    return RebalanceAction(
        token_symbol=token,
        side=side,
        action=action,
        delta_usd=delta_usd,
        current_usd=current_usd,
        target_usd=target_usd,
        mark_price=mark_price,
    )


# ===========================================================================
# 1. TestOrderTypeSelection
# ===========================================================================


class TestOrderTypeSelection:
    """Tests for select_order_type()."""

    def test_close_is_market(self):
        """CLOSE action always produces a MARKET order."""
        a = _action(action="CLOSE", delta_usd=-10_000, current_usd=10_000, target_usd=0)
        assert select_order_type(a) == "MARKET"

    def test_decrease_is_market(self):
        """DECREASE action always produces a MARKET order."""
        a = _action(action="DECREASE", delta_usd=-3_000, current_usd=10_000, target_usd=7_000)
        assert select_order_type(a) == "MARKET"

    def test_open_is_market(self):
        """OPEN action (current_usd == 0) always produces a MARKET order."""
        a = _action(action="OPEN", delta_usd=5_000, current_usd=0, target_usd=5_000)
        assert select_order_type(a) == "MARKET"

    def test_small_increase_is_limit(self):
        """INCREASE with delta <= 20% of current -> LIMIT."""
        # 1_000 / 10_000 = 10% < 20%
        a = _action(action="INCREASE", delta_usd=1_000, current_usd=10_000, target_usd=11_000)
        assert select_order_type(a) == "LIMIT"

    def test_large_increase_is_market(self):
        """INCREASE with delta > 20% of current -> MARKET."""
        # 5_000 / 10_000 = 50% > 20%
        a = _action(action="INCREASE", delta_usd=5_000, current_usd=10_000, target_usd=15_000)
        assert select_order_type(a) == "MARKET"

    def test_increase_exactly_20pct_is_limit(self):
        """INCREASE with delta exactly 20% of current -> LIMIT (not strictly greater)."""
        # 2_000 / 10_000 = 20%, which is NOT > 20%, so LIMIT
        a = _action(action="INCREASE", delta_usd=2_000, current_usd=10_000, target_usd=12_000)
        assert select_order_type(a) == "LIMIT"


# ===========================================================================
# 2. TestSlippageCalculation
# ===========================================================================


class TestSlippageCalculation:
    """Tests for get_slippage_bps() and compute_limit_price()."""

    def test_btc_slippage(self):
        """BTC has 3 bps slippage."""
        assert get_slippage_bps("BTC") == 3

    def test_eth_slippage(self):
        """ETH has 5 bps slippage."""
        assert get_slippage_bps("ETH") == 5

    def test_sol_slippage(self):
        """SOL has 10 bps slippage."""
        assert get_slippage_bps("SOL") == 10

    def test_unknown_token_default(self):
        """Unknown token falls back to DEFAULT = 15 bps."""
        assert get_slippage_bps("XYZ") == 15

    def test_limit_price_long(self):
        """Long buy: limit price = mark * (1 + bps/10000).

        BTC at 50_000 with 3 bps: 50_000 * 1.0003 = 50_015.
        """
        price = compute_limit_price(50_000.0, "Long", "BTC")
        assert price == pytest.approx(50_015.0)

    def test_limit_price_short(self):
        """Short sell: limit price = mark * (1 - bps/10000).

        BTC at 50_000 with 3 bps: 50_000 * 0.9997 = 49_985.
        """
        price = compute_limit_price(50_000.0, "Short", "BTC")
        assert price == pytest.approx(49_985.0)


# ===========================================================================
# 3. TestStopPrices
# ===========================================================================


class TestStopPrices:
    """Tests for compute_stop_loss_price() and compute_initial_trailing_stop()."""

    def test_stop_loss_long(self):
        """Long stop loss: entry * (1 - 5/100) = 50_000 * 0.95 = 47_500."""
        assert compute_stop_loss_price(50_000.0, "Long") == pytest.approx(47_500.0)

    def test_stop_loss_short(self):
        """Short stop loss: entry * (1 + 5/100) = 50_000 * 1.05 = 52_500."""
        assert compute_stop_loss_price(50_000.0, "Short") == pytest.approx(52_500.0)

    def test_trailing_stop_long(self):
        """Long trailing: entry * (1 - 8/100) = 50_000 * 0.92 = 46_000."""
        assert compute_initial_trailing_stop(50_000.0, "Long") == pytest.approx(46_000.0)

    def test_trailing_stop_short(self):
        """Short trailing: entry * (1 + 8/100) = 50_000 * 1.08 = 54_000."""
        assert compute_initial_trailing_stop(50_000.0, "Short") == pytest.approx(54_000.0)


# ===========================================================================
# 4. TestPaperTradeClient
# ===========================================================================


class TestPaperTradeClient:
    """Tests for the PaperTradeClient simulated exchange."""

    async def test_place_order_returns_fill(self):
        """Placing an order returns an immediate FILLED status."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})
        result = await client.place_order(
            token="BTC", side="Long", size=0.1, order_type="MARKET"
        )
        assert result["status"] == "FILLED"
        assert "order_id" in result
        assert result["filled_size"] == 0.1

    async def test_slippage_applied_correctly_long(self):
        """Long buy fill price includes upward slippage."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})
        result = await client.place_order(
            token="BTC", side="Long", size=0.1, order_type="MARKET"
        )
        # BTC slippage = 3 bps; fill = 50_000 * 1.0003 = 50_015
        assert result["avg_price"] == pytest.approx(50_015.0)

    async def test_slippage_applied_correctly_short(self):
        """Short sell fill price includes downward slippage."""
        client = PaperTradeClient(mark_prices={"ETH": 3_000.0})
        result = await client.place_order(
            token="ETH", side="Short", size=1.0, order_type="MARKET"
        )
        # ETH slippage = 5 bps; fill = 3_000 * 0.9995 = 2_998.5
        assert result["avg_price"] == pytest.approx(2_998.5)

    async def test_cancel_order(self):
        """cancel_order always returns True in paper mode."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})
        assert await client.cancel_order("fake-id") is True

    async def test_get_mark_price(self):
        """get_mark_price returns the configured price."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0, "ETH": 3_000.0})
        assert await client.get_mark_price("BTC") == 50_000.0
        assert await client.get_mark_price("ETH") == 3_000.0
        assert await client.get_mark_price("UNKNOWN") == 0.0

    async def test_get_order_status_known(self):
        """get_order_status returns stored fill info for a placed order."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})
        result = await client.place_order(
            token="BTC", side="Long", size=0.2, order_type="MARKET"
        )
        status = await client.get_order_status(result["order_id"])
        assert status["status"] == "FILLED"
        assert status["filled_size"] == 0.2

    async def test_get_order_status_unknown(self):
        """get_order_status returns CANCELLED for unknown order IDs."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})
        status = await client.get_order_status("nonexistent")
        assert status["status"] == "CANCELLED"

    async def test_close_slippage_direction_long(self):
        """Closing a long: fill price slips *down* (selling)."""
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})
        result = await client.place_order(
            token="BTC", side="Long", size=0.1, order_type="MARKET",
            is_close=True,
        )
        # Closing long: price slips down → 50_000 * (1 - 3/10_000) = 49_985
        assert result["avg_price"] == pytest.approx(49_985.0)


# ===========================================================================
# 5. TestFillPolling
# ===========================================================================


class _FillAfterNClient(HyperliquidClient):
    """Test client that returns FILLED only after N polls."""

    def __init__(self, fills_after: int = 0):
        self._calls = 0
        self._fills_after = fills_after
        self._cancelled = False

    async def place_order(self, token, side, size, order_type, price=None,
                          leverage=5, margin_type="isolated") -> dict:
        return {"order_id": "test-123", "status": "PENDING"}

    async def cancel_order(self, order_id) -> bool:
        self._cancelled = True
        return True

    async def get_order_status(self, order_id) -> dict:
        self._calls += 1
        if self._calls >= self._fills_after:
            return {
                "status": "FILLED",
                "filled_size": 1.0,
                "avg_price": 50_000.0,
                "fee": 2.5,
            }
        return {
            "status": "PENDING",
            "filled_size": 0.0,
            "avg_price": 0.0,
            "fee": 0.0,
        }

    async def get_mark_price(self, token) -> float:
        return 50_000.0


class _NeverFillClient(HyperliquidClient):
    """Test client that never fills (always PENDING)."""

    def __init__(self):
        self._cancelled = False

    async def place_order(self, token, side, size, order_type, price=None,
                          leverage=5, margin_type="isolated") -> dict:
        return {"order_id": "never-fill", "status": "PENDING"}

    async def cancel_order(self, order_id) -> bool:
        self._cancelled = True
        return True

    async def get_order_status(self, order_id) -> dict:
        return {
            "status": "PENDING",
            "filled_size": 0.0,
            "avg_price": 0.0,
            "fee": 0.0,
        }

    async def get_mark_price(self, token) -> float:
        return 50_000.0


class TestFillPolling:
    """Tests for poll_for_fill()."""

    async def test_poll_immediate_fill(self):
        """Client fills on the first poll -> returns FILLED immediately."""
        client = _FillAfterNClient(fills_after=1)
        result = await poll_for_fill(client, "test-123", timeout_s=10, interval_s=0.01)
        assert result["status"] == "FILLED"
        assert result["filled_size"] == 1.0
        assert result["avg_price"] == 50_000.0

    async def test_poll_timeout_cancellation(self):
        """Client never fills -> timeout, cancel, return CANCELLED."""
        client = _NeverFillClient()
        result = await poll_for_fill(client, "never-fill", timeout_s=0.05, interval_s=0.01)
        assert result["status"] == "CANCELLED"
        assert client._cancelled is True


# ===========================================================================
# 6. TestExecuteRebalance (integration with paper-trade mode)
# ===========================================================================


class TestExecuteRebalance:
    """Integration tests using PaperTradeClient + real SQLite DB."""

    def _setup_db(self, tmp_path) -> str:
        """Create and initialize a fresh database, return its path."""
        db_path = str(tmp_path / "test_exec.db")
        conn = init_db(db_path)
        conn.close()
        return db_path

    async def test_full_rebalance_open_positions(self, tmp_path):
        """OPEN 2 positions from scratch.

        Verify orders table and our_positions table are populated correctly.
        """
        db_path = self._setup_db(tmp_path)
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0, "ETH": 3_000.0})

        actions = [
            _action(token="BTC", side="Long", action="OPEN",
                    delta_usd=10_000, current_usd=0, target_usd=10_000,
                    mark_price=50_000.0),
            _action(token="ETH", side="Short", action="OPEN",
                    delta_usd=6_000, current_usd=0, target_usd=6_000,
                    mark_price=3_000.0),
        ]

        summary = await execute_rebalance(
            client=client,
            rebalance_id="rebal-001",
            actions=actions,
            db_path=db_path,
        )

        assert summary["orders_sent"] == 2
        assert summary["orders_filled"] == 2
        assert summary["orders_failed"] == 0

        # Verify orders table
        conn = get_connection(db_path)
        try:
            orders = conn.execute(
                "SELECT * FROM orders WHERE rebalance_id = 'rebal-001'"
            ).fetchall()
            assert len(orders) == 2
            for order in orders:
                assert order["status"] == "FILLED"
                assert order["filled_size"] > 0
                assert order["filled_avg_price"] > 0

            # Verify our_positions table
            positions = conn.execute("SELECT * FROM our_positions").fetchall()
            assert len(positions) == 2
            pos_by_token = {p["token_symbol"]: dict(p) for p in positions}

            assert "BTC" in pos_by_token
            assert pos_by_token["BTC"]["side"] == "Long"
            assert pos_by_token["BTC"]["size"] > 0
            assert pos_by_token["BTC"]["stop_loss_price"] is not None
            assert pos_by_token["BTC"]["trailing_stop_price"] is not None
            assert pos_by_token["BTC"]["max_close_at"] is not None

            assert "ETH" in pos_by_token
            assert pos_by_token["ETH"]["side"] == "Short"
        finally:
            conn.close()

    async def test_full_rebalance_close_positions(self, tmp_path):
        """Close an existing position, verify pnl_ledger and positions cleared."""
        db_path = self._setup_db(tmp_path)
        client = PaperTradeClient(mark_prices={"BTC": 52_000.0})

        # Pre-seed a position in our_positions
        conn = get_connection(db_path)
        with conn:
            conn.execute(
                """INSERT INTO our_positions
                   (token_symbol, side, size, entry_price, current_price,
                    position_usd, unrealized_pnl, stop_loss_price,
                    trailing_stop_price, trailing_high,
                    opened_at, max_close_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "BTC", "Long", 0.2, 50_000.0, 52_000.0,
                    10_000.0, 400.0,
                    47_500.0, 46_000.0, 52_000.0,
                    "2026-02-07T00:00:00Z", "2026-02-10T00:00:00Z",
                    "2026-02-07T00:00:00Z",
                ),
            )
        conn.close()

        actions = [
            _action(token="BTC", side="Long", action="CLOSE",
                    delta_usd=-10_000, current_usd=10_000, target_usd=0,
                    mark_price=52_000.0),
        ]

        summary = await execute_rebalance(
            client=client,
            rebalance_id="rebal-002",
            actions=actions,
            db_path=db_path,
        )

        assert summary["orders_sent"] == 1
        assert summary["orders_filled"] == 1
        assert summary["orders_failed"] == 0

        conn = get_connection(db_path)
        try:
            # Position should be removed
            positions = conn.execute("SELECT * FROM our_positions").fetchall()
            assert len(positions) == 0

            # PnL ledger should have an entry
            pnl = conn.execute("SELECT * FROM pnl_ledger").fetchall()
            assert len(pnl) == 1
            assert pnl[0]["token_symbol"] == "BTC"
            assert pnl[0]["side"] == "Long"
            assert pnl[0]["entry_price"] == pytest.approx(50_000.0)
            assert pnl[0]["exit_reason"] == "REBALANCE"
        finally:
            conn.close()

    async def test_full_rebalance_mixed(self, tmp_path):
        """CLOSE + OPEN in the same rebalance cycle.

        Pre-seed a BTC Long position, close it, and open an ETH Short.
        Verify order priority (CLOSE before OPEN) and both DB effects.
        """
        db_path = self._setup_db(tmp_path)
        client = PaperTradeClient(mark_prices={"BTC": 51_000.0, "ETH": 3_100.0})

        # Pre-seed BTC Long position
        conn = get_connection(db_path)
        with conn:
            conn.execute(
                """INSERT INTO our_positions
                   (token_symbol, side, size, entry_price, current_price,
                    position_usd, unrealized_pnl, stop_loss_price,
                    trailing_stop_price, trailing_high,
                    opened_at, max_close_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "BTC", "Long", 0.2, 50_000.0, 51_000.0,
                    10_000.0, 200.0,
                    47_500.0, 46_000.0, 51_000.0,
                    "2026-02-07T00:00:00Z", "2026-02-10T00:00:00Z",
                    "2026-02-07T00:00:00Z",
                ),
            )
        conn.close()

        # Actions in priority order: CLOSE first, then OPEN
        actions = [
            _action(token="BTC", side="Long", action="CLOSE",
                    delta_usd=-10_000, current_usd=10_000, target_usd=0,
                    mark_price=51_000.0),
            _action(token="ETH", side="Short", action="OPEN",
                    delta_usd=6_000, current_usd=0, target_usd=6_000,
                    mark_price=3_100.0),
        ]

        summary = await execute_rebalance(
            client=client,
            rebalance_id="rebal-003",
            actions=actions,
            db_path=db_path,
        )

        assert summary["orders_sent"] == 2
        assert summary["orders_filled"] == 2
        assert summary["orders_failed"] == 0

        conn = get_connection(db_path)
        try:
            # Only ETH position should remain (BTC was closed)
            positions = conn.execute("SELECT * FROM our_positions").fetchall()
            assert len(positions) == 1
            assert positions[0]["token_symbol"] == "ETH"
            assert positions[0]["side"] == "Short"

            # PnL ledger should record the BTC close
            pnl = conn.execute("SELECT * FROM pnl_ledger").fetchall()
            assert len(pnl) == 1
            assert pnl[0]["token_symbol"] == "BTC"

            # Both orders should be in the orders table
            orders = conn.execute(
                "SELECT * FROM orders WHERE rebalance_id = 'rebal-003'"
            ).fetchall()
            assert len(orders) == 2
            statuses = {o["token_symbol"]: o["status"] for o in orders}
            assert statuses["BTC"] == "FILLED"
            assert statuses["ETH"] == "FILLED"
        finally:
            conn.close()

    async def test_decrease_position(self, tmp_path):
        """DECREASE an existing position and verify size is reduced."""
        db_path = self._setup_db(tmp_path)
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})

        # Pre-seed a BTC Long position with 0.4 BTC
        conn = get_connection(db_path)
        with conn:
            conn.execute(
                """INSERT INTO our_positions
                   (token_symbol, side, size, entry_price, current_price,
                    position_usd, unrealized_pnl, stop_loss_price,
                    trailing_stop_price, trailing_high,
                    opened_at, max_close_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "BTC", "Long", 0.4, 50_000.0, 50_000.0,
                    20_000.0, 0.0,
                    47_500.0, 46_000.0, 50_000.0,
                    "2026-02-07T00:00:00Z", "2026-02-10T00:00:00Z",
                    "2026-02-07T00:00:00Z",
                ),
            )
        conn.close()

        # DECREASE by 5_000 USD (= 0.1 BTC at mark 50_000)
        actions = [
            _action(token="BTC", side="Long", action="DECREASE",
                    delta_usd=-5_000, current_usd=20_000, target_usd=15_000,
                    mark_price=50_000.0),
        ]

        summary = await execute_rebalance(
            client=client,
            rebalance_id="rebal-004",
            actions=actions,
            db_path=db_path,
        )

        assert summary["orders_filled"] == 1

        conn = get_connection(db_path)
        try:
            pos = conn.execute(
                "SELECT * FROM our_positions WHERE token_symbol = 'BTC'"
            ).fetchone()
            assert pos is not None
            # Original 0.4 - 0.1 = 0.3 BTC remaining
            assert pos["size"] == pytest.approx(0.3, abs=0.01)
        finally:
            conn.close()

    async def test_increase_position(self, tmp_path):
        """INCREASE an existing position and verify size grows."""
        db_path = self._setup_db(tmp_path)
        client = PaperTradeClient(mark_prices={"BTC": 50_000.0})

        # Pre-seed a BTC Long position with 0.2 BTC
        conn = get_connection(db_path)
        with conn:
            conn.execute(
                """INSERT INTO our_positions
                   (token_symbol, side, size, entry_price, current_price,
                    position_usd, unrealized_pnl, stop_loss_price,
                    trailing_stop_price, trailing_high,
                    opened_at, max_close_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "BTC", "Long", 0.2, 50_000.0, 50_000.0,
                    10_000.0, 0.0,
                    47_500.0, 46_000.0, 50_000.0,
                    "2026-02-07T00:00:00Z", "2026-02-10T00:00:00Z",
                    "2026-02-07T00:00:00Z",
                ),
            )
        conn.close()

        # INCREASE by 5_000 USD (= 0.1 BTC at mark 50_000)
        # delta > 20% of current (5k/10k=50%) so MARKET order
        actions = [
            _action(token="BTC", side="Long", action="INCREASE",
                    delta_usd=5_000, current_usd=10_000, target_usd=15_000,
                    mark_price=50_000.0),
        ]

        summary = await execute_rebalance(
            client=client,
            rebalance_id="rebal-005",
            actions=actions,
            db_path=db_path,
        )

        assert summary["orders_filled"] == 1

        conn = get_connection(db_path)
        try:
            pos = conn.execute(
                "SELECT * FROM our_positions WHERE token_symbol = 'BTC'"
            ).fetchone()
            assert pos is not None
            # Size should have grown (original 0.2 + ~0.1 fill)
            assert pos["size"] > 0.2
        finally:
            conn.close()

    async def test_stop_prices_set_on_open(self, tmp_path):
        """Verify stop-loss and trailing-stop prices are written on OPEN."""
        db_path = self._setup_db(tmp_path)
        client = PaperTradeClient(mark_prices={"SOL": 100.0})

        actions = [
            _action(token="SOL", side="Long", action="OPEN",
                    delta_usd=1_000, current_usd=0, target_usd=1_000,
                    mark_price=100.0),
        ]

        await execute_rebalance(
            client=client,
            rebalance_id="rebal-006",
            actions=actions,
            db_path=db_path,
        )

        conn = get_connection(db_path)
        try:
            pos = conn.execute(
                "SELECT * FROM our_positions WHERE token_symbol = 'SOL'"
            ).fetchone()
            assert pos is not None
            entry = pos["entry_price"]
            # Stop loss should be ~5% below entry
            expected_sl = entry * (1 - STOP_LOSS_PERCENT / 100)
            assert pos["stop_loss_price"] == pytest.approx(expected_sl, rel=0.01)
            # Trailing stop should be ~8% below entry
            expected_ts = entry * (1 - TRAILING_STOP_PERCENT / 100)
            assert pos["trailing_stop_price"] == pytest.approx(expected_ts, rel=0.01)
        finally:
            conn.close()
