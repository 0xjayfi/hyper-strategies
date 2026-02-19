"""Filter variant definitions for the grid search and live runs."""

from __future__ import annotations

VARIANTS: dict[str, dict] = {
    "V1": {
        "FILTER_PERCENTILE": 0.50,
        "WIN_RATE_MIN": 0.30,
        "WIN_RATE_MAX": 0.95,
        "TREND_TRADER_MIN_PF": 2.5,
        "TREND_TRADER_MAX_WR": 0.40,
        "hft_tpd": 5.0,
        "hft_ahh": 4.0,
        "position_mult": 0.8,
        "weights": {
            "roi": 0.25,
            "sharpe": 0.20,
            "win_rate": 0.15,
            "consistency": 0.20,
            "smart_money": 0.10,
            "risk_mgmt": 0.10,
        },
    },
    "V2": {
        "FILTER_PERCENTILE": 0.65,
        "WIN_RATE_MIN": 0.45,
        "WIN_RATE_MAX": 0.92,
        "TREND_TRADER_MIN_PF": 3.0,
        "TREND_TRADER_MAX_WR": 0.35,
        "hft_tpd": 4.0,
        "hft_ahh": 6.0,
        "position_mult": 0.7,
        "weights": {
            "roi": 0.25,
            "sharpe": 0.20,
            "win_rate": 0.15,
            "consistency": 0.20,
            "smart_money": 0.10,
            "risk_mgmt": 0.10,
        },
    },
    "V3": {
        "FILTER_PERCENTILE": 0.35,
        "WIN_RATE_MIN": 0.25,
        "WIN_RATE_MAX": 0.97,
        "TREND_TRADER_MIN_PF": 2.0,
        "TREND_TRADER_MAX_WR": 0.45,
        "hft_tpd": 5.0,
        "hft_ahh": 4.0,
        "position_mult": 0.85,
        "weights": {
            "roi": 0.25,
            "sharpe": 0.20,
            "win_rate": 0.15,
            "consistency": 0.20,
            "smart_money": 0.10,
            "risk_mgmt": 0.10,
        },
    },
    "V4": {
        "FILTER_PERCENTILE": 0.50,
        "WIN_RATE_MIN": 0.30,
        "WIN_RATE_MAX": 0.95,
        "TREND_TRADER_MIN_PF": 2.5,
        "TREND_TRADER_MAX_WR": 0.40,
        "hft_tpd": 5.0,
        "hft_ahh": 4.0,
        "position_mult": 0.8,
        "weights": {
            "roi": 0.35,
            "sharpe": 0.30,
            "win_rate": 0.10,
            "consistency": 0.10,
            "smart_money": 0.05,
            "risk_mgmt": 0.10,
        },
    },
    "V5": {
        "FILTER_PERCENTILE": 0.45,
        "WIN_RATE_MIN": 0.30,
        "WIN_RATE_MAX": 0.97,
        "TREND_TRADER_MIN_PF": 2.5,
        "TREND_TRADER_MAX_WR": 0.40,
        "hft_tpd": 5.0,
        "hft_ahh": 4.0,
        "position_mult": 0.9,
        "weights": {
            "roi": 0.30,
            "sharpe": 0.20,
            "win_rate": 0.15,
            "consistency": 0.15,
            "smart_money": 0.10,
            "risk_mgmt": 0.10,
        },
    },
}

VARIANT_LABELS: dict[str, str] = {
    "V1": "Baseline",
    "V2": "Quality Focused",
    "V3": "Volume Relaxed",
    "V4": "ROI Heavy",
    "V5": "Hybrid Balanced",
}

VARIANT_DESCRIPTIONS: dict[str, str] = {
    "V1": (
        "The default balanced strategy. Uses median (50th percentile) filter cutoffs "
        "with standard scoring weights spread evenly across ROI, Sharpe, win rate, "
        "consistency, smart money, and risk management. Good all-around starting point."
    ),
    "V2": (
        "Prioritizes trader quality over quantity. Raises the filter percentile to 65th, "
        "requiring higher win rates (45%+) and profit factors (3.0+). Keeps the same "
        "balanced scoring weights but only passes the most consistent, high-quality traders."
    ),
    "V3": (
        "Relaxes filters to cast a wider net. Lowers the percentile cutoff to 35th "
        "and accepts win rates as low as 25%. Allows more trend-following traders through "
        "with lower profit factor requirements. Best when the leaderboard is thin."
    ),
    "V4": (
        "Heavily weights raw ROI (35%) and Sharpe ratio (30%) in scoring, reducing "
        "emphasis on win rate and consistency. Same filters as Baseline but favors "
        "traders who generate outsized returns, even if less consistent."
    ),
    "V5": (
        "A hybrid approach balancing return and stability. Slightly relaxed filters "
        "(45th percentile) with a higher position multiplier (0.9). Weights ROI at 30% "
        "with moderate Sharpe/consistency. Aims for steady, diversified exposure."
    ),
}


def format_variant_details(key: str) -> str:
    """Generate a formatted parameter summary for a variant."""
    v = VARIANTS.get(key)
    if not v:
        return ""
    w = v.get("weights", {})
    lines = [
        VARIANT_DESCRIPTIONS.get(key, ""),
        "",
        "Parameters:",
        f"  Filter Percentile:   {v.get('FILTER_PERCENTILE', 0):.0%}",
        f"  Win Rate Range:      {v.get('WIN_RATE_MIN', 0):.0%} – {v.get('WIN_RATE_MAX', 0):.0%}",
        f"  Min Profit Factor:   {v.get('TREND_TRADER_MIN_PF', 0):.1f}",
        f"  Position Multiplier: {v.get('position_mult', 0):.2f}",
        "",
        "Scoring Weights:",
        f"  ROI:         {w.get('roi', 0):>5.0%}   Sharpe:      {w.get('sharpe', 0):>5.0%}",
        f"  Win Rate:    {w.get('win_rate', 0):>5.0%}   Consistency: {w.get('consistency', 0):>5.0%}",
        f"  Smart Money: {w.get('smart_money', 0):>5.0%}   Risk Mgmt:   {w.get('risk_mgmt', 0):>5.0%}",
    ]
    return "\n".join(lines)
