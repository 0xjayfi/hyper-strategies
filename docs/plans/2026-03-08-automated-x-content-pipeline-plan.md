# Automated X Content Pipeline — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an automated daily pipeline that detects interesting score movers, generates charts, and uses a 3-agent writer team to draft wallet spotlight posts pushed to Typefully.

**Architecture:** Python detection module compares daily score snapshots to find movers → chart generator renders 1-2 random chart types as PNGs → cron invokes Claude Code (`cldy`) which runs a 3-agent writer team (Drafter → CT Editor → Final Polish) → final post with charts pushed to Typefully as a draft for manual review.

**Tech Stack:** Python 3.11+, SQLite (existing datastore), matplotlib (charts), httpx (Typefully API), Claude Code CLI (`cldy`)

---

### Task 1: Add `score_snapshots` table to DataStore

**Files:**
- Modify: `src/datastore.py:57-183` (add table to `_create_tables`)
- Modify: `src/datastore.py` (add new CRUD methods after line 435)
- Test: `tests/test_content_pipeline.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_content_pipeline.py`:

```python
"""Tests for the content pipeline: score snapshots + mover detection."""

import pytest
from datetime import date
from src.datastore import DataStore


@pytest.fixture
def ds():
    with DataStore(":memory:") as store:
        yield store


class TestScoreSnapshots:

    def test_insert_and_get_snapshot(self, ds):
        ds.upsert_trader("0xAAA", label="Test Trader")
        ds.insert_score_snapshot(
            snapshot_date=date(2026, 3, 7),
            trader_id="0xAAA",
            rank=1,
            composite_score=0.80,
            growth_score=0.72,
            drawdown_score=0.99,
            leverage_score=0.85,
            liq_distance_score=1.00,
            diversity_score=0.88,
            consistency_score=0.60,
            smart_money=True,
        )
        rows = ds.get_score_snapshots_for_date(date(2026, 3, 7))
        assert len(rows) == 1
        assert rows[0]["trader_id"] == "0xAAA"
        assert rows[0]["composite_score"] == 0.80
        assert rows[0]["rank"] == 1
        assert rows[0]["smart_money"] == 1

    def test_get_snapshot_returns_empty_for_missing_date(self, ds):
        rows = ds.get_score_snapshots_for_date(date(2026, 1, 1))
        assert rows == []

    def test_multiple_traders_same_date(self, ds):
        ds.upsert_trader("0xAAA", label="Trader A")
        ds.upsert_trader("0xBBB", label="Trader B")
        for addr, rank, score in [("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65)]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7),
                trader_id=addr,
                rank=rank,
                composite_score=score,
                growth_score=0.5,
                drawdown_score=0.5,
                leverage_score=0.5,
                liq_distance_score=0.5,
                diversity_score=0.5,
                consistency_score=0.5,
                smart_money=False,
            )
        rows = ds.get_score_snapshots_for_date(date(2026, 3, 7))
        assert len(rows) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline.py::TestScoreSnapshots -v`
Expected: FAIL — `insert_score_snapshot` not found

**Step 3: Write minimal implementation**

Add to `src/datastore.py` `_create_tables` method (inside the `executescript` block, after the `position_snapshots` table):

```sql
CREATE TABLE IF NOT EXISTS score_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date       TEXT NOT NULL,
    trader_id           TEXT NOT NULL,
    rank                INTEGER NOT NULL,
    composite_score     REAL NOT NULL,
    growth_score        REAL,
    drawdown_score      REAL,
    leverage_score      REAL,
    liq_distance_score  REAL,
    diversity_score     REAL,
    consistency_score   REAL,
    smart_money         INTEGER DEFAULT 0,
    UNIQUE(snapshot_date, trader_id)
);

CREATE INDEX IF NOT EXISTS idx_score_snapshots_date
    ON score_snapshots(snapshot_date);
```

Add new methods to `DataStore` class (after the `get_latest_score_timestamp` method around line 435):

```python
# ------------------------------------------------------------------
# Score snapshots (for content pipeline)
# ------------------------------------------------------------------

def insert_score_snapshot(
    self,
    snapshot_date: "date",
    trader_id: str,
    rank: int,
    composite_score: float,
    growth_score: float,
    drawdown_score: float,
    leverage_score: float,
    liq_distance_score: float,
    diversity_score: float,
    consistency_score: float,
    smart_money: bool,
) -> None:
    """Insert or replace a daily score snapshot for a trader."""
    self._conn.execute(
        """
        INSERT OR REPLACE INTO score_snapshots
            (snapshot_date, trader_id, rank, composite_score,
             growth_score, drawdown_score, leverage_score,
             liq_distance_score, diversity_score, consistency_score,
             smart_money)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_date.isoformat(),
            trader_id,
            rank,
            composite_score,
            growth_score,
            drawdown_score,
            leverage_score,
            liq_distance_score,
            diversity_score,
            consistency_score,
            1 if smart_money else 0,
        ),
    )
    self._conn.commit()

def get_score_snapshots_for_date(self, snapshot_date: "date") -> list[dict]:
    """Return all score snapshot rows for a given date."""
    rows = self._conn.execute(
        """
        SELECT * FROM score_snapshots
         WHERE snapshot_date = ?
         ORDER BY rank ASC
        """,
        (snapshot_date.isoformat(),),
    ).fetchall()
    return [dict(r) for r in rows]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_pipeline.py::TestScoreSnapshots -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/datastore.py tests/test_content_pipeline.py
git commit -m "feat: add score_snapshots table and CRUD methods to DataStore"
```

---

### Task 2: Add snapshot job to scheduler

**Files:**
- Modify: `src/scheduler.py:111-226` (add snapshot after scoring cycle)
- Test: `tests/test_content_pipeline.py` (add new test class)

**Step 1: Write the failing test**

Add to `tests/test_content_pipeline.py`:

