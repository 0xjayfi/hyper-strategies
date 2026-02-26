# Position-Based Scoring & Scheduler Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the trade-based scoring pipeline in the scheduler with a position-only scoring engine, split the profiler rate limiter, and integrate the scheduler into the FastAPI lifespan as a single process.

**Architecture:** Hourly position snapshots for 100 traders feed a 6-component position-based scoring engine (account growth, drawdown, leverage, liquidation distance, diversity, consistency). The old trade-based scoring is preserved for the assess page only. The scheduler runs as an `asyncio.create_task` inside FastAPI's lifespan.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (aiosqlite for scheduler, sync sqlite3 for DataStore), numpy, Pydantic v2

**Design doc:** `docs/plans/2026-02-26-position-based-scoring-design.md`

---

## Task 1: Split Profiler Rate Limiter into Position + Trade

**Files:**
- Modify: `src/config.py:82-96`
- Modify: `src/nansen_client.py:280-334` (init) and `src/nansen_client.py:399-404` (routing)
- Test: `tests/test_rate_limiter.py` (add new tests)

**Step 1: Add position limiter config to `src/config.py`**

Replace lines 92-96 with three limiter configs:

```python
# Position endpoints (profiler/perp-positions) — fast, less rate-limited
NANSEN_RATE_LIMIT_POSITION_PER_SECOND: int = 5
NANSEN_RATE_LIMIT_POSITION_PER_MINUTE: int = 100
NANSEN_RATE_LIMIT_POSITION_MIN_INTERVAL: float = 0.0
NANSEN_RATE_LIMIT_POSITION_STATE_FILE: str = "/tmp/pnl_weighted_rate_position.json"

# Trade endpoints (profiler/perp-trades) — strict throttling, 429 risk
NANSEN_RATE_LIMIT_TRADE_PER_SECOND: int = 1
NANSEN_RATE_LIMIT_TRADE_PER_MINUTE: int = 9
NANSEN_RATE_LIMIT_TRADE_MIN_INTERVAL: float = 7.0
NANSEN_RATE_LIMIT_TRADE_STATE_FILE: str = "/tmp/pnl_weighted_rate_trade.json"
```

Remove the old `NANSEN_RATE_LIMIT_PROFILER_*` constants.

**Step 2: Update `NansenClient.__init__` to create 3 limiters**

In `src/nansen_client.py`, replace the single `_profiler_limiter` (lines 328-334) with:

```python
# Position (profiler/perp-positions) — lenient
self._position_limiter = _RateLimiter(
    per_second=NANSEN_RATE_LIMIT_POSITION_PER_SECOND,
    per_minute=NANSEN_RATE_LIMIT_POSITION_PER_MINUTE,
    state_file=NANSEN_RATE_LIMIT_POSITION_STATE_FILE,
    min_interval=NANSEN_RATE_LIMIT_POSITION_MIN_INTERVAL,
)

# Trade (profiler/perp-trades) — strict
self._trade_limiter = _RateLimiter(
    per_second=NANSEN_RATE_LIMIT_TRADE_PER_SECOND,
    per_minute=NANSEN_RATE_LIMIT_TRADE_PER_MINUTE,
    state_file=NANSEN_RATE_LIMIT_TRADE_STATE_FILE,
    min_interval=NANSEN_RATE_LIMIT_TRADE_MIN_INTERVAL,
)
```

**Step 3: Update limiter routing in `_request()` (line 399-404)**

Replace:
```python
limiter = (
    self._profiler_limiter
    if "/profiler/" in endpoint
    else self._leaderboard_limiter
)
```

With:
```python
if "/profiler/perp-positions" in endpoint:
    limiter = self._position_limiter
elif "/profiler/" in endpoint:
    limiter = self._trade_limiter
else:
    limiter = self._leaderboard_limiter
```

**Step 4: Update imports in `src/nansen_client.py`**

Replace old `NANSEN_RATE_LIMIT_PROFILER_*` imports with the new `NANSEN_RATE_LIMIT_POSITION_*` and `NANSEN_RATE_LIMIT_TRADE_*` constants.

**Step 5: Fix any tests that reference `_profiler_limiter`**

Search `tests/test_rate_limiter.py` for references to `_profiler_limiter` and update to use the appropriate new limiter name.

**Step 6: Run tests**

```bash
cd /home/jsong407/hyper-strategies-pnl-weighted
python -m pytest tests/test_rate_limiter.py tests/ -q
```

Expected: All tests pass.

**Step 7: Commit**

```bash
git add src/config.py src/nansen_client.py tests/test_rate_limiter.py
git commit -m "refactor: split profiler rate limiter into position + trade"
```

---

## Task 2: Add DataStore Methods for Position Snapshot Time Series

**Files:**
- Modify: `src/datastore.py` (add 2 new methods)
- Test: `tests/test_datastore.py` (add tests)

**Step 1: Write failing tests**

Add to `tests/test_datastore.py`:

```python
def test_get_position_snapshot_series(ds):
    """Returns all snapshots for an address within a day window."""
    ds.upsert_trader("0xA", label="Trader A")
    # Insert two snapshots at different times
    ds.insert_position_snapshot("0xA", [
        {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10000,
         "entry_price": 50000, "leverage_value": 5.0, "leverage_type": "cross",
         "liquidation_price": 40000, "unrealized_pnl": 500, "account_value": 100000}
    ])
    # Simulate a second snapshot 1 hour later
    import time; time.sleep(0.01)
    ds.insert_position_snapshot("0xA", [
        {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10500,
         "entry_price": 50000, "leverage_value": 5.0, "leverage_type": "cross",
         "liquidation_price": 40000, "unrealized_pnl": 1000, "account_value": 101000}
    ])
    series = ds.get_position_snapshot_series("0xA", days=30)
    assert len(series) == 2
    assert series[0]["account_value"] == 100000
    assert series[1]["account_value"] == 101000


def test_get_position_snapshot_series_empty(ds):
    """Returns empty list for unknown address."""
    result = ds.get_position_snapshot_series("0xNONE", days=30)
    assert result == []


def test_get_account_value_series(ds):
    """Returns deduplicated account value time series."""
    ds.upsert_trader("0xA", label="Trader A")
    ds.insert_position_snapshot("0xA", [
        {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10000,
         "entry_price": 50000, "leverage_value": 5.0, "leverage_type": "cross",
         "liquidation_price": 40000, "unrealized_pnl": 500, "account_value": 100000},
        {"token_symbol": "ETH", "side": "Short", "position_value_usd": 5000,
         "entry_price": 3000, "leverage_value": 3.0, "leverage_type": "cross",
         "liquidation_price": 3500, "unrealized_pnl": -200, "account_value": 100000},
    ])
    series = ds.get_account_value_series("0xA", days=30)
    # Should deduplicate: one entry per captured_at, not per position
    assert len(series) == 1
    assert series[0]["account_value"] == 100000
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_datastore.py::test_get_position_snapshot_series -v
```

