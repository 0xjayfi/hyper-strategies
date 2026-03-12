"""Leaderboard Shake-up angle — reports on shuffles in the top 10.

Compares today vs yesterday score_snapshots for the top 10 wallets
to detect rank changes and new entrants.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.content.base import ContentAngle, PageCapture, ScreenshotConfig

logger = logging.getLogger(__name__)


class LeaderboardShakeup(ContentAngle):
    """Detects significant shuffles in the top-10 leaderboard."""

    angle_type = "leaderboard_shakeup"
    auto_publish = True
    cooldown_days = 2
    tone = "neutral"

    def __init__(self) -> None:
        self._shakeup_data: Optional[dict] = None

    # ---- detect --------------------------------------------------

    def detect(self, datastore, nansen_client=None) -> float:
        """Score how much the top-10 leaderboard shuffled.

        Returns a value in [0, 1] or 0 when below threshold.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        today_rows = datastore.get_score_snapshots_for_date(today)
        yesterday_rows = datastore.get_score_snapshots_for_date(yesterday)

        if not today_rows or not yesterday_rows:
            return 0.0

        # Build maps for top-10 comparison
        today_top10 = [r for r in today_rows if r["rank"] <= 10]
        yesterday_map = {r["trader_id"]: r for r in yesterday_rows}

        shuffled_wallets = 0
        rank_changes: list[dict] = []
        new_top3_entrants: list[dict] = []

        for row in today_top10:
            addr = row["trader_id"]
            prev = yesterday_map.get(addr)

            if prev is None:
                # Completely new entrant in top 10
                shuffled_wallets += 1
                rank_changes.append(
                    {
                        "address": addr,
                        "label": datastore.get_trader_label(addr),
                        "old_rank": None,
                        "new_rank": row["rank"],
                        "rank_delta": None,
                        "score": row["composite_score"],
                    }
                )
                if row["rank"] <= 3:
                    new_top3_entrants.append(
                        {
                            "address": addr,
                            "label": datastore.get_trader_label(addr),
                            "new_rank": row["rank"],
                            "old_rank": None,
                        }
                    )
                continue

            old_rank = prev["rank"]
            new_rank = row["rank"]
            if old_rank != new_rank:
                shuffled_wallets += 1
                rank_changes.append(
                    {
                        "address": addr,
                        "label": datastore.get_trader_label(addr),
                        "old_rank": old_rank,
                        "new_rank": new_rank,
                        "rank_delta": old_rank - new_rank,
                        "score": row["composite_score"],
                    }
                )
                # New entrant to top 3 (was outside top 3 yesterday)
                if new_rank <= 3 and old_rank > 3:
                    new_top3_entrants.append(
                        {
                            "address": addr,
                            "label": datastore.get_trader_label(addr),
                            "new_rank": new_rank,
                            "old_rank": old_rank,
                        }
                    )

        # Threshold gate
        has_enough_shuffles = shuffled_wallets >= 3
        has_top3_entrant = len(new_top3_entrants) > 0

        if not has_enough_shuffles and not has_top3_entrant:
            return 0.0

        # Scoring formula
        score = min(1.0, shuffled_wallets / 8)

        # Sort rank_changes by magnitude of change (descending)
        rank_changes.sort(
            key=lambda c: abs(c["rank_delta"] or 0), reverse=True
        )

        # Build top-10-today list for payload
        top_10_today = [
            {
                "address": r["trader_id"],
                "label": datastore.get_trader_label(r["trader_id"]),
                "rank": r["rank"],
                "score": r["composite_score"],
            }
            for r in today_top10
        ]

        self._shakeup_data = {
            "total_shuffled": shuffled_wallets,
            "new_top3_entrants": new_top3_entrants,
            "rank_changes": rank_changes,
            "top_10_today": top_10_today,
        }

        return score

    # ---- build_payload -------------------------------------------

    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload for the detected leaderboard shakeup."""
        today = datetime.now(timezone.utc).date()
        data = self._shakeup_data
        assert data is not None, "detect() must be called before build_payload()"

        return {
            "post_worthy": True,
            "snapshot_date": today.isoformat(),
            "total_shuffled": data["total_shuffled"],
            "new_top3_entrants": data["new_top3_entrants"],
            "rank_changes": data["rank_changes"],
            "top_10_today": data["top_10_today"],
        }

    # ---- screenshot_config ---------------------------------------

    def screenshot_config(self) -> ScreenshotConfig:
        """Return capture config for the leaderboard page."""
        return ScreenshotConfig(
            pages=[
                PageCapture(
                    route="/leaderboard",
                    wait_selector='[data-testid="leaderboard-table"]',
                    capture_selector='[data-testid="leaderboard-table"]',
                    filename="leaderboard_shakeup.png",
                ),
            ]
        )