```python
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from src.scheduler import save_daily_score_snapshot


class TestDailyScoreSnapshot:

    def test_save_snapshot_from_scores(self, ds):
        # Set up traders with scores
        ds.upsert_trader("0xAAA", label="Smart Trader")
        ds.upsert_trader("0xBBB", label="Regular")

        # Insert scores (simulating what position_scoring_cycle produces)
        ds.insert_score("0xAAA", {
            "normalized_roi": 0.72,
            "normalized_sharpe": 0.99,
            "normalized_win_rate": 0.85,
            "consistency_score": 0.60,
            "smart_money_bonus": 1.08,
            "risk_management_score": 1.00,
            "style_multiplier": 0.88,
            "recency_decay": 1.0,
            "raw_composite_score": 0.80,
            "final_score": 0.80,
            "roi_tier_multiplier": 1.0,
            "passes_anti_luck": 1,
        })
        ds.insert_score("0xBBB", {
            "normalized_roi": 0.50,
            "normalized_sharpe": 0.60,
            "normalized_win_rate": 0.70,
            "consistency_score": 0.40,
            "smart_money_bonus": 1.0,
            "risk_management_score": 0.80,
            "style_multiplier": 0.50,
            "recency_decay": 0.90,
            "raw_composite_score": 0.55,
            "final_score": 0.55,
            "roi_tier_multiplier": 1.0,
            "passes_anti_luck": 1,
        })

        today = date(2026, 3, 8)
        save_daily_score_snapshot(ds, today)

        rows = ds.get_score_snapshots_for_date(today)
        assert len(rows) == 2
        # 0xAAA should be rank 1 (higher score)
        assert rows[0]["trader_id"] == "0xAAA"
        assert rows[0]["rank"] == 1
        assert rows[0]["composite_score"] == 0.80
        # 0xBBB should be rank 2
        assert rows[1]["trader_id"] == "0xBBB"
        assert rows[1]["rank"] == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline.py::TestDailyScoreSnapshot -v`
Expected: FAIL — `save_daily_score_snapshot` not found

**Step 3: Write minimal implementation**

Add to `src/scheduler.py` (after the `_map_score_to_db_schema` function, before `run_scheduler`):

```python
def save_daily_score_snapshot(datastore: DataStore, snapshot_date=None) -> None:
    """Save a daily snapshot of all trader scores for content pipeline comparison.

    Reads the latest scores from trader_scores, ranks them by final_score,
    and stores one row per trader in score_snapshots.
    """
    from datetime import date as _date

    if snapshot_date is None:
        snapshot_date = datetime.now(timezone.utc).date()

    scores = datastore.get_latest_scores()
    if not scores:
        logger.info("No scores to snapshot")
        return

    # Rank by final_score descending
    ranked = sorted(scores.items(), key=lambda x: x[1]["final_score"], reverse=True)

    for rank, (address, score_data) in enumerate(ranked, start=1):
        label = datastore.get_trader_label(address)
        is_smart = bool(
            label and ("smart" in label.lower() or "fund" in label.lower())
        )

        datastore.insert_score_snapshot(
            snapshot_date=snapshot_date,
            trader_id=address,
            rank=rank,
            composite_score=score_data["final_score"],
            growth_score=score_data.get("normalized_roi", 0.0),
            drawdown_score=score_data.get("normalized_sharpe", 0.0),
            leverage_score=score_data.get("normalized_win_rate", 0.0),
            liq_distance_score=score_data.get("risk_management_score", 0.0),
            diversity_score=score_data.get("style_multiplier", 0.0),
            consistency_score=score_data.get("consistency_score", 0.0),
            smart_money=is_smart,
        )

    logger.info("Saved daily score snapshot: %d traders for %s", len(ranked), snapshot_date)
```

Also add the snapshot call in `run_scheduler`, inside the daily leaderboard refresh block (after `refresh_leaderboard` succeeds, around line 367):

```python
# Daily score snapshot for content pipeline
try:
    save_daily_score_snapshot(datastore)
except Exception as e:
    logger.error(f"Daily score snapshot failed: {e}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_pipeline.py::TestDailyScoreSnapshot -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/scheduler.py tests/test_content_pipeline.py
git commit -m "feat: add daily score snapshot job to scheduler"
```

---

### Task 3: Build content detection module

**Files:**
- Create: `src/content_pipeline.py`
- Test: `tests/test_content_pipeline.py` (add new test class)

**Step 1: Write the failing test**

Add to `tests/test_content_pipeline.py`:

