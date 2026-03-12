"""Allocation Shift angle — reports on entries, exits, and weight changes.

Compares today vs yesterday allocation_snapshots to detect traders
entering or exiting the portfolio, and significant weight changes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.content.base import ContentAngle, PageCapture, ScreenshotConfig

logger = logging.getLogger(__name__)


class AllocationShift(ContentAngle):
    """Detects significant allocation changes (entries, exits, weight shifts)."""

    angle_type = "allocation_shift"
    auto_publish = True
    cooldown_days = 3
    tone = "neutral"

    def __init__(self) -> None:
        self._shift_data: Optional[dict] = None

    # ---- detect --------------------------------------------------

    def detect(self, datastore, nansen_client=None) -> float:
        """Score how much the allocation shifted.

        Returns a value in [0, 1] or 0 when below threshold.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        today_rows = datastore.get_allocation_snapshots_for_date(today)
        yesterday_rows = datastore.get_allocation_snapshots_for_date(yesterday)

        if not today_rows and not yesterday_rows:
            return 0.0

        today_map = {r["trader_id"]: r for r in today_rows}
        yesterday_map = {r["trader_id"]: r for r in yesterday_rows}

        changes: list[dict] = []
        max_score = 0.0

        # Detect entries: in today but not yesterday
        for trader_id in today_map:
            if trader_id not in yesterday_map:
                label = datastore.get_trader_label(trader_id)
                changes.append(
                    {
                        "trader_id": trader_id,
                        "label": label,
                        "change_type": "entry",
                        "old_weight": None,
                        "new_weight": today_map[trader_id]["weight"],
                        "weight_delta": None,
                    }
                )
                max_score = max(max_score, 0.6)

        # Detect exits: in yesterday but not today
        for trader_id in yesterday_map:
            if trader_id not in today_map:
                label = datastore.get_trader_label(trader_id)
                changes.append(
                    {
                        "trader_id": trader_id,
                        "label": label,
                        "change_type": "exit",
                        "old_weight": yesterday_map[trader_id]["weight"],
                        "new_weight": None,
                        "weight_delta": None,
                    }
                )
                max_score = max(max_score, 0.6)

        # Detect weight changes: in both days
        max_weight_delta = 0.0
        for trader_id in today_map:
            if trader_id in yesterday_map:
                old_w = yesterday_map[trader_id]["weight"]
                new_w = today_map[trader_id]["weight"]
                delta = abs(new_w - old_w)
                if delta > 0.001:  # ignore floating-point noise
                    changes.append(
                        {
                            "trader_id": trader_id,
                            "label": datastore.get_trader_label(trader_id),
                            "change_type": "weight_change",
                            "old_weight": old_w,
                            "new_weight": new_w,
                            "weight_delta": round(new_w - old_w, 6),
                        }
                    )
                    max_weight_delta = max(max_weight_delta, delta)
                    weight_score = min(1.0, delta / 0.25)
                    max_score = max(max_score, weight_score)

        if not changes:
            return 0.0

        # Threshold gate: entry/exit OR weight change >= 10pp (0.10)
        # Use small epsilon to avoid floating-point boundary issues
        has_entry_or_exit = any(
            c["change_type"] in ("entry", "exit") for c in changes
        )
        has_big_weight_change = max_weight_delta >= 0.10 - 1e-9

        if not has_entry_or_exit and not has_big_weight_change:
            return 0.0

        self._shift_data = {
            "changes": changes,
            "max_weight_delta": max_weight_delta,
        }

        return max_score

    # ---- build_payload -------------------------------------------

    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload for the detected allocation shift."""
        today = datetime.now(timezone.utc).date()
        data = self._shift_data
        assert data is not None, "detect() must be called before build_payload()"

        changes = data["changes"]
        total_entries = sum(1 for c in changes if c["change_type"] == "entry")
        total_exits = sum(1 for c in changes if c["change_type"] == "exit")
        total_weight_changes = sum(
            1 for c in changes if c["change_type"] == "weight_change"
        )

        return {
            "post_worthy": True,
            "snapshot_date": today.isoformat(),
            "changes": changes,
            "total_entries": total_entries,
            "total_exits": total_exits,
            "total_weight_changes": total_weight_changes,
            "max_weight_delta": data["max_weight_delta"],
        }

    # ---- screenshot_config ---------------------------------------

    def screenshot_config(self) -> ScreenshotConfig:
        """Return capture config for the allocation dashboard page."""
        return ScreenshotConfig(
            pages=[
                PageCapture(
                    route="/allocations",
                    wait_selector='[data-testid="allocation-dashboard"]',
                    capture_selector='[data-testid="allocation-dashboard"]',
                    filename="allocation_shift.png",
                ),
            ]
        )
