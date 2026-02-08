import pytest
from src.backtest import (
    BacktestResult,
    date_range,
    compute_max_drawdown,
    compute_portfolio_sharpe,
    compute_turnover,
    compute_period_pnl,
    filter_trades_by_window,
    filter_trades_by_period,
    backtest_allocations,
)
from tests.conftest import make_trade


# ---------------------------------------------------------------------------
# date_range
# ---------------------------------------------------------------------------

class TestDateRange:
    def test_daily(self):
        dates = date_range("2026-01-01", "2026-01-05", 1)
        assert dates == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]

    def test_step_2(self):
        dates = date_range("2026-01-01", "2026-01-06", 2)
        assert dates == ["2026-01-01", "2026-01-03", "2026-01-05"]

    def test_single_day(self):
        dates = date_range("2026-01-01", "2026-01-01", 1)
        assert dates == ["2026-01-01"]

    def test_start_after_end(self):
        dates = date_range("2026-01-10", "2026-01-01", 1)
        assert dates == []


# ---------------------------------------------------------------------------
# compute_max_drawdown
# ---------------------------------------------------------------------------

class TestComputeMaxDrawdown:
    def test_no_drawdown(self):
        timeline = [{"portfolio_value": v} for v in [100, 110, 120, 130]]
        assert compute_max_drawdown(timeline) == pytest.approx(0.0)

    def test_simple_drawdown(self):
        timeline = [{"portfolio_value": v} for v in [100, 80]]
        assert compute_max_drawdown(timeline) == pytest.approx(0.20)

    def test_recovery_drawdown(self):
        # Peak 200, trough 150 -> 25% drawdown, then recovers
        timeline = [{"portfolio_value": v} for v in [100, 200, 150, 250]]
        assert compute_max_drawdown(timeline) == pytest.approx(0.25)

    def test_empty_timeline(self):
        assert compute_max_drawdown([]) == 0.0

    def test_single_entry(self):
        assert compute_max_drawdown([{"portfolio_value": 100}]) == 0.0


# ---------------------------------------------------------------------------
# compute_portfolio_sharpe
# ---------------------------------------------------------------------------

class TestComputePortfolioSharpe:
    def test_single_entry_zero(self):
        assert compute_portfolio_sharpe([{"portfolio_value": 100}]) == 0.0

    def test_empty_zero(self):
        assert compute_portfolio_sharpe([]) == 0.0

    def test_constant_values_zero(self):
        # No variance -> Sharpe is 0
        timeline = [{"portfolio_value": 100} for _ in range(5)]
        assert compute_portfolio_sharpe(timeline) == 0.0

    def test_positive_returns(self):
        # Steadily increasing portfolio -> positive Sharpe
        timeline = [{"portfolio_value": 100 + i * 10} for i in range(10)]
        sharpe = compute_portfolio_sharpe(timeline)
        assert sharpe > 0


# ---------------------------------------------------------------------------
# compute_turnover
# ---------------------------------------------------------------------------

class TestComputeTurnover:
    def test_identical_allocations(self):
        a = {"A": 0.5, "B": 0.5}
        assert compute_turnover(a, a) == pytest.approx(0.0)

    def test_full_swap(self):
        old = {"A": 1.0}
        new = {"B": 1.0}
        # A goes from 1->0, B goes from 0->1, total = 2.0
        assert compute_turnover(new, old) == pytest.approx(2.0)

    def test_partial_change(self):
        old = {"A": 0.6, "B": 0.4}
        new = {"A": 0.4, "B": 0.6}
        # |0.4-0.6| + |0.6-0.4| = 0.4
        assert compute_turnover(new, old) == pytest.approx(0.4)

    def test_empty_allocations(self):
        assert compute_turnover({}, {}) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_period_pnl
# ---------------------------------------------------------------------------