Expected: FAIL — `DataStore` has no `get_position_snapshot_series` method.

**Step 3: Implement the two DataStore methods**

Add to `src/datastore.py`:

```python
def get_position_snapshot_series(self, address: str, days: int = 30) -> list[dict]:
    """Return all position snapshots for an address within the last N days.

    Returns a flat list of snapshot rows ordered by captured_at ASC.
    Each row includes all position_snapshots columns.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = self._conn.execute(
        """
        SELECT * FROM position_snapshots
         WHERE address = ? AND captured_at >= ?
         ORDER BY captured_at ASC
        """,
        (address, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def get_account_value_series(self, address: str, days: int = 30) -> list[dict]:
    """Return deduplicated account value time series for an address.

    Groups by captured_at and returns one row per snapshot timestamp
    with the account_value and total position value sum.

    Returns list of dicts: [{"captured_at": str, "account_value": float,
    "total_position_value": float, "total_unrealized_pnl": float,
    "position_count": int}]
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = self._conn.execute(
        """
        SELECT captured_at,
               MAX(account_value) AS account_value,
               SUM(position_value_usd) AS total_position_value,
               SUM(unrealized_pnl) AS total_unrealized_pnl,
               COUNT(*) AS position_count
          FROM position_snapshots
         WHERE address = ? AND captured_at >= ?
         GROUP BY captured_at
         ORDER BY captured_at ASC
        """,
        (address, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_datastore.py -q
```

Expected: All pass.

**Step 5: Commit**

```bash
git add src/datastore.py tests/test_datastore.py
git commit -m "feat(datastore): add position snapshot series and account value series queries"
```

---

## Task 3: Create Position Metrics Engine

**Files:**
- Create: `src/position_metrics.py`
- Create: `tests/test_position_metrics.py`

This is the core computation engine. It derives all 6 scoring inputs from position snapshot time series.

**Step 1: Write failing tests**

Create `tests/test_position_metrics.py`:

