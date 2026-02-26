"""Integration tests for FastAPI router endpoints.

Uses httpx.AsyncClient with ASGITransport to test endpoints against the real
FastAPI app with mocked DataStore, NansenClient, and CacheLayer dependencies.
"""
from __future__ import annotations

import os

os.environ["TESTING"] = "1"

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
import pytest
from httpx import ASGITransport

from backend.cache import CacheLayer
from backend.dependencies import get_cache, get_datastore, get_nansen_client
from backend.main import app
from src.models import TradeMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metrics(**overrides) -> TradeMetrics:
    """Return a TradeMetrics with reasonable defaults."""
    defaults = dict(
        window_days=30,
        total_trades=50,
        winning_trades=30,
        losing_trades=20,
        win_rate=0.6,
        gross_profit=15000.0,
        gross_loss=5000.0,
        profit_factor=3.0,
        avg_return=0.05,
        std_return=0.03,
        pseudo_sharpe=1.67,
        total_pnl=10000.0,
        roi_proxy=20.0,
        max_drawdown_proxy=0.05,
        max_leverage=5.0,
        leverage_std=1.2,
        largest_trade_pnl_ratio=0.15,
        pnl_trend_slope=0.001,
        total_fills=120,
    )
    defaults.update(overrides)
    return TradeMetrics(**defaults)


ADDR_A = "0x" + "a1" * 20  # 0xa1a1...a1a1
ADDR_B = "0x" + "b2" * 20


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_datastore():
    """Return a MagicMock DataStore with default no-data returns."""
    ds = MagicMock()
    # Stub a real sqlite-like _conn.execute for health check
    conn_mock = MagicMock()
    conn_mock.execute.return_value = True
    ds._conn = conn_mock

    # Default empty returns
    ds.get_latest_scores.return_value = {}
    ds.get_latest_allocations.return_value = {}
    ds.get_allocation_history.return_value = []
    ds.get_latest_metrics.return_value = None
    ds.get_trader.return_value = None
    ds.get_trader_label.return_value = None
    ds.is_blacklisted.return_value = False
    ds.get_latest_position_snapshot.return_value = []
    ds.get_last_trade_time.return_value = None
    ds.get_latest_allocation_timestamp.return_value = None
    return ds