class TestComputePeriodPnl:
    def test_close_trades_summed(self):
        trades = [
            make_trade(action="Close", closed_pnl=100),
            make_trade(action="Reduce", closed_pnl=-30),
        ]
        assert compute_period_pnl(trades) == pytest.approx(70.0)

    def test_open_trades_ignored(self):
        trades = [
            make_trade(action="Open", closed_pnl=0),
            make_trade(action="Close", closed_pnl=50),
        ]
        assert compute_period_pnl(trades) == pytest.approx(50.0)

    def test_empty_trades(self):
        assert compute_period_pnl([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# filter_trades_by_window
# ---------------------------------------------------------------------------

class TestFilterTradesByWindow:
    def test_filters_within_window(self):
        trades = [
            make_trade(timestamp="2026-01-10T12:00:00"),
            make_trade(timestamp="2026-01-05T12:00:00"),
            make_trade(timestamp="2025-12-01T12:00:00"),  # outside window
        ]
        result = filter_trades_by_window(trades, "2026-01-15", 10)
        assert len(result) == 2

    def test_empty_trades(self):
        assert filter_trades_by_window([], "2026-01-15", 7) == []


# ---------------------------------------------------------------------------
# filter_trades_by_period
# ---------------------------------------------------------------------------

class TestFilterTradesByPeriod:
    def test_filters_within_period(self):
        trades = [
            make_trade(timestamp="2026-01-02T12:00:00"),
            make_trade(timestamp="2026-01-05T12:00:00"),
            make_trade(timestamp="2026-01-10T12:00:00"),  # outside
        ]
        result = filter_trades_by_period(trades, "2026-01-01", "2026-01-06")
        assert len(result) == 2

    def test_empty_trades(self):
        assert filter_trades_by_period([], "2026-01-01", "2026-01-07") == []


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------

class TestBacktestResult:
    def test_dataclass_fields(self):
        result = BacktestResult(
            timeline=[],
            total_return=0.15,
            max_drawdown=0.05,
            avg_turnover=0.10,
            sharpe=1.5,
        )
        assert result.total_return == 0.15
        assert result.max_drawdown == 0.05
        assert result.avg_turnover == 0.10
        assert result.sharpe == 1.5
        assert result.timeline == []


# ---------------------------------------------------------------------------
# backtest_allocations (integration)
# ---------------------------------------------------------------------------

class TestBacktestAllocations:
    def _build_trades(self, address, pnls, base_date="2026-01-"):
        """Build Close trades spread across dates for a trader."""
        trades = []
        for i, pnl in enumerate(pnls, start=1):
            day = f"{base_date}{i:02d}T12:00:00"
            trades.append(make_trade(
                action="Close",
                closed_pnl=pnl,
                value_usd=abs(pnl) * 10 if pnl != 0 else 1000,
                timestamp=day,
            ))
        return trades

    def test_returns_backtest_result(self):
        # Minimal: single trader, short window, no trades pass anti-luck
        # but the function should still return a valid BacktestResult
        trades = {"0xA": self._build_trades("0xA", [10, 20, -5, 15, 30])}
        result = backtest_allocations(
            historical_trades=trades,
            account_values={"0xA": 100000},
            start_date="2026-01-01",
            end_date="2026-01-05",
            rebalance_frequency_days=1,
            starting_capital=100000,
        )
        assert isinstance(result, BacktestResult)
        assert len(result.timeline) > 0

    def test_empty_trades_returns_result(self):
        result = backtest_allocations(
            historical_trades={},
            account_values={},
            start_date="2026-01-01",
            end_date="2026-01-03",
        )
        assert isinstance(result, BacktestResult)
        assert result.total_return == pytest.approx(0.0)

    def test_portfolio_value_starts_at_capital(self):
        result = backtest_allocations(
            historical_trades={},
            account_values={},
            start_date="2026-01-01",
            end_date="2026-01-01",
            starting_capital=50000,
        )
        assert result.timeline[0]["portfolio_value"] == pytest.approx(50000)

    def test_timeline_has_expected_dates(self):
        result = backtest_allocations(
            historical_trades={},
            account_values={},
            start_date="2026-01-01",
            end_date="2026-01-03",
            rebalance_frequency_days=1,
        )
        dates = [entry["date"] for entry in result.timeline]
        assert dates == ["2026-01-01", "2026-01-02", "2026-01-03"]

    def test_rebalance_frequency(self):
        result = backtest_allocations(
            historical_trades={},
            account_values={},
            start_date="2026-01-01",
            end_date="2026-01-10",
            rebalance_frequency_days=3,
        )
        dates = [entry["date"] for entry in result.timeline]
        assert dates == ["2026-01-01", "2026-01-04", "2026-01-07", "2026-01-10"]
