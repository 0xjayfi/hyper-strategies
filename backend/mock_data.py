"""Deterministic mock data generators for frontend development."""
import hashlib
import math
from datetime import datetime, timedelta, timezone


def _seed_from_address(address: str) -> int:
    """Create a deterministic seed from an address."""
    return int(hashlib.sha256(address.encode()).hexdigest()[:8], 16)


def generate_mock_score(address: str) -> dict:
    """Generate deterministic mock score breakdown."""
    seed = _seed_from_address(address)

    def val(offset: int) -> float:
        return 0.3 + 0.7 * ((seed + offset) % 1000) / 1000

    return {
        "roi": val(1),
        "sharpe": val(2),
        "win_rate": val(3),
        "consistency": val(4),
        "smart_money": val(5),
        "risk_mgmt": val(6),
        "style_multiplier": 1.0,
        "recency_decay": 0.95,
        "final_score": (
            0.25 * val(1)
            + 0.20 * val(2)
            + 0.15 * val(3)
            + 0.20 * val(4)
            + 0.10 * val(5)
            + 0.10 * val(6)
        ),
    }


def generate_mock_pnl_curve(address: str, days: int = 90) -> list[dict]:
    """Generate a deterministic mock PnL curve (random walk with upward drift)."""
    seed = _seed_from_address(address)
    points: list[dict] = []
    pnl = 0.0
    now = datetime.now(timezone.utc)
    for i in range(days):
        step = math.sin(seed * 0.1 + i * 0.7) * 5000 + 1000  # upward drift
        pnl += step
        ts = (now - timedelta(days=days - i)).isoformat()
        points.append({"timestamp": ts, "cumulative_pnl": round(pnl, 2)})
    return points


def generate_mock_allocation_weight(address: str) -> float:
    """Generate a deterministic mock allocation weight."""
    seed = _seed_from_address(address)
    return round(0.02 + 0.18 * (seed % 1000) / 1000, 4)


def generate_mock_allocations(n_traders: int = 8) -> list[dict]:
    """Generate mock allocation entries."""
    addresses = [f"0x{'0' * 37}{i:03d}" for i in range(n_traders)]
    labels = [
        "Smart Whale", "Top Trader", "Momentum King", "DeFi Degen",
        "Whale #5", "Fund Alpha", "HL Pro", "Swing Master",
    ]
    raw_weights = [generate_mock_allocation_weight(a) for a in addresses]
    total = sum(raw_weights)
    entries = []
    for i, addr in enumerate(addresses):
        entries.append({
            "address": addr,
            "label": labels[i] if i < len(labels) else None,
            "weight": round(raw_weights[i] / total, 4) if total > 0 else 0.0,
            "roi_tier": [1.0, 0.75, 0.5][i % 3],
        })
    return entries


def generate_mock_index_portfolio() -> list[dict]:
    """Generate mock index portfolio entries for Strategy #2."""
    return [
        {"token": "BTC", "side": "Long", "target_weight": 0.35, "target_usd": 35000},
        {"token": "ETH", "side": "Long", "target_weight": 0.25, "target_usd": 25000},
        {"token": "SOL", "side": "Long", "target_weight": 0.20, "target_usd": 20000},
        {"token": "HYPE", "side": "Short", "target_weight": 0.10, "target_usd": 10000},
    ]


def generate_mock_consensus() -> dict:
    """Generate mock consensus data for Strategy #3."""
    return {
        "BTC": {"direction": "Long", "confidence": 0.78, "voter_count": 5},
        "ETH": {"direction": "Short", "confidence": 0.62, "voter_count": 3},
        "SOL": {"direction": "Long", "confidence": 0.71, "voter_count": 4},
        "HYPE": {"direction": "Long", "confidence": 0.55, "voter_count": 2},
    }