```python
from src.content_pipeline import detect_score_movers, generate_content_payload


class TestDetectScoreMovers:

    def _seed_two_days(self, ds):
        """Seed snapshots for day1 and day2 with a rank change."""
        ds.upsert_trader("0xAAA", label="Smart Trader")
        ds.upsert_trader("0xBBB", label="Token Millionaire")
        ds.upsert_trader("0xCCC", label="Whale")

        # Day 1: AAA=#1, BBB=#2, CCC=#3
        for addr, rank, score in [
            ("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65), ("0xCCC", 3, 0.50),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7),
                trader_id=addr, rank=rank, composite_score=score,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        # Day 2: BBB jumped to #1, AAA dropped to #3
        for addr, rank, score, growth in [
            ("0xBBB", 1, 0.85, 0.90),
            ("0xCCC", 2, 0.70, 0.60),
            ("0xAAA", 3, 0.55, 0.30),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 8),
                trader_id=addr, rank=rank, composite_score=score,
                growth_score=growth, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

    def test_detects_rank_mover(self, ds):
        self._seed_two_days(ds)
        movers = detect_score_movers(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        # BBB moved from rank 2 to rank 1 (+1), AAA moved from 1 to 3 (-2)
        assert len(movers) >= 1
        addresses = [m["address"] for m in movers]
        # AAA had 2-rank drop so should be detected
        assert "0xAAA" in addresses

    def test_detects_score_delta_mover(self, ds):
        self._seed_two_days(ds)
        movers = detect_score_movers(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
            min_score_delta=0.10,
        )
        addresses = [m["address"] for m in movers]
        # BBB went 0.65 -> 0.85 (+0.20), AAA went 0.80 -> 0.55 (-0.25)
        assert "0xBBB" in addresses
        assert "0xAAA" in addresses

    def test_no_movers_when_stable(self, ds):
        ds.upsert_trader("0xAAA", label="Stable")
        for d in [date(2026, 3, 7), date(2026, 3, 8)]:
            ds.insert_score_snapshot(
                snapshot_date=d, trader_id="0xAAA", rank=1,
                composite_score=0.80,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )
        movers = detect_score_movers(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert movers == []


class TestGenerateContentPayload:

    def test_generates_payload_for_top_mover(self, ds):
        ds.upsert_trader("0xBBB", label="Token Millionaire")
        ds.upsert_trader("0xAAA", label="Smart Trader")
        # Day 1
        for addr, rank, score in [("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65)]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money="smart" in (ds.get_trader_label(addr) or "").lower(),
            )
        # Day 2: BBB jumps to #1
        for addr, rank, score in [("0xBBB", 1, 0.85), ("0xAAA", 2, 0.55)]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 8), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=0.9, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        payload = generate_content_payload(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert payload["post_worthy"] is True
        assert payload["wallet"]["address"] in ("0xBBB", "0xAAA")
        assert "change" in payload
        assert "top_movers" in payload
        assert "context" in payload

    def test_not_post_worthy_when_no_movers(self, ds):
        ds.upsert_trader("0xAAA", label="Stable")
        for d in [date(2026, 3, 7), date(2026, 3, 8)]:
            ds.insert_score_snapshot(
                snapshot_date=d, trader_id="0xAAA", rank=1,
                composite_score=0.80,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )
        payload = generate_content_payload(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert payload["post_worthy"] is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline.py::TestDetectScoreMovers tests/test_content_pipeline.py::TestGenerateContentPayload -v`
Expected: FAIL — module `src.content_pipeline` not found

**Step 3: Write minimal implementation**

Create `src/content_pipeline.py`:

```python
"""Content Pipeline — Score mover detection and payload generation.

Compares daily score snapshots to detect interesting rank/score changes,
then generates a JSON payload for the writer agent team.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.datastore import DataStore
from src.config import (
    CONTENT_MIN_RANK_CHANGE,
    CONTENT_MIN_SCORE_DELTA,
    CONTENT_TOP_N,
)

logger = logging.getLogger(__name__)


def detect_score_movers(
    datastore: DataStore,
    today: date | None = None,
    yesterday: date | None = None,
    min_rank_change: int | None = None,
    min_score_delta: float | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """Detect wallets with significant rank or score changes between two days.

    Returns a list of mover dicts sorted by combined change magnitude (largest first).
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if yesterday is None:
        yesterday = today - timedelta(days=1)
    if min_rank_change is None:
        min_rank_change = CONTENT_MIN_RANK_CHANGE
    if min_score_delta is None:
        min_score_delta = CONTENT_MIN_SCORE_DELTA
    if top_n is None:
        top_n = CONTENT_TOP_N

    today_rows = datastore.get_score_snapshots_for_date(today)
    yesterday_rows = datastore.get_score_snapshots_for_date(yesterday)

    if not today_rows or not yesterday_rows:
        logger.info("Missing snapshot data for comparison (today=%s, yesterday=%s)", today, yesterday)
        return []

    yesterday_map = {r["trader_id"]: r for r in yesterday_rows}

    movers = []
    for row in today_rows:
        addr = row["trader_id"]
        if addr not in yesterday_map:
            # New entrant to top N — always interesting
            if row["rank"] <= top_n:
                movers.append({
                    "address": addr,
                    "old_rank": None,
                    "new_rank": row["rank"],
                    "rank_delta": None,
                    "old_score": None,
                    "new_score": row["composite_score"],
                    "score_delta": None,
                    "new_entrant": True,
                    "today": row,
                    "yesterday": None,
                })
            continue

        prev = yesterday_map[addr]
        rank_delta = prev["rank"] - row["rank"]  # positive = improved
        score_delta = row["composite_score"] - prev["composite_score"]

        is_rank_mover = abs(rank_delta) >= min_rank_change
        is_score_mover = abs(score_delta) >= min_score_delta

        # Entry/exit top N
        entered_top_n = row["rank"] <= top_n and prev["rank"] > top_n
        exited_top_n = row["rank"] > top_n and prev["rank"] <= top_n

        if is_rank_mover or is_score_mover or entered_top_n or exited_top_n:
            movers.append({
                "address": addr,
                "old_rank": prev["rank"],
                "new_rank": row["rank"],
                "rank_delta": rank_delta,
                "old_score": prev["composite_score"],
                "new_score": row["composite_score"],
                "score_delta": score_delta,
                "new_entrant": False,
                "today": row,
                "yesterday": prev,
            })

    # Sort by combined magnitude: |rank_delta| + |score_delta| * 10
    def sort_key(m):
        rd = abs(m["rank_delta"] or 0)
        sd = abs(m["score_delta"] or 0)
        return rd + sd * 10

    movers.sort(key=sort_key, reverse=True)
    return movers


def _compute_top_dimension_movers(today_row: dict, yesterday_row: dict | None) -> list[dict]:
    """Find the 2-3 dimensions that changed most between days."""
    if yesterday_row is None:
        return []

    dimensions = [
        ("growth", "growth_score"),
        ("drawdown", "drawdown_score"),
        ("leverage", "leverage_score"),
        ("liq_distance", "liq_distance_score"),
        ("diversity", "diversity_score"),
        ("consistency", "consistency_score"),
    ]

    deltas = []
    for name, col in dimensions:
        old_val = yesterday_row.get(col, 0.0) or 0.0
        new_val = today_row.get(col, 0.0) or 0.0
        delta = new_val - old_val
        if abs(delta) > 0.001:
            deltas.append({"dimension": name, "delta": round(delta, 4)})

    deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return deltas[:3]


def generate_content_payload(
    datastore: DataStore,
    today: date | None = None,
    yesterday: date | None = None,
) -> dict:
    """Generate the content payload JSON for the writer agent team.

    Returns a dict with `post_worthy: True/False` and the full signal data.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if yesterday is None:
        yesterday = today - timedelta(days=1)

    movers = detect_score_movers(datastore, today=today, yesterday=yesterday)

    if not movers:
        return {"post_worthy": False, "snapshot_date": today.isoformat()}

    # Pick the most interesting mover (first after sorting)
    top_mover = movers[0]
    top_dimension_movers = _compute_top_dimension_movers(
        top_mover["today"], top_mover.get("yesterday"),
    )

    # Build context: current top 5
    today_rows = datastore.get_score_snapshots_for_date(today)
    top_5 = [
        {
            "address": r["trader_id"],
            "label": datastore.get_trader_label(r["trader_id"]),
            "score": r["composite_score"],
            "rank": r["rank"],
            "smart_money": bool(r.get("smart_money")),
        }
        for r in today_rows[:5]
    ]

    # Build dimension snapshots
    current_dims = {}
    previous_dims = {}
    for name, col in [
        ("growth", "growth_score"), ("drawdown", "drawdown_score"),
        ("leverage", "leverage_score"), ("liq_distance", "liq_distance_score"),
        ("diversity", "diversity_score"), ("consistency", "consistency_score"),
    ]:
        current_dims[name] = top_mover["today"].get(col, 0.0) or 0.0
        if top_mover.get("yesterday"):
            previous_dims[name] = top_mover["yesterday"].get(col, 0.0) or 0.0

    label = datastore.get_trader_label(top_mover["address"])

    return {
        "post_worthy": True,
        "snapshot_date": today.isoformat(),
        "wallet": {
            "address": top_mover["address"],
            "label": label,
            "smart_money": bool(top_mover["today"].get("smart_money")),
        },
        "change": {
            "old_rank": top_mover["old_rank"],
            "new_rank": top_mover["new_rank"],
            "rank_delta": top_mover["rank_delta"],
            "old_score": top_mover["old_score"],
            "new_score": top_mover["new_score"],
            "score_delta": top_mover["score_delta"],
            "new_entrant": top_mover["new_entrant"],
        },
        "current_dimensions": current_dims,
        "previous_dimensions": previous_dims,
        "top_movers": top_dimension_movers,
        "context": {
            "top_5_wallets": top_5,
        },
    }


def run_content_pipeline(db_path: str = "data/pnl_weighted.db") -> bool:
    """Main entry point. Detect movers, write payload to data/content_payload.json.

    Returns True if a post-worthy payload was generated.
    """
    datastore = DataStore(db_path)
    try:
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        payload = generate_content_payload(datastore, today=today, yesterday=yesterday)

        output_dir = Path("data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "content_payload.json"

        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2)

        logger.info("Content payload written to %s (post_worthy=%s)", output_path, payload["post_worthy"])
        return payload["post_worthy"]

    finally:
        datastore.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    result = run_content_pipeline()
    sys.exit(0 if result else 1)
```

