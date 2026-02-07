"""Trader scoring, classification, filtering, and tier assignment.

Phase 3 (Tasks 3.1-3.6): daily scoring pipeline that evaluates traders from
the Nansen leaderboard, computes composite scores with recency decay, classifies
trading styles, applies selection filters, and assigns copy-trading tiers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean, stdev

import structlog

from src.config import settings
from src import db
from src.nansen_client import NansenClient, map_leaderboard_entry, map_trade

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Task 3.1 — Daily scoring job
# ---------------------------------------------------------------------------


async def refresh_trader_scores(client: NansenClient) -> None:
    """Fetch leaderboard data, score every candidate, and persist results.

    This is the main entry point called once per day by the scheduler.
    """
    now = datetime.now(timezone.utc)
    date_to = now.isoformat()

    # ---- 1. Fetch leaderboards for three look-back windows ----
    windows = {
        "7d": (now - timedelta(days=7)).isoformat(),
        "30d": (now - timedelta(days=30)).isoformat(),
        "90d": (now - timedelta(days=90)).isoformat(),
    }

    raw_boards: dict[str, list[dict]] = {}
    for label, date_from in windows.items():
        raw_boards[label] = await client.get_perp_leaderboard(date_from, date_to)
        log.info("leaderboard_fetched", window=label, count=len(raw_boards[label]))

    # ---- 2. Merge into a unified dict keyed by address ----
    traders: dict[str, dict] = {}
    for window_label, raw_entries in raw_boards.items():
        for raw in raw_entries:
            entry = map_leaderboard_entry(raw)
            addr = entry["address"]
            if addr not in traders:
                traders[addr] = {
                    "address": addr,
                    "label": entry["label"],
                    "account_value": entry["account_value"],
                    "roi_7d": 0.0,
                    "roi_30d": 0.0,
                    "roi_90d": 0.0,
                }
            # Always keep the freshest label / account_value
            if entry["label"]:
                traders[addr]["label"] = entry["label"]
            if entry["account_value"]:
                traders[addr]["account_value"] = entry["account_value"]

            roi_key = f"roi_{window_label}"
            traders[addr][roi_key] = entry["roi"]

    log.info("traders_merged", unique_addresses=len(traders))

    # ---- 3-9. Score each candidate ----
    scored_traders: list[dict] = []
    date_from_90d = windows["90d"]

    # Look up existing DB records for blacklist info
    existing_rows = await db.get_all_traders()
    blacklist_map: dict[str, str | None] = {
        row["address"]: row.get("blacklisted_until") for row in existing_rows
    }

    for addr, trader in traders.items():
        try:
            # 3. Fetch 90-day trade history
            raw_trades = await client.get_address_perp_trades(
                addr, date_from_90d, date_to
            )

            # 4. Map trades
            mapped_trades = [map_trade(rt) for rt in raw_trades]

            # 5. Compute nof_trades (Close actions only) and win_rate
            close_trades = [t for t in mapped_trades if t.action == "Close"]
            nof_trades = len(close_trades)

            winning = sum(
                1
                for rt in raw_trades
                if rt.get("action") == "Close" and rt.get("closed_pnl") is not None and float(rt.get("closed_pnl", 0)) > 0
            )
            total_closes_raw = sum(
                1 for rt in raw_trades if rt.get("action") == "Close"
            )
            win_rate = winning / total_closes_raw if total_closes_raw > 0 else 0.0

            # 6. Classify style
            days_active = max(
                1,
                (now - datetime.fromisoformat(date_from_90d)).days,
            )
            style = classify_trader_style(mapped_trades, days_active)

            # 7. Selection filter
            blacklisted_until = blacklist_map.get(addr)
            if not passes_selection_filter(
                nof_trades=nof_trades,
                style=style,
                account_value=trader["account_value"],
                roi_30d=trader["roi_30d"],
                win_rate=win_rate,
                blacklisted_until=blacklisted_until,
            ):
                log.debug("trader_filtered_out", address=addr, style=style, nof_trades=nof_trades)
                continue

            # 8. Compute score
            score = compute_trader_score(
                trader=trader,
                trades_90d=raw_trades,
                roi_7d=trader["roi_7d"],
                roi_30d=trader["roi_30d"],
                roi_90d=trader["roi_90d"],
            )

            scored_traders.append(
                {
                    "address": addr,
                    "label": trader["label"],
                    "score": score,
                    "style": style,
                    "roi_7d": trader["roi_7d"],
                    "roi_30d": trader["roi_30d"],
                    "account_value": trader["account_value"],
                    "nof_trades": nof_trades,
                }
            )

        except Exception:
            log.exception("scoring_failed", address=addr)
            continue

    # ---- 9. Assign tiers ----
    scored_traders = assign_tiers(scored_traders)

    # ---- 10. Persist to DB ----
    now_iso = datetime.now(timezone.utc).isoformat()
    for t in scored_traders:
        await db.upsert_trader(
            address=t["address"],
            label=t["label"],
            score=t["score"],
            style=t["style"],
            tier=t.get("tier"),
            roi_7d=t["roi_7d"],
            roi_30d=t["roi_30d"],
            account_value=t["account_value"],
            nof_trades=t["nof_trades"],
            last_scored_at=now_iso,
        )

    log.info(
        "scoring_complete",
        total_scored=len(scored_traders),
        primary=sum(1 for t in scored_traders if t.get("tier") == "primary"),
        secondary=sum(1 for t in scored_traders if t.get("tier") == "secondary"),
    )


# ---------------------------------------------------------------------------
# Task 3.2 — Style classification
# ---------------------------------------------------------------------------


def calculate_avg_hold_time(trades: list) -> float:
    """Compute the average hold time in hours across matched Open/Close pairs.

    Opens are matched to the next Close with the same *token_symbol* and *side*,
    ordered by timestamp.  If an Open has no subsequent Close the hold time is
    measured from the open to *now*.

    Returns 0.0 when there are no Open trades.
    """
    now = datetime.now(timezone.utc)

    # Separate opens and closes, sorted by timestamp
    opens: list = []
    closes: list = []
    for t in trades:
        if t.action == "Open":
            opens.append(t)
        elif t.action == "Close":
            closes.append(t)

    if not opens:
        return 0.0

    opens.sort(key=lambda t: t.timestamp)
    closes.sort(key=lambda t: t.timestamp)

    # Track which closes have been consumed
    used_close_indices: set[int] = set()
    hold_hours: list[float] = []

    for o in opens:
        open_ts = datetime.fromisoformat(o.timestamp)
        matched = False
        for idx, c in enumerate(closes):
            if idx in used_close_indices:
                continue
            if c.token_symbol == o.token_symbol and c.side == o.side:
                close_ts = datetime.fromisoformat(c.timestamp)
                if close_ts >= open_ts:
                    hold_hours.append((close_ts - open_ts).total_seconds() / 3600)
                    used_close_indices.add(idx)
                    matched = True
                    break
        if not matched:
            hold_hours.append((now - open_ts).total_seconds() / 3600)

    return sum(hold_hours) / len(hold_hours) if hold_hours else 0.0


def classify_trader_style(trades: list, days_active: int) -> str:
    """Classify a trader as HFT, SWING, or POSITION based on activity patterns."""
    trades_per_day = len(trades) / max(days_active, 1)
    avg_hold_time_hours = calculate_avg_hold_time(trades)

    if trades_per_day > 5 and avg_hold_time_hours < 4:
        return "HFT"
    elif trades_per_day >= 0.3 and avg_hold_time_hours < 336:
        return "SWING"
    else:
        return "POSITION"


# ---------------------------------------------------------------------------
# Task 3.3 — Composite scoring
# ---------------------------------------------------------------------------


def compute_trader_score(
    trader: dict,
    trades_90d: list,
    roi_7d: float,
    roi_30d: float,
    roi_90d: float,
) -> float:
    """Compute a composite trader score with recency decay.

    Args:
        trader: merged leaderboard entry with roi_7d, roi_30d, roi_90d, label.
        trades_90d: list of *raw* trade dicts (unmapped).
        roi_7d: ROI over the last 7 days.
        roi_30d: ROI over the last 30 days.
        roi_90d: ROI over the last 90 days.

    Returns:
        Final composite score (0-1 range, after decay).
    """
    weights = settings.TRADER_SCORE_WEIGHTS

    # 1. Normalized ROI (0-1)
    normalized_roi = min(1.0, max(0.0, roi_90d / 100))

    # 2. Pseudo-Sharpe ratio (0-1)
    close_returns: list[float] = []
    for rt in trades_90d:
        if rt.get("action") != "Close":
            continue
        closed_pnl = rt.get("closed_pnl")
        if closed_pnl is None:
            continue
        value_usd = float(rt.get("value_usd", 0))
        if value_usd <= 0:
            continue
        close_returns.append(float(closed_pnl) / value_usd)

    if len(close_returns) > 1:
        std_ret = stdev(close_returns)
        if std_ret > 0:
            normalized_sharpe = min(1.0, max(0.0, mean(close_returns) / std_ret / 3))
        else:
            normalized_sharpe = 0.0
    else:
        normalized_sharpe = 0.0

    # 3. Win rate (disqualify outliers)
    close_trades_raw = [rt for rt in trades_90d if rt.get("action") == "Close"]
    total_closes = len(close_trades_raw)
    if total_closes > 0:
        wins = sum(
            1 for rt in close_trades_raw
            if rt.get("closed_pnl") is not None and float(rt.get("closed_pnl", 0)) > 0
        )
        win_rate = wins / total_closes
    else:
        win_rate = 0.0

    if win_rate > 0.85 or win_rate < 0.35:
        return 0.0

    normalized_win_rate = win_rate  # already 0-1

    # 4. Consistency
    cons = consistency_score(roi_7d, roi_30d, roi_90d)

    # 5. Smart Money Bonus (0-1)
    label = trader.get("label") or ""
    if "Fund" in label:
        smart_money_bonus = 1.0
    elif "Smart" in label:
        smart_money_bonus = 0.8
    elif label:
        smart_money_bonus = 0.5
    else:
        smart_money_bonus = 0.0

    # 6. Risk Management (0-1) — based on average leverage
    leverages: list[float] = []
    for rt in trades_90d:
        value_usd = float(rt.get("value_usd", 0))
        margin_used = float(rt.get("margin_used", 0)) if rt.get("margin_used") else 0.0
        if margin_used > 0 and value_usd > 0:
            leverages.append(value_usd / margin_used)
        elif value_usd > 0:
            leverages.append(value_usd / value_usd)  # fallback = 1x

    if leverages:
        avg_leverage = sum(leverages) / len(leverages)
    else:
        avg_leverage = 1.0

    risk_management_score = min(1.0, max(0.0, 1 - (avg_leverage - 1) / 20))

    # 7. Weighted composite
    components = {
        "normalized_roi": normalized_roi,
        "normalized_sharpe": normalized_sharpe,
        "normalized_win_rate": normalized_win_rate,
        "consistency_score": cons,
        "smart_money_bonus": smart_money_bonus,
        "risk_management_score": risk_management_score,
    }

    raw_score = sum(components[k] * weights[k] for k in weights)

    # 8. Recency decay
    latest_ts: datetime | None = None
    for rt in trades_90d:
        ts_str = rt.get("timestamp")
        if ts_str:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts

    if latest_ts is not None:
        now = datetime.now(timezone.utc)
        age_days = (now - latest_ts).total_seconds() / 86400
        decay = 2 ** (-age_days / settings.RECENCY_DECAY_HALFLIFE_DAYS)
    else:
        decay = 1.0

    return raw_score * decay


# ---------------------------------------------------------------------------
# Task 3.4 — Consistency score
# ---------------------------------------------------------------------------


def consistency_score(roi_7d: float, roi_30d: float, roi_90d: float) -> float:
    """Evaluate how consistently profitable a trader has been across time windows.

    Returns a score between 0.2 and 1.0.
    """
    positives = sum(1 for r in (roi_7d, roi_30d, roi_90d) if r > 0)

    if positives == 3:
        base = 0.7
        weekly_equiv = [roi_7d, roi_30d / 4, roi_90d / 12]
        mean_val = sum(weekly_equiv) / len(weekly_equiv)
        variance = sum((x - mean_val) ** 2 for x in weekly_equiv) / len(weekly_equiv)
        bonus = max(0.0, 0.3 - variance / 100)
        return base + bonus

    if positives == 2:
        return 0.5

    return 0.2


# ---------------------------------------------------------------------------
# Task 3.5 — Selection filter
# ---------------------------------------------------------------------------


def passes_selection_filter(
    nof_trades: int,
    style: str,
    account_value: float,
    roi_30d: float,
    win_rate: float,
    blacklisted_until: str | None,
) -> bool:
    """Return True only if the trader passes every selection criterion."""
    if nof_trades < settings.MIN_TRADES_REQUIRED:
        return False
    if style == "HFT":
        return False
    if account_value < 50_000:
        return False
    if roi_30d <= 0:
        return False
    if not (0.35 <= win_rate <= 0.85):
        return False
    if blacklisted_until is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        if blacklisted_until >= now_iso:
            return False
    return True


# ---------------------------------------------------------------------------
# Task 3.6 — Tier assignment
# ---------------------------------------------------------------------------


def assign_tiers(scored_traders: list[dict]) -> list[dict]:
    """Assign copy-trading tiers based on score ranking.

    - Top 15  -> tier = "primary"   (active copy-trading)
    - Next 15 -> tier = "secondary" (monitoring pool)
    - Rest    -> tier = None        (dropped from rotation)
    """
    sorted_traders = sorted(scored_traders, key=lambda t: t["score"], reverse=True)

    for idx, trader in enumerate(sorted_traders):
        if idx < 15:
            trader["tier"] = "primary"
        elif idx < 30:
            trader["tier"] = "secondary"
        else:
            trader["tier"] = None

    return sorted_traders
