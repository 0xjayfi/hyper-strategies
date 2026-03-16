# Content Pipeline Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 bugs in the content pipeline identified by code review — stale selections, missing NansenClient, placeholder snapshots, Vite health check, and fragile cooldown tracking.

**Architecture:** Bugs 1, 5, 6 are infrastructure fixes in `dispatcher.py` and `run-content-pipeline.sh`. Bugs 2-4 are connected — once the CLI instantiates NansenClient (bug 2), the consensus and portfolio snapshot placeholders (bugs 3-4) can be replaced with real implementations that use existing `strategy_interface.py` functions and Nansen data.

**Tech Stack:** Python 3.11+, SQLite, bash, pytest, httpx (NansenClient)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/content/dispatcher.py` | Modify | Bugs 1-4: delete stale selections, init NansenClient, implement snapshot functions |
| `src/content/poster.py` | Create | Bug 6: single code-owned function that pushes to Typefully AND records to DB |
| `scripts/run-content-pipeline.sh` | Modify | Bug 5: validate Vite PID is alive, not just port responding |
| `src/content/prompts/*.md` | Modify (6 files) | Bug 6: replace inline Typefully+DB code with `poster.py` call |
| `tests/test_content/test_dispatcher.py` | Modify | Tests for bugs 1-4 |
| `tests/test_content/test_poster.py` | Create | Tests for bug 6 |

---

## Chunk 1: Bug 1 — Stale `content_selections.json`

### Task 1: Delete stale selections file at start of detection

**Files:**
- Modify: `src/content/dispatcher.py:108-183` (the `detect_and_select` function)
- Modify: `tests/test_content/test_dispatcher.py`

- [ ] **Step 1: Write failing test — stale file is deleted when no angles qualify**

Add to `tests/test_content/test_dispatcher.py`:

```python
class TestStaleSelectionsCleanup:
    """Bug 1: stale content_selections.json must be deleted when no angles qualify."""

    def test_stale_file_deleted_when_no_angles_qualify(self, ds, tmp_path, monkeypatch):
        """If no angles score > 0, any existing selections file is removed."""
        monkeypatch.setattr("src.content.dispatcher._DATA_DIR", str(tmp_path))
        stale_path = tmp_path / "content_selections.json"
        stale_path.write_text('[{"angle_type": "old_stale_data"}]')

        # Patch ALL_ANGLES to return a single angle that scores 0
        monkeypatch.setattr("src.content.dispatcher.ALL_ANGLES", [StubAngle("zero_scorer", raw_score=0.0)])

        result = detect_and_select(ds)

        assert result == []
        assert not stale_path.exists(), "Stale selections file should be deleted"

    def test_stale_file_deleted_when_all_in_cooldown(self, ds, tmp_path, monkeypatch):
        """If all angles are blocked by cooldown, stale file is removed."""
        monkeypatch.setattr("src.content.dispatcher._DATA_DIR", str(tmp_path))
        stale_path = tmp_path / "content_selections.json"
        stale_path.write_text('[{"angle_type": "old_stale_data"}]')

        monkeypatch.setattr("src.content.dispatcher.ALL_ANGLES", [StubAngle("cooled", raw_score=0.8, cooldown_days=3)])
        _insert_post(ds, "cooled", TODAY)  # Posted today -> cooldown active

        result = detect_and_select(ds)

        assert result == []
        assert not stale_path.exists()

    def test_file_not_deleted_when_angles_selected(self, ds, tmp_path, monkeypatch):
        """Normal case: file is written (not deleted) when angles qualify."""
        monkeypatch.setattr("src.content.dispatcher._DATA_DIR", str(tmp_path))

        monkeypatch.setattr("src.content.dispatcher.ALL_ANGLES", [StubAngle("good_angle", raw_score=0.8)])

        result = detect_and_select(ds)

        assert len(result) == 1
        assert (tmp_path / "content_selections.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_content/test_dispatcher.py::TestStaleSelectionsCleanup -v`
Expected: FAIL — stale file still exists after `detect_and_select()` returns empty

- [ ] **Step 3: Implement the fix in `detect_and_select()`**

In `src/content/dispatcher.py`, add cleanup at the top of `detect_and_select()`, right after the `today = ...` line:

```python
def detect_and_select(datastore: DataStore, nansen_client=None) -> list[dict]:
    today = datetime.now(timezone.utc).date()

    # Remove any stale selections file from a previous run (Bug 1 fix)
    selections_path = os.path.join(_DATA_DIR, "content_selections.json")
    if os.path.exists(selections_path):
        os.remove(selections_path)
        logger.info("Removed stale %s", selections_path)

    # ... rest of function unchanged ...
```

Also update the two early-return paths (lines 182-183 and 216-220) — they no longer need to worry about stale files since we delete upfront. And update the final write (line 222) to reuse `selections_path` instead of recomputing it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_content/test_dispatcher.py -v`
Expected: ALL PASS (including existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/content/dispatcher.py tests/test_content/test_dispatcher.py
git commit -m "fix: delete stale content_selections.json at start of detection (bug 1)"
```

---

## Chunk 2: Bug 2 — CLI never instantiates NansenClient

### Task 2: Add NansenClient to dispatcher CLI path

**Files:**
- Modify: `src/content/dispatcher.py:234-265` (CLI `__main__` block)
- Modify: `tests/test_content/test_dispatcher.py`

- [ ] **Step 1: Write failing test — CLI creates NansenClient**

```python
class TestCLINansenClient:
    """Bug 2: CLI path must instantiate and pass NansenClient."""

    @patch("src.content.dispatcher.detect_and_select")
    @patch("src.content.dispatcher.take_daily_snapshots")
    @patch("src.content.dispatcher.NansenClient")
    def test_nansen_client_passed_to_snapshot(
        self, MockNansen, mock_snapshots, mock_detect, monkeypatch
    ):
        monkeypatch.setenv("NANSEN_API_KEY", "test-key")
        from src.content.dispatcher import _run_cli
        _run_cli(snapshot=True, detect=False)

        MockNansen.assert_called_once()
        mock_snapshots.assert_called_once()
        # Second arg should be the nansen_client instance
        call_args = mock_snapshots.call_args
        assert call_args[1].get("nansen_client") is not None or call_args[0][1] is not None

    @patch("src.content.dispatcher.detect_and_select")
    @patch("src.content.dispatcher.take_daily_snapshots")
    @patch("src.content.dispatcher.NansenClient")
    def test_nansen_client_passed_to_detect(
        self, MockNansen, mock_snapshots, mock_detect, monkeypatch
    ):
        monkeypatch.setenv("NANSEN_API_KEY", "test-key")
        from src.content.dispatcher import _run_cli
        _run_cli(snapshot=False, detect=True)

        mock_detect.assert_called_once()
        call_args = mock_detect.call_args
        assert call_args[1].get("nansen_client") is not None or call_args[0][1] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_content/test_dispatcher.py::TestCLINansenClient -v`
Expected: FAIL — `_run_cli` doesn't exist yet / NansenClient not instantiated

- [ ] **Step 3: Implement — extract CLI logic into `_run_cli()` and add NansenClient**

In `src/content/dispatcher.py`, add the import and refactor the CLI:

```python
from src.nansen_client import NansenClient

def _run_cli(snapshot: bool = False, detect: bool = False) -> None:
    """CLI entry-point logic, extracted for testability."""
    nansen_client = NansenClient()  # Reads NANSEN_API_KEY from env
    datastore = DataStore()
    try:
        if snapshot:
            take_daily_snapshots(datastore, nansen_client=nansen_client)
        if detect:
            detect_and_select(datastore, nansen_client=nansen_client)
    finally:
        datastore.close()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Multi-angle content pipeline dispatcher"
    )
    parser.add_argument("--snapshot", action="store_true",
        help="Take daily snapshots (scores, consensus, allocations, portfolio)")
    parser.add_argument("--detect", action="store_true",
        help="Run angle detection, rank, select, write outputs")
    args = parser.parse_args()

    _run_cli(snapshot=args.snapshot, detect=args.detect)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_content/test_dispatcher.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/content/dispatcher.py tests/test_content/test_dispatcher.py
git commit -m "fix: instantiate NansenClient in dispatcher CLI path (bug 2)"
```

---

## Chunk 3: Bugs 3-4 — Implement consensus and index portfolio snapshots

### Task 3: Implement `take_consensus_snapshot()`

**Files:**
- Modify: `src/content/dispatcher.py:41-55` (replace placeholder)
- Modify: `tests/test_content/test_dispatcher.py`

The consensus snapshot needs to compute `weighted_consensus()` for each token that the top traders hold, using today's allocations and positions from the DB.

- [ ] **Step 1: Write failing test**

First, add to the imports at the top of `tests/test_content/test_dispatcher.py`:

```python
from src.content.dispatcher import (
    _DATA_DIR,
    detect_and_select,
    take_daily_snapshots,
    take_consensus_snapshot,
    take_index_portfolio_snapshot,
)
```

Then add the test class:

```python
class TestConsensusSnapshotImplementation:
    """Bug 3: take_consensus_snapshot must populate consensus_snapshots table."""

    def test_consensus_snapshot_populates_table(self, ds):
        """With allocations and position snapshots, consensus rows are written."""
        today = datetime.now(timezone.utc).date()

        # Seed traders and allocations
        ds.upsert_trader("0xAAA")
        ds.upsert_trader("0xBBB")
        ds.insert_allocations({"0xAAA": 0.6, "0xBBB": 0.4})

        # Seed position snapshots for today
        ds.insert_position_snapshot("0xAAA", [
            {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10000,
             "entry_price": 50000, "leverage_value": 1.0},
            {"token_symbol": "ETH", "side": "Long", "position_value_usd": 5000,
             "entry_price": 3000, "leverage_value": 1.0},
        ])
        ds.insert_position_snapshot("0xBBB", [
            {"token_symbol": "BTC", "side": "Short", "position_value_usd": 8000,
             "entry_price": 50000, "leverage_value": 1.0},
        ])

        take_consensus_snapshot(ds)

        rows = ds.get_consensus_snapshots_for_date(today)
        tokens = {r["token"] for r in rows}
        assert "BTC" in tokens
        assert "ETH" in tokens
        # BTC should have both long and short exposure
        btc_row = next(r for r in rows if r["token"] == "BTC")
        assert btc_row["sm_long_usd"] > 0
        assert btc_row["sm_short_usd"] > 0

    def test_consensus_snapshot_empty_positions(self, ds):
        """No positions -> no consensus rows, no error."""
        today = datetime.now(timezone.utc).date()
        take_consensus_snapshot(ds)
        rows = ds.get_consensus_snapshots_for_date(today)
        assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_content/test_dispatcher.py::TestConsensusSnapshotImplementation -v`
Expected: FAIL — function is still a placeholder

- [ ] **Step 3: Implement `take_consensus_snapshot()`**

Replace the placeholder in `src/content/dispatcher.py`.

First, add the import at the top of the file (alongside the existing imports from `src.config`):

```python
from src.strategy_interface import build_index_portfolio, weighted_consensus
```

Then replace the `take_consensus_snapshot` function:

```python
def take_consensus_snapshot(datastore: DataStore, nansen_client=None) -> None:
    """Compute consensus from current allocations + positions and snapshot it.

    For each token held by allocated traders, computes weighted long/short
    exposure and derives a consensus direction and confidence percentage.
    """
    today = datetime.now(timezone.utc).date()

    allocations = datastore.get_latest_allocations()
    if not allocations:
        logger.info("Consensus snapshot: no allocations, skipping")
        return

    # Gather latest positions per allocated trader
    trader_positions: dict[str, list] = {}
    for address in allocations:
        positions = datastore.get_latest_position_snapshot(address)
        if positions:
            trader_positions[address] = [
                {
                    "token_symbol": p["token_symbol"],
                    "side": p["side"],
                    "position_value_usd": abs(float(p["position_value_usd"])),
                }
                for p in positions
            ]

    # Collect all unique tokens across all positions
    all_tokens: set[str] = set()
    for positions in trader_positions.values():
        for p in positions:
            all_tokens.add(p["token_symbol"])

    if not all_tokens:
        logger.info("Consensus snapshot: no positions found, skipping")
        return

    count = 0
    for token in sorted(all_tokens):
        result = weighted_consensus(token, allocations, trader_positions)
        long_usd = result["long_weight"]
        short_usd = result["short_weight"]
        total = long_usd + short_usd

        if total == 0:
            continue

        confidence_pct = (max(long_usd, short_usd) / total) * 100
        direction = "LONG" if long_usd >= short_usd else "SHORT"

        datastore.insert_consensus_snapshot(
            snapshot_date=today,
            token=token,
            direction=direction,
            confidence_pct=round(confidence_pct, 1),
            sm_long_usd=round(long_usd, 2),
            sm_short_usd=round(short_usd, 2),
        )
        count += 1

    logger.info("Consensus snapshot: %d tokens snapshotted", count)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_content/test_dispatcher.py::TestConsensusSnapshotImplementation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/content/dispatcher.py tests/test_content/test_dispatcher.py
git commit -m "fix: implement take_consensus_snapshot with real data (bug 3)"
```

---

### Task 4: Implement `take_index_portfolio_snapshot()`

**Files:**
- Modify: `src/content/dispatcher.py:58-66` (replace placeholder)
- Modify: `tests/test_content/test_dispatcher.py`

The index portfolio snapshot uses `build_index_portfolio()` from `strategy_interface.py` to compute the aggregate portfolio, then snapshots each (token, side) entry.

- [ ] **Step 1: Write failing test**

```python
class TestIndexPortfolioSnapshotImplementation:
    """Bug 4: take_index_portfolio_snapshot must populate index_portfolio_snapshots."""

    def test_portfolio_snapshot_populates_table(self, ds):
        today = datetime.now(timezone.utc).date()

        # Seed traders, allocations, and positions
        ds.upsert_trader("0xAAA")
        ds.upsert_trader("0xBBB")
        ds.insert_allocations({"0xAAA": 0.6, "0xBBB": 0.4})
        ds.insert_position_snapshot("0xAAA", [
            {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10000,
             "entry_price": 50000, "leverage_value": 1.0},
        ])
        ds.insert_position_snapshot("0xBBB", [
            {"token_symbol": "ETH", "side": "Short", "position_value_usd": 5000,
             "entry_price": 3000, "leverage_value": 1.0},
        ])

        take_index_portfolio_snapshot(ds)

        rows = ds.get_index_portfolio_snapshots_for_date(today)
        assert len(rows) >= 2
        tokens = {r["token"] for r in rows}
        assert "BTC" in tokens
        assert "ETH" in tokens

    def test_portfolio_snapshot_empty_positions(self, ds):
        today = datetime.now(timezone.utc).date()
        take_index_portfolio_snapshot(ds)
        rows = ds.get_index_portfolio_snapshots_for_date(today)
        assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_content/test_dispatcher.py::TestIndexPortfolioSnapshotImplementation -v`
Expected: FAIL — function is still a placeholder

- [ ] **Step 3: Implement `take_index_portfolio_snapshot()`**

Replace the placeholder in `src/content/dispatcher.py` (the `build_index_portfolio` import was already added in Task 3):

```python
def take_index_portfolio_snapshot(datastore: DataStore) -> None:
    """Compute index portfolio from allocations + positions and snapshot it.

    Uses build_index_portfolio() to aggregate weighted positions across
    all allocated traders, then stores each (token, side) entry.
    """
    today = datetime.now(timezone.utc).date()

    allocations = datastore.get_latest_allocations()
    if not allocations:
        logger.info("Index portfolio snapshot: no allocations, skipping")
        return

    # Gather latest positions per allocated trader
    trader_positions: dict[str, list] = {}
    for address in allocations:
        positions = datastore.get_latest_position_snapshot(address)
        if positions:
            trader_positions[address] = [
                {
                    "token_symbol": p["token_symbol"],
                    "side": p["side"],
                    "position_value_usd": abs(float(p["position_value_usd"])),
                }
                for p in positions
            ]

    if not trader_positions:
        logger.info("Index portfolio snapshot: no positions found, skipping")
        return

    # Use a notional $100k account for weight normalization (absolute value
    # doesn't matter since we normalize to relative weights below)
    portfolio = build_index_portfolio(allocations, trader_positions, 100_000.0)

    if not portfolio:
        logger.info("Index portfolio snapshot: empty portfolio, skipping")
        return

    total_usd = sum(portfolio.values())

    count = 0
    for (token, side), target_usd in portfolio.items():
        weight = (target_usd / total_usd) if total_usd > 0 else 0.0
        datastore.insert_index_portfolio_snapshot(
            snapshot_date=today,
            token=token,
            side=side,
            target_weight=round(weight, 4),
            target_usd=round(target_usd, 2),
        )
        count += 1

    logger.info("Index portfolio snapshot: %d entries snapshotted", count)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_content/test_dispatcher.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/content/dispatcher.py tests/test_content/test_dispatcher.py
git commit -m "fix: implement take_index_portfolio_snapshot with real data (bug 4)"
```

---

## Chunk 4: Bug 5 — Vite health check can attach to wrong server

### Task 5: Validate Vite PID is alive during health check

**Files:**
- Modify: `scripts/run-content-pipeline.sh:40-51`

- [ ] **Step 1: Update the Vite health check in the shell script**

Replace the health check loop in `scripts/run-content-pipeline.sh`:

```bash
VITE_READY=false
for i in $(seq 1 15); do
    # First check: is our Vite process still alive?
    if ! kill -0 "$VITE_PID" 2>/dev/null; then
        echo "[$(date -u)] ERROR: Vite process (PID $VITE_PID) died."
        exit 1
    fi
    if curl -s -o /dev/null http://localhost:5173/; then
        VITE_READY=true
        break
    fi
    sleep 1
done
if [ "$VITE_READY" = false ]; then
    echo "[$(date -u)] ERROR: Vite dev server failed to start within 15s. Aborting."
    exit 1
fi
```

This ensures: (a) if the spawned Vite process crashes, we abort immediately rather than attaching to a stale server on the same port, and (b) if the port responds but our process is dead, we know something is wrong.

- [ ] **Step 2: Verify the script is syntactically valid**

Run: `bash -n scripts/run-content-pipeline.sh`
Expected: No output (valid syntax)

- [ ] **Step 3: Commit**

```bash
git add scripts/run-content-pipeline.sh
git commit -m "fix: validate Vite PID is alive during health check (bug 5)"
```

---

## Chunk 5: Bug 6 — Cooldown tracking depends on prompt compliance

### Task 6: Create `poster.py` — single code-owned posting function

**Files:**
- Create: `src/content/poster.py`
- Create: `tests/test_content/test_poster.py`
- Modify: `src/content/prompts/*.md` (all 6 prompt templates)

The current approach has each prompt template containing inline Python that pushes to Typefully and records to the DB. If the agent skips the DB step, cooldown breaks. The fix is to create a single Python module that atomically does both: push to Typefully, then record to the DB.

- [ ] **Step 1: Write failing test for `post_and_record()`**

Create `tests/test_content/test_poster.py`:

```python
"""Tests for the content poster module."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.datastore import DataStore


@pytest.fixture
def ds(tmp_path):
    db_path = str(tmp_path / "test.db")
    store = DataStore(db_path)
    yield store
    store.close()


@pytest.fixture
def selections_file(tmp_path):
    """Write a fake content_selections.json and return its path."""
    sel = [
        {
            "angle_type": "leaderboard_shakeup",
            "raw_score": 0.75,
            "effective_score": 0.85,
            "auto_publish": True,
            "payload_path": "data/content_payload_leaderboard_shakeup.json",
        }
    ]
    path = tmp_path / "content_selections.json"
    path.write_text(json.dumps(sel))
    return str(path)


class TestPostAndRecord:
    """post_and_record pushes to Typefully AND records to DB atomically."""

    @patch("src.content.poster.TypefullyClient")
    def test_records_to_db_after_typefully_push(
        self, MockClient, ds, selections_file, tmp_path
    ):
        from src.content.poster import post_and_record

        # Mock the Typefully client
        mock_instance = MockClient.return_value
        mock_instance.upload_media = AsyncMock(return_value="media-id-123")
        mock_instance.create_draft = AsyncMock(
            return_value={"id": "draft-1", "private_url": "https://typefully.com/d/123"}
        )
        mock_instance.close = AsyncMock()

        draft = {"tweets": [{"text": "Hello world", "screenshots": []}]}

        result = post_and_record(
            draft=draft,
            angle_type="leaderboard_shakeup",
            title="Leaderboard Shakeup — 2026-03-16",
            selections_path=selections_file,
            db_path=str(tmp_path / "test.db"),
        )

        assert result["private_url"] == "https://typefully.com/d/123"

        # Verify DB was populated
        last = ds.get_last_post_date("leaderboard_shakeup")
        # post_and_record uses its own DataStore, so we need to check directly
        from src.datastore import DataStore as DS
        ds2 = DS(str(tmp_path / "test.db"))
        last = ds2.get_last_post_date("leaderboard_shakeup")
        ds2.close()
        assert last is not None

    @patch("src.content.poster.TypefullyClient")
    def test_auto_publish_sets_publish_at(self, MockClient, ds, selections_file, tmp_path):
        from src.content.poster import post_and_record

        mock_instance = MockClient.return_value
        mock_instance.upload_media = AsyncMock(return_value="media-id")
        mock_instance.create_draft = AsyncMock(
            return_value={"id": "1", "private_url": "https://typefully.com/d/1"}
        )
        mock_instance.close = AsyncMock()

        draft = {"tweets": [{"text": "Test", "screenshots": []}]}

        post_and_record(
            draft=draft,
            angle_type="leaderboard_shakeup",
            title="Test",
            selections_path=selections_file,
            db_path=str(tmp_path / "test.db"),
            auto_publish=True,
        )

        # Verify create_draft was called with publish_at
        call_kwargs = mock_instance.create_draft.call_args
        assert "publish_at" in (call_kwargs[1] if call_kwargs[1] else {}) or \
               (len(call_kwargs[0]) > 4 and call_kwargs[0][4] is not None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_content/test_poster.py -v`
Expected: FAIL — `src.content.poster` does not exist

- [ ] **Step 3: Implement `src/content/poster.py`**

```python
"""Content poster — atomic Typefully push + DB recording.

Single code-owned function that ensures cooldown tracking stays
accurate even if the prompt-driven agent skips a step.

Usage from prompt templates::

    from src.content.poster import post_and_record
    result = post_and_record(
        draft=final_draft,
        angle_type="leaderboard_shakeup",
        title="Leaderboard Shakeup — DATE",
        auto_publish=True,
    )
    print(result['private_url'])
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.datastore import DataStore
from src.typefully_client import TypefullyClient

logger = logging.getLogger(__name__)

_SELECTIONS_PATH = "data/content_selections.json"
_CHARTS_DIR = "data/charts"
_AUTO_PUBLISH_DELAY_MINUTES = 90


async def _do_post(
    client: TypefullyClient,
    draft: dict,
    title: str,
    auto_publish: bool,
) -> dict:
    """Async inner function — upload media, create draft, return result."""
    # Upload media
    media_map: dict[str, str] = {}
    for tweet in draft["tweets"]:
        for filename in tweet.get("screenshots", []):
            if filename not in media_map:
                filepath = os.path.join(_CHARTS_DIR, filename)
                media_map[filename] = await client.upload_media(filepath)

    # Build per-post media
    per_post_media: list[list[str]] = []
    for tweet in draft["tweets"]:
        ids = [media_map[f] for f in tweet.get("screenshots", []) if f in media_map]
        per_post_media.append(ids)

    # Determine publish_at
    publish_at: Optional[str] = None
    if auto_publish:
        publish_at = (
            datetime.now(timezone.utc) + timedelta(minutes=_AUTO_PUBLISH_DELAY_MINUTES)
        ).isoformat()

    # Create draft
    result = await client.create_draft(
        posts=[t["text"] for t in draft["tweets"]],
        title=title,
        per_post_media=per_post_media,
        publish_at=publish_at,
    )

    await client.close()
    return result


def post_and_record(
    draft: dict,
    angle_type: str,
    title: str,
    auto_publish: bool = False,
    selections_path: str = _SELECTIONS_PATH,
    db_path: str = "data/pnl_weighted.db",
) -> dict:
    """Push draft to Typefully and record to content_posts. Returns Typefully result dict."""

    api_key = os.environ["TYPEFULLY_API_KEY"]
    social_set_id = int(os.environ["TYPEFULLY_SOCIAL_SET_ID"])

    client = TypefullyClient(api_key=api_key, social_set_id=social_set_id)

    # Single asyncio.run() call for all async operations
    result = asyncio.run(_do_post(client, draft, title, auto_publish))

    # Record to DB (synchronous)
    sel = _load_selection(angle_type, selections_path)
    ds = DataStore(db_path)
    try:
        ds.insert_content_post(
            post_date=datetime.now(timezone.utc).date(),
            angle_type=angle_type,
            raw_score=sel.get("raw_score", 0.0),
            effective_score=sel.get("effective_score", 0.0),
            auto_published=auto_publish,
            typefully_url=result.get("private_url"),
            payload_path=sel.get("payload_path"),
        )
    finally:
        ds.close()

    logger.info(
        "Posted %s -> %s (recorded to DB)", angle_type, result.get("private_url")
    )
    return result


def _load_selection(angle_type: str, selections_path: str) -> dict:
    """Load the selection entry for this angle from content_selections.json."""
    try:
        with open(selections_path) as f:
            selections = json.load(f)
        return next(
            (s for s in selections if s["angle_type"] == angle_type),
            {"raw_score": 0.0, "effective_score": 0.0},
        )
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not load selections from %s", selections_path)
        return {"raw_score": 0.0, "effective_score": 0.0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_content/test_poster.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/content/poster.py tests/test_content/test_poster.py
git commit -m "feat: add poster.py — atomic Typefully push + DB recording (bug 6)"
```

---

### Task 7: Update all 6 prompt templates to use `poster.py`

**Files:**
- Modify: `src/content/prompts/leaderboard_shakeup.md`
- Modify: `src/content/prompts/allocation_shift.md`
- Modify: `src/content/prompts/index_portfolio.md`
- Modify: `src/content/prompts/wallet_spotlight.md`
- Modify: `src/content/prompts/smart_money_consensus.md`
- Modify: `src/content/prompts/token_spotlight.md`

- [ ] **Step 1: Replace Step 5 in all 3 auto-publish prompts**

For `leaderboard_shakeup.md`, `allocation_shift.md`, and `index_portfolio.md`, replace the entire Step 5 section (from `## Step 5: Push to Typefully` to end of file) with:

```markdown
## Step 5: Push to Typefully and record (AUTO-PUBLISH)

After the merge step completes (the final draft is ready):

1. Parse the final JSON output into a Python dict with `tweets` list.
2. Call `post_and_record()` which handles media upload, draft creation, scheduling, AND recording to the database:
   ```python
   from src.content.poster import post_and_record

   result = post_and_record(
       draft=final_draft,
       angle_type='ANGLE_TYPE_HERE',
       title='TITLE_HERE — DATE',
       auto_publish=True,
   )
   print(result['private_url'])
   ```
3. Print the Typefully draft URL to confirm success. This post is scheduled to publish in ~90 minutes.
```

(Replace `ANGLE_TYPE_HERE` and `TITLE_HERE` with the correct values for each prompt.)

- [ ] **Step 2: Replace Step 5 in all 3 manual-draft prompts**

For `wallet_spotlight.md`, `smart_money_consensus.md`, and `token_spotlight.md`, replace Step 5 with:

```markdown
## Step 5: Push to Typefully and record

After the merge step completes (the final draft is ready):

1. Parse the final JSON output into a Python dict with `tweets` list.
2. Call `post_and_record()` which handles media upload, draft creation, AND recording to the database:
   ```python
   from src.content.poster import post_and_record

   result = post_and_record(
       draft=final_draft,
       angle_type='ANGLE_TYPE_HERE',
       title='TITLE_HERE — DATE',
       auto_publish=False,
   )
   print(result['private_url'])
   ```
3. Print the Typefully draft URL to confirm success. This is a DRAFT. It will NOT auto-publish. Review before manually publishing.
```

- [ ] **Step 3: Verify prompts are consistent**

Run: `grep -l "post_and_record" src/content/prompts/*.md | wc -l`
Expected: `6` (all prompts updated)

Run: `grep -l "insert_content_post\|asyncio.run(client" src/content/prompts/*.md | wc -l`
Expected: `0` (no prompts still use inline Typefully/DB code)

- [ ] **Step 4: Commit**

```bash
git add src/content/prompts/*.md
git commit -m "refactor: all prompts use poster.py instead of inline Typefully+DB code (bug 6)"
```

---

## Final Validation

- [ ] **Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Run the integration smoke test**

```bash
python scripts/test_content_angles.py
```

Expected: PASS

- [ ] **Verify no regressions in existing dispatcher tests**

```bash
python -m pytest tests/test_content/test_dispatcher.py tests/test_content/test_poster.py -v
```

Expected: ALL PASS
