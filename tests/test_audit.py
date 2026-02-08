"""Tests for the audit and verification module (Phase 9).

Covers:
1. audit_risk_caps — risk limit verification
2. verify_stop_triggers — stop type confirmation
3. compare_paper_pnl — PnL comparison
4. generate_audit_report — markdown report generation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from snap.config import (
    MAX_SINGLE_POSITION_HARD_CAP,
    MAX_SINGLE_POSITION_PCT,
    MAX_TOTAL_EXPOSURE_PCT,
    MAX_TOTAL_POSITIONS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.database import get_connection, init_db
from snap.audit import (
    audit_risk_caps,
    compare_paper_pnl,
    generate_audit_report,
    verify_stop_triggers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_state(db_path: str, key: str, value: str) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            now = _now_str()
            conn.execute(
                """INSERT INTO system_state (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
                (key, value, now, value, now),
            )
    finally:
        conn.close()


def _insert_order(
    db_path: str,
    rebalance_id: str = "reb-001",
    token: str = "BTC",
    side: str = "Long",
    intended_usd: float = 5_000.0,
    status: str = "FILLED",
) -> None:
    now = _now_str()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO orders
                   (rebalance_id, token_symbol, side, order_type,
                    intended_usd, intended_size, status, created_at)
                   VALUES (?, ?, ?, 'MARKET', ?, 0.1, ?, ?)""",
                (rebalance_id, token, side, intended_usd, status, now),
            )
    finally:
        conn.close()


def _insert_target(
    db_path: str,
    rebalance_id: str = "reb-001",
    token: str = "BTC",
    side: str = "Long",
    target_usd: float = 5_000.0,
) -> None:
    now = _now_str()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO target_allocations
                   (rebalance_id, token_symbol, side, raw_weight,
                    capped_weight, target_usd, target_size, computed_at)
                   VALUES (?, ?, ?, 0.2, 0.2, ?, 0.1, ?)""",
                (rebalance_id, token, side, target_usd, now),
            )
    finally:
        conn.close()


def _insert_pnl(
    db_path: str,
    token: str = "BTC",
    side: str = "Long",
    realized_pnl: float = 500.0,
    fees_total: float = 5.0,
    exit_reason: str = "REBALANCE",
) -> None:
    now = _now_str()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO pnl_ledger
                   (token_symbol, side, entry_price, exit_price, size,
                    realized_pnl, fees_total, hold_hours, exit_reason, closed_at)
                   VALUES (?, ?, 50000.0, 51000.0, 1.0, ?, ?, 24.0, ?, ?)""",
                (token, side, realized_pnl, fees_total, exit_reason, now),
            )
    finally:
        conn.close()


def _insert_trader(db_path: str, address: str, label: str = "Smart") -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO traders (address, label, account_value) VALUES (?, ?, 100000.0)",
                (address, label),
            )
    finally:
        conn.close()


def _insert_score(
    db_path: str, address: str, composite_score: float = 0.8,
    roi_30d: float = 25.0, is_eligible: int = 1,
) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO trader_scores
                   (address, composite_score, roi_30d, is_eligible,
                    passes_tier1, passes_quality)
                   VALUES (?, ?, ?, ?, 1, 1)""",
                (address, composite_score, roi_30d, is_eligible),
            )
    finally:
        conn.close()


# ===========================================================================
# 1. Audit Risk Caps
# ===========================================================================