@pytest.fixture
def mock_nansen():
    """Return an AsyncMock NansenClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_cache():
    """Return a real CacheLayer (in-memory, no external deps)."""
    return CacheLayer()


@pytest.fixture
async def client(mock_datastore, mock_nansen, mock_cache):
    """Async httpx test client with dependency overrides."""
    app.dependency_overrides[get_datastore] = lambda: mock_datastore
    app.dependency_overrides[get_nansen_client] = lambda: mock_nansen
    app.dependency_overrides[get_cache] = lambda: mock_cache

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ===========================================================================
# 1. GET /api/v1/health
# ===========================================================================


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    async def test_health_ok(self, client, mock_datastore):
        """Health returns 200 with status fields when DB is accessible."""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db_connected"] is True
        assert "nansen_key_set" in body

    async def test_health_degraded_when_db_fails(self, client, mock_datastore):
        """Health returns degraded status when DB execute raises."""
        mock_datastore._conn.execute.side_effect = Exception("DB down")

        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db_connected"] is False


# ===========================================================================
# 2. GET /api/v1/leaderboard
# ===========================================================================


class TestLeaderboardEndpoint:
    """Tests for the leaderboard endpoint."""

    async def test_leaderboard_from_datastore(self, client, mock_datastore):
        """Returns leaderboard from DataStore scores when available."""
        mock_datastore.get_latest_scores.return_value = {
            ADDR_A: {
                "final_score": 85.0,
                "passes_anti_luck": 1,
                "normalized_roi": 0.9,
                "normalized_sharpe": 0.8,
                "normalized_win_rate": 0.7,
                "consistency_score": 0.6,
                "smart_money_bonus": 0.1,
                "risk_management_score": 0.5,
            },
        }
        mock_datastore.get_latest_allocations.return_value = {ADDR_A: 0.25}
        mock_datastore.get_latest_metrics.return_value = _make_metrics()
        mock_datastore.get_trader.return_value = {"label": "TestTrader"}
        mock_datastore.get_trader_label.return_value = "TestTrader"
        mock_datastore.is_blacklisted.return_value = False

        resp = await client.get("/api/v1/leaderboard")
        assert resp.status_code == 200
        body = resp.json()

        assert body["source"] == "datastore"
        assert body["timeframe"] == "30d"
        assert len(body["traders"]) == 1

        trader = body["traders"][0]
        assert trader["rank"] == 1
        assert trader["address"] == ADDR_A
        assert trader["score"] == 85.0
        assert trader["allocation_weight"] == 0.25
        assert trader["win_rate"] == 0.6
        assert trader["num_trades"] == 50

    async def test_leaderboard_empty_datastore_falls_to_nansen(
        self, client, mock_datastore, mock_nansen
    ):
        """Falls back to Nansen API when DataStore has no scores."""
        mock_datastore.get_latest_scores.return_value = {}

        # Mock the Nansen leaderboard response
        entry = MagicMock()
        entry.trader_address = ADDR_A
        entry.trader_address_label = None
        entry.total_pnl = 5000.0
        entry.roi = 15.0
        mock_nansen.fetch_leaderboard.return_value = [entry]

        resp = await client.get("/api/v1/leaderboard")
        assert resp.status_code == 200
        body = resp.json()

        assert body["source"] == "nansen_api"
        assert len(body["traders"]) >= 1
        assert body["traders"][0]["pnl_usd"] == 5000.0

    async def test_leaderboard_with_sort_and_limit(self, client, mock_datastore):
        """Respects sort_by and limit query params."""
        mock_datastore.get_latest_scores.return_value = {
            ADDR_A: {"final_score": 80.0, "passes_anti_luck": 1},
            ADDR_B: {"final_score": 90.0, "passes_anti_luck": 1},
        }
        mock_datastore.get_latest_allocations.return_value = {}
        mock_datastore.get_latest_metrics.return_value = _make_metrics()

        resp = await client.get("/api/v1/leaderboard?limit=1&sort_by=score")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["traders"]) == 1
        # Highest score first
        assert body["traders"][0]["score"] == 90.0


# ===========================================================================
# 3. GET /api/v1/allocations
# ===========================================================================


class TestAllocationsEndpoint:
    """Tests for the allocations endpoint."""

    async def test_allocations_from_datastore(self, client, mock_datastore):
        """Returns allocations from DataStore when available."""
        mock_datastore.get_latest_allocations.return_value = {
            ADDR_A: 0.6,
            ADDR_B: 0.4,
        }
        mock_datastore.get_latest_scores.return_value = {}
        mock_datastore.get_latest_allocation_timestamp.return_value = (
            "2026-02-26T12:00:00+00:00"
        )

        resp = await client.get("/api/v1/allocations")
        assert resp.status_code == 200
        body = resp.json()

        assert body["total_allocated_traders"] == 2
        assert len(body["allocations"]) == 2
        assert "softmax_temperature" in body
        assert "risk_caps" in body
        assert body["computed_at"] == "2026-02-26T12:00:00+00:00"

        # Verify weights are present and sum close to 1.0
        weights = [a["weight"] for a in body["allocations"]]
        assert abs(sum(weights) - 1.0) < 0.01

    async def test_allocations_empty_returns_mock_or_empty(
        self, client, mock_datastore
    ):
        """Empty DataStore returns either mock data (if enabled) or empty list."""
        mock_datastore.get_latest_allocations.return_value = {}
        mock_datastore.get_latest_scores.return_value = {}

        resp = await client.get("/api/v1/allocations")
        assert resp.status_code == 200
        body = resp.json()

        # MOCK_STRATEGY_DATA is False by default, so we get empty allocations
        assert "allocations" in body
        assert "risk_caps" in body
        assert isinstance(body["allocations"], list)

    async def test_allocations_response_shape(self, client, mock_datastore):
        """Verify full response shape matches AllocationsResponse schema."""
        mock_datastore.get_latest_allocations.return_value = {ADDR_A: 1.0}
        mock_datastore.get_latest_scores.return_value = {}
        mock_datastore.get_latest_allocation_timestamp.return_value = (
            "2026-02-26T12:00:00+00:00"
        )

        resp = await client.get("/api/v1/allocations")
        assert resp.status_code == 200
        body = resp.json()

        # Top-level keys
        assert set(body.keys()) >= {
            "allocations",
            "softmax_temperature",
            "total_allocated_traders",
            "risk_caps",
        }

        # Risk caps structure
        rc = body["risk_caps"]
        for dim in ["position_count", "max_token_exposure", "directional_long", "directional_short"]:
            assert dim in rc
            assert "current" in rc[dim]
            assert "max" in rc[dim]


# ===========================================================================
# 4. GET /api/v1/allocations/history
# ===========================================================================


class TestAllocationHistoryEndpoint:
    """Tests for the allocation history endpoint."""

    async def test_history_returns_snapshots(self, client, mock_datastore):
        """Returns historical snapshots from DataStore."""
        ts = datetime.now(timezone.utc).isoformat()
        mock_datastore.get_allocation_history.return_value = [
            {
                "computed_at": ts,
                "allocations": [
                    {"address": ADDR_A, "final_weight": 0.7, "label": None},
                    {"address": ADDR_B, "final_weight": 0.3, "label": None},
                ],
            }
        ]

        resp = await client.get("/api/v1/allocations/history")
        assert resp.status_code == 200
        body = resp.json()

        assert body["days"] == 30  # default
        assert len(body["snapshots"]) == 1
        snap = body["snapshots"][0]
        assert snap["computed_at"] == ts
        assert len(snap["allocations"]) == 2

    async def test_history_with_days_param(self, client, mock_datastore):
        """The days parameter is passed through to DataStore."""
        mock_datastore.get_allocation_history.return_value = []

        resp = await client.get("/api/v1/allocations/history?days=7")
        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 7

        # Verify the DataStore was called with days=7
        mock_datastore.get_allocation_history.assert_called_once_with(days=7)

    async def test_history_empty(self, client, mock_datastore):
        """Empty history returns an empty snapshots list."""
        mock_datastore.get_allocation_history.return_value = []

        resp = await client.get("/api/v1/allocations/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["snapshots"] == []


# ===========================================================================
# 5. GET /api/v1/assess/{address}
# ===========================================================================


class TestAssessEndpoint:
    """Tests for the trader assessment endpoint."""

    async def test_assess_invalid_address_format(self, client):
        """Returns 400 for a non-0x address."""
        resp = await client.get("/api/v1/assess/not-a-valid-address")
        assert resp.status_code == 400
        assert "Invalid address" in resp.json()["detail"]

    async def test_assess_invalid_short_address(self, client):
        """Returns 400 for an 0x address that is too short."""
        resp = await client.get("/api/v1/assess/0x1234")
        assert resp.status_code == 400

    async def test_assess_valid_cached_address(self, client, mock_datastore):
        """Returns assessment for a cached address (metrics in DataStore)."""
        metrics = _make_metrics()
        mock_datastore.get_latest_metrics.return_value = metrics
        mock_datastore.get_last_trade_time.return_value = (
            datetime.now(timezone.utc).isoformat()
        )

        resp = await client.get(f"/api/v1/assess/{ADDR_A}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["address"] == ADDR_A
        assert body["is_cached"] is True
        assert body["window_days"] == 30
        assert body["trade_count"] == 120  # total_fills
        assert "confidence" in body
        assert "strategies" in body
        assert body["confidence"]["total"] == 10  # 10 strategies
        assert isinstance(body["strategies"], list)
        assert len(body["strategies"]) == 10

    async def test_assess_valid_live_fetch(
        self, client, mock_datastore, mock_nansen
    ):
        """Returns assessment for an uncached address (fetches from Nansen)."""
        mock_datastore.get_latest_metrics.return_value = None
        mock_datastore.get_last_trade_time.return_value = None

        # Mock Nansen positions response
        pos_snapshot = MagicMock()
        pos_snapshot.margin_summary_account_value_usd = "50000.0"
        pos_snapshot.asset_positions = []
        mock_nansen.fetch_address_positions.return_value = pos_snapshot

        # Mock Nansen trades response (empty list = 0 trades)
        mock_nansen.fetch_address_trades.return_value = []

        resp = await client.get(f"/api/v1/assess/{ADDR_A}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["address"] == ADDR_A
        assert body["is_cached"] is False
        assert "confidence" in body
        assert "strategies" in body

    async def test_assess_response_strategy_shape(self, client, mock_datastore):
        """Each strategy result has name, category, score, passed, explanation."""
        metrics = _make_metrics()
        mock_datastore.get_latest_metrics.return_value = metrics
        mock_datastore.get_last_trade_time.return_value = (
            datetime.now(timezone.utc).isoformat()
        )

        resp = await client.get(f"/api/v1/assess/{ADDR_A}")
        assert resp.status_code == 200
        body = resp.json()

        for strategy in body["strategies"]:
            assert "name" in strategy
            assert "category" in strategy
            assert "score" in strategy
            assert "passed" in strategy
            assert "explanation" in strategy
            assert isinstance(strategy["score"], int)
            assert isinstance(strategy["passed"], bool)

    async def test_assess_confidence_tiers(self, client, mock_datastore):
        """Confidence tier is one of the expected values."""
        metrics = _make_metrics()
        mock_datastore.get_latest_metrics.return_value = metrics
        mock_datastore.get_last_trade_time.return_value = (
            datetime.now(timezone.utc).isoformat()
        )

        resp = await client.get(f"/api/v1/assess/{ADDR_A}")
        assert resp.status_code == 200
        body = resp.json()

        valid_tiers = {"Elite", "Strong", "Moderate", "Weak", "Avoid", "Insufficient Data"}
        assert body["confidence"]["tier"] in valid_tiers
