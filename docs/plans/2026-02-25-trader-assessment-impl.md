# Trader Assessment Feature — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 10-strategy trader assessment system with full-stack UI so users can evaluate any Hyperliquid address.

**Architecture:** Hybrid — shared `src/metrics.py` data layer, new `src/assessment/` strategy package independent from `src/scoring.py`. New FastAPI router + React pages at `/assess` and `/assess/:address`.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / SQLite (backend), React 19 / TypeScript / React Query / Recharts / TanStack Table (frontend), pytest (tests)

**Design doc:** `docs/plans/2026-02-25-trader-assessment-design.md`

---

## Task 1: Extend TradeMetrics with 4 New Fields

**Files:**
- Modify: `src/models.py:230-275` (TradeMetrics class)
- Test: `tests/test_metrics.py`

**Step 1: Write the failing test**

Add to `tests/test_metrics.py`:

```python
def test_trade_metrics_has_extended_fields():
    """TradeMetrics must include the 4 new assessment fields."""
    m = make_metrics(
        max_leverage=25.0,
        leverage_std=5.0,
        largest_trade_pnl_ratio=0.35,
        pnl_trend_slope=0.02,
    )
    assert m.max_leverage == 25.0
    assert m.leverage_std == 5.0
    assert m.largest_trade_pnl_ratio == 0.35
    assert m.pnl_trend_slope == 0.02


def test_trade_metrics_empty_has_extended_fields():
    """TradeMetrics.empty() must zero-out the new fields."""
    m = TradeMetrics.empty(30)
    assert m.max_leverage == 0.0
    assert m.leverage_std == 0.0
    assert m.largest_trade_pnl_ratio == 0.0
    assert m.pnl_trend_slope == 0.0
```

**Step 2: Run test to verify it fails**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_metrics.py::test_trade_metrics_has_extended_fields tests/test_metrics.py::test_trade_metrics_empty_has_extended_fields -v`
Expected: FAIL — fields don't exist on TradeMetrics

**Step 3: Implement — add 4 fields to TradeMetrics**

In `src/models.py`, add these fields to the `TradeMetrics` class after `max_drawdown_proxy`:

```python
    # Extended fields for assessment strategies
    max_leverage: float = 0.0
    leverage_std: float = 0.0
    largest_trade_pnl_ratio: float = 0.0
    pnl_trend_slope: float = 0.0
```

Update `TradeMetrics.empty()` — the defaults of `0.0` handle this automatically, so no change needed there.

Update `tests/conftest.py` `make_metrics` defaults to include the new fields:

```python
def make_metrics(window_days=30, **overrides):
    defaults = dict(
        window_days=window_days, total_trades=50, winning_trades=30, losing_trades=20,
        win_rate=0.6, gross_profit=15000.0, gross_loss=5000.0, profit_factor=3.0,
        avg_return=0.05, std_return=0.03, pseudo_sharpe=1.67,
        total_pnl=10000.0, roi_proxy=20.0, max_drawdown_proxy=0.05,
        max_leverage=0.0, leverage_std=0.0, largest_trade_pnl_ratio=0.0, pnl_trend_slope=0.0,
    )
    defaults.update(overrides)
    return TradeMetrics(**defaults)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_metrics.py -v`
Expected: ALL PASS

**Step 5: Run full test suite to check for regressions**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/ -v`
Expected: ALL PASS (existing tests use `make_metrics` which now has defaults for new fields)

**Step 6: Commit**

```bash
git add src/models.py tests/test_metrics.py tests/conftest.py
git commit -m "feat: extend TradeMetrics with assessment fields (max_leverage, leverage_std, largest_trade_pnl_ratio, pnl_trend_slope)"
```

---

## Task 2: Compute Extended Metrics in metrics.py

**Files:**
- Modify: `src/metrics.py:23-90` (compute_trade_metrics function)
- Test: `tests/test_metrics.py`

**Step 1: Write the failing tests**

Add to `tests/test_metrics.py`:

```python
from src.metrics import compute_trade_metrics
from tests.conftest import make_trade


def test_compute_extended_metrics_leverage():
    """compute_trade_metrics populates max_leverage and leverage_std from trade value/size."""
    trades = [
        make_trade(closed_pnl=500, value_usd=5000, size=0.5),   # effective leverage ~ value/size proxy
        make_trade(closed_pnl=200, value_usd=10000, size=0.2),
        make_trade(closed_pnl=-100, value_usd=3000, size=0.3),
    ]
    m = compute_trade_metrics(trades, account_value=50000, window_days=30)
    # max_leverage should be > 0 (derived from value_usd / account_value proxy)
    assert m.max_leverage >= 0.0
    assert m.leverage_std >= 0.0


def test_compute_extended_metrics_largest_trade_ratio():
    """Largest trade PnL ratio should identify the dominant trade."""
    trades = [
        make_trade(closed_pnl=1000, value_usd=5000),   # This is the biggest
        make_trade(closed_pnl=200, value_usd=5000),
        make_trade(closed_pnl=-100, value_usd=5000),
    ]
    m = compute_trade_metrics(trades, account_value=50000, window_days=30)
    # 1000 / (1000+200+100) = ~0.77
    assert m.largest_trade_pnl_ratio > 0.5


def test_compute_extended_metrics_pnl_trend_positive():
    """PnL trend slope should be positive when later trades are more profitable."""
    trades = [
        make_trade(closed_pnl=100, value_usd=5000, timestamp="2026-02-01T00:00:00"),
        make_trade(closed_pnl=200, value_usd=5000, timestamp="2026-02-10T00:00:00"),
        make_trade(closed_pnl=300, value_usd=5000, timestamp="2026-02-20T00:00:00"),
        make_trade(closed_pnl=400, value_usd=5000, timestamp="2026-02-25T00:00:00"),
    ]
    m = compute_trade_metrics(trades, account_value=50000, window_days=30)
    assert m.pnl_trend_slope > 0


def test_compute_extended_metrics_empty_trades():
    """Empty trade list should return zero for all extended fields."""
    m = compute_trade_metrics([], account_value=50000, window_days=30)
    assert m.max_leverage == 0.0
    assert m.leverage_std == 0.0
    assert m.largest_trade_pnl_ratio == 0.0
    assert m.pnl_trend_slope == 0.0
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_metrics.py::test_compute_extended_metrics_leverage tests/test_metrics.py::test_compute_extended_metrics_largest_trade_ratio tests/test_metrics.py::test_compute_extended_metrics_pnl_trend_positive tests/test_metrics.py::test_compute_extended_metrics_empty_trades -v`
Expected: FAIL (new fields default to 0.0 regardless of trades)

**Step 3: Implement — extend compute_trade_metrics**

In `src/metrics.py`, in the `compute_trade_metrics` function, add computation of the 4 fields before the `return TradeMetrics(...)` statement. After the `max_drawdown_proxy` computation and before the return:

```python
    # --- Extended fields for assessment strategies ---

    # Max leverage: use value_usd / account_value as leverage proxy per trade
    leverages = []
    for t in close_trades:
        if account_value > 0:
            leverages.append(t.value_usd / account_value)
    max_leverage = max(leverages) if leverages else 0.0
    leverage_std_val = float(np.std(leverages, ddof=1)) if len(leverages) > 1 else 0.0

    # Largest trade PnL ratio: biggest |closed_pnl| / sum of all |closed_pnl|
    abs_pnls = [abs(t.closed_pnl) for t in close_trades]
    total_abs_pnl = sum(abs_pnls)
    largest_trade_pnl_ratio = max(abs_pnls) / total_abs_pnl if total_abs_pnl > 0 else 0.0

    # PnL trend slope: split trades into two halves by time, compare cumulative PnL
    sorted_trades = sorted(close_trades, key=lambda t: t.timestamp)
    mid = len(sorted_trades) // 2
    if mid > 0:
        first_half_pnl = sum(t.closed_pnl for t in sorted_trades[:mid])
        second_half_pnl = sum(t.closed_pnl for t in sorted_trades[mid:])
        # Normalized slope: (second - first) / total_abs_pnl
        pnl_trend_slope = (second_half_pnl - first_half_pnl) / total_abs_pnl if total_abs_pnl > 0 else 0.0
    else:
        pnl_trend_slope = 0.0
```

Update the `return TradeMetrics(...)` call to include the new fields:

```python
    return TradeMetrics(
        window_days=window_days,
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_return=avg_return,
        std_return=std_return,
        pseudo_sharpe=pseudo_sharpe,
        total_pnl=total_pnl,
        roi_proxy=roi_proxy,
        max_drawdown_proxy=max_drawdown_proxy,
        max_leverage=max_leverage,
        leverage_std=leverage_std_val,
        largest_trade_pnl_ratio=largest_trade_pnl_ratio,
        pnl_trend_slope=pnl_trend_slope,
    )
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_metrics.py -v`
Expected: ALL PASS

**Step 5: Run full suite**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/metrics.py tests/test_metrics.py
git commit -m "feat: compute extended metrics (leverage, position sizing, pnl trend) in metrics engine"
```

---

## Task 3: Extend DataStore for New TradeMetrics Fields

**Files:**
- Modify: `src/datastore.py:82-100` (trade_metrics table schema)
- Modify: `src/datastore.py:273-342` (insert_trade_metrics + get_latest_metrics)
- Test: `tests/test_datastore.py`

**Step 1: Write the failing test**

Add to `tests/test_datastore.py`:

```python
from tests.conftest import make_metrics


def test_insert_and_get_extended_metrics(ds):
    """DataStore should persist and retrieve the 4 extended TradeMetrics fields."""
    ds.upsert_trader("0xEXT")
    m = make_metrics(
        max_leverage=15.0,
        leverage_std=3.5,
        largest_trade_pnl_ratio=0.28,
        pnl_trend_slope=0.04,
    )
    ds.insert_trade_metrics("0xEXT", m)
    result = ds.get_latest_metrics("0xEXT", window_days=30)
    assert result is not None
    assert result.max_leverage == 15.0
    assert result.leverage_std == 3.5
    assert result.largest_trade_pnl_ratio == 0.28
    assert result.pnl_trend_slope == 0.04
```

**Step 2: Run test to verify it fails**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_datastore.py::test_insert_and_get_extended_metrics -v`
Expected: FAIL — columns don't exist in schema

**Step 3: Implement**

In `src/datastore.py`, update the `trade_metrics` CREATE TABLE to add 4 columns after `max_drawdown_proxy`:

```sql
                max_leverage    REAL DEFAULT 0.0,
                leverage_std    REAL DEFAULT 0.0,
                largest_trade_pnl_ratio REAL DEFAULT 0.0,
                pnl_trend_slope REAL DEFAULT 0.0
```

Update `insert_trade_metrics` to include the new fields in the INSERT:

```python
    def insert_trade_metrics(self, address: str, metrics: TradeMetrics) -> None:
        computed_at = datetime.utcnow().isoformat()
        self._conn.execute(
            """
            INSERT INTO trade_metrics
                (address, computed_at, window_days, total_trades, winning_trades,
                 losing_trades, win_rate, gross_profit, gross_loss, profit_factor,
                 avg_return, std_return, pseudo_sharpe, total_pnl, roi_proxy,
                 max_drawdown_proxy, max_leverage, leverage_std,
                 largest_trade_pnl_ratio, pnl_trend_slope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                address, computed_at, metrics.window_days, metrics.total_trades,
                metrics.winning_trades, metrics.losing_trades, metrics.win_rate,
                metrics.gross_profit, metrics.gross_loss, metrics.profit_factor,
                metrics.avg_return, metrics.std_return, metrics.pseudo_sharpe,
                metrics.total_pnl, metrics.roi_proxy, metrics.max_drawdown_proxy,
                metrics.max_leverage, metrics.leverage_std,
                metrics.largest_trade_pnl_ratio, metrics.pnl_trend_slope,
            ),
        )
        self._conn.commit()
```

Update `get_latest_metrics` to include the new fields in the TradeMetrics construction:

```python
        return TradeMetrics(
            window_days=row["window_days"],
            total_trades=row["total_trades"],
            winning_trades=row["winning_trades"],
            losing_trades=row["losing_trades"],
            win_rate=row["win_rate"],
            gross_profit=row["gross_profit"],
            gross_loss=row["gross_loss"],
            profit_factor=row["profit_factor"],
            avg_return=row["avg_return"],
            std_return=row["std_return"],
            pseudo_sharpe=row["pseudo_sharpe"],
            total_pnl=row["total_pnl"],
            roi_proxy=row["roi_proxy"],
            max_drawdown_proxy=row["max_drawdown_proxy"],
            max_leverage=row["max_leverage"] or 0.0,
            leverage_std=row["leverage_std"] or 0.0,
            largest_trade_pnl_ratio=row["largest_trade_pnl_ratio"] or 0.0,
            pnl_trend_slope=row["pnl_trend_slope"] or 0.0,
        )
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_datastore.py -v`
Expected: ALL PASS

**Step 5: Run full suite**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/datastore.py tests/test_datastore.py
git commit -m "feat: extend datastore schema with 4 assessment metric columns"
```

---

## Task 4: BaseStrategy ABC and StrategyResult

**Files:**
- Create: `src/assessment/__init__.py`
- Create: `src/assessment/base.py`
- Test: `tests/test_assessment/__init__.py`
- Test: `tests/test_assessment/test_base.py`

**Step 1: Write the failing test**

Create `tests/test_assessment/__init__.py` (empty).

Create `tests/test_assessment/test_base.py`:

```python
import pytest
from src.assessment.base import BaseStrategy, StrategyResult


def test_strategy_result_creation():
    r = StrategyResult(
        name="Test Strategy",
        category="Core Performance",
        score=75,
        passed=True,
        explanation="Looks good",
    )
    assert r.name == "Test Strategy"
    assert r.score == 75
    assert r.passed is True


def test_strategy_result_score_bounds():
    """Score must be clamped to 0-100."""
    r = StrategyResult(name="T", category="C", score=150, passed=True, explanation="")
    assert r.score == 100
    r2 = StrategyResult(name="T", category="C", score=-10, passed=False, explanation="")
    assert r2.score == 0


