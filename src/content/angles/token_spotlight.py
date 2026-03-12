"""Token Spotlight angle — highlights a large new or growing position from smart money.

Identifies smart money wallets that opened or significantly grew large
positions, then spotlights the single largest new/grown position.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.content.base import ContentAngle, PageCapture, ScreenshotConfig

logger = logging.getLogger(__name__)


class TokenSpotlight(ContentAngle):
    """Detects large new or growing positions from smart money wallets."""

    angle_type = "token_spotlight"
    auto_publish = False
    cooldown_days = 3
    tone = "analytical"

    def __init__(self) -> None:
        self._spotlight_data: Optional[dict] = None

    # ---- detect --------------------------------------------------

    def detect(self, datastore, nansen_client=None) -> float:
        """Score the largest new/grown smart money position.

        Returns a value in [0, 1] or 0 when no qualifying position found.
        """
        now = datetime.now(timezone.utc)
        today = now.date()

        sm_addresses = datastore.get_smart_money_addresses(today)
        if not sm_addresses:
            return 0.0

        best_candidate: Optional[dict] = None
        best_value: float = 0.0

        for address in sm_addresses:
            snapshots = datastore.get_position_snapshot_series(address, days=2)
            if not snapshots:
                continue

            # Bucket into "recent" (within last 24h) and "prior" (24-48h ago)
            cutoff_recent = now - timedelta(hours=24)
            cutoff_prior = now - timedelta(hours=48)

            recent_by_token: dict[str, dict] = {}
            prior_by_token: dict[str, dict] = {}

            for snap in snapshots:
                captured_str = snap["captured_at"]
                captured_dt = datetime.fromisoformat(captured_str)
                # Ensure timezone-aware comparison
                if captured_dt.tzinfo is None:
                    captured_dt = captured_dt.replace(tzinfo=timezone.utc)

                token = snap["token_symbol"]

                if captured_dt >= cutoff_recent:
                    # Keep the most recent snapshot per token in the recent bucket
                    if token not in recent_by_token or captured_str > recent_by_token[token]["captured_at"]:
                        recent_by_token[token] = snap
                elif captured_dt >= cutoff_prior:
                    # Keep the most recent snapshot per token in the prior bucket
                    if token not in prior_by_token or captured_str > prior_by_token[token]["captured_at"]:
                        prior_by_token[token] = snap

            # Detect new large positions and significant growth
            for token, recent_snap in recent_by_token.items():
                position_value = recent_snap.get("position_value_usd") or 0.0

                if token not in prior_by_token:
                    # New position — must be >= $500,000
                    if position_value >= 500_000:
                        if position_value > best_value:
                            best_value = position_value
                            best_candidate = {
                                "address": address,
                                "token": token,
                                "position_value_usd": position_value,
                                "is_new_position": True,
                                "growth_amount_usd": None,
                                "snapshot": recent_snap,
                            }
                else:
                    # Existing position — growth must be >= $500,000
                    prior_value = prior_by_token[token].get("position_value_usd") or 0.0
                    growth = position_value - prior_value
                    if growth >= 500_000:
                        if position_value > best_value:
                            best_value = position_value
                            best_candidate = {
                                "address": address,
                                "token": token,
                                "position_value_usd": position_value,
                                "is_new_position": False,
                                "growth_amount_usd": growth,
                                "snapshot": recent_snap,
                            }

        if best_candidate is None:
            return 0.0

        score = min(1.0, best_value / 2_000_000)

        self._spotlight_data = best_candidate
        return score

    # ---- build_payload -------------------------------------------

    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload for the detected token spotlight."""
        today = datetime.now(timezone.utc).date()
        data = self._spotlight_data
        assert data is not None, "detect() must be called before build_payload()"

        address = data["address"]
        label = datastore.get_trader_label(address)
        snap = data["snapshot"]

        return {
            "post_worthy": True,
            "snapshot_date": today.isoformat(),
            "trader": {
                "address": address,
                "label": label,
                "smart_money": True,
            },
            "token": data["token"],
            "position_value_usd": data["position_value_usd"],
            "is_new_position": data["is_new_position"],
            "growth_amount_usd": data["growth_amount_usd"],
            "position_details": {
                "side": snap.get("side"),
                "entry_price": snap.get("entry_price"),
                "leverage_value": snap.get("leverage_value"),
                "unrealized_pnl": snap.get("unrealized_pnl"),
            },
        }

    # ---- screenshot_config ---------------------------------------

    def screenshot_config(self) -> ScreenshotConfig:
        """Return capture config for the position explorer page."""
        return ScreenshotConfig(
            pages=[
                PageCapture(
                    route="/positions",
                    wait_selector='[data-testid="position-explorer"]',
                    capture_selector='[data-testid="position-explorer"]',
                    filename="token_spotlight.png",
                ),
            ]
        )