class TestAuditRiskCaps:
    """Tests for audit_risk_caps()."""

    def test_empty_db_passes(self, tmp_path):
        """Empty database passes all checks."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        result = audit_risk_caps(db_path)
        assert result["passed"] is True
        assert result["violations"] == []
        assert result["checks_run"] == 3

    def test_normal_orders_pass(self, tmp_path):
        """Orders within limits pass."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "100000")

        _insert_order(db_path, intended_usd=5_000.0)
        _insert_order(db_path, token="ETH", intended_usd=8_000.0)

        result = audit_risk_caps(db_path)
        assert result["passed"] is True

    def test_single_position_cap_violated(self, tmp_path):
        """Order exceeding single position cap is flagged."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "100000")

        # Max single = min(100k * 0.10, 50k) = 10k
        _insert_order(db_path, intended_usd=15_000.0)

        result = audit_risk_caps(db_path)
        assert result["passed"] is False
        assert len(result["violations"]) == 1
        assert result["violations"][0]["type"] == "single_position_cap"

    def test_total_exposure_cap_violated(self, tmp_path):
        """Total target allocation exceeding exposure cap is flagged."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "100000")

        # Max total = 100k * 0.50 = 50k
        _insert_target(db_path, token="BTC", target_usd=20_000.0)
        _insert_target(db_path, token="ETH", target_usd=20_000.0)
        _insert_target(db_path, token="SOL", target_usd=15_000.0)

        result = audit_risk_caps(db_path)
        assert result["passed"] is False
        violations = [v for v in result["violations"] if v["type"] == "total_exposure_cap"]
        assert len(violations) == 1

    def test_position_count_cap_violated(self, tmp_path):
        """More than MAX_TOTAL_POSITIONS targets is flagged."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "100000")

        for i in range(MAX_TOTAL_POSITIONS + 1):
            _insert_target(db_path, token=f"TOKEN{i}", target_usd=5_000.0)

        result = audit_risk_caps(db_path)
        assert result["passed"] is False
        violations = [v for v in result["violations"] if v["type"] == "position_count_cap"]
        assert len(violations) == 1

    def test_multiple_rebalances_checked(self, tmp_path):
        """Each rebalance cycle is checked independently."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "100000")

        # Rebalance 1: within limits
        _insert_target(db_path, rebalance_id="reb-001", token="BTC", target_usd=20_000.0)
        # Rebalance 2: over limit
        _insert_target(db_path, rebalance_id="reb-002", token="BTC", target_usd=30_000.0)
        _insert_target(db_path, rebalance_id="reb-002", token="ETH", target_usd=25_000.0)

        result = audit_risk_caps(db_path)
        assert result["passed"] is False
        assert any(v["rebalance_id"] == "reb-002" for v in result["violations"])


# ===========================================================================
# 2. Verify Stop Triggers
# ===========================================================================