def test_base_strategy_cannot_instantiate():
    """BaseStrategy is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseStrategy()
```

**Step 2: Run test to verify it fails**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_base.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/assessment/__init__.py`:

```python
"""Trader assessment engine — 10 independent scoring strategies."""
```

Create `src/assessment/base.py`:

```python
"""Base class and result dataclass for assessment strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.models import TradeMetrics


@dataclass
class StrategyResult:
    """Result from a single assessment strategy."""

    name: str
    category: str
    score: int  # 0-100
    passed: bool
    explanation: str

    def __post_init__(self):
        self.score = max(0, min(100, self.score))


class BaseStrategy(ABC):
    """Abstract base for all assessment strategies."""

    name: str = ""
    description: str = ""
    category: str = ""

    @abstractmethod
    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        """Evaluate a trader and return a StrategyResult."""
        ...
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_base.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/assessment/ tests/test_assessment/
git commit -m "feat: add BaseStrategy ABC and StrategyResult for assessment"
```

---

## Task 5: Core Performance Strategies (ROI, Sharpe, Profit Factor)

**Files:**
- Create: `src/assessment/strategies/__init__.py`
- Create: `src/assessment/strategies/roi.py`
- Create: `src/assessment/strategies/sharpe.py`
- Create: `src/assessment/strategies/profit_factor.py`
- Test: `tests/test_assessment/test_core_performance.py`

**Step 1: Write the failing tests**

Create `tests/test_assessment/test_core_performance.py`:

```python
import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.roi import ROIStrategy
from src.assessment.strategies.sharpe import SharpeStrategy
from src.assessment.strategies.profit_factor import ProfitFactorStrategy


class TestROIStrategy:
    def test_high_roi_passes(self):
        m = make_metrics(roi_proxy=8.0)
        r = ROIStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_negative_roi_fails(self):
        m = make_metrics(roi_proxy=-5.0)
        r = ROIStrategy().evaluate(m, [])
        assert r.passed is False
        assert r.score == 0

    def test_max_score_at_10_plus(self):
        m = make_metrics(roi_proxy=15.0)
        r = ROIStrategy().evaluate(m, [])
        assert r.score == 100

    def test_name_and_category(self):
        s = ROIStrategy()
        assert s.name == "ROI Performance"
        assert s.category == "Core Performance"


class TestSharpeStrategy:
    def test_good_sharpe_passes(self):
        m = make_metrics(pseudo_sharpe=1.5)
        r = SharpeStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score == 50

    def test_low_sharpe_fails(self):
        m = make_metrics(pseudo_sharpe=0.3)
        r = SharpeStrategy().evaluate(m, [])
        assert r.passed is False

    def test_max_sharpe(self):
        m = make_metrics(pseudo_sharpe=3.5)
        r = SharpeStrategy().evaluate(m, [])
        assert r.score == 100


class TestProfitFactorStrategy:
    def test_good_pf_passes(self):
        m = make_metrics(profit_factor=2.0)
        r = ProfitFactorStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 0

    def test_low_pf_fails(self):
        m = make_metrics(profit_factor=0.8)
        r = ProfitFactorStrategy().evaluate(m, [])
        assert r.passed is False

    def test_pf_at_threshold(self):
        m = make_metrics(profit_factor=1.1)
        r = ProfitFactorStrategy().evaluate(m, [])
        assert r.passed is True
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_core_performance.py -v`
Expected: FAIL — modules not found

**Step 3: Implement**

Create `src/assessment/strategies/__init__.py`:

```python
"""Assessment strategy implementations."""
```

Create `src/assessment/strategies/roi.py`:

```python
"""ROI Performance strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class ROIStrategy(BaseStrategy):
    name = "ROI Performance"
    description = "Raw returns relative to capital"
    category = "Core Performance"

    PASS_THRESHOLD = 0.0  # ROI >= 0%
    MAX_ROI = 10.0        # 10%+ maps to score 100

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        roi = metrics.roi_proxy
        passed = roi >= self.PASS_THRESHOLD
        score = int(min(100, max(0, roi / self.MAX_ROI * 100))) if roi > 0 else 0
        explanation = f"30d ROI of {roi:.1f}%, {'above' if passed else 'below'} {self.PASS_THRESHOLD}% threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

Create `src/assessment/strategies/sharpe.py`:

```python
"""Risk-Adjusted Returns (Sharpe) strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class SharpeStrategy(BaseStrategy):
    name = "Risk-Adjusted Returns"
    description = "Pseudo-Sharpe ratio (return per unit volatility)"
    category = "Core Performance"

    PASS_THRESHOLD = 0.5
    MAX_SHARPE = 3.0

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        sharpe = metrics.pseudo_sharpe
        passed = sharpe >= self.PASS_THRESHOLD
        score = int(min(100, max(0, sharpe / self.MAX_SHARPE * 100)))
        explanation = f"Pseudo-Sharpe of {sharpe:.2f}, {'above' if passed else 'below'} {self.PASS_THRESHOLD} threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

Create `src/assessment/strategies/profit_factor.py`:

```python
"""Profit Factor strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class ProfitFactorStrategy(BaseStrategy):
    name = "Profit Factor"
    description = "Gross profit / gross loss ratio"
    category = "Core Performance"

    PASS_THRESHOLD = 1.1
    MIN_PF = 1.0
    MAX_PF = 3.0

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        pf = metrics.profit_factor
        passed = pf >= self.PASS_THRESHOLD
        # Scale 1.0-3.0 to 0-100
        score = int(min(100, max(0, (pf - self.MIN_PF) / (self.MAX_PF - self.MIN_PF) * 100)))
        explanation = f"Profit factor of {pf:.2f}, {'above' if passed else 'below'} {self.PASS_THRESHOLD} threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_core_performance.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/assessment/strategies/ tests/test_assessment/test_core_performance.py
git commit -m "feat: add Core Performance strategies (ROI, Sharpe, Profit Factor)"
```

---

## Task 6: Behavioral Quality Strategies (Win Rate, Anti-Luck, Consistency)

**Files:**
- Create: `src/assessment/strategies/win_rate.py`
- Create: `src/assessment/strategies/anti_luck.py`
- Create: `src/assessment/strategies/consistency.py`
- Test: `tests/test_assessment/test_behavioral.py`

**Step 1: Write the failing tests**

Create `tests/test_assessment/test_behavioral.py`:

```python
import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.win_rate import WinRateStrategy
from src.assessment.strategies.anti_luck import AntiLuckStrategy
from src.assessment.strategies.consistency import ConsistencyStrategy


class TestWinRateStrategy:
    def test_healthy_win_rate_passes(self):
        m = make_metrics(win_rate=0.55)
        r = WinRateStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50  # Near optimal

    def test_too_low_fails(self):
        m = make_metrics(win_rate=0.20)
        r = WinRateStrategy().evaluate(m, [])
        assert r.passed is False

    def test_too_high_fails(self):
        m = make_metrics(win_rate=0.90)
        r = WinRateStrategy().evaluate(m, [])
        assert r.passed is False


class TestAntiLuckStrategy:
    def test_sufficient_trades_passes(self):
        m = make_metrics(total_trades=50, total_pnl=1000, win_rate=0.55)
        r = AntiLuckStrategy().evaluate(m, [])
        assert r.passed is True

    def test_insufficient_trades_fails(self):
        m = make_metrics(total_trades=5, total_pnl=1000)
        r = AntiLuckStrategy().evaluate(m, [])
        assert r.passed is False

    def test_low_pnl_fails(self):
        m = make_metrics(total_trades=50, total_pnl=100)
        r = AntiLuckStrategy().evaluate(m, [])
        assert r.passed is False


class TestConsistencyStrategy:
    def test_multi_window_positive_passes(self):
        """Simulate consistency by passing metrics that imply multi-window profit."""
        m = make_metrics(roi_proxy=10.0, total_pnl=5000)
        r = ConsistencyStrategy().evaluate(m, [])
        assert r.passed is True

    def test_negative_pnl_fails(self):
        m = make_metrics(roi_proxy=-5.0, total_pnl=-500)
        r = ConsistencyStrategy().evaluate(m, [])
        assert r.passed is False
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_behavioral.py -v`
Expected: FAIL — modules not found

**Step 3: Implement**

Create `src/assessment/strategies/win_rate.py`:

```python
"""Win Rate Quality strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class WinRateStrategy(BaseStrategy):
    name = "Win Rate Quality"
    description = "Trade success rate within healthy bounds"
    category = "Behavioral Quality"

    LOW_BOUND = 0.30
    HIGH_BOUND = 0.85
    OPTIMAL = 0.55

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        wr = metrics.win_rate
        passed = self.LOW_BOUND <= wr <= self.HIGH_BOUND
        if not passed:
            score = 0
            explanation = f"Win rate {wr:.0%} outside healthy range [{self.LOW_BOUND:.0%}, {self.HIGH_BOUND:.0%}]"
        else:
            # Score based on distance from optimal — closer to 0.55 = higher score
            distance = abs(wr - self.OPTIMAL)
            max_distance = max(self.OPTIMAL - self.LOW_BOUND, self.HIGH_BOUND - self.OPTIMAL)
            score = int(max(0, (1 - distance / max_distance) * 100))
            explanation = f"Win rate {wr:.0%} within healthy range, {abs(wr - self.OPTIMAL):.0%} from optimal {self.OPTIMAL:.0%}"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

Create `src/assessment/strategies/anti_luck.py`:

```python
"""Anti-Luck Filter strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class AntiLuckStrategy(BaseStrategy):
    name = "Anti-Luck Filter"
    description = "Statistical significance checks"
    category = "Behavioral Quality"

    MIN_TRADES = 10
    MIN_PNL = 500.0
    WR_LOW = 0.25
    WR_HIGH = 0.90

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        failures = []
        if metrics.total_trades < self.MIN_TRADES:
            failures.append(f"{metrics.total_trades} trades < {self.MIN_TRADES} minimum")
        if metrics.total_pnl < self.MIN_PNL:
            failures.append(f"PnL ${metrics.total_pnl:.0f} < ${self.MIN_PNL:.0f} minimum")
        if not (self.WR_LOW <= metrics.win_rate <= self.WR_HIGH):
            failures.append(f"Win rate {metrics.win_rate:.0%} outside [{self.WR_LOW:.0%}, {self.WR_HIGH:.0%}]")

        passed = len(failures) == 0
        # Score: 100 if all pass, lose ~33 per failure
        score = max(0, 100 - len(failures) * 33)
        explanation = "All significance checks passed" if passed else "; ".join(failures)
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

Create `src/assessment/strategies/consistency.py`:

```python
"""Consistency strategy — multi-timeframe profitability."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class ConsistencyStrategy(BaseStrategy):
    name = "Consistency"
    description = "Profitability across multiple time windows"
    category = "Behavioral Quality"

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        # With a single metrics window, we check ROI > 0 and PnL > 0
        # as a simplified consistency check.
        # When the engine passes multiple windows, this strategy could
        # be extended. For now, use the single-window data available.
        checks_passed = 0
        total_checks = 2

        if metrics.roi_proxy > 0:
            checks_passed += 1
        if metrics.total_pnl > 0:
            checks_passed += 1

        passed = checks_passed >= 2
        score = int(checks_passed / total_checks * 100)
        explanation = f"{checks_passed}/{total_checks} profitability checks passed (ROI {'>' if metrics.roi_proxy > 0 else '<='} 0%, PnL {'>' if metrics.total_pnl > 0 else '<='} $0)"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_behavioral.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/assessment/strategies/win_rate.py src/assessment/strategies/anti_luck.py src/assessment/strategies/consistency.py tests/test_assessment/test_behavioral.py
git commit -m "feat: add Behavioral Quality strategies (Win Rate, Anti-Luck, Consistency)"
```

---

## Task 7: Risk Discipline Strategies (Drawdown, Leverage, Position Sizing)

**Files:**
- Create: `src/assessment/strategies/drawdown.py`
- Create: `src/assessment/strategies/leverage.py`
- Create: `src/assessment/strategies/position_sizing.py`
- Test: `tests/test_assessment/test_risk.py`

**Step 1: Write the failing tests**

Create `tests/test_assessment/test_risk.py`:

```python
import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.drawdown import DrawdownStrategy
from src.assessment.strategies.leverage import LeverageStrategy
from src.assessment.strategies.position_sizing import PositionSizingStrategy


class TestDrawdownStrategy:
    def test_low_drawdown_passes(self):
        m = make_metrics(max_drawdown_proxy=0.10)
        r = DrawdownStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_high_drawdown_fails(self):
        m = make_metrics(max_drawdown_proxy=0.40)
        r = DrawdownStrategy().evaluate(m, [])
        assert r.passed is False

    def test_zero_drawdown_max_score(self):
        m = make_metrics(max_drawdown_proxy=0.0)
        r = DrawdownStrategy().evaluate(m, [])
        assert r.score == 100


class TestLeverageStrategy:
    def test_low_leverage_passes(self):
        m = make_metrics(max_leverage=5.0, leverage_std=1.0)
        r = LeverageStrategy().evaluate(m, [])
        assert r.passed is True

    def test_high_leverage_fails(self):
        m = make_metrics(max_leverage=60.0, leverage_std=10.0)
        r = LeverageStrategy().evaluate(m, [])
        assert r.passed is False

    def test_moderate_leverage(self):
        m = make_metrics(max_leverage=15.0, leverage_std=3.0)
        r = LeverageStrategy().evaluate(m, [])
        assert r.passed is True
        assert 30 < r.score < 80


