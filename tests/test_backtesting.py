"""Unit tests for the backtesting engine.

Covers four groups:

1. TestExecutionSimulator  (6 tests)
2. TestPerformanceMetrics  (9 tests)
3. TestStopChecks          (6 tests)
4. TestGenerateReport      (2 tests)

Total: 23 tests
"""

from __future__ import annotations

import math
import os

import pytest

from snap.backtesting import (
    BacktestMetrics,
    ExecutionSimulator,
    SimPosition,
    SimulatedFill,
    check_stop_loss,
    check_trailing_stop,
    check_time_stop,
    compute_backtest_metrics,
    generate_backtest_report,
    make_sim_position,
)
from snap.config import (
    MAX_POSITION_DURATION_HOURS,
    SLIPPAGE_BPS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.portfolio import RebalanceAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    token: str = "BTC",
    side: str = "Long",
    action: str = "OPEN",
    delta_usd: float = 10_000.0,
    mark_price: float = 50_000.0,
) -> RebalanceAction:
    """Create a ``RebalanceAction`` for testing."""
    return RebalanceAction(
        token_symbol=token,
        side=side,
        action=action,
        delta_usd=delta_usd,
        current_usd=0.0,
        target_usd=abs(delta_usd),
        mark_price=mark_price,
    )


# ===========================================================================
# 1. TestExecutionSimulator
# ===========================================================================


class TestExecutionSimulator:
    """Tests for ``ExecutionSimulator.simulate_fill``."""

    def test_market_order_always_fills(self) -> None:
        """CLOSE (MARKET) actions always fill, even with miss_rate=1.0."""
        sim = ExecutionSimulator(miss_rate=1.0, rng_seed=42)
        action = _make_action(action="CLOSE", delta_usd=-10_000)
        fill = sim.simulate_fill(action)

        assert fill.is_filled is True
        assert fill.size > 0

    def test_limit_order_can_miss(self) -> None:
        """OPEN (LIMIT) action misses when the RNG draw < miss_rate.

        We set miss_rate=1.0 so every non-CLOSE order misses.
        """
        sim = ExecutionSimulator(miss_rate=1.0, rng_seed=99)
        action = _make_action(action="OPEN")
        fill = sim.simulate_fill(action)

        assert fill.is_filled is False
        assert fill.size == 0.0
        assert fill.fee_usd == 0.0

    def test_slippage_applied(self) -> None:
        """Fill price should differ from mark price by ~base_bps +/- noise."""
        sim = ExecutionSimulator(
            slippage_bps={"BTC": 10, "DEFAULT": 15},
            miss_rate=0.0,
            partial_rate=0.0,
            rng_seed=123,
        )
        action = _make_action(token="BTC", side="Long", action="OPEN", mark_price=50_000)
        fill = sim.simulate_fill(action)

        assert fill.is_filled is True
        # For Long open: fill_price = mark * (1 + actual_bps/10000)
        # actual_bps = 10 + uniform(-5,5) -- always positive sum
        assert fill.fill_price > action.mark_price  # Long buy: slipped up

    def test_partial_fill(self) -> None:
        """Partial fill produces a size < full intended size."""
        sim = ExecutionSimulator(
            miss_rate=0.0,
            partial_rate=1.0,  # force partial
            rng_seed=7,
        )
        action = _make_action(
            action="OPEN", delta_usd=10_000, mark_price=50_000
        )
        fill = sim.simulate_fill(action)

        intended_size = 10_000 / 50_000  # 0.2
        assert fill.is_filled is True
        assert fill.size < intended_size
        assert fill.size >= intended_size * 0.5  # at least 50 %

    def test_deterministic_with_seed(self) -> None:
        """Two simulators with the same seed produce identical fills."""
        action = _make_action(action="OPEN")

        sim_a = ExecutionSimulator(rng_seed=42)
        fill_a = sim_a.simulate_fill(action)

        sim_b = ExecutionSimulator(rng_seed=42)
        fill_b = sim_b.simulate_fill(action)

        assert fill_a.fill_price == fill_b.fill_price
        assert fill_a.size == fill_b.size
        assert fill_a.fee_usd == fill_b.fee_usd
        assert fill_a.is_filled == fill_b.is_filled

    def test_fee_calculated(self) -> None:
        """Fee should be ~0.05 % of the filled notional value."""
        sim = ExecutionSimulator(
            miss_rate=0.0,
            partial_rate=0.0,
            rng_seed=1,
        )
        action = _make_action(action="OPEN", delta_usd=10_000, mark_price=50_000)
        fill = sim.simulate_fill(action)

        assert fill.is_filled is True
        expected_value = fill.size * fill.fill_price
        expected_fee = expected_value * 0.0005
        assert fill.fee_usd == pytest.approx(expected_fee, rel=1e-9)