**Step 4: Add config constants**

Add to `src/config.py` (at the end):

```python
# ---------------------------------------------------------------------------
# Content pipeline
# ---------------------------------------------------------------------------

CONTENT_MIN_RANK_CHANGE = 2       # Minimum rank positions moved to trigger
CONTENT_MIN_SCORE_DELTA = 0.10    # Minimum composite score change to trigger
CONTENT_TOP_N = 5                 # Track entry/exit from top N
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_content_pipeline.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/content_pipeline.py src/config.py tests/test_content_pipeline.py
git commit -m "feat: add content pipeline with score mover detection"
```

---

### Task 4: Build Typefully client

**Files:**
- Create: `src/typefully_client.py`
- Test: `tests/test_typefully_client.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_typefully_client.py`:

```python
"""Tests for the Typefully API client (mocked HTTP)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.typefully_client import TypefullyClient


@pytest.fixture
def client():
    return TypefullyClient(api_key="test-key", social_set_id=123)


class TestTypefullyClient:

    def test_build_draft_payload_single_tweet(self, client):
        payload = client._build_draft_payload(
            posts=["Hello world"],
            title="Test Draft",
        )
        assert payload["platforms"]["x"]["enabled"] is True
        assert len(payload["platforms"]["x"]["posts"]) == 1
        assert payload["platforms"]["x"]["posts"][0]["text"] == "Hello world"
        assert payload["draft_title"] == "Test Draft"

    def test_build_draft_payload_thread(self, client):
        payload = client._build_draft_payload(
            posts=["Tweet 1", "Tweet 2", "Tweet 3"],
            title="Thread",
        )
        assert len(payload["platforms"]["x"]["posts"]) == 3

    def test_build_draft_payload_with_media(self, client):
        payload = client._build_draft_payload(
            posts=["Check this chart"],
            title="Chart Post",
            media_ids=["uuid-1234"],
        )
        assert payload["platforms"]["x"]["posts"][0]["media"] == ["uuid-1234"]

    @pytest.mark.asyncio
    async def test_create_draft_calls_api(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 99,
            "status": "draft",
            "private_url": "https://typefully.com/draft/abc",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.create_draft(
                posts=["Test post"],
                title="Test",
            )
        assert result["id"] == 99
        assert result["private_url"] == "https://typefully.com/draft/abc"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_typefully_client.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

Create `src/typefully_client.py`:

```python
"""Typefully API v2 client for creating X drafts with media.

Usage::

    client = TypefullyClient(api_key="...", social_set_id=123)
    result = await client.create_draft(
        posts=["Tweet 1", "Tweet 2"],
        title="My Thread",
        media_ids=["uuid-1234"],
    )
    print(result["private_url"])
    await client.close()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.typefully.com/v2"


class TypefullyClient:
    """Async client for Typefully API v2."""

    def __init__(self, api_key: str, social_set_id: int) -> None:
        self._api_key = api_key
        self._social_set_id = social_set_id
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    def _build_draft_payload(
        self,
        posts: list[str],
        title: str = "",
        media_ids: Optional[list[str]] = None,
    ) -> dict:
        """Build the JSON payload for creating a draft."""
        x_posts = []
        for i, text in enumerate(posts):
            post = {"text": text}
            # Attach media to first post only (if provided)
            if i == 0 and media_ids:
                post["media"] = media_ids
            x_posts.append(post)

        payload = {
            "platforms": {
                "x": {
                    "enabled": True,
                    "posts": x_posts,
                }
            },
        }
        if title:
            payload["draft_title"] = title

        return payload

    async def upload_media(self, file_path: str) -> str:
        """Upload a media file and return its media_id.

        Two-step process:
        1. Get presigned upload URL from Typefully
        2. PUT the file to S3
        """
        path = Path(file_path)
        resp = await self._http.post(
            f"/social-sets/{self._social_set_id}/media/upload",
            json={"file_name": path.name},
        )
        resp.raise_for_status()
        data = resp.json()
        media_id = data["media_id"]
        upload_url = data["upload_url"]

        # Upload to S3
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
        }
        content_type = mime_types.get(path.suffix.lower(), "application/octet-stream")

        async with httpx.AsyncClient(timeout=60.0) as s3_client:
            with open(file_path, "rb") as f:
                s3_resp = await s3_client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": content_type},
                )
                s3_resp.raise_for_status()

        logger.info("Uploaded media %s -> %s", path.name, media_id)
        return media_id

    async def get_media_status(self, media_id: str) -> str:
        """Check media processing status. Returns 'ready', 'processing', or 'error'."""
        resp = await self._http.get(
            f"/social-sets/{self._social_set_id}/media/{media_id}"
        )
        resp.raise_for_status()
        return resp.json()["status"]

    async def create_draft(
        self,
        posts: list[str],
        title: str = "",
        media_ids: Optional[list[str]] = None,
    ) -> dict:
        """Create a Typefully draft. Returns the draft response dict."""
        payload = self._build_draft_payload(posts, title, media_ids)
        resp = await self._http.post(
            f"/social-sets/{self._social_set_id}/drafts",
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "Created Typefully draft #%s: %s",
            result.get("id"),
            result.get("private_url"),
        )
        return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_typefully_client.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/typefully_client.py tests/test_typefully_client.py
git commit -m "feat: add Typefully API client for draft creation and media upload"
```

---

### Task 5: Build chart generator

**Files:**
- Create: `src/chart_generator.py`
- Test: `tests/test_chart_generator.py` (new file)

**Step 1: Add matplotlib to dependencies**

Edit `pyproject.toml` — add `"matplotlib>=3.8"` to the `dependencies` list.

**Step 2: Write the failing test**

Create `tests/test_chart_generator.py`:

```python
"""Tests for chart generation."""

import json
import pytest
from pathlib import Path
from src.chart_generator import generate_charts, CHART_TYPES


@pytest.fixture
def sample_payload():
    return {
        "post_worthy": True,
        "snapshot_date": "2026-03-08",
        "wallet": {
            "address": "0xBBB",
            "label": "Token Millionaire",
            "smart_money": True,
        },
        "change": {
            "old_rank": 5,
            "new_rank": 2,
            "rank_delta": 3,
            "old_score": 0.65,
            "new_score": 0.78,
            "score_delta": 0.13,
            "new_entrant": False,
        },
        "current_dimensions": {
            "growth": 0.72,
            "drawdown": 0.99,
            "leverage": 0.85,
            "liq_distance": 1.00,
            "diversity": 0.88,
            "consistency": 0.60,
        },
        "previous_dimensions": {
            "growth": 0.55,
            "drawdown": 0.92,
            "leverage": 0.80,
            "liq_distance": 0.95,
            "diversity": 0.88,
            "consistency": 0.60,
        },
        "top_movers": [
            {"dimension": "growth", "delta": 0.17},
            {"dimension": "drawdown", "delta": 0.07},
        ],
        "context": {
            "top_5_wallets": [
                {"address": "0xAAA", "label": "Smart Trader", "score": 0.80, "rank": 1, "smart_money": True},
                {"address": "0xBBB", "label": "Token Millionaire", "score": 0.78, "rank": 2, "smart_money": True},
                {"address": "0xCCC", "label": "Whale", "score": 0.70, "rank": 3, "smart_money": False},
                {"address": "0xDDD", "label": "Yield Farmer", "score": 0.65, "rank": 4, "smart_money": True},
                {"address": "0xEEE", "label": "Degen", "score": 0.50, "rank": 5, "smart_money": False},
            ],
        },
    }


class TestChartGenerator:

    def test_generates_png_files(self, sample_payload, tmp_path):
        chart_paths = generate_charts(sample_payload, output_dir=str(tmp_path), count=1)
        assert len(chart_paths) >= 1
        for p in chart_paths:
            path = Path(p)
            assert path.exists()
            assert path.suffix == ".png"
            assert path.stat().st_size > 0

    def test_generates_up_to_count(self, sample_payload, tmp_path):
        chart_paths = generate_charts(sample_payload, output_dir=str(tmp_path), count=2)
        assert len(chart_paths) <= 2

    def test_all_chart_types_callable(self, sample_payload, tmp_path):
        """Each chart type function runs without error."""
        for chart_type, func in CHART_TYPES.items():
            out = tmp_path / f"test_{chart_type}.png"
            func(sample_payload, str(out))
            assert out.exists()
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/test_chart_generator.py -v`
Expected: FAIL — module not found

**Step 4: Write minimal implementation**

Create `src/chart_generator.py`:

```python
"""Chart Generator — Visually varied chart images for X posts.