class TestPositionSizingStrategy:
    def test_diversified_passes(self):
        m = make_metrics(largest_trade_pnl_ratio=0.15)
        r = PositionSizingStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_concentrated_fails(self):
        m = make_metrics(largest_trade_pnl_ratio=0.60)
        r = PositionSizingStrategy().evaluate(m, [])
        assert r.passed is False

    def test_at_threshold(self):
        m = make_metrics(largest_trade_pnl_ratio=0.40)
        r = PositionSizingStrategy().evaluate(m, [])
        assert r.passed is True  # equal to threshold passes
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_risk.py -v`
Expected: FAIL — modules not found

**Step 3: Implement**

Create `src/assessment/strategies/drawdown.py`:

```python
"""Drawdown Resilience strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class DrawdownStrategy(BaseStrategy):
    name = "Drawdown Resilience"
    description = "Worst peak-to-trough decline"
    category = "Risk Discipline"

    MAX_DD_THRESHOLD = 0.30  # 30% of peak

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        dd = metrics.max_drawdown_proxy
        passed = dd < self.MAX_DD_THRESHOLD
        # Score: inverse of drawdown, scaled 0-100
        score = int(max(0, (1 - dd / self.MAX_DD_THRESHOLD) * 100)) if dd < self.MAX_DD_THRESHOLD else 0
        explanation = f"Max drawdown {dd:.0%}, {'below' if passed else 'exceeds'} {self.MAX_DD_THRESHOLD:.0%} threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

Create `src/assessment/strategies/leverage.py`:

```python
"""Leverage Discipline strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class LeverageStrategy(BaseStrategy):
    name = "Leverage Discipline"
    description = "Consistency of leverage use, no extreme bets"
    category = "Risk Discipline"

    AVG_LEVERAGE_MAX = 20.0  # avg leverage threshold (using max as proxy)
    SINGLE_TRADE_MAX = 50.0  # max single trade leverage

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        max_lev = metrics.max_leverage
        lev_std = metrics.leverage_std
        failures = []
        if max_lev > self.SINGLE_TRADE_MAX:
            failures.append(f"Max leverage {max_lev:.1f}x exceeds {self.SINGLE_TRADE_MAX:.0f}x cap")
        if max_lev > self.AVG_LEVERAGE_MAX:
            failures.append(f"Leverage {max_lev:.1f}x exceeds {self.AVG_LEVERAGE_MAX:.0f}x threshold")

        passed = len(failures) == 0
        # Score: based on how far below the threshold
        if max_lev <= 0:
            score = 100
        else:
            score = int(max(0, min(100, (1 - max_lev / self.SINGLE_TRADE_MAX) * 100)))
        explanation = "Leverage within safe bounds" if passed else "; ".join(failures)
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

Create `src/assessment/strategies/position_sizing.py`:

```python
"""Position Sizing strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class PositionSizingStrategy(BaseStrategy):
    name = "Position Sizing"
    description = "No single trade dominates total PnL"
    category = "Risk Discipline"

    MAX_RATIO = 0.40  # largest trade < 40% of total PnL

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        ratio = metrics.largest_trade_pnl_ratio
        passed = ratio <= self.MAX_RATIO
        # Score: inverse of concentration
        score = int(max(0, min(100, (1 - ratio) * 100)))
        explanation = f"Largest trade is {ratio:.0%} of total PnL, {'within' if passed else 'exceeds'} {self.MAX_RATIO:.0%} limit"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_risk.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/assessment/strategies/drawdown.py src/assessment/strategies/leverage.py src/assessment/strategies/position_sizing.py tests/test_assessment/test_risk.py
git commit -m "feat: add Risk Discipline strategies (Drawdown, Leverage, Position Sizing)"
```

---

## Task 8: Pattern Quality Strategy (Profitability Trend)

**Files:**
- Create: `src/assessment/strategies/trend.py`
- Test: `tests/test_assessment/test_pattern.py`

**Step 1: Write the failing tests**

Create `tests/test_assessment/test_pattern.py`:

```python
import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.trend import TrendStrategy


class TestTrendStrategy:
    def test_positive_trend_passes(self):
        m = make_metrics(pnl_trend_slope=0.3)
        r = TrendStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_declining_trend_fails(self):
        m = make_metrics(pnl_trend_slope=-0.6)
        r = TrendStrategy().evaluate(m, [])
        assert r.passed is False

    def test_flat_trend_passes(self):
        m = make_metrics(pnl_trend_slope=0.0)
        r = TrendStrategy().evaluate(m, [])
        assert r.passed is True  # 0 means second half = first half

    def test_name_and_category(self):
        s = TrendStrategy()
        assert s.name == "Profitability Trend"
        assert s.category == "Pattern Quality"
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_pattern.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/assessment/strategies/trend.py`:

```python
"""Profitability Trend strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class TrendStrategy(BaseStrategy):
    name = "Profitability Trend"
    description = "PnL trajectory direction"
    category = "Pattern Quality"

    # Fail if second half PnL < 50% of first half
    # pnl_trend_slope < -0.5 means second half is less than half of first half
    MIN_SLOPE = -0.5

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        slope = metrics.pnl_trend_slope
        passed = slope >= self.MIN_SLOPE
        # Score: map slope from [-1, 1] to [0, 100], centered at 0 = 50
        score = int(max(0, min(100, (slope + 1) / 2 * 100)))
        if slope > 0:
            explanation = f"PnL improving: second half outperformed first half by {slope:.0%}"
        elif slope >= self.MIN_SLOPE:
            explanation = f"PnL stable: trend slope {slope:.2f} within acceptable range"
        else:
            explanation = f"PnL declining: second half underperformed by {abs(slope):.0%}"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_pattern.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/assessment/strategies/trend.py tests/test_assessment/test_pattern.py
git commit -m "feat: add Pattern Quality strategy (Profitability Trend)"
```

---

## Task 9: AssessmentEngine Orchestrator

**Files:**
- Create: `src/assessment/engine.py`
- Test: `tests/test_assessment/test_engine.py`

**Step 1: Write the failing tests**

Create `tests/test_assessment/test_engine.py`:

```python
import pytest
from tests.conftest import make_metrics
from src.assessment.engine import AssessmentEngine


def test_engine_runs_all_strategies():
    m = make_metrics(
        roi_proxy=8.0, pseudo_sharpe=1.5, profit_factor=2.0,
        win_rate=0.55, total_trades=50, total_pnl=5000,
        max_drawdown_proxy=0.10, max_leverage=10.0, leverage_std=2.0,
        largest_trade_pnl_ratio=0.15, pnl_trend_slope=0.1,
    )
    result = AssessmentEngine().assess(m, [])
    assert len(result["strategies"]) == 10
    assert result["confidence"]["total"] == 10
    assert result["confidence"]["passed"] >= 0
    assert result["confidence"]["tier"] in ("Elite", "Strong", "Moderate", "Weak", "Avoid", "Insufficient Data")


def test_engine_all_pass_elite():
    m = make_metrics(
        roi_proxy=12.0, pseudo_sharpe=2.0, profit_factor=2.5,
        win_rate=0.55, total_trades=50, total_pnl=5000,
        max_drawdown_proxy=0.05, max_leverage=5.0, leverage_std=1.0,
        largest_trade_pnl_ratio=0.10, pnl_trend_slope=0.2,
    )
    result = AssessmentEngine().assess(m, [])
    assert result["confidence"]["passed"] >= 9
    assert result["confidence"]["tier"] in ("Elite", "Strong")


def test_engine_empty_metrics():
    from src.models import TradeMetrics
    m = TradeMetrics.empty(30)
    result = AssessmentEngine().assess(m, [])
    assert result["confidence"]["tier"] == "Insufficient Data"
    assert result["confidence"]["passed"] == 0


def test_engine_strategy_results_structure():
    m = make_metrics()
    result = AssessmentEngine().assess(m, [])
    for s in result["strategies"]:
        assert "name" in s
        assert "category" in s
        assert "score" in s
        assert "passed" in s
        assert "explanation" in s
        assert 0 <= s["score"] <= 100
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_engine.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/assessment/engine.py`:

```python
"""Assessment engine — orchestrates all 10 scoring strategies."""
from __future__ import annotations

from dataclasses import asdict

from src.assessment.base import StrategyResult
from src.assessment.strategies.roi import ROIStrategy
from src.assessment.strategies.sharpe import SharpeStrategy
from src.assessment.strategies.profit_factor import ProfitFactorStrategy
from src.assessment.strategies.win_rate import WinRateStrategy
from src.assessment.strategies.anti_luck import AntiLuckStrategy
from src.assessment.strategies.consistency import ConsistencyStrategy
from src.assessment.strategies.drawdown import DrawdownStrategy
from src.assessment.strategies.leverage import LeverageStrategy
from src.assessment.strategies.position_sizing import PositionSizingStrategy
from src.assessment.strategies.trend import TrendStrategy
from src.models import TradeMetrics

ALL_STRATEGIES = [
    ROIStrategy(),
    SharpeStrategy(),
    ProfitFactorStrategy(),
    WinRateStrategy(),
    AntiLuckStrategy(),
    ConsistencyStrategy(),
    DrawdownStrategy(),
    LeverageStrategy(),
    PositionSizingStrategy(),
    TrendStrategy(),
]

TIERS = {
    (9, 10): "Elite",
    (7, 8): "Strong",
    (5, 6): "Moderate",
    (3, 4): "Weak",
    (0, 2): "Avoid",
}


def _get_tier(passed: int, total_trades: int) -> str:
    if total_trades == 0:
        return "Insufficient Data"
    for (lo, hi), tier in TIERS.items():
        if lo <= passed <= hi:
            return tier
    return "Avoid"


class AssessmentEngine:
    """Runs all assessment strategies and aggregates results."""

    def __init__(self, strategies=None):
        self.strategies = strategies or ALL_STRATEGIES

    def assess(self, metrics: TradeMetrics, positions: list) -> dict:
        results: list[StrategyResult] = []
        for strategy in self.strategies:
            result = strategy.evaluate(metrics, positions)
            results.append(result)

        passed_count = sum(1 for r in results if r.passed)
        total = len(results)
        tier = _get_tier(passed_count, metrics.total_trades)

        return {
            "strategies": [asdict(r) for r in results],
            "confidence": {
                "passed": passed_count,
                "total": total,
                "tier": tier,
            },
        }
```

**Step 4: Run tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/test_engine.py -v`
Expected: ALL PASS

**Step 5: Run full assessment test suite**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/test_assessment/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/assessment/engine.py tests/test_assessment/test_engine.py
git commit -m "feat: add AssessmentEngine orchestrator with 10 strategies and confidence tiers"
```

---

## Task 10: Backend API Schemas

**Files:**
- Modify: `backend/schemas.py` (add assessment response models at end of file)

**Step 1: Write the failing test**

No separate test file — schema correctness is validated by the router test in Task 12.

**Step 2: Implement**

Add to the end of `backend/schemas.py`:

```python
# ---------------------------------------------------------------------------
# Assessment models
# ---------------------------------------------------------------------------


class AssessmentStrategyResult(BaseModel):
    """Result from a single assessment strategy."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    category: str
    score: int
    passed: bool
    explanation: str


class AssessmentConfidence(BaseModel):
    """Overall confidence from the assessment."""

    model_config = ConfigDict(populate_by_name=True)

    passed: int
    total: int
    tier: str


class AssessmentResponse(BaseModel):
    """Response envelope for the trader assessment endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    is_cached: bool
    window_days: int
    trade_count: int
    confidence: AssessmentConfidence
    strategies: list[AssessmentStrategyResult]
    computed_at: str
```

**Step 3: Commit**

```bash
git add backend/schemas.py
git commit -m "feat: add assessment Pydantic response schemas"
```

---

## Task 11: Backend Assessment Router

**Files:**
- Create: `backend/routers/assess.py`
- Test: Manual testing via curl (router depends on Nansen client + datastore — full integration test)

**Step 1: Implement**

Create `backend/routers/assess.py`:

```python
"""Assessment router — evaluate any trader address across 10 strategies."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.dependencies import get_cache, get_datastore, get_nansen_client
from backend.schemas import (
    AssessmentConfidence,
    AssessmentResponse,
    AssessmentStrategyResult,
)
from src.assessment.engine import AssessmentEngine
from src.datastore import DataStore
from src.metrics import compute_trade_metrics
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["assessment"])

# Hex address pattern (0x followed by 40 hex chars)
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

CACHE_STALENESS_HOURS = 6


@router.get("/assess/{address}", response_model=AssessmentResponse)
async def assess_trader(
    address: str,
    window_days: int = Query(default=30, ge=7, le=90),
    nansen_client: NansenClient = Depends(get_nansen_client),
    datastore: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> AssessmentResponse:
    """Assess a trader address across 10 independent scoring strategies."""
    # Validate address format
    if not _ADDRESS_RE.match(address):
        raise HTTPException(status_code=400, detail="Invalid address format. Expected 0x followed by 40 hex characters.")

    # Check response cache first
    cache_key = f"assess:{address}:{window_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    is_cached = False
    metrics = None

    # Try datastore cache for leaderboard addresses
    cached_metrics = datastore.get_latest_metrics(address, window_days=window_days)
    if cached_metrics is not None:
        # Check freshness
        last_trade_time = datastore.get_last_trade_time(address)
        if last_trade_time:
            computed = datetime.fromisoformat(last_trade_time).replace(tzinfo=timezone.utc)
            if now - computed < timedelta(hours=CACHE_STALENESS_HOURS):
                metrics = cached_metrics
                is_cached = True

    # Live fetch from Nansen if no cached data
    if metrics is None:
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=window_days)).strftime("%Y-%m-%d")

        try:
            raw_trades = await nansen_client.fetch_address_trades(
                address=address,
                date_from=date_from,
                date_to=date_to,
                order_by=[{"field": "timestamp", "direction": "DESC"}],
            )
        except NansenRateLimitError:
            raise HTTPException(
                status_code=429,
                detail="Nansen rate limit exceeded. Try again in a few seconds.",
            )
        except NansenAPIError as exc:
            logger.error("Nansen API error assessing %s: %s", address, exc)
            raise HTTPException(
                status_code=502,
                detail="Failed to fetch trade data from upstream API. Please try again.",
            )

        # Get account value for ROI calculation
        account_value = 0.0
        try:
            position_snapshot = await nansen_client.fetch_address_positions(address)
            av_str = position_snapshot.margin_summary_account_value_usd
            account_value = float(av_str) if av_str else 0.0
        except Exception:
            logger.warning("Could not fetch account value for %s, using 0", address)

        metrics = compute_trade_metrics(raw_trades, account_value, window_days)

    # Fetch current positions for strategies that need them
    positions = []
    try:
        pos_snapshot = await nansen_client.fetch_address_positions(address)
        for ap in pos_snapshot.asset_positions:
            p = ap.position
            positions.append({
                "token_symbol": p.token_symbol,
                "leverage_value": p.leverage_value,
                "leverage_type": p.leverage_type,
                "position_value_usd": float(p.position_value_usd) if p.position_value_usd else 0.0,
            })
    except Exception:
        logger.warning("Could not fetch positions for %s during assessment", address)

    # Run assessment engine
    engine = AssessmentEngine()
    result = engine.assess(metrics, positions)

    response = AssessmentResponse(
        address=address,
        is_cached=is_cached,
        window_days=window_days,
        trade_count=metrics.total_trades,
        confidence=AssessmentConfidence(**result["confidence"]),
        strategies=[AssessmentStrategyResult(**s) for s in result["strategies"]],
        computed_at=now.isoformat(),
    )

    # Cache for 10 minutes
    cache.set(cache_key, response, ttl=600)
    return response
```