# ===========================================================================
# 2. TestPerformanceMetrics
# ===========================================================================


class TestPerformanceMetrics:
    """Tests for ``compute_backtest_metrics``."""

    def test_total_return(self) -> None:
        """Equity [100, 110] => 10 % return."""
        m = compute_backtest_metrics([100, 110], [], 1)
        assert m.total_return_pct == pytest.approx(10.0)

    def test_annualized_return(self) -> None:
        """Known equity over 90 days."""
        # 20 % over 90 days
        m = compute_backtest_metrics([100, 120], [], 90)
        expected = ((1.20) ** (365 / 90) - 1) * 100
        assert m.annualized_return_pct == pytest.approx(expected, rel=1e-6)

    def test_max_drawdown(self) -> None:
        """Equity [100, 90, 95, 80, 100] => 20 % max drawdown."""
        m = compute_backtest_metrics([100, 90, 95, 80, 100], [], 4)
        assert m.max_drawdown_pct == pytest.approx(20.0)

    def test_max_drawdown_duration(self) -> None:
        """Drawdown duration: longest consecutive period below peak."""
        # Peak at index 0 (100), dips at 1-3, recovers at 4
        # Duration = 4 - 0 = 4 indices below peak (indices 1,2,3 are below,
        # index 4 recovers) => 3 is the furthest below-peak index from peak at 0
        equity = [100, 90, 85, 95, 100]
        m = compute_backtest_metrics(equity, [], 4)
        # dd_start_idx stays 0 until equity >= peak at index 4
        # current_dd_days at index 3 = 3, which is max
        assert m.max_drawdown_duration_days == pytest.approx(3.0)

    def test_sharpe_ratio(self) -> None:
        """Sharpe with known constant daily returns."""
        # Constant 1 % daily => std = 0 in a degenerate case;
        # use varied returns instead.
        equity = [100, 101, 100.5, 102, 103]  # 4 daily returns
        m = compute_backtest_metrics(equity, [], 4)
        # Just check it is positive and finite
        assert m.sharpe_ratio > 0
        assert math.isfinite(m.sharpe_ratio)

    def test_sortino_ratio_all_positive(self) -> None:
        """All positive daily returns => downside_std has < 2 negative values => sortino = 0."""
        equity = [100, 101, 102, 103, 104]
        m = compute_backtest_metrics(equity, [], 4)
        assert m.sortino_ratio == 0.0

    def test_win_rate(self) -> None:
        """3 wins, 2 losses => 60 % win rate."""
        positions = [
            {"pnl": 100, "hold_hours": 10, "exit_reason": "rebalance", "fees": 1, "slippage_cost": 0.5},
            {"pnl": 200, "hold_hours": 20, "exit_reason": "rebalance", "fees": 2, "slippage_cost": 0.3},
            {"pnl": 50, "hold_hours": 5, "exit_reason": "stop_loss", "fees": 0.5, "slippage_cost": 0.1},
            {"pnl": -80, "hold_hours": 12, "exit_reason": "trailing_stop", "fees": 1.5, "slippage_cost": 0.4},
            {"pnl": -30, "hold_hours": 8, "exit_reason": "time_stop", "fees": 0.8, "slippage_cost": 0.2},
        ]
        m = compute_backtest_metrics([100, 110], positions, 1)
        assert m.win_rate == pytest.approx(0.6)
        assert m.total_positions == 5

    def test_empty_equity_curve(self) -> None:
        """Empty equity curve returns zero metrics."""
        m = compute_backtest_metrics([], [], 0)
        assert m.total_return_pct == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.max_drawdown_pct == 0.0

    def test_exit_reason_counts(self) -> None:
        """Verify stop/trailing/time/rebalance exit counts."""
        positions = [
            {"pnl": -10, "hold_hours": 1, "exit_reason": "stop_loss", "fees": 0, "slippage_cost": 0},
            {"pnl": -20, "hold_hours": 2, "exit_reason": "stop_loss", "fees": 0, "slippage_cost": 0},
            {"pnl": -5, "hold_hours": 3, "exit_reason": "trailing_stop", "fees": 0, "slippage_cost": 0},
            {"pnl": -15, "hold_hours": 72, "exit_reason": "time_stop", "fees": 0, "slippage_cost": 0},
            {"pnl": 50, "hold_hours": 10, "exit_reason": "rebalance", "fees": 0, "slippage_cost": 0},
            {"pnl": 30, "hold_hours": 8, "exit_reason": "rebalance", "fees": 0, "slippage_cost": 0},
        ]
        m = compute_backtest_metrics([100, 100], positions, 1)
        assert m.stop_loss_exits == 2
        assert m.trailing_stop_exits == 1
        assert m.time_stop_exits == 1
        assert m.rebalance_exits == 2