Generates 1-2 random chart types from the content payload.
All charts use a consistent dark theme.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)

# --- Dark theme defaults ---

DARK_BG = "#0d1117"
CARD_BG = "#161b22"
TEXT_COLOR = "#e6edf3"
ACCENT = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_RED = "#f85149"
ACCENT_YELLOW = "#d29922"
GRID_COLOR = "#21262d"

plt.rcParams.update({
    "figure.facecolor": DARK_BG,
    "axes.facecolor": CARD_BG,
    "axes.edgecolor": GRID_COLOR,
    "axes.labelcolor": TEXT_COLOR,
    "text.color": TEXT_COLOR,
    "xtick.color": TEXT_COLOR,
    "ytick.color": TEXT_COLOR,
    "grid.color": GRID_COLOR,
    "font.size": 11,
})


def _shorten_label(label: str | None, max_len: int = 14) -> str:
    if not label:
        return "Unknown"
    return label if len(label) <= max_len else label[:max_len - 2] + ".."


def chart_radar(payload: dict, output_path: str) -> None:
    """Radar/spider chart showing 6 dimensions for the spotlight wallet."""
    dims = payload["current_dimensions"]
    categories = list(dims.keys())
    values = [dims[c] for c in categories]

    # Close the polygon
    values += values[:1]
    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.set_facecolor(CARD_BG)
    ax.fill(angles, values, color=ACCENT, alpha=0.25)
    ax.plot(angles, values, color=ACCENT, linewidth=2)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([c.replace("_", " ").title() for c in categories], size=10)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], size=8, color=TEXT_COLOR)
    ax.grid(True, color=GRID_COLOR, alpha=0.5)

    wallet_label = _shorten_label(payload["wallet"].get("label"))
    score = payload["change"]["new_score"]
    ax.set_title(f"{wallet_label}  |  Score: {score:.2f}", pad=20, fontsize=14, fontweight="bold")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)