**Step 2: Commit**

```bash
git add backend/routers/assess.py
git commit -m "feat: add /api/v1/assess/{address} assessment endpoint"
```

---

## Task 12: Register Assessment Router in FastAPI App

**Files:**
- Modify: `backend/main.py:14` (import) and `backend/main.py:69` (include_router)

**Step 1: Implement**

In `backend/main.py`, add to the imports:

```python
from backend.routers import allocations, assess, health, leaderboard, market, positions, screener, traders
```

Add after the last `include_router` call:

```python
app.include_router(assess.router)
```

**Step 2: Verify server starts**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -c "from backend.main import app; print('Router registered:', [r.path for r in app.routes if hasattr(r, 'path') and 'assess' in r.path])"`
Expected: Output includes `/api/v1/assess/{address}`

**Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: register assessment router in FastAPI app"
```

---

## Task 13: Frontend TypeScript Types and React Query Hook

**Files:**
- Modify: `frontend/src/api/types.ts` (add assessment types)
- Modify: `frontend/src/api/hooks.ts` (add useAssessment hook)

**Step 1: Implement types**

Add to the end of `frontend/src/api/types.ts`:

```typescript
// Assessment
export interface AssessmentStrategyResult {
  name: string;
  category: string;
  score: number;
  passed: boolean;
  explanation: string;
}

export interface AssessmentConfidence {
  passed: number;
  total: number;
  tier: string;
}

export interface AssessmentResponse {
  address: string;
  is_cached: boolean;
  window_days: number;
  trade_count: number;
  confidence: AssessmentConfidence;
  strategies: AssessmentStrategyResult[];
  computed_at: string;
}
```

**Step 2: Implement hook**

Add to `frontend/src/api/hooks.ts`:

Import the new type:

```typescript
import type {
  // ... existing imports ...
  AssessmentResponse,
} from './types';
```

Add the hook:

```typescript
export function useAssessment(address: string, windowDays: number = 30) {
  return useQuery({
    queryKey: ['assessment', address, windowDays],
    queryFn: () => apiClient.get<AssessmentResponse>(`/api/v1/assess/${address}`, {
      window_days: windowDays,
    }),
    staleTime: 5 * 60_000,
    enabled: !!address,
    retry: 1,
  });
}
```

**Step 3: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/hooks.ts
git commit -m "feat: add assessment TypeScript types and React Query hook"
```

---

## Task 14: Assessment Input Page

**Files:**
- Create: `frontend/src/pages/AssessTrader.tsx`

**Step 1: Implement**

Create `frontend/src/pages/AssessTrader.tsx`:

```tsx
import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { Search, Clock, ArrowRight } from 'lucide-react';
import { PageLayout } from '../components/layout/PageLayout';

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
const HISTORY_KEY = 'assess-history';
const MAX_HISTORY = 10;

function getHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  } catch {
    return [];
  }
}

function addToHistory(address: string) {
  const history = getHistory().filter((a) => a !== address);
  history.unshift(address);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
}