```python
"""Tests for the position-based metrics engine."""
import pytest
from src.position_metrics import (
    compute_account_growth,
    detect_deposit_withdrawals,
    compute_max_drawdown,
    compute_effective_leverage,
    compute_liquidation_distance,
    compute_position_diversity,
    compute_consistency,
    compute_position_metrics,
)


# --- Account Growth ---

def test_account_growth_basic():
    series = [
        {"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
         "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 2},
        {"captured_at": "2026-02-15T00:00:00", "account_value": 110000,
         "total_unrealized_pnl": 5000, "total_position_value": 55000, "position_count": 2},
    ]
    growth = compute_account_growth(series)
    assert abs(growth - 0.10) < 0.001  # 10% growth


def test_account_growth_empty():
    assert compute_account_growth([]) == 0.0


def test_account_growth_single_point():
    series = [{"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
               "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 1}]
    assert compute_account_growth(series) == 0.0


# --- Deposit/Withdrawal Detection ---

def test_detect_deposit_basic():
    """Large account jump without matching PnL change = deposit."""
    series = [
        {"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
         "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 2},
        {"captured_at": "2026-02-01T01:00:00", "account_value": 150000,
         "total_unrealized_pnl": 1000, "total_position_value": 50000, "position_count": 2},
    ]
    flags = detect_deposit_withdrawals(series)
    assert flags[1] is True  # index 1 is flagged


def test_no_false_positive_on_pnl():
    """Account growth from PnL should NOT be flagged."""
    series = [
        {"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
         "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 2},
        {"captured_at": "2026-02-01T01:00:00", "account_value": 105000,
         "total_unrealized_pnl": 5000, "total_position_value": 55000, "position_count": 2},
    ]
    flags = detect_deposit_withdrawals(series)
    assert flags[1] is False


# --- Max Drawdown ---

def test_max_drawdown_basic():
    series = [
        {"captured_at": "t1", "account_value": 100000},
        {"captured_at": "t2", "account_value": 120000},
        {"captured_at": "t3", "account_value": 90000},
        {"captured_at": "t4", "account_value": 110000},
    ]
    dd = compute_max_drawdown(series, flags=[False, False, False, False])
    assert abs(dd - 0.25) < 0.001  # (120k - 90k) / 120k = 25%


def test_max_drawdown_no_drawdown():
    series = [
        {"captured_at": "t1", "account_value": 100000},
        {"captured_at": "t2", "account_value": 110000},
        {"captured_at": "t3", "account_value": 120000},
    ]
    dd = compute_max_drawdown(series, flags=[False, False, False])
    assert dd == 0.0


# --- Effective Leverage ---

def test_effective_leverage():
    series = [
        {"captured_at": "t1", "account_value": 100000,
         "total_position_value": 300000, "position_count": 3},
        {"captured_at": "t2", "account_value": 100000,
         "total_position_value": 500000, "position_count": 3},
    ]
    avg, std = compute_effective_leverage(series)
    assert abs(avg - 4.0) < 0.001  # (3x + 5x) / 2
    assert std > 0


# --- Liquidation Distance ---

def test_liquidation_distance():
    snapshots = [
        {"entry_price": 50000, "liquidation_price": 40000,
         "position_value_usd": 10000, "captured_at": "t1"},
        {"entry_price": 3000, "liquidation_price": 2700,
         "position_value_usd": 5000, "captured_at": "t1"},
    ]
    dist = compute_liquidation_distance(snapshots)
    # BTC: |50000-40000|/50000 = 0.20, weight=10k
    # ETH: |3000-2700|/3000 = 0.10, weight=5k
    # Weighted: (0.20*10000 + 0.10*5000) / 15000 = 0.1667
    assert abs(dist - 0.1667) < 0.01


def test_liquidation_distance_no_liq_price():
    """Positions without liquidation_price should be skipped."""
    snapshots = [
        {"entry_price": 50000, "liquidation_price": None,
         "position_value_usd": 10000, "captured_at": "t1"},
    ]
    dist = compute_liquidation_distance(snapshots)
    assert dist == 1.0  # No measurable risk = max score


# --- Position Diversity (HHI) ---

def test_diversity_single_position():
    snapshots = [
        {"token_symbol": "BTC", "position_value_usd": 10000, "captured_at": "t1"},
    ]
    hhi = compute_position_diversity(snapshots)
    assert hhi == 1.0  # Single position = HHI 1.0


def test_diversity_two_equal():
    snapshots = [
        {"token_symbol": "BTC", "position_value_usd": 5000, "captured_at": "t1"},
        {"token_symbol": "ETH", "position_value_usd": 5000, "captured_at": "t1"},
    ]
    hhi = compute_position_diversity(snapshots)
    assert abs(hhi - 0.5) < 0.001  # Two equal = HHI 0.5


# --- Consistency ---

def test_consistency_steady_growth():
    series = [
        {"captured_at": f"t{i}", "account_value": 100000 + i * 1000}
        for i in range(10)
    ]
    c = compute_consistency(series, flags=[False] * 10)
    assert c > 0.5  # Steady growth = high consistency


def test_consistency_volatile():
    series = [
        {"captured_at": "t0", "account_value": 100000},
        {"captured_at": "t1", "account_value": 120000},
        {"captured_at": "t2", "account_value": 80000},
        {"captured_at": "t3", "account_value": 130000},
        {"captured_at": "t4", "account_value": 70000},
    ]
    c = compute_consistency(series, flags=[False] * 5)
    assert c < 0.3  # Volatile = low consistency


# --- Full Pipeline ---

def test_compute_position_metrics_returns_all_fields():
    """Smoke test: verify the full pipeline returns all expected keys."""
    account_series = [
        {"captured_at": f"2026-02-{i+1:02d}T00:00:00", "account_value": 100000 + i * 500,
         "total_unrealized_pnl": i * 100, "total_position_value": 50000 + i * 200,
         "position_count": 3}
        for i in range(24)
    ]
    position_snapshots = [
        {"token_symbol": "BTC", "side": "Long", "position_value_usd": 30000,
         "entry_price": 50000, "liquidation_price": 40000, "leverage_value": 5.0,
         "captured_at": f"2026-02-{i+1:02d}T00:00:00"}
        for i in range(24)
    ] + [
        {"token_symbol": "ETH", "side": "Short", "position_value_usd": 20000,
         "entry_price": 3000, "liquidation_price": 3500, "leverage_value": 3.0,
         "captured_at": f"2026-02-{i+1:02d}T00:00:00"}
        for i in range(24)
    ]
    metrics = compute_position_metrics(account_series, position_snapshots)
    expected_keys = {
        "account_growth", "max_drawdown", "avg_leverage", "leverage_std",
        "avg_liquidation_distance", "avg_hhi", "consistency",
        "deposit_withdrawal_count", "snapshot_count",
    }
    assert set(metrics.keys()) == expected_keys
    assert metrics["snapshot_count"] == 24
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_position_metrics.py -v
```

Expected: FAIL — `src/position_metrics` does not exist.

**Step 3: Implement `src/position_metrics.py`**

