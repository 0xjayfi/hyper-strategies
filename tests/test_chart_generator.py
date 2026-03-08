"""Tests for chart generation."""

import pytest
from pathlib import Path
from src.chart_generator import generate_charts, CHART_TYPES


@pytest.fixture
def sample_payload():
    return {
        "post_worthy": True,
        "snapshot_date": "2026-03-08",
        "wallet": {
            "address": "0xBBB",
            "label": "Token Millionaire",
            "smart_money": True,
        },
        "change": {
            "old_rank": 5,
            "new_rank": 2,
            "rank_delta": 3,
            "old_score": 0.65,
            "new_score": 0.78,
            "score_delta": 0.13,
            "new_entrant": False,
        },
        "current_dimensions": {
            "growth": 0.72,
            "drawdown": 0.99,
            "leverage": 0.85,
            "liq_distance": 1.00,
            "diversity": 0.88,
            "consistency": 0.60,
        },
        "previous_dimensions": {
            "growth": 0.55,
            "drawdown": 0.92,
            "leverage": 0.80,
            "liq_distance": 0.95,
            "diversity": 0.88,
            "consistency": 0.60,
        },
        "top_movers": [
            {"dimension": "growth", "delta": 0.17},
            {"dimension": "drawdown", "delta": 0.07},
        ],
        "context": {
            "top_5_wallets": [
                {"address": "0xAAA", "label": "Smart Trader", "score": 0.80, "rank": 1, "smart_money": True},
                {"address": "0xBBB", "label": "Token Millionaire", "score": 0.78, "rank": 2, "smart_money": True},
                {"address": "0xCCC", "label": "Whale", "score": 0.70, "rank": 3, "smart_money": False},
                {"address": "0xDDD", "label": "Yield Farmer", "score": 0.65, "rank": 4, "smart_money": True},
                {"address": "0xEEE", "label": "Degen", "score": 0.50, "rank": 5, "smart_money": False},
            ],
        },
    }


class TestChartGenerator:

    def test_generates_png_files(self, sample_payload, tmp_path):
        chart_paths = generate_charts(sample_payload, output_dir=str(tmp_path), count=1)
        assert len(chart_paths) >= 1
        for p in chart_paths:
            path = Path(p)
            assert path.exists()
            assert path.suffix == ".png"
            assert path.stat().st_size > 0

    def test_generates_up_to_count(self, sample_payload, tmp_path):
        chart_paths = generate_charts(sample_payload, output_dir=str(tmp_path), count=2)
        assert len(chart_paths) <= 2

    def test_all_chart_types_callable(self, sample_payload, tmp_path):
        """Each chart type function runs without error."""
        for chart_type, func in CHART_TYPES.items():
            out = tmp_path / f"test_{chart_type}.png"
            func(sample_payload, str(out))
            assert out.exists()
            assert out.stat().st_size > 0
