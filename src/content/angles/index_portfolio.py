"""Index Portfolio Update angle — reports on side flips and new entries.

Compares today vs yesterday index_portfolio_snapshots to detect tokens
whose side flipped or that are new entries in the portfolio.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.content.base import ContentAngle, PageCapture, ScreenshotConfig

logger = logging.getLogger(__name__)


class IndexPortfolio(ContentAngle):
    """Detects significant changes in the index portfolio (side flips, new entries)."""

    angle_type = "index_portfolio"
    auto_publish = True
    cooldown_days = 4
    tone = "neutral"

    def __init__(self) -> None:
        self._portfolio_data: Optional[dict] = None

    # ---- detect --------------------------------------------------

    def detect(self, datastore, nansen_client=None) -> float:
        """Score how much the index portfolio changed.

        Returns a value in [0, 1] or 0 when below threshold.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        today_rows = datastore.get_index_portfolio_snapshots_for_date(today)
        yesterday_rows = datastore.get_index_portfolio_snapshots_for_date(yesterday)

        if not today_rows or not yesterday_rows:
            return 0.0

        today_map = {r["token"]: r for r in today_rows}
        yesterday_map = {r["token"]: r for r in yesterday_rows}

        flipped_tokens: list[dict] = []
        new_entries: list[dict] = []

        for token, today_snap in today_map.items():
            if token not in yesterday_map:
                # New token entry
                new_entries.append({
                    "token": token,
                    "side": today_snap["side"],
                    "weight": today_snap["target_weight"],
                })
            else:
                yesterday_snap = yesterday_map[token]
                if today_snap["side"] != yesterday_snap["side"]:
                    # Side flip
                    flipped_tokens.append({
                        "token": token,
                        "old_side": yesterday_snap["side"],
                        "new_side": today_snap["side"],
                        "old_weight": yesterday_snap["target_weight"],
                        "new_weight": today_snap["target_weight"],
                    })

        tokens_flipped = len(flipped_tokens) + len(new_entries)

        # Determine top 5 by target_weight in today's snapshot
        sorted_today = sorted(today_rows, key=lambda r: r["target_weight"], reverse=True)
        top_5_tokens = {r["token"] for r in sorted_today[:5]}

        # Check if any new entry is in the top 5
        new_entry_in_top5 = any(e["token"] in top_5_tokens for e in new_entries)

        # Threshold gate: >= 2 tokens flipped OR new token entered top 5
        if tokens_flipped < 2 and not new_entry_in_top5:
            return 0.0

        score = min(1.0, tokens_flipped / 3)

        # Build portfolio_today for payload
        portfolio_today = [
            {
                "token": r["token"],
                "side": r["side"],
                "target_weight": r["target_weight"],
                "target_usd": r["target_usd"],
            }
            for r in today_rows
        ]

        self._portfolio_data = {
            "tokens_flipped": tokens_flipped,
            "flipped_tokens": flipped_tokens,
            "new_entries": new_entries,
            "portfolio_today": portfolio_today,
        }

        return score

    # ---- build_payload -------------------------------------------

    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload for the detected index portfolio update."""
        today = datetime.now(timezone.utc).date()
        data = self._portfolio_data
        assert data is not None, "detect() must be called before build_payload()"

        return {
            "post_worthy": True,
            "snapshot_date": today.isoformat(),
            "tokens_flipped": data["tokens_flipped"],
            "flipped_tokens": data["flipped_tokens"],
            "new_entries": data["new_entries"],
            "portfolio_today": data["portfolio_today"],
        }

    # ---- screenshot_config ---------------------------------------

    def screenshot_config(self) -> ScreenshotConfig:
        """Return capture config for the allocations page with Index Portfolio tab."""
        return ScreenshotConfig(
            pages=[
                PageCapture(
                    route="/allocations",
                    wait_selector='[data-testid="allocation-dashboard"]',
                    capture_selector='[data-testid="allocation-strategies"]',
                    filename="index_portfolio.png",
                    pre_capture_js=(
                        'document.querySelector(\'[data-testid="allocation-strategies"]\')?.scrollIntoView();'
                    ),
                ),
            ]
        )