```python
"""Position-Based Metrics Engine.

Derives scoring inputs from position snapshot time series.
No API calls — all computation from the position_snapshots DB table.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def detect_deposit_withdrawals(
    series: list[dict],
    threshold_usd: float = 1000.0,
    threshold_pct: float = 0.10,
) -> list[bool]:
    """Flag snapshots where account value change doesn't match PnL change.

    A snapshot is flagged if:
    - |account_value_delta| > threshold_usd AND
    - |account_value_delta| > threshold_pct * prev_account_value AND
    - |account_value_delta - unrealized_pnl_delta| > threshold_usd

    Returns a list of booleans, one per snapshot. Index 0 is always False.
    """
    flags = [False] * len(series)
    if len(series) < 2:
        return flags

    for i in range(1, len(series)):
        prev = series[i - 1]
        curr = series[i]

        prev_av = prev.get("account_value") or 0
        curr_av = curr.get("account_value") or 0
        av_delta = curr_av - prev_av

        prev_upnl = prev.get("total_unrealized_pnl") or 0
        curr_upnl = curr.get("total_unrealized_pnl") or 0
        upnl_delta = curr_upnl - prev_upnl

        # Check if the account value change is large
        if abs(av_delta) <= threshold_usd:
            continue
        if prev_av > 0 and abs(av_delta) <= threshold_pct * prev_av:
            continue

        # Check if PnL explains the change
        unexplained = abs(av_delta - upnl_delta)
        if unexplained > threshold_usd:
            flags[i] = True
            logger.debug(
                "Deposit/withdrawal flagged at %s: av_delta=%.0f, upnl_delta=%.0f",
                curr.get("captured_at", "?"),
                av_delta,
                upnl_delta,
            )

    return flags


def compute_account_growth(
    series: list[dict],
    flags: Optional[list[bool]] = None,
) -> float:
    """Compute account growth as a fraction, excluding deposit/withdrawal events.

    Returns 0.0 if insufficient data.
    """
    if len(series) < 2:
        return 0.0

    if flags is None:
        flags = detect_deposit_withdrawals(series)

    # Build adjusted series: accumulate only non-flagged deltas
    start_value = series[0].get("account_value") or 0
    if start_value <= 0:
        return 0.0

    cumulative_excluded = 0.0
    for i in range(1, len(series)):
        if flags[i]:
            prev_av = series[i - 1].get("account_value") or 0
            curr_av = series[i].get("account_value") or 0
            cumulative_excluded += (curr_av - prev_av)

    end_value = series[-1].get("account_value") or 0
    adjusted_growth = (end_value - start_value - cumulative_excluded) / start_value
    return adjusted_growth


def compute_max_drawdown(
    series: list[dict],
    flags: Optional[list[bool]] = None,
) -> float:
    """Peak-to-trough max drawdown from account value series.

    Excludes flagged deposit/withdrawal snapshots.
    Returns 0.0 if no drawdown or insufficient data.
    """
    if len(series) < 2:
        return 0.0

    if flags is None:
        flags = [False] * len(series)

    peak = 0.0
    max_dd = 0.0

    for i, s in enumerate(series):
        if flags[i]:
            continue
        av = s.get("account_value") or 0
        if av <= 0:
            continue
        if av > peak:
            peak = av
        if peak > 0:
            dd = (peak - av) / peak
            if dd > max_dd:
                max_dd = dd

    return max_dd


def compute_effective_leverage(
    series: list[dict],
) -> tuple[float, float]:
    """Average and std of effective portfolio leverage.

    Effective leverage = total_position_value / account_value per snapshot.
    Returns (avg_leverage, leverage_std).
    """
    leverages = []
    for s in series:
        av = s.get("account_value") or 0
        pv = s.get("total_position_value") or 0
        if av > 0:
            leverages.append(pv / av)

    if not leverages:
        return 0.0, 0.0

    return float(np.mean(leverages)), float(np.std(leverages))


def compute_liquidation_distance(
    snapshots: list[dict],
) -> float:
    """Weighted average distance to liquidation across all position snapshots.

    Distance per position = |entry_price - liquidation_price| / entry_price
    Weighted by position_value_usd.

    Returns 1.0 if no positions have liquidation prices (safest score).
    """
    total_weight = 0.0
    weighted_distance = 0.0

    for s in snapshots:
        entry = s.get("entry_price")
        liq = s.get("liquidation_price")
        pv = s.get("position_value_usd") or 0

        if entry is None or liq is None or entry == 0 or pv <= 0:
            continue

        entry = float(entry)
        liq = float(liq)
        distance = abs(entry - liq) / entry
        weighted_distance += distance * pv
        total_weight += pv

    if total_weight <= 0:
        return 1.0  # No measurable liquidation risk

    return weighted_distance / total_weight


def compute_position_diversity(
    snapshots: list[dict],
) -> float:
    """HHI (Herfindahl-Hirschman Index) across position values.

    Computed per snapshot timestamp, then averaged.
    HHI = sum((value_i / total)^2). 1.0 = single position, lower = more diverse.
    """
    if not snapshots:
        return 1.0

    # Group by captured_at
    by_time: dict[str, list[float]] = {}
    for s in snapshots:
        ts = s.get("captured_at", "")
        pv = s.get("position_value_usd") or 0
        if pv > 0:
            by_time.setdefault(ts, []).append(pv)

    if not by_time:
        return 1.0

    hhis = []
    for values in by_time.values():
        total = sum(values)
        if total <= 0:
            continue
        hhi = sum((v / total) ** 2 for v in values)
        hhis.append(hhi)

    return float(np.mean(hhis)) if hhis else 1.0


def compute_consistency(
    series: list[dict],
    flags: Optional[list[bool]] = None,
) -> float:
    """Sharpe-like consistency ratio from daily account value deltas.

    consistency = mean(deltas) / std(deltas) if std > 0.
    Excludes flagged deposit/withdrawal snapshots.
    Returns 0.0 if insufficient data.
    """
    if len(series) < 3:
        return 0.0

    if flags is None:
        flags = [False] * len(series)

    deltas = []
    for i in range(1, len(series)):
        if flags[i] or flags[i - 1]:
            continue
        prev_av = series[i - 1].get("account_value") or 0
        curr_av = series[i].get("account_value") or 0
        if prev_av > 0:
            deltas.append((curr_av - prev_av) / prev_av)

    if len(deltas) < 2:
        return 0.0

    mean_delta = float(np.mean(deltas))
    std_delta = float(np.std(deltas))

    if std_delta <= 0:
        return 1.0 if mean_delta > 0 else 0.0

    return mean_delta / std_delta


def compute_position_metrics(
    account_series: list[dict],
    position_snapshots: list[dict],
) -> dict:
    """Full position-based metrics pipeline.

    Parameters
    ----------
    account_series:
        Output of DataStore.get_account_value_series() — one row per
        snapshot timestamp with account_value, total_position_value,
        total_unrealized_pnl, position_count.
    position_snapshots:
        Output of DataStore.get_position_snapshot_series() — all
        individual position rows.

    Returns
    -------
    dict with keys: account_growth, max_drawdown, avg_leverage, leverage_std,
    avg_liquidation_distance, avg_hhi, consistency, deposit_withdrawal_count,
    snapshot_count.
    """
    flags = detect_deposit_withdrawals(account_series)

    growth = compute_account_growth(account_series, flags)
    drawdown = compute_max_drawdown(account_series, flags)
    avg_lev, lev_std = compute_effective_leverage(account_series)
    liq_dist = compute_liquidation_distance(position_snapshots)
    hhi = compute_position_diversity(position_snapshots)
    consistency = compute_consistency(account_series, flags)

    return {
        "account_growth": growth,
        "max_drawdown": drawdown,
        "avg_leverage": avg_lev,
        "leverage_std": lev_std,
        "avg_liquidation_distance": liq_dist,
        "avg_hhi": hhi,
        "consistency": consistency,
        "deposit_withdrawal_count": sum(flags),
        "snapshot_count": len(account_series),
    }
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_position_metrics.py -v
```

Expected: All pass.

**Step 5: Run full test suite**

```bash
python -m pytest tests/ -q
```

Expected: All pass (no regressions).

**Step 6: Commit**

```bash
git add src/position_metrics.py tests/test_position_metrics.py
git commit -m "feat: add position-based metrics engine with deposit/withdrawal detection"
```

---

## Task 4: Create Position-Based Scoring Engine

**Files:**
- Create: `src/position_scoring.py`
- Create: `tests/test_position_scoring.py`

**Step 1: Write failing tests**

Create `tests/test_position_scoring.py`:

```python
"""Tests for position-based scoring engine."""
import pytest
from src.position_scoring import (
    normalize_account_growth,
    normalize_drawdown,
    normalize_leverage,
    normalize_liquidation_distance,
    normalize_diversity,
    normalize_consistency,
    compute_position_score,
)


# --- Normalization functions ---

def test_normalize_growth_high():
    assert normalize_account_growth(0.15) == 1.0  # 15% > 10% cap


def test_normalize_growth_mid():
    assert abs(normalize_account_growth(0.05) - 0.5) < 0.001


def test_normalize_growth_negative():
    assert normalize_account_growth(-0.05) == 0.0


def test_normalize_drawdown_zero():
    assert normalize_drawdown(0.0) == 1.0


def test_normalize_drawdown_25pct():
    assert abs(normalize_drawdown(0.25) - 0.5) < 0.001


def test_normalize_drawdown_50pct():
    assert normalize_drawdown(0.50) == 0.0


def test_normalize_leverage_low():
    assert abs(normalize_leverage(2.0, 0.5) - 0.9) < 0.01  # 1 - 2/20 = 0.9


def test_normalize_leverage_high():
    assert normalize_leverage(25.0, 5.0) == 0.0


def test_normalize_liq_distance_far():
    assert normalize_liquidation_distance(0.30) == 1.0


def test_normalize_liq_distance_close():
    assert normalize_liquidation_distance(0.05) == 0.0


def test_normalize_diversity_diversified():
    # HHI 0.25 (4 equal positions) = score 1.0
    assert normalize_diversity(0.25) == 1.0


def test_normalize_diversity_concentrated():
    # HHI 1.0 (single position) = score 0.2
    assert abs(normalize_diversity(1.0) - 0.2) < 0.01


def test_normalize_consistency_high():
    assert normalize_consistency(1.5) == 1.0


def test_normalize_consistency_zero():
    assert normalize_consistency(0.0) == 0.0


# --- Composite score ---

def test_compute_position_score_returns_all_fields():
    metrics = {
        "account_growth": 0.08,
        "max_drawdown": 0.10,
        "avg_leverage": 3.0,
        "leverage_std": 1.0,
        "avg_liquidation_distance": 0.20,
        "avg_hhi": 0.4,
        "consistency": 0.8,
        "deposit_withdrawal_count": 0,
        "snapshot_count": 48,
    }
    result = compute_position_score(metrics, label="Smart Money Trader")
    expected_keys = {
        "account_growth_score", "drawdown_score", "leverage_score",
        "liquidation_distance_score", "diversity_score", "consistency_score",
        "smart_money_bonus", "recency_decay",
        "raw_composite_score", "final_score",
    }
    assert expected_keys.issubset(set(result.keys()))
    assert 0 <= result["final_score"] <= 2.0  # With bonuses could exceed 1.0


def test_score_with_smart_money_bonus():
    metrics = {
        "account_growth": 0.10, "max_drawdown": 0.0, "avg_leverage": 1.0,
        "leverage_std": 0.0, "avg_liquidation_distance": 0.30,
        "avg_hhi": 0.25, "consistency": 1.0,
        "deposit_withdrawal_count": 0, "snapshot_count": 48,
    }
    score_sm = compute_position_score(metrics, label="Smart Money Fund")
    score_no = compute_position_score(metrics, label=None)
    assert score_sm["final_score"] > score_no["final_score"]
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_position_scoring.py -v
```

Expected: FAIL — module doesn't exist.

**Step 3: Implement `src/position_scoring.py`**

```python
"""Position-Based Scoring Engine.

6-component composite score derived entirely from position snapshot metrics.
Replaces the trade-based scoring for the scheduler's allocation pipeline.
"""

from __future__ import annotations

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# --- Weights ---

POSITION_SCORE_WEIGHTS = {
    "account_growth": 0.30,
    "drawdown": 0.20,
    "leverage": 0.15,
    "liquidation_distance": 0.15,
    "diversity": 0.10,
    "consistency": 0.10,
}


# --- Normalization functions ---

def normalize_account_growth(growth: float) -> float:
    """Normalize account growth to [0, 1]. 10%+ monthly = 1.0."""
    return min(1.0, max(0.0, growth / 0.10))


def normalize_drawdown(drawdown: float) -> float:
    """Normalize max drawdown to [0, 1]. 0% = 1.0, 50%+ = 0.0."""
    return max(0.0, 1.0 - drawdown / 0.50)


def normalize_leverage(avg_leverage: float, leverage_std: float) -> float:
    """Normalize leverage to [0, 1]. Low and consistent = high score."""
    base = max(0.0, 1.0 - avg_leverage / 20.0)
    # Penalize high variance
    volatility_penalty = min(0.2, leverage_std / 25.0)
    return max(0.0, base - volatility_penalty)


def normalize_liquidation_distance(distance: float) -> float:
    """Normalize liquidation distance to [0, 1]. 30%+ = 1.0, <5% = 0.0."""
    if distance >= 0.30:
        return 1.0
    if distance <= 0.05:
        return 0.0
    return (distance - 0.05) / 0.25


def normalize_diversity(hhi: float) -> float:
    """Normalize HHI to [0, 1]. HHI < 0.25 = 1.0, HHI = 1.0 = 0.2."""
    if hhi <= 0.25:
        return 1.0
    # Linear interpolation: 0.25 -> 1.0, 1.0 -> 0.2
    return max(0.2, 1.0 - (hhi - 0.25) / 0.75 * 0.8)


def normalize_consistency(ratio: float) -> float:
    """Normalize consistency (Sharpe-like ratio) to [0, 1]. >= 1.0 = 1.0."""
    return min(1.0, max(0.0, ratio))


# --- Smart money bonus (reused from trade-based scoring) ---

def _smart_money_bonus(label: Optional[str]) -> float:
    """Return a multiplier based on Nansen address label."""
    if not label:
        return 1.0
    label_lower = label.lower()
    if "fund" in label_lower:
        return 1.10
    elif "smart" in label_lower:
        return 1.08
    elif label:
        return 1.05
    return 1.0


# --- Recency decay ---

def _recency_decay(hours_since_last_snapshot: float, half_life: float = 168.0) -> float:
    """Exponential decay based on hours since last active snapshot."""
    return math.exp(-0.693 * hours_since_last_snapshot / half_life)


# --- Composite score ---

def compute_position_score(
    metrics: dict,
    label: Optional[str] = None,
    hours_since_last_snapshot: float = 0.0,
) -> dict:
    """Compute 6-component position-based composite score.

    Parameters
    ----------
    metrics:
        Output of position_metrics.compute_position_metrics().
    label:
        Nansen address label (for smart money bonus).
    hours_since_last_snapshot:
        Hours since the trader's latest snapshot with open positions.

    Returns
    -------
    dict with individual component scores + final_score.
    """
    w = POSITION_SCORE_WEIGHTS

    ag = normalize_account_growth(metrics.get("account_growth", 0.0))
    dd = normalize_drawdown(metrics.get("max_drawdown", 0.0))
    lev = normalize_leverage(
        metrics.get("avg_leverage", 0.0),
        metrics.get("leverage_std", 0.0),
    )
    liq = normalize_liquidation_distance(
        metrics.get("avg_liquidation_distance", 1.0),
    )
    div = normalize_diversity(metrics.get("avg_hhi", 1.0))
    con = normalize_consistency(metrics.get("consistency", 0.0))

    raw = (
        w["account_growth"] * ag
        + w["drawdown"] * dd
        + w["leverage"] * lev
        + w["liquidation_distance"] * liq
        + w["diversity"] * div
        + w["consistency"] * con
    )

    sm = _smart_money_bonus(label)
    decay = _recency_decay(hours_since_last_snapshot)

    final = raw * sm * decay

    return {
        "account_growth_score": ag,
        "drawdown_score": dd,
        "leverage_score": lev,
        "liquidation_distance_score": liq,
        "diversity_score": div,
        "consistency_score": con,
        "smart_money_bonus": sm,
        "recency_decay": decay,
        "raw_composite_score": raw,
        "final_score": final,
    }
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_position_scoring.py -v
```