def chart_before_after_bars(payload: dict, output_path: str) -> None:
    """Before/after bar chart for top 5 wallets, spotlight highlighted."""
    wallets = payload["context"]["top_5_wallets"]
    spotlight = payload["wallet"]["address"]

    labels = [_shorten_label(w.get("label")) for w in wallets]
    scores = [w["score"] for w in wallets]

    colors = [ACCENT_GREEN if w["address"] == spotlight else ACCENT for w in wallets]

    fig, ax = plt.subplots(figsize=(8, 5))
    y_pos = range(len(labels))
    ax.barh(y_pos, scores, color=colors, height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Composite Score")
    ax.invert_yaxis()

    for i, v in enumerate(scores):
        ax.text(v + 0.02, i, f"{v:.2f}", va="center", fontsize=10, color=TEXT_COLOR)

    ax.set_title("Top 5 Trader Rankings", fontsize=14, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)


def chart_heatmap(payload: dict, output_path: str) -> None:
    """Score heatmap — top 5 wallets x 6 dimensions."""
    wallets = payload["context"]["top_5_wallets"]
    dims = ["growth", "drawdown", "leverage", "liq_distance", "diversity", "consistency"]
    spotlight_addr = payload["wallet"]["address"]

    # Use current dimensions for spotlight, mock others with their composite score
    labels = []
    data = []
    for w in wallets:
        labels.append(_shorten_label(w.get("label")))
        if w["address"] == spotlight_addr:
            row = [payload["current_dimensions"].get(d, 0.5) for d in dims]
        else:
            # Approximate: spread the composite score across dimensions
            base = w["score"]
            row = [base + random.uniform(-0.1, 0.1) for _ in dims]
            row = [max(0, min(1, v)) for v in row]
        data.append(row)

    data_arr = np.array(data)

    fig, ax = plt.subplots(figsize=(9, 4))
    im = ax.imshow(data_arr, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(dims)))
    ax.set_xticklabels([d.replace("_", " ").title() for d in dims], fontsize=10)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=10)

    # Annotate cells
    for i in range(len(labels)):
        for j in range(len(dims)):
            val = data_arr[i, j]
            color = "black" if val > 0.6 else "white"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=9, color=color)

    ax.set_title("Trader Dimension Heatmap", fontsize=14, fontweight="bold")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Score")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)


def chart_dimension_delta(payload: dict, output_path: str) -> None:
    """Horizontal bars showing which dimensions changed most."""
    current = payload.get("current_dimensions", {})
    previous = payload.get("previous_dimensions", {})

    if not previous:
        # Fallback: just show current dimensions as bars
        chart_radar(payload, output_path)
        return

    dims = list(current.keys())
    deltas = [current.get(d, 0) - previous.get(d, 0) for d in dims]

    colors = [ACCENT_GREEN if d >= 0 else ACCENT_RED for d in deltas]

    fig, ax = plt.subplots(figsize=(8, 5))
    y_pos = range(len(dims))
    ax.barh(y_pos, deltas, color=colors, height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([d.replace("_", " ").title() for d in dims])
    ax.axvline(x=0, color=TEXT_COLOR, linewidth=0.8)
    ax.set_xlabel("Score Change")

    for i, v in enumerate(deltas):
        x_pos = v + 0.005 if v >= 0 else v - 0.005
        ha = "left" if v >= 0 else "right"
        ax.text(x_pos, i, f"{v:+.2f}", va="center", ha=ha, fontsize=10, color=TEXT_COLOR)

    wallet_label = _shorten_label(payload["wallet"].get("label"))
    ax.set_title(f"{wallet_label} — Dimension Changes", fontsize=14, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)


def chart_rank_comparison(payload: dict, output_path: str) -> None:
    """Visual comparison of old rank vs new rank for the spotlight wallet."""
    change = payload["change"]
    wallet_label = _shorten_label(payload["wallet"].get("label"))

    fig, ax = plt.subplots(figsize=(7, 4))

    categories = ["Score", "Rank"]
    old_vals = [change.get("old_score") or 0, change.get("old_rank") or 0]
    new_vals = [change.get("new_score") or 0, change.get("new_rank") or 0]

    x = np.arange(len(categories))
    width = 0.3

    # For score: higher is better. For rank: lower is better
    ax.bar(x[0] - width/2, old_vals[0], width, label="Yesterday", color=ACCENT, alpha=0.6)
    ax.bar(x[0] + width/2, new_vals[0], width, label="Today", color=ACCENT_GREEN)

    ax2 = ax.twinx()
    ax2.bar(x[1] - width/2, old_vals[1], width, color=ACCENT, alpha=0.6)
    ax2.bar(x[1] + width/2, new_vals[1], width, color=ACCENT_GREEN)
    ax2.invert_yaxis()
    ax2.set_ylabel("Rank (lower = better)")

    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.set_ylabel("Score")
    ax.legend(loc="upper left")
    ax.set_title(f"{wallet_label} — Yesterday vs Today", fontsize=14, fontweight="bold")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)


