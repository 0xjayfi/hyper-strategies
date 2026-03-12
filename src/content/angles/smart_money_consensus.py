"""Smart Money Consensus angle — reports on shifts in smart-money direction.

Compares today vs yesterday consensus_snapshots for each token to
detect direction flips and significant confidence swings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.content.base import ContentAngle, PageCapture, ScreenshotConfig

logger = logging.getLogger(__name__)


class SmartMoneyConsensus(ContentAngle):
    """Detects significant changes in smart-money consensus direction/confidence."""

    angle_type = "smart_money_consensus"
    auto_publish = False
    cooldown_days = 3
    tone = "analytical"

    def __init__(self) -> None:
        self._consensus_data: Optional[dict] = None

    # ---- detect --------------------------------------------------

    def detect(self, datastore, nansen_client=None) -> float:
        """Score how much smart-money consensus shifted.

        Returns a value in [0, 1] or 0 when below threshold.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        today_rows = datastore.get_consensus_snapshots_for_date(today)
        yesterday_rows = datastore.get_consensus_snapshots_for_date(yesterday)

        if not today_rows or not yesterday_rows:
            return 0.0

        yesterday_map = {r["token"]: r for r in yesterday_rows}

        all_token_changes: list[dict] = []
        best_score = 0.0
        best_token_data: Optional[dict] = None

        for row in today_rows:
            token = row["token"]
            prev = yesterday_map.get(token)
            if prev is None:
                continue

            direction_flipped = row["direction"] != prev["direction"]
            confidence_swing = abs(row["confidence_pct"] - prev["confidence_pct"])

            # Scoring
            if direction_flipped:
                score = min(1.0, 0.7 + confidence_swing / 40)
            else:
                score = min(1.0, confidence_swing / 40)

            token_change = {
                "token": token,
                "direction_flipped": direction_flipped,
                "old_direction": prev["direction"],
                "new_direction": row["direction"],
                "old_confidence_pct": prev["confidence_pct"],
                "new_confidence_pct": row["confidence_pct"],
                "confidence_swing": confidence_swing,
                "sm_long_usd": row.get("sm_long_usd"),
                "sm_short_usd": row.get("sm_short_usd"),
                "score": score,
            }
            all_token_changes.append(token_change)

            if score > best_score:
                best_score = score
                best_token_data = token_change

        # Threshold gate: direction flip on any token OR confidence swing >= 20pp
        any_flip = any(c["direction_flipped"] for c in all_token_changes)
        any_big_swing = any(c["confidence_swing"] >= 20 for c in all_token_changes)

        if not any_flip and not any_big_swing:
            return 0.0

        self._consensus_data = {
            "best_token": best_token_data,
            "all_token_changes": all_token_changes,
        }

        return best_score

    # ---- build_payload -------------------------------------------

    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload for the detected consensus shift."""
        today = datetime.now(timezone.utc).date()
        data = self._consensus_data
        assert data is not None, "detect() must be called before build_payload()"

        best = data["best_token"]
        return {
            "post_worthy": True,
            "snapshot_date": today.isoformat(),
            "token": best["token"],
            "direction_flipped": best["direction_flipped"],
            "old_direction": best["old_direction"],
            "new_direction": best["new_direction"],
            "old_confidence_pct": best["old_confidence_pct"],
            "new_confidence_pct": best["new_confidence_pct"],
            "confidence_swing": best["confidence_swing"],
            "sm_long_usd": best["sm_long_usd"],
            "sm_short_usd": best["sm_short_usd"],
            "all_token_changes": data["all_token_changes"],
        }

    # ---- screenshot_config ---------------------------------------

    def screenshot_config(self) -> ScreenshotConfig:
        """Return capture config for the market consensus page."""
        return ScreenshotConfig(
            pages=[
                PageCapture(
                    route="/market",
                    wait_selector='[data-testid="market-overview"]',
                    capture_selector='[data-testid="market-overview"]',
                    filename="market_consensus.png",
                ),
            ]
        )