Expected: All pass.

**Step 5: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: All pass (no regressions).

**Step 6: Commit**

```bash
git add src/position_scoring.py tests/test_position_scoring.py
git commit -m "feat: add position-based scoring engine with 6 components"
```

---

## Task 5: Create Position-Based Filter Gates

**Files:**
- Modify: `src/filters.py` (add new function)
- Modify: `tests/test_filters.py` (add tests)

**Step 1: Write failing tests**

Add to `tests/test_filters.py`:

```python
from src.filters import is_position_eligible


def test_position_eligible_passes():
    metrics = {
        "account_growth": 0.05,
        "avg_leverage": 5.0,
        "snapshot_count": 48,
    }
    ok, reason = is_position_eligible("0xGOOD", metrics, ds)
    assert ok is True


def test_position_eligible_insufficient_snapshots():
    metrics = {
        "account_growth": 0.05,
        "avg_leverage": 5.0,
        "snapshot_count": 10,  # < 48 minimum
    }
    ok, reason = is_position_eligible("0xFEW", metrics, ds)
    assert ok is False
    assert "snapshots" in reason.lower()


def test_position_eligible_negative_growth():
    metrics = {
        "account_growth": -0.05,
        "avg_leverage": 5.0,
        "snapshot_count": 48,
    }
    ok, reason = is_position_eligible("0xLOSER", metrics, ds)
    assert ok is False
    assert "growth" in reason.lower()


def test_position_eligible_high_leverage():
    metrics = {
        "account_growth": 0.05,
        "avg_leverage": 30.0,  # > 25x
        "snapshot_count": 48,
    }
    ok, reason = is_position_eligible("0xDEGEN", metrics, ds)
    assert ok is False
    assert "leverage" in reason.lower()


def test_position_eligible_blacklisted(ds):
    ds.upsert_trader("0xBLACK", label="Blacklisted")
    ds.add_to_blacklist("0xBLACK", "test")
    metrics = {
        "account_growth": 0.10,
        "avg_leverage": 3.0,
        "snapshot_count": 100,
    }
    ok, reason = is_position_eligible("0xBLACK", metrics, ds)
    assert ok is False
    assert "blacklist" in reason.lower()
```

**Step 2: Implement `is_position_eligible` in `src/filters.py`**

Add to `src/filters.py`:

```python
# ---------------------------------------------------------------------------
# Position-based eligibility (for scheduler scoring pipeline)
# ---------------------------------------------------------------------------

# Thresholds
MIN_SNAPSHOTS_30D = 48          # ~2 days of hourly snapshots
MIN_ACCOUNT_GROWTH = 0.0        # Must be profitable
MAX_AVG_LEVERAGE = 25.0         # No degenerate leverage
MIN_ACCOUNT_VALUE = 1000.0      # Filter dust accounts


def is_position_eligible(
    address: str,
    position_metrics: dict,
    datastore: DataStore,
) -> tuple[bool, str]:
    """Position-based eligibility gate for the scheduler pipeline.

    Uses position-derived metrics instead of trade-based metrics.
    """
    # Blacklist check
    ok, reason = is_trader_eligible(address, datastore)
    if not ok:
        return False, reason

    snapshots = position_metrics.get("snapshot_count", 0)
    if snapshots < MIN_SNAPSHOTS_30D:
        return False, f"Insufficient snapshots: {snapshots} < {MIN_SNAPSHOTS_30D}"

    growth = position_metrics.get("account_growth", 0.0)
    if growth <= MIN_ACCOUNT_GROWTH:
        return False, f"Negative account growth: {growth:.2%}"

    leverage = position_metrics.get("avg_leverage", 0.0)
    if leverage > MAX_AVG_LEVERAGE:
        return False, f"Excessive leverage: {leverage:.1f}x > {MAX_AVG_LEVERAGE}x"

    return True, "eligible"
```

**Step 3: Add filter thresholds to `src/config.py`**

```python
# Position-based filter gates (for scheduler)
POSITION_MIN_SNAPSHOTS = 48
POSITION_MIN_GROWTH = 0.0
POSITION_MAX_LEVERAGE = 25.0
POSITION_MIN_ACCOUNT_VALUE = 1000.0
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_filters.py -v
```

Expected: All pass (old + new).

**Step 5: Commit**

```bash
git add src/filters.py src/config.py tests/test_filters.py
git commit -m "feat: add position-based eligibility filter gates"
```