export function AssessTrader() {
  const [address, setAddress] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const history = getHistory();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = address.trim().toLowerCase();
    if (!ADDRESS_RE.test(trimmed)) {
      setError('Invalid address. Expected 0x followed by 40 hex characters.');
      return;
    }
    setError('');
    addToHistory(trimmed);
    navigate(`/assess/${trimmed}`);
  };

  return (
    <PageLayout
      title="Assess Trader"
      description="Evaluate any Hyperliquid trader address across 10 independent scoring strategies. Get a quality verdict with confidence tier based on how many strategies the address passes."
    >
      <div className="mx-auto max-w-2xl pt-12">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <Search className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={address}
              onChange={(e) => { setAddress(e.target.value); setError(''); }}
              placeholder="Enter trader address (0x...)"
              className="w-full rounded-lg border border-border bg-card py-3 pl-12 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent font-mono"
              autoFocus
            />
          </div>
          {error && <p className="text-sm text-red">{error}</p>}
          <button
            type="submit"
            className="w-full rounded-lg bg-accent px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
            disabled={!address.trim()}
          >
            Assess Trader
          </button>
        </form>

        {history.length > 0 && (
          <div className="mt-8">
            <h3 className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-muted">
              <Clock className="h-3.5 w-3.5" />
              Recent Assessments
            </h3>
            <div className="space-y-1">
              {history.map((addr) => (
                <button
                  key={addr}
                  onClick={() => { addToHistory(addr); navigate(`/assess/${addr}`); }}
                  className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left font-mono text-sm text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
                >
                  <span className="truncate">{addr}</span>
                  <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </PageLayout>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/pages/AssessTrader.tsx
git commit -m "feat: add assessment input page with address validation and history"
```

---

## Task 15: Assessment Results Page

**Files:**
- Create: `frontend/src/pages/AssessmentResults.tsx`

**Step 1: Implement**

Create `frontend/src/pages/AssessmentResults.tsx`:

```tsx
import { useParams, Link } from 'react-router';
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer, Legend } from 'recharts';
import { ArrowLeft, CheckCircle2, XCircle, Shield } from 'lucide-react';
import { PageLayout } from '../components/layout/PageLayout';
import { LoadingState } from '../components/shared/LoadingState';
import { ErrorState } from '../components/shared/ErrorState';
import { useAssessment } from '../api/hooks';
import type { AssessmentStrategyResult } from '../api/types';
import { cn } from '../lib/utils';

const TIER_COLORS: Record<string, string> = {
  Elite: 'bg-green/20 text-green border-green/30',
  Strong: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  Moderate: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  Weak: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  Avoid: 'bg-red/20 text-red border-red/30',
  'Insufficient Data': 'bg-text-muted/20 text-text-muted border-text-muted/30',
};

const CATEGORY_COLORS: Record<string, string> = {
  'Core Performance': '#58a6ff',
  'Behavioral Quality': '#3fb950',
  'Risk Discipline': '#f0883e',
  'Pattern Quality': '#bc8cff',
};

function truncateAddress(addr: string): string {
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

function RadarSection({ strategies }: { strategies: AssessmentStrategyResult[] }) {
  const data = strategies.map((s) => ({
    strategy: s.name.replace(' ', '\n'),
    score: s.score,
    fullMark: 100,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-4 text-sm font-medium text-text-primary">Score Radar</h2>
      <ResponsiveContainer width="100%" height={400}>
        <RadarChart data={data}>
          <PolarGrid stroke="#30363d" />
          <PolarAngleAxis dataKey="strategy" tick={{ fill: '#8b949e', fontSize: 11 }} />
          <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#8b949e', fontSize: 10 }} />
          <Radar name="Score" dataKey="score" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.2} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ScorecardTable({ strategies }: { strategies: AssessmentStrategyResult[] }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium text-text-primary">Strategy Scorecard</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-text-muted">
              <th className="px-4 py-2 font-medium">Strategy</th>
              <th className="px-4 py-2 font-medium">Category</th>
              <th className="px-4 py-2 font-medium">Score</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Explanation</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr key={s.name} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-medium text-text-primary">{s.name}</td>
                <td className="px-4 py-3">
                  <span
                    className="inline-block rounded px-2 py-0.5 text-xs font-medium"
                    style={{ color: CATEGORY_COLORS[s.category] || '#8b949e', backgroundColor: `${CATEGORY_COLORS[s.category] || '#8b949e'}20` }}
                  >
                    {s.category}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${s.score}%`,
                          backgroundColor: s.score >= 70 ? '#3fb950' : s.score >= 40 ? '#f0883e' : '#f85149',
                        }}
                      />
                    </div>
                    <span className="text-xs text-text-muted">{s.score}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  {s.passed ? (
                    <span className="inline-flex items-center gap-1 text-xs text-green">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Pass
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-red">
                      <XCircle className="h-3.5 w-3.5" /> Fail
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-text-muted">{s.explanation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AssessmentResults() {
  const { address } = useParams<{ address: string }>();
  const { data, isLoading, isError, error, refetch } = useAssessment(address || '');

  if (isLoading) {
    return (
      <PageLayout title="Assessing Trader...">
        <LoadingState message="Fetching trades and computing strategies..." />
      </PageLayout>
    );
  }

  if (isError || !data) {
    return (
      <PageLayout title="Assessment Failed">
        <ErrorState
          message={error?.message || 'Failed to assess trader'}
          onRetry={() => refetch()}
        />
      </PageLayout>
    );
  }

  const tierClass = TIER_COLORS[data.confidence.tier] || TIER_COLORS.Avoid;

  return (
    <PageLayout title="Assessment Results">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-4">
          <Link
            to="/assess"
            className="flex items-center gap-1 text-sm text-text-muted transition-colors hover:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" /> Assess another
          </Link>

          <div className="flex items-center gap-3">
            <h1 className="font-mono text-lg text-text-primary">{truncateAddress(data.address)}</h1>
            <span className={cn('rounded-md border px-2.5 py-1 text-xs font-semibold', tierClass)}>
              {data.confidence.tier}
            </span>
            <span className="flex items-center gap-1 text-sm text-text-muted">
              <Shield className="h-4 w-4" />
              {data.confidence.passed}/{data.confidence.total} passed
            </span>
          </div>

          {data.is_cached && (
            <span className="rounded bg-surface px-2 py-0.5 text-xs text-text-muted">Cached</span>
          )}

          <span className="text-xs text-text-muted">
            {data.trade_count} trades ({data.window_days}d)
          </span>

          <Link
            to={`/traders/${data.address}`}
            className="ml-auto text-xs text-accent hover:underline"
          >
            View Deep Dive
          </Link>
        </div>

        {/* Radar Chart */}
        <RadarSection strategies={data.strategies} />

        {/* Scorecard Table */}
        <ScorecardTable strategies={data.strategies} />
      </div>
    </PageLayout>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/pages/AssessmentResults.tsx
git commit -m "feat: add assessment results page with radar chart and scorecard table"
```

---

## Task 16: Add Routes and Sidebar Navigation

**Files:**
- Modify: `frontend/src/App.tsx` (add routes)
- Modify: `frontend/src/components/layout/Sidebar.tsx` (add nav item)

**Step 1: Implement — App.tsx**

Add lazy import for the two new pages alongside the existing lazy imports:

```typescript
const AssessTrader = lazy(() => import('./pages/AssessTrader').then(m => ({ default: m.AssessTrader })));
const AssessmentResults = lazy(() => import('./pages/AssessmentResults').then(m => ({ default: m.AssessmentResults })));
```

Add two new Route elements inside the `<Routes>` block, after the `/allocations` route:

```tsx
<Route path="/assess" element={<AssessTrader />} />
<Route path="/assess/:address" element={<AssessmentResults />} />
```

**Step 2: Implement — Sidebar.tsx**

Add `ClipboardCheck` to the lucide-react import:

```typescript
import { BarChart3, Table, Trophy, PieChart, PanelLeftClose, PanelLeft, ClipboardCheck } from 'lucide-react';
```

Add to the `NAV_ITEMS` array after the Allocations entry:

```typescript
  { to: '/assess', label: 'Assess Trader', icon: ClipboardCheck, shortcut: '5' },
```

**Step 3: Verify build**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted/frontend && npx tsc --noEmit`
Expected: No type errors

**Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat: add assessment routes and sidebar navigation"
```

---

## Task 17: Full Integration Test

**Step 1: Run all Python tests**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 2: Run frontend type check**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Run frontend build**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted/frontend && npm run build`
Expected: Build succeeds

**Step 4: Verify backend starts**

Run: `cd /home/jsong407/hyper-strategies-pnl-weighted && python -c "from backend.main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; assert '/api/v1/assess/{address}' in routes; print('Assessment route registered')"`
Expected: "Assessment route registered"

**Step 5: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: integration test fixes for trader assessment feature"
```

---

## Dependency Graph

```
Task 1 (TradeMetrics model)
  └→ Task 2 (compute extended metrics)
      └→ Task 3 (datastore schema)
          └→ Task 4 (BaseStrategy + StrategyResult)
              ├→ Task 5 (Core Performance strategies)
              ├→ Task 6 (Behavioral Quality strategies)
              ├→ Task 7 (Risk Discipline strategies)
              └→ Task 8 (Pattern Quality strategy)
                  └→ Task 9 (AssessmentEngine)
                      └→ Task 10 (API schemas)
                          └→ Task 11 (Backend router)
                              └→ Task 12 (Register router)
                                  └→ Task 13 (Frontend types + hook)
                                      ├→ Task 14 (Input page)
                                      └→ Task 15 (Results page)
                                          └→ Task 16 (Routes + sidebar)
                                              └→ Task 17 (Integration test)
```

**Parallelizable:** Tasks 5, 6, 7, 8 can run in parallel (all depend on Task 4, independent of each other). Tasks 14, 15 can run in parallel (both depend on Task 13).