# --- Chart type registry ---

CHART_TYPES = {
    "radar": chart_radar,
    "before_after_bars": chart_before_after_bars,
    "heatmap": chart_heatmap,
    "dimension_delta": chart_dimension_delta,
    "rank_comparison": chart_rank_comparison,
}


def generate_charts(
    payload: dict,
    output_dir: str = "data/charts",
    count: int = 2,
) -> list[str]:
    """Generate 1-2 random chart types from the payload.

    Returns list of file paths to generated PNGs.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    available = list(CHART_TYPES.keys())
    selected = random.sample(available, min(count, len(available)))

    paths = []
    for chart_type in selected:
        output_path = str(out / f"{chart_type}.png")
        try:
            CHART_TYPES[chart_type](payload, output_path)
            paths.append(output_path)
            logger.info("Generated chart: %s", output_path)
        except Exception as e:
            logger.error("Failed to generate %s chart: %s", chart_type, e)

    return paths


if __name__ == "__main__":
    import json
    import sys
    logging.basicConfig(level=logging.INFO)

    payload_path = sys.argv[1] if len(sys.argv) > 1 else "data/content_payload.json"
    with open(payload_path) as f:
        payload = json.load(f)

    if not payload.get("post_worthy"):
        print("Payload not post-worthy, skipping chart generation")
        sys.exit(1)

    paths = generate_charts(payload)
    print(f"Generated {len(paths)} charts: {paths}")
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_chart_generator.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/chart_generator.py tests/test_chart_generator.py pyproject.toml
git commit -m "feat: add chart generator with 5 dark-themed chart types"
```

---

### Task 6: Write the content prompt file

**Files:**
- Create: `scripts/content-prompt.md`

**Step 1: Write the prompt file**

Create `scripts/content-prompt.md`:

````markdown
# Automated Wallet Spotlight — Writer Agent Team

You are running an automated content pipeline. Your job is to generate a wallet spotlight post for X (Twitter) and push it to Typefully as a draft.

## Step 1: Load context

Read these files:
- `data/content_payload.json` — the signal data (wallet, score change, dimensions)
- `x_writer/writing_style.md` — voice rules (DO's and DON'Ts)
- `x_writer/studied_x_writiing_styles.md` — Cryptor reference posts (the target voice)
- `x_writer/review_notes.md` — editorial pitfalls from previous review

## Step 2: Pick a random style variation

From writing_style.md, randomly select ONE of these 8 styles:
1. Lead with a hot take, back it up with data
2. Start with a surprising number, then explain context
3. Narrative style — tell the story of what changed on-chain
4. Conversational — "been watching X and here's what I see"
5. Contrarian — "everyone's talking about Y but look at Z on-chain"
6. Question hook — "why is smart money doing X when price is doing Y?"
7. Casual observation — "gm. spotted something interesting on-chain"
8. Direct analysis — clean, no fluff, just the signal

## Step 3: Run the writer agent team

### Agent 1: Drafter
Launch a subagent with this prompt:
> You are a CT (Crypto Twitter) content writer. Read data/content_payload.json, x_writer/writing_style.md, x_writer/studied_x_writiing_styles.md, and x_writer/review_notes.md.
>
> Write a wallet spotlight post (1-3 tweets) using style variation #{picked_number}.
>
> Rules:
> - Pure data analysis. No product mentions. No "I built" or "my system."
> - Lead with the interesting change, explain with 2-3 dimensions that moved
> - Interpret the data — what does it SIGNAL? (accumulation, risk discipline, conviction, etc.)
> - Use concrete numbers from the payload
> - Follow every rule in writing_style.md
> - Each tweet MUST be under 280 characters
>
> Also note which chart files from data/charts/ should attach to which tweet.
>
> Output ONLY the tweet text and chart placements as JSON:
> ```json
> {"tweets": [{"text": "...", "chart": "filename.png or null"}], "style_used": "..."}
> ```

### Agent 2: CT Editor
Launch a subagent with this prompt:
> You are a senior CT content editor. Read the draft from Agent 1, plus x_writer/writing_style.md, x_writer/studied_x_writiing_styles.md, and x_writer/review_notes.md.
>
> Review checklist:
> - Does it sound like a real trader, not a product pitch?
> - Any em dashes (-- or —)? Remove them. Hard rule.
> - Any banned phrases ("Let's dive in", "Here's what you need to know", "BREAKING")?
> - Are numbers interpreted with a take, not just listed?
> - Each tweet under 280 characters?
> - Does it follow the chosen style variation consistently?
> - Would Cryptor post this? If not, what's off?
>
> Rewrite any problem areas. Output the improved version in the same JSON format.

### Agent 3: Final Polish
Launch a subagent with this prompt:
> You are doing a final vibe check. Read x_writer/studied_x_writiing_styles.md ONLY (the Cryptor reference posts).
>
> Read the draft from Agent 2. Does this feel like it belongs in Cryptor's feed?
> Check: sentence rhythm, tone, CT lingo, punchiness.
> Make final tweaks. Small adjustments only — don't rewrite.
>
> Output the final version in the same JSON format.

## Step 4: Push to Typefully

After Agent 3 finishes:

1. List PNG files in `data/charts/`
2. For each chart that the final draft references, upload it:
   ```bash
   python -c "
   import asyncio
   from src.typefully_client import TypefullyClient
   import os
   client = TypefullyClient(
       api_key=os.environ['TYPEFULLY_API_KEY'],
       social_set_id=int(os.environ['TYPEFULLY_SOCIAL_SET_ID']),
   )
   media_id = asyncio.run(client.upload_media('data/charts/FILENAME.png'))
   print(media_id)
   asyncio.run(client.close())
   "
   ```
3. Create the draft with media:
   ```bash
   python -c "
   import asyncio, json, os
   from src.typefully_client import TypefullyClient
   client = TypefullyClient(
       api_key=os.environ['TYPEFULLY_API_KEY'],
       social_set_id=int(os.environ['TYPEFULLY_SOCIAL_SET_ID']),
   )
   result = asyncio.run(client.create_draft(
       posts=FINAL_TWEETS_LIST,
       title='Wallet Spotlight — DATE',
       media_ids=MEDIA_IDS_LIST,
   ))
   print(json.dumps(result, indent=2))
   asyncio.run(client.close())
   "
   ```
4. Print the draft URL to confirm success.
````

**Step 2: Commit**

```bash
git add scripts/content-prompt.md
git commit -m "feat: add content prompt file for writer agent team"
```

---

### Task 7: Update .env.example and config

**Files:**
- Modify: `.env.example`
- Already modified: `src/config.py` (done in Task 3)

**Step 1: Update .env.example**

Add to `.env.example`:

```env
# Typefully API Configuration
TYPEFULLY_API_KEY=your_typefully_api_key_here
TYPEFULLY_SOCIAL_SET_ID=your_social_set_id_here
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "chore: add Typefully env vars to .env.example"
```

---

### Task 8: Wire up the cron entry

**Files:**
- Create: `scripts/run-content-pipeline.sh`

**Step 1: Create the runner script**

Create `scripts/run-content-pipeline.sh`:

```bash
#!/usr/bin/env bash
# Automated X Content Pipeline — Daily cron runner
# Crontab entry:
#   0 8 * * *  /home/jsong407/hyper-strategies-pnl-weighted/scripts/run-content-pipeline.sh >> /home/jsong407/hyper-strategies-pnl-weighted/logs/content-pipeline.log 2>&1

set -euo pipefail

cd /home/jsong407/hyper-strategies-pnl-weighted

# Load environment
set -a
source .env
set +a

echo "[$(date -u)] Starting content pipeline"

# Step 1: Detect score movers
python -m src.content_pipeline
if [ $? -ne 0 ]; then
    echo "[$(date -u)] No post-worthy content found. Done."
    exit 0
fi

# Step 2: Verify payload is post-worthy
if ! grep -q '"post_worthy": true' data/content_payload.json; then
    echo "[$(date -u)] Payload not post-worthy. Done."
    exit 0
fi

echo "[$(date -u)] Post-worthy content detected. Generating charts..."

# Step 3: Generate charts
python -m src.chart_generator

echo "[$(date -u)] Charts generated. Launching Claude Code writer team..."

# Step 4: Launch Claude Code to write and push to Typefully
cldy -p scripts/content-prompt.md

echo "[$(date -u)] Content pipeline complete."
```

**Step 2: Make it executable and commit**

```bash
chmod +x scripts/run-content-pipeline.sh
git add scripts/run-content-pipeline.sh
git commit -m "feat: add cron runner script for content pipeline"
```

---

### Task 9: Integration test — full pipeline dry run

**Files:**
- Test: `tests/test_content_pipeline.py` (add integration test)

**Step 1: Write the integration test**

Add to `tests/test_content_pipeline.py`:

```python
class TestFullPipelineIntegration:

    def test_end_to_end_payload_generation(self, ds, tmp_path):
        """Full pipeline: seed data -> detect movers -> generate payload -> generate charts."""
        from src.content_pipeline import generate_content_payload
        from src.chart_generator import generate_charts

        # Seed traders
        ds.upsert_trader("0xAAA", label="Smart Trader")
        ds.upsert_trader("0xBBB", label="Token Millionaire")
        ds.upsert_trader("0xCCC", label="Whale")

        # Day 1 snapshots
        for addr, rank, score in [
            ("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65), ("0xCCC", 3, 0.50),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        # Day 2 snapshots with a big mover
        for addr, rank, score, growth in [
            ("0xBBB", 1, 0.85, 0.90),
            ("0xCCC", 2, 0.70, 0.60),
            ("0xAAA", 3, 0.55, 0.30),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 8), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=growth, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        # Generate payload
        payload = generate_content_payload(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert payload["post_worthy"] is True

        # Generate charts from the payload
        chart_dir = str(tmp_path / "charts")
        chart_paths = generate_charts(payload, output_dir=chart_dir, count=2)
        assert len(chart_paths) >= 1
        for p in chart_paths:
            assert Path(p).exists()
            assert Path(p).stat().st_size > 1000  # Not empty image
```

**Step 2: Run the full test suite**

Run: `pytest tests/test_content_pipeline.py tests/test_typefully_client.py tests/test_chart_generator.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/test_content_pipeline.py
git commit -m "test: add full pipeline integration test"
```

---

## Summary

| Task | Description | New/Modified Files |
|------|-------------|-------------------|
| 1 | score_snapshots table + CRUD | `src/datastore.py`, `tests/test_content_pipeline.py` |
| 2 | Daily snapshot job in scheduler | `src/scheduler.py`, `tests/test_content_pipeline.py` |
| 3 | Content detection module | `src/content_pipeline.py`, `src/config.py`, `tests/test_content_pipeline.py` |
| 4 | Typefully client | `src/typefully_client.py`, `tests/test_typefully_client.py` |
| 5 | Chart generator (5 types) | `src/chart_generator.py`, `tests/test_chart_generator.py`, `pyproject.toml` |
| 6 | Content prompt file | `scripts/content-prompt.md` |
| 7 | Env config | `.env.example` |
| 8 | Cron runner script | `scripts/run-content-pipeline.sh` |
| 9 | Integration test | `tests/test_content_pipeline.py` |

Tasks 1-3 are sequential (each depends on the previous). Tasks 4 and 5 are independent of each other and can be parallelized. Tasks 6-8 are independent config/script tasks. Task 9 ties it all together.