class TestVerifyStopTriggers:
    """Tests for verify_stop_triggers()."""

    def test_all_stops_triggered(self, tmp_path):
        """All 3 stop types triggered -> PASS."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="ETH", exit_reason="TRAILING_STOP")
        _insert_pnl(db_path, token="SOL", exit_reason="TIME_STOP")

        result = verify_stop_triggers(db_path)
        assert result["passed"] is True
        assert result["missing"] == []
        assert result["total_stop_events"] == 3

    def test_missing_stop_type(self, tmp_path):
        """Missing TIME_STOP -> FAIL."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="ETH", exit_reason="TRAILING_STOP")

        result = verify_stop_triggers(db_path)
        assert result["passed"] is False
        assert "TIME_STOP" in result["missing"]

    def test_no_stops_at_all(self, tmp_path):
        """No stop events -> FAIL with all 3 missing."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        result = verify_stop_triggers(db_path)
        assert result["passed"] is False
        assert len(result["missing"]) == 3
        assert result["total_stop_events"] == 0

    def test_multiple_of_same_type(self, tmp_path):
        """Multiple of same type still counts."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="ETH", exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="SOL", exit_reason="TRAILING_STOP")
        _insert_pnl(db_path, token="HYPE", exit_reason="TIME_STOP")

        result = verify_stop_triggers(db_path)
        assert result["passed"] is True
        assert result["counts"]["STOP_LOSS"] == 2
        assert result["total_stop_events"] == 4

    def test_rebalance_exits_ignored(self, tmp_path):
        """REBALANCE exits don't count as stop triggers."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, exit_reason="REBALANCE")
        _insert_pnl(db_path, token="ETH", exit_reason="REBALANCE")

        result = verify_stop_triggers(db_path)
        assert result["passed"] is False
        assert result["total_stop_events"] == 0


# ===========================================================================
# 3. Compare Paper PnL
# ===========================================================================


class TestComparePaperPnl:
    """Tests for compare_paper_pnl()."""

    def test_empty_db(self, tmp_path):
        """Empty database returns zero metrics."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        result = compare_paper_pnl(db_path)
        assert result["our_total_pnl"] == 0.0
        assert result["our_trade_count"] == 0
        assert result["our_win_rate"] == 0.0
        assert result["tracked_trader_count"] == 0

    def test_positive_pnl(self, tmp_path):
        """Winning trades reflected correctly."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "10000")

        _insert_pnl(db_path, realized_pnl=500.0, fees_total=5.0)
        _insert_pnl(db_path, token="ETH", realized_pnl=300.0, fees_total=3.0)

        result = compare_paper_pnl(db_path)
        assert result["our_total_pnl"] == pytest.approx(800.0)
        assert result["our_total_fees"] == pytest.approx(8.0)
        assert result["our_net_pnl"] == pytest.approx(792.0)
        assert result["our_return_pct"] == pytest.approx(7.92)
        assert result["our_win_rate"] == 1.0

    def test_mixed_pnl(self, tmp_path):
        """Mix of wins and losses computed correctly."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "10000")

        _insert_pnl(db_path, realized_pnl=500.0, fees_total=5.0)
        _insert_pnl(db_path, token="ETH", realized_pnl=-200.0, fees_total=3.0)
        _insert_pnl(db_path, token="SOL", realized_pnl=-100.0, fees_total=2.0)

        result = compare_paper_pnl(db_path)
        assert result["our_total_pnl"] == pytest.approx(200.0)
        assert result["our_trade_count"] == 3
        assert result["our_win_rate"] == pytest.approx(1 / 3)

    def test_exit_reason_breakdown(self, tmp_path):
        """Exit reasons are tallied."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, exit_reason="REBALANCE")
        _insert_pnl(db_path, token="ETH", exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="SOL", exit_reason="REBALANCE")

        result = compare_paper_pnl(db_path)
        assert result["exit_counts"]["REBALANCE"] == 2
        assert result["exit_counts"]["STOP_LOSS"] == 1

    def test_trader_comparison(self, tmp_path):
        """Tracked trader ROI is computed for comparison."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_trader(db_path, address="0xabc")
        _insert_trader(db_path, address="0xdef")
        _insert_score(db_path, address="0xabc", roi_30d=30.0)
        _insert_score(db_path, address="0xdef", roi_30d=20.0)

        result = compare_paper_pnl(db_path)
        assert result["tracked_trader_count"] == 2
        assert result["avg_trader_roi_30d"] == pytest.approx(25.0)

    def test_zero_account_value(self, tmp_path):
        """Zero account value doesn't cause division by zero."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, realized_pnl=100.0)

        result = compare_paper_pnl(db_path)
        assert result["our_return_pct"] == 0.0


# ===========================================================================
# 4. Generate Audit Report
# ===========================================================================


class TestGenerateAuditReport:
    """Tests for generate_audit_report()."""

    def test_report_is_markdown(self, tmp_path):
        """Report starts with markdown header."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        report = generate_audit_report(db_path)
        assert report.startswith("# Snap Paper Trading Audit Report")

    def test_report_contains_all_sections(self, tmp_path):
        """Report has all 4 sections."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        report = generate_audit_report(db_path)
        assert "## 1. Risk Cap Audit" in report
        assert "## 2. Stop Trigger Verification" in report
        assert "## 3. Paper PnL vs Tracked Traders" in report
        assert "## 4. Graduation Criteria" in report

    def test_report_with_data(self, tmp_path):
        """Report with real data includes values."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "10000")

        _insert_pnl(db_path, realized_pnl=500.0, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="ETH", realized_pnl=-200.0, exit_reason="TRAILING_STOP")
        _insert_pnl(db_path, token="SOL", realized_pnl=100.0, exit_reason="TIME_STOP")

        report = generate_audit_report(db_path)
        assert "PASS" in report
        assert "STOP_LOSS" in report
        assert "TRAILING_STOP" in report
        assert "TIME_STOP" in report
        assert "$10,000" in report

    def test_report_with_violations(self, tmp_path):
        """Report shows violations when risk caps breached."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "100000")

        # Exceed single position cap (10k)
        _insert_order(db_path, intended_usd=15_000.0)

        report = generate_audit_report(db_path)
        assert "FAIL" in report
        assert "single_position_cap" in report

    def test_report_graduation_criteria(self, tmp_path):
        """Report shows graduation criteria status."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "account_value", "10000")

        _insert_pnl(db_path, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="ETH", exit_reason="TRAILING_STOP")
        _insert_pnl(db_path, token="SOL", exit_reason="TIME_STOP")

        report = generate_audit_report(db_path)
        # All stops triggered + no risk violations = graduation criteria met
        assert "All stop types triggered (3/3) | PASS" in report
        assert "All risk caps applied correctly | PASS" in report