# ===========================================================================
# 3. TestStopChecks
# ===========================================================================


class TestStopChecks:
    """Tests for ``check_stop_loss``, ``check_trailing_stop``, ``check_time_stop``."""

    def test_stop_loss_long_triggered(self) -> None:
        """Long position: price drops below stop => triggered."""
        pos = make_sim_position("BTC", "Long", 0.1, 50_000.0, opened_at=0)
        # stop_loss_price = 50000 * 0.95 = 47500
        assert check_stop_loss(pos, 47_000.0) is True

    def test_stop_loss_long_not_triggered(self) -> None:
        """Long position: price above stop => NOT triggered."""
        pos = make_sim_position("BTC", "Long", 0.1, 50_000.0, opened_at=0)
        assert check_stop_loss(pos, 49_000.0) is False

    def test_stop_loss_short_triggered(self) -> None:
        """Short position: price rises above stop => triggered."""
        pos = make_sim_position("BTC", "Short", 0.1, 50_000.0, opened_at=0)
        # stop_loss_price = 50000 * 1.05 = 52500
        assert check_stop_loss(pos, 53_000.0) is True

    def test_trailing_stop_ratchets_up(self) -> None:
        """Long trailing high ratchets upward when price rises."""
        pos = make_sim_position("BTC", "Long", 0.1, 50_000.0, opened_at=0)
        assert pos.trailing_high == 50_000.0

        triggered, pos = check_trailing_stop(pos, 55_000.0)
        assert triggered is False
        assert pos.trailing_high == 55_000.0
        # trailing_stop_price = 55000 * 0.92 = 50600
        assert pos.trailing_stop_price == pytest.approx(55_000 * (1 - TRAILING_STOP_PERCENT / 100))

    def test_trailing_stop_triggers_after_ratchet(self) -> None:
        """Price rises then drops below trailing stop => triggered."""
        pos = make_sim_position("BTC", "Long", 0.1, 50_000.0, opened_at=0)

        # Price rises to 60k
        triggered, pos = check_trailing_stop(pos, 60_000.0)
        assert triggered is False
        assert pos.trailing_high == 60_000.0
        # trailing_stop_price = 60000 * 0.92 = 55200

        # Price drops to 55000 (below 55200)
        triggered, pos = check_trailing_stop(pos, 55_000.0)
        assert triggered is True

    def test_time_stop(self) -> None:
        """Position should close after MAX_POSITION_DURATION_HOURS."""
        pos = make_sim_position("BTC", "Long", 0.1, 50_000.0, opened_at=10)
        assert pos.max_close_step == 10 + MAX_POSITION_DURATION_HOURS

        assert check_time_stop(pos, 10 + MAX_POSITION_DURATION_HOURS - 1) is False
        assert check_time_stop(pos, 10 + MAX_POSITION_DURATION_HOURS) is True
        assert check_time_stop(pos, 10 + MAX_POSITION_DURATION_HOURS + 1) is True


# ===========================================================================
# 4. TestGenerateReport
# ===========================================================================


class TestGenerateReport:
    """Tests for ``generate_backtest_report``."""

    def test_report_contains_metrics(self) -> None:
        """Report markdown contains key metric values."""
        metrics = BacktestMetrics(
            total_return_pct=15.5,
            annualized_return_pct=62.3,
            max_drawdown_pct=8.2,
            max_drawdown_duration_days=5.0,
            sharpe_ratio=1.85,
            sortino_ratio=2.40,
            win_rate=0.65,
            avg_hold_hours=24.0,
            total_positions=100,
            total_fees_usd=250.0,
            total_slippage_cost_usd=180.0,
            stop_loss_exits=10,
            trailing_stop_exits=5,
            time_stop_exits=3,
            rebalance_exits=82,
        )
        report = generate_backtest_report(metrics)

        assert "# Backtest Report" in report
        assert "15.50%" in report
        assert "62.30%" in report
        assert "8.20%" in report
        assert "1.850" in report
        assert "2.400" in report
        assert "65.00%" in report
        assert "100" in report
        assert "$250.00" in report
        assert "$180.00" in report

    def test_report_writes_file(self, tmp_path) -> None:
        """Report is written to disk when ``output_path`` is given."""
        metrics = BacktestMetrics(total_return_pct=10.0)
        out = str(tmp_path / "report.md")
        result = generate_backtest_report(metrics, output_path=out)

        assert os.path.exists(out)
        with open(out) as fh:
            content = fh.read()
        assert content == result
        assert "10.00%" in content