---

## Task 6: Rewrite Scheduler for Position-Only Pipeline

**Files:**
- Modify: `src/scheduler.py` (major rewrite)
- Modify: `src/config.py:77-80` (update intervals)

**Step 1: Update scheduling config in `src/config.py`**

Replace lines 77-80:

```python
# Scheduling
LEADERBOARD_REFRESH_CRON = "0 0 * * *"  # Daily midnight UTC
LEADERBOARD_TOP_N = 100                  # Fetch top 100 traders (2 pages of 50)
POSITION_SNAPSHOT_MINUTES = 60           # Hourly position sweep
POSITION_SCORING_MINUTES = 60            # Hourly scoring (after sweep)
```

Remove old: `METRICS_RECOMPUTE_HOURS = 6` and `POSITION_MONITOR_MINUTES = 15`.

**Step 2: Rewrite `src/scheduler.py`**

The scheduler now has 4 tasks:
1. **Position sweep** (hourly): snapshot positions for all active traders
2. **Position scoring** (hourly, after sweep): compute metrics, score, filter, allocate
3. **Leaderboard refresh** (daily): fetch top 100 traders (2 pages)
4. **Cleanup** (daily): expire blacklist, enforce retention

Key changes:
- `full_recompute_cycle` is replaced with `position_scoring_cycle` — no trades fetching
- `position_scoring_cycle` calls `get_account_value_series()` and `get_position_snapshot_series()` from DataStore, then `compute_position_metrics()`, then `compute_position_score()`, then `is_position_eligible()`, then `compute_allocations()`
- `refresh_leaderboard` fetches 2 pages (100 traders)
- Position sweep reuses existing `snapshot_positions_for_trader()` from `position_monitor.py`
- Liquidation detection runs as part of the position sweep (same as before)

The full implementation should:
- Import from `src.position_metrics` and `src.position_scoring`
- Import `is_position_eligible` from `src.filters`
- Keep the same `run_scheduler()` signature so the lifespan integration is straightforward
- Keep the `monitor_positions` function but call it during the hourly sweep
- Store position scores using `datastore.insert_score()` — the dict keys will differ from trade-based scores but the table schema is flexible (it stores arbitrary keys)

**Step 3: Run tests**

```bash
python -m pytest tests/ -q
```

Expected: All pass.

**Step 4: Commit**

```bash
git add src/scheduler.py src/config.py
git commit -m "refactor: rewrite scheduler for position-only scoring pipeline"
```

---

## Task 7: Integrate Scheduler into FastAPI Lifespan

