"""Wallet Spotlight angle — highlights a single top mover each day.

Compares today vs yesterday score_snapshots to find the wallet with
the most significant rank/score change, then builds a detailed payload
for the writer agent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.content.base import ContentAngle, PageCapture, ScreenshotConfig

logger = logging.getLogger(__name__)

# Dimension columns used for top-mover computation
_DIMENSIONS = [
    ("growth", "growth_score"),
    ("drawdown", "drawdown_score"),
    ("leverage", "leverage_score"),
    ("liq_distance", "liq_distance_score"),
    ("diversity", "diversity_score"),
    ("consistency", "consistency_score"),
]


# ------------------------------------------------------------------
# Helpers (adapted from content_pipeline.py)
# ------------------------------------------------------------------


def _detect_score_movers(
    datastore,
    today,
    yesterday,
    *,
    min_rank_change: int = 2,
    min_score_delta: float = 0.10,
    top_n: int = 5,
) -> list[dict]:
    """Detect wallets with significant rank or score changes between two days.

    Returns a list of mover dicts sorted by combined change magnitude (largest
    first).
    """
    today_rows = datastore.get_score_snapshots_for_date(today)
    yesterday_rows = datastore.get_score_snapshots_for_date(yesterday)

    if not today_rows or not yesterday_rows:
        logger.info(
            "Missing snapshot data for comparison (today=%s, yesterday=%s)",
            today,
            yesterday,
        )
        return []

    yesterday_map = {r["trader_id"]: r for r in yesterday_rows}

    movers: list[dict] = []
    for row in today_rows:
        addr = row["trader_id"]
        if addr not in yesterday_map:
            if row["rank"] <= top_n:
                movers.append(
                    {
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
                    }
                )
            continue

        prev = yesterday_map[addr]
        rank_delta = prev["rank"] - row["rank"]  # positive = improved
        score_delta = row["composite_score"] - prev["composite_score"]

        is_rank_mover = abs(rank_delta) >= min_rank_change
        is_score_mover = abs(score_delta) >= min_score_delta

        entered_top_n = row["rank"] <= top_n and prev["rank"] > top_n
        exited_top_n = row["rank"] > top_n and prev["rank"] <= top_n

        if is_rank_mover or is_score_mover or entered_top_n or exited_top_n:
            movers.append(
                {
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
                }
            )

    def _sort_key(m: dict) -> float:
        rd = abs(m["rank_delta"] or 0)
        sd = abs(m["score_delta"] or 0)
        return rd + sd * 10

    movers.sort(key=_sort_key, reverse=True)
    return movers


def _compute_top_dimension_movers(
    today_row: dict, yesterday_row: dict | None
) -> list[dict]:
    """Find the 2-3 dimensions that changed most between days."""
    if yesterday_row is None:
        return []

    deltas: list[dict] = []
    for name, col in _DIMENSIONS:
        old_val = yesterday_row.get(col, 0.0) or 0.0
        new_val = today_row.get(col, 0.0) or 0.0
        delta = new_val - old_val
        if abs(delta) > 0.001:
            deltas.append({"dimension": name, "delta": round(delta, 4)})

    deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return deltas[:3]


async def _fetch_current_positions(address: str, nansen_client) -> list[dict]:
    """Fetch live positions for a wallet via the Nansen API.

    Returns a simplified list of position dicts for the content payload.
    """
    try:
        snapshot = await nansen_client.fetch_address_positions(address)
    except Exception:
        logger.exception("Failed to fetch positions for %s", address)
        return []

    positions: list[dict] = []
    for ap in snapshot.asset_positions:
        p = ap.position
        size = float(p.size)
        positions.append(
            {
                "token": p.token_symbol,
                "side": "Long" if size > 0 else "Short",
                "position_value_usd": round(float(p.position_value_usd), 2),
                "entry_price": round(float(p.entry_price_usd), 2),
                "leverage": p.leverage_value,
                "liquidation_price": (
                    round(float(p.liquidation_price_usd), 2)
                    if p.liquidation_price_usd
                    else None
                ),
                "unrealized_pnl_usd": (
                    round(float(p.unrealized_pnl_usd), 2)
                    if p.unrealized_pnl_usd
                    else None
                ),
            }
        )

    positions.sort(key=lambda x: abs(x["position_value_usd"]), reverse=True)
    return positions


# ------------------------------------------------------------------
# Wallet Spotlight angle
# ------------------------------------------------------------------


class WalletSpotlight(ContentAngle):
    """Detects the single most interesting wallet move each day."""

    angle_type = "wallet_spotlight"
    auto_publish = False
    cooldown_days = 2
    tone = "analytical"

    def __init__(self) -> None:
        self._mover: Optional[dict] = None

    # ---- detect --------------------------------------------------

    def detect(self, datastore, nansen_client=None) -> float:
        """Score the top mover between today and yesterday.

        Returns a value in [0, 1] or 0 when no mover meets the threshold.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        movers = _detect_score_movers(datastore, today, yesterday)
        if not movers:
            return 0.0

        top = movers[0]
        score_delta = abs(top["score_delta"] or 0)
        rank_change = abs(top["rank_delta"] or 0)
        new_entrant = top["new_entrant"]

        # Check if wallet entered or exited top 5
        entered_top5 = (
            not new_entrant
            and top["new_rank"] <= 5
            and (top["old_rank"] is not None and top["old_rank"] > 5)
        )
        exited_top5 = (
            not new_entrant
            and top["new_rank"] > 5
            and (top["old_rank"] is not None and top["old_rank"] <= 5)
        )
        top5_change = entered_top5 or exited_top5 or new_entrant

        # Threshold gate
        if score_delta < 0.10 and rank_change < 2 and not top5_change:
            return 0.0

        # Scoring formula
        top5_floor = 0.5 if top5_change else 0.0
        raw = (score_delta / 0.30) * 0.5 + (rank_change / 10) * 0.5
        score = max(top5_floor, min(1.0, raw))

        self._mover = top
        return score

    # ---- build_payload -------------------------------------------

    def build_payload(self, datastore, nansen_client=None) -> dict:
        """Build the content payload for the detected top mover."""
        today = datetime.now(timezone.utc).date()
        mover = self._mover
        assert mover is not None, "detect() must be called before build_payload()"

        top_dimension_movers = _compute_top_dimension_movers(
            mover["today"], mover.get("yesterday")
        )

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

        # Build dimension dicts
        current_dims: dict[str, float] = {}
        previous_dims: dict[str, float] = {}
        for name, col in _DIMENSIONS:
            current_dims[name] = mover["today"].get(col, 0.0) or 0.0
            if mover.get("yesterday"):
                previous_dims[name] = mover["yesterday"].get(col, 0.0) or 0.0

        label = datastore.get_trader_label(mover["address"])

        # Fetch live positions if nansen_client is available
        current_positions: list[dict] = []
        if nansen_client is not None:
            current_positions = asyncio.run(
                _fetch_current_positions(mover["address"], nansen_client)
            )
            logger.info(
                "Fetched %d live positions for %s",
                len(current_positions),
                mover["address"],
            )

        return {
            "post_worthy": True,
            "snapshot_date": today.isoformat(),
            "wallet": {
                "address": mover["address"],
                "label": label,
                "smart_money": bool(mover["today"].get("smart_money")),
            },
            "change": {
                "old_rank": mover["old_rank"],
                "new_rank": mover["new_rank"],
                "rank_delta": mover["rank_delta"],
                "old_score": mover["old_score"],
                "new_score": mover["new_score"],
                "score_delta": mover["score_delta"],
                "new_entrant": mover["new_entrant"],
            },
            "current_dimensions": current_dims,
            "previous_dimensions": previous_dims,
            "top_movers": top_dimension_movers,
            "current_positions": current_positions,
            "context": {
                "top_5_wallets": top_5,
            },
        }

    # ---- load_payload ---------------------------------------------

    def load_payload(self, payload: dict) -> None:
        """Hydrate _mover from a saved payload so screenshot_config works."""
        wallet = payload.get("wallet")
        if wallet:
            self._mover = {"address": wallet["address"]}

    # ---- screenshot_config ---------------------------------------

    def screenshot_config(self) -> ScreenshotConfig:
        """Return capture config for leaderboard + trader detail pages."""
        address = self._mover["address"] if self._mover else "unknown"
        return ScreenshotConfig(
            pages=[
                PageCapture(
                    route="/leaderboard",
                    wait_selector='[data-testid="leaderboard-table"]',
                    capture_selector='[data-testid="leaderboard-table"]',
                    filename="leaderboard_top5.png",
                    pre_capture_js=(
                        "document.querySelectorAll('[data-testid=\"leaderboard-table\"] tbody tr')"
                        ".forEach((r, i) => { if (i >= 5) r.style.display = 'none'; });"
                    ),
                ),
                PageCapture(
                    route=f"/traders/{address}",
                    wait_selector='[data-testid="trader-scoring"]',
                    capture_selector='[data-testid="trader-scoring"]',
                    filename="trader_scoring.png",
                ),
                PageCapture(
                    route=f"/traders/{address}",
                    wait_selector='[data-testid="trader-overview"]',
                    capture_selector='[data-testid="trader-overview"]',
                    filename="trader_positions.png",
                ),
            ]
        )