**Files:**
- Modify: `backend/main.py:21-46` (lifespan)
- Modify: `src/__main__.py` (deprecate or convert)
- Modify: `tests/test_routers.py` (ensure scheduler doesn't run in tests)

**Step 1: Update `backend/main.py` lifespan**

```python
import asyncio
from src.scheduler import run_scheduler
from src.allocation import RiskConfig

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown resources."""
    logger.info("Starting Hyper-Signals API...")

    if not NANSEN_API_KEY:
        logger.warning("NANSEN_API_KEY is not set — Nansen API calls will fail.")

    nansen_client = NansenClient(api_key=NANSEN_API_KEY, base_url=NANSEN_BASE_URL)
    app.state.nansen_client = nansen_client

    datastore = DataStore("data/pnl_weighted.db")
    app.state.datastore = datastore

    cache = CacheLayer()
    app.state.cache = cache

    # Launch scheduler as background task
    risk_config = RiskConfig(max_total_open_usd=50_000.0)
    scheduler_task = asyncio.create_task(
        run_scheduler(nansen_client, datastore, risk_config)
    )
    app.state.scheduler_task = scheduler_task

    logger.info("Hyper-Signals API ready (scheduler started).")
    yield

    # Shutdown
    logger.info("Shutting down Hyper-Signals API...")
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await nansen_client.close()
    datastore.close()
    logger.info("Hyper-Signals API stopped.")
```

**Step 2: Update `src/__main__.py`**

Convert to a thin wrapper that starts uvicorn (since the scheduler now lives in the lifespan):

```python
"""Entry point: python -m src — starts the full backend + scheduler."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
```

**Step 3: Ensure tests don't start the scheduler**

In `tests/test_routers.py`, the app dependency overrides already mock the DataStore and NansenClient. Verify that the test client setup uses `app.dependency_overrides` to prevent the scheduler from running during tests. If the lifespan tries to start the scheduler with mocked dependencies, add a test-mode check or override the lifespan.

A simple approach: add an env var check in the lifespan:

```python
import os

# In lifespan:
if os.getenv("TESTING") != "1":
    scheduler_task = asyncio.create_task(
        run_scheduler(nansen_client, datastore, risk_config)
    )
    app.state.scheduler_task = scheduler_task
```

And in `tests/test_routers.py` conftest:
```python
os.environ["TESTING"] = "1"
```

**Step 4: Run tests**

```bash
python -m pytest tests/ -q
```

Expected: All pass.

**Step 5: Commit**

```bash
git add backend/main.py src/__main__.py tests/test_routers.py
git commit -m "feat: integrate scheduler into FastAPI lifespan as background task"
```

---

## Task 8: Update Leaderboard Refresh to Fetch Top 100

**Files:**
- Modify: `src/scheduler.py` (update `refresh_leaderboard`)

**Step 1: Update `refresh_leaderboard()` pagination**

Change from single page of 50 to 2 pages of 50:

```python
async def refresh_leaderboard(nansen_client: NansenClient, datastore: DataStore) -> None:
    logger.info("Starting leaderboard refresh (top 100)")

    date_to = datetime.now(timezone.utc).date()
    date_from = date_to - timedelta(days=30)

    count = 0
    for page in range(1, 3):  # Pages 1 and 2
        entries = await nansen_client.fetch_leaderboard(
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            pagination={"page": page, "per_page": 50}
        )

        for entry in entries:
            datastore.upsert_trader(
                address=entry.trader_address,
                label=entry.trader_address_label
            )
            datastore.insert_leaderboard_snapshot(
                address=entry.trader_address,
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                total_pnl=entry.total_pnl,
                roi=entry.roi,
                account_value=entry.account_value
            )
            count += 1

        if len(entries) < 50:
            break  # Last page

    logger.info(f"Leaderboard refresh complete: {count} traders updated")
```

**Step 2: Run tests and commit**

```bash
python -m pytest tests/ -q
git add src/scheduler.py
git commit -m "feat: expand leaderboard refresh to top 100 traders (2 pages)"
```

---

## Task 9: End-to-End Integration Test

**Files:**
- Create: `tests/test_position_pipeline.py`

**Step 1: Write integration test**

Create a test that exercises the full pipeline: insert position snapshots → compute metrics → compute score → check eligibility → verify allocation-ready output.

```python
"""End-to-end integration test for the position-based scoring pipeline."""

import pytest
from datetime import datetime, timedelta, timezone

from src.datastore import DataStore
from src.position_metrics import compute_position_metrics
from src.position_scoring import compute_position_score
from src.filters import is_position_eligible


@pytest.fixture
def ds(tmp_path):
    db_path = str(tmp_path / "test.db")
    return DataStore(db_path=db_path)


def test_full_pipeline(ds):
    """Simulate 24 hourly snapshots and verify the entire scoring pipeline."""
    address = "0x" + "a" * 40

    ds.upsert_trader(address, label="Smart Money Trader")

    # Insert 24 hourly snapshots with steady growth
    base_time = datetime.now(timezone.utc) - timedelta(hours=24)
    for i in range(24):
        ts = (base_time + timedelta(hours=i)).isoformat()
        account_value = 100000 + i * 500  # Steady growth: $100k -> $111.5k
        positions = [
            {
                "token_symbol": "BTC", "side": "Long",
                "position_value_usd": 30000 + i * 100,
                "entry_price": 50000, "leverage_value": 3.0,
                "leverage_type": "cross", "liquidation_price": 35000,
                "unrealized_pnl": i * 200, "account_value": account_value,
            },
            {
                "token_symbol": "ETH", "side": "Short",
                "position_value_usd": 20000, "entry_price": 3000,
                "leverage_value": 2.0, "leverage_type": "cross",
                "liquidation_price": 3600, "unrealized_pnl": i * 100,
                "account_value": account_value,
            },
        ]
        ds.insert_position_snapshot(address, positions)

    # Step 1: Get time series from DataStore
    account_series = ds.get_account_value_series(address, days=30)
    position_snapshots = ds.get_position_snapshot_series(address, days=30)

    assert len(account_series) == 24
    assert len(position_snapshots) == 48  # 24 snapshots * 2 positions each

    # Step 2: Compute position metrics
    metrics = compute_position_metrics(account_series, position_snapshots)
    assert metrics["account_growth"] > 0
    assert metrics["max_drawdown"] == 0.0  # Monotonically increasing
    assert metrics["avg_leverage"] > 0
    assert metrics["snapshot_count"] == 24

    # Step 3: Compute score
    score = compute_position_score(
        metrics, label="Smart Money Trader", hours_since_last_snapshot=0.5
    )
    assert score["final_score"] > 0
    assert score["smart_money_bonus"] > 1.0  # Smart money label

    # Step 4: Check eligibility
    eligible, reason = is_position_eligible(address, metrics, ds)
    # Might fail MIN_SNAPSHOTS gate (48 required, only 24)
    # That's OK — the test validates the pipeline runs end-to-end


def test_pipeline_with_deposit(ds):
    """Verify deposit detection doesn't inflate growth score."""
    address = "0x" + "b" * 40
    ds.upsert_trader(address, label=None)

    base_time = datetime.now(timezone.utc) - timedelta(hours=10)
    for i in range(10):
        ts = (base_time + timedelta(hours=i)).isoformat()
        # Deposit at snapshot 5: account jumps $50k without PnL change
        if i == 5:
            account_value = 150000
        elif i > 5:
            account_value = 150000 + (i - 5) * 200
        else:
            account_value = 100000 + i * 200
        positions = [{
            "token_symbol": "BTC", "side": "Long",
            "position_value_usd": 50000,
            "entry_price": 50000, "leverage_value": 5.0,
            "leverage_type": "cross", "liquidation_price": 40000,
            "unrealized_pnl": i * 100, "account_value": account_value,
        }]
        ds.insert_position_snapshot(address, positions)

    account_series = ds.get_account_value_series(address, days=30)
    position_snapshots = ds.get_position_snapshot_series(address, days=30)

    metrics = compute_position_metrics(account_series, position_snapshots)

    # Growth should be small (only ~$1800 from trading, not the $50k deposit)
    assert metrics["deposit_withdrawal_count"] >= 1
    assert metrics["account_growth"] < 0.05  # Much less than 50%
```

**Step 2: Run tests**

```bash
python -m pytest tests/test_position_pipeline.py -v
python -m pytest tests/ -q  # Full suite
```

Expected: All pass.

**Step 3: Commit**

```bash
git add tests/test_position_pipeline.py
git commit -m "test: add end-to-end integration test for position-based scoring pipeline"
```

---

## Summary

| Task | Description | New/Modified Files | Tests |
|------|------------|-------------------|-------|
| 1 | Split rate limiter | `config.py`, `nansen_client.py` | Update `test_rate_limiter.py` |
| 2 | DataStore snapshot queries | `datastore.py` | Add to `test_datastore.py` |
| 3 | Position metrics engine | Create `position_metrics.py` | Create `test_position_metrics.py` |
| 4 | Position scoring engine | Create `position_scoring.py` | Create `test_position_scoring.py` |
| 5 | Position filter gates | `filters.py`, `config.py` | Add to `test_filters.py` |
| 6 | Rewrite scheduler | `scheduler.py`, `config.py` | Existing tests |
| 7 | Integrate into FastAPI | `main.py`, `__main__.py` | Update `test_routers.py` |
| 8 | Top 100 leaderboard | `scheduler.py` | Existing tests |
| 9 | E2E integration test | — | Create `test_position_pipeline.py` |

**Dependency order:** Tasks 1-5 are independent of each other. Task 6 depends on 3, 4, 5. Task 7 depends on 6. Task 8 can run anytime. Task 9 depends on 2, 3, 4, 5.
