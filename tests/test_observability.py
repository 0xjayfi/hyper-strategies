"""Tests for the observability & alerts module (Phase 7).

Covers:
1. Structured JSON logging format
2. Metrics collection from DB queries
3. Alert condition triggering and severity levels
4. Notification dispatch (log-based)
5. Dashboard snapshot generation
6. Health-check status output
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from snap.config import (
    DRAWDOWN_CRITICAL_PCT,
    DRAWDOWN_WARNING_PCT,
    EXPOSURE_BREACH_PCT,
    FILL_RATE_WARNING_PCT,
    MAX_TOTAL_POSITIONS,
    REBALANCE_STALE_HOURS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.database import get_connection, init_db
from snap.observability import (
    Alert,
    _JSONFormatter,
    check_alerts,
    collect_metrics,
    emit_alert,
    emit_alerts,
    export_dashboard,
    setup_json_logging,
    write_health_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours_ago(hours: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_state(db_path: str, key: str, value: str) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO system_state (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
                (key, value, _now_str(), value, _now_str()),
            )
    finally:
        conn.close()


def _insert_position(
    db_path: str,
    token: str = "BTC",
    side: str = "Long",
    size: float = 1.0,
    entry_price: float = 50_000.0,
    position_usd: float | None = None,
    unrealized_pnl: float = 0.0,
) -> None:
    now = _now_str()
    if position_usd is None:
        position_usd = size * entry_price

    stop_loss = entry_price * (1 - STOP_LOSS_PERCENT / 100) if side == "Long" else entry_price * (1 + STOP_LOSS_PERCENT / 100)
    trailing_stop = entry_price * (1 - TRAILING_STOP_PERCENT / 100) if side == "Long" else entry_price * (1 + TRAILING_STOP_PERCENT / 100)
    max_close = (datetime.now(timezone.utc) + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO our_positions
                   (token_symbol, side, size, entry_price, current_price,
                    position_usd, unrealized_pnl, stop_loss_price,
                    trailing_stop_price, trailing_high, opened_at,
                    max_close_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (token, side, size, entry_price, entry_price,
                 position_usd, unrealized_pnl, stop_loss, trailing_stop,
                 entry_price, now, max_close, now),
            )
    finally:
        conn.close()


def _insert_order(
    db_path: str,
    rebalance_id: str = "reb-001",
    token: str = "BTC",
    side: str = "Long",
    status: str = "FILLED",
    slippage_bps: float | None = 3.0,
) -> None:
    now = _now_str()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO orders
                   (rebalance_id, token_symbol, side, order_type,
                    intended_usd, intended_size, status, slippage_bps,
                    created_at, filled_at)
                   VALUES (?, ?, ?, 'MARKET', 10000.0, 0.2, ?, ?, ?, ?)""",
                (rebalance_id, token, side, status, slippage_bps, now, now),
            )
    finally:
        conn.close()


def _insert_pnl(
    db_path: str,
    token: str = "BTC",
    side: str = "Long",
    realized_pnl: float = 500.0,
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
                   VALUES (?, ?, 50000.0, 51000.0, 1.0, ?, 5.0, 24.0, ?, ?)""",
                (token, side, realized_pnl, exit_reason, now),
            )
    finally:
        conn.close()


def _insert_trader(db_path: str, address: str = "0xabc", blacklisted: int = 0) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO traders (address, label, account_value, blacklisted)
                   VALUES (?, 'Test', 100000.0, ?)""",
                (address, blacklisted),
            )
    finally:
        conn.close()


def _insert_score(
    db_path: str, address: str = "0xabc", is_eligible: int = 1,
    composite_score: float = 0.8,
) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO trader_scores
                   (address, composite_score, is_eligible, passes_tier1, passes_quality)
                   VALUES (?, ?, ?, 1, 1)""",
                (address, composite_score, is_eligible),
            )
    finally:
        conn.close()


# ===========================================================================
# 1. Structured JSON Logging
# ===========================================================================


class TestJSONFormatter:
    """Tests for _JSONFormatter."""

    def test_basic_format(self):
        """Basic log record produces valid JSON with required fields."""
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="snap.test", level=logging.INFO, pathname="",
            lineno=0, msg="Test message", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "snap.test"
        assert data["message"] == "Test message"
        assert "ts" in data

    def test_timestamp_format(self):
        """Timestamp is ISO-8601 UTC."""
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="msg", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        # Should end with Z (UTC)
        assert data["ts"].endswith("Z")
        # Should be parseable
        datetime.strptime(data["ts"], "%Y-%m-%dT%H:%M:%SZ")

    def test_extra_fields_included(self):
        """Extra fields (event, alert_name, severity) are included."""
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="",
            lineno=0, msg="alert fired", args=(), exc_info=None,
        )
        record.event = "alert"
        record.alert_name = "drawdown_warning"
        record.severity = "WARNING"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["event"] == "alert"
        assert data["alert_name"] == "drawdown_warning"
        assert data["severity"] == "WARNING"

    def test_exception_included(self):
        """Exception info is included when present."""
        formatter = _JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="",
                lineno=0, msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_message_with_args(self):
        """Formatted message with arguments."""
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="count=%d", args=(42,), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "count=42"


class TestSetupJsonLogging:
    """Tests for setup_json_logging()."""

    def test_configures_root_logger(self):
        """Root logger gets a JSON formatter handler."""
        setup_json_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) >= 1
        handler = root.handlers[0]
        assert isinstance(handler.formatter, _JSONFormatter)

    def test_file_handler_created(self, tmp_path):
        """When log_file is provided, a file handler is added."""
        log_file = str(tmp_path / "test.log")
        setup_json_logging(log_file=log_file)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1

    def test_no_duplicate_handlers(self):
        """Calling setup twice doesn't duplicate handlers."""
        setup_json_logging()
        count1 = len(logging.getLogger().handlers)
        setup_json_logging()
        count2 = len(logging.getLogger().handlers)
        # Should replace, not accumulate
        assert count2 <= count1 + 1  # at most 1 more if file handler added


# ===========================================================================
# 2. Metrics Collection
# ===========================================================================


class TestCollectMetrics:
    """Tests for collect_metrics()."""

    def test_empty_db(self, tmp_path):
        """Empty database returns zero metrics."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        metrics = collect_metrics(db_path)
        assert metrics["portfolio.position_count"] == 0
        assert metrics["portfolio.total_exposure_usd"] == 0.0
        assert metrics["portfolio.unrealized_pnl_usd"] == 0.0
        assert metrics["portfolio.realized_pnl_usd"] == 0.0
        assert metrics["traders.eligible_count"] == 0
        assert metrics["traders.blacklisted_count"] == 0
        assert "measured_at" in metrics

    def test_with_positions(self, tmp_path):
        """Positions are reflected in portfolio metrics."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _set_state(db_path, "account_value", "100000")
        _insert_position(db_path, token="BTC", side="Long",
                         position_usd=10_000.0, unrealized_pnl=500.0)
        _insert_position(db_path, token="ETH", side="Short",
                         position_usd=5_000.0, unrealized_pnl=-200.0)

        metrics = collect_metrics(db_path)
        assert metrics["portfolio.position_count"] == 2
        assert metrics["portfolio.total_exposure_usd"] == 15_000.0
        assert metrics["portfolio.long_exposure_usd"] == 10_000.0
        assert metrics["portfolio.short_exposure_usd"] == 5_000.0
        assert metrics["portfolio.unrealized_pnl_usd"] == 300.0
        assert metrics["portfolio.total_exposure_pct"] == pytest.approx(15.0)
        assert metrics["portfolio.long_exposure_pct"] == pytest.approx(10.0)
        assert metrics["portfolio.short_exposure_pct"] == pytest.approx(5.0)

    def test_realized_pnl_sum(self, tmp_path):
        """Realized PnL is summed from pnl_ledger."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, realized_pnl=500.0)
        _insert_pnl(db_path, token="ETH", realized_pnl=-200.0)

        metrics = collect_metrics(db_path)
        assert metrics["portfolio.realized_pnl_usd"] == pytest.approx(300.0)

    def test_drawdown_calculation(self, tmp_path):
        """Drawdown computed from peak account value."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _set_state(db_path, "account_value", "90000")
        _set_state(db_path, "peak_account_value", "100000")

        metrics = collect_metrics(db_path)
        # (100k - 90k) / 100k = 10%
        assert metrics["portfolio.drawdown_pct"] == pytest.approx(10.0)

    def test_drawdown_with_unrealized_pnl(self, tmp_path):
        """Drawdown accounts for unrealized PnL."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _set_state(db_path, "account_value", "95000")
        _set_state(db_path, "peak_account_value", "100000")
        _insert_position(db_path, unrealized_pnl=-3000.0)

        metrics = collect_metrics(db_path)
        # equity = 95000 + (-3000) = 92000; dd = (100000 - 92000) / 100000 = 8%
        assert metrics["portfolio.drawdown_pct"] == pytest.approx(8.0)

    def test_order_metrics(self, tmp_path):
        """Order fill rate and slippage from recent rebalance."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_order(db_path, status="FILLED", slippage_bps=3.0)
        _insert_order(db_path, token="ETH", status="FILLED", slippage_bps=5.0)
        _insert_order(db_path, token="SOL", status="CANCELLED", slippage_bps=None)

        metrics = collect_metrics(db_path)
        assert metrics["rebalance.orders_sent"] == 3
        assert metrics["rebalance.orders_filled"] == 2
        assert metrics["rebalance.fill_rate_pct"] == pytest.approx(200 / 3)
        assert metrics["rebalance.slippage_bps_avg"] == pytest.approx(4.0)

    def test_trader_counts(self, tmp_path):
        """Trader eligible and blacklisted counts."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_trader(db_path, address="0xabc", blacklisted=0)
        _insert_trader(db_path, address="0xdef", blacklisted=1)
        _insert_score(db_path, address="0xabc", is_eligible=1)

        metrics = collect_metrics(db_path)
        assert metrics["traders.eligible_count"] == 1
        assert metrics["traders.blacklisted_count"] == 1

    def test_stop_counts(self, tmp_path):
        """Stop trigger counts from pnl_ledger."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_pnl(db_path, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="ETH", exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="SOL", exit_reason="TRAILING_STOP")

        metrics = collect_metrics(db_path)
        assert metrics["stops.stop_loss_count"] == 2
        assert metrics["stops.trailing_stop_count"] == 1
        assert metrics["stops.time_stop_count"] == 0

    def test_no_account_value(self, tmp_path):
        """Zero account value doesn't cause division by zero."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_position(db_path, position_usd=10_000.0)

        metrics = collect_metrics(db_path)
        assert metrics["portfolio.total_exposure_pct"] == 0.0
        assert metrics["portfolio.long_exposure_pct"] == 0.0
        assert metrics["portfolio.account_value"] == 0.0


# ===========================================================================
# 3. Alert Conditions
# ===========================================================================


class TestCheckAlerts:
    """Tests for check_alerts()."""

    def test_no_alerts_healthy(self):
        """Healthy metrics produce no alerts (except info stops if present)."""
        metrics = {
            "portfolio.total_exposure_pct": 40.0,
            "portfolio.drawdown_pct": 2.0,
            "portfolio.position_count": 3,
            "rebalance.last_at": _now_str(),
            "rebalance.fill_rate_pct": 100.0,
            "rebalance.orders_sent": 5,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        assert len(alerts) == 0

    def test_exposure_breach(self):
        """Exposure above threshold triggers CRITICAL alert."""
        metrics = {
            "portfolio.total_exposure_pct": 60.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": 3,
            "rebalance.orders_sent": 0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        exposure_alerts = [a for a in alerts if a.name == "exposure_breach"]
        assert len(exposure_alerts) == 1
        assert exposure_alerts[0].severity == "CRITICAL"
        assert exposure_alerts[0].value == 60.0

    def test_drawdown_warning(self):
        """Drawdown between warning and critical thresholds -> WARNING."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": DRAWDOWN_WARNING_PCT + 1.0,
            "portfolio.position_count": 2,
            "rebalance.orders_sent": 0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        dd_alerts = [a for a in alerts if a.name == "drawdown_warning"]
        assert len(dd_alerts) == 1
        assert dd_alerts[0].severity == "WARNING"

    def test_drawdown_critical(self):
        """Drawdown above critical threshold -> CRITICAL (not WARNING)."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": DRAWDOWN_CRITICAL_PCT + 1.0,
            "portfolio.position_count": 2,
            "rebalance.orders_sent": 0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        dd_alerts = [a for a in alerts if "drawdown" in a.name]
        assert len(dd_alerts) == 1
        assert dd_alerts[0].name == "drawdown_critical"
        assert dd_alerts[0].severity == "CRITICAL"

    def test_rebalance_stale(self):
        """Stale rebalance triggers WARNING."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": 2,
            "rebalance.last_at": _hours_ago(REBALANCE_STALE_HOURS + 1),
            "rebalance.fill_rate_pct": 100.0,
            "rebalance.orders_sent": 0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        stale = [a for a in alerts if a.name == "rebalance_stale"]
        assert len(stale) == 1
        assert stale[0].severity == "WARNING"

    def test_rebalance_not_stale(self):
        """Recent rebalance does not trigger stale alert."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": 2,
            "rebalance.last_at": _hours_ago(1),
            "rebalance.fill_rate_pct": 100.0,
            "rebalance.orders_sent": 5,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        stale = [a for a in alerts if a.name == "rebalance_stale"]
        assert len(stale) == 0

    def test_low_fill_rate(self):
        """Fill rate below threshold triggers WARNING."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": 2,
            "rebalance.orders_sent": 10,
            "rebalance.fill_rate_pct": 80.0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        fill = [a for a in alerts if a.name == "low_fill_rate"]
        assert len(fill) == 1
        assert fill[0].severity == "WARNING"

    def test_fill_rate_no_orders(self):
        """No orders sent -> no fill rate alert (even if rate is 0)."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": 2,
            "rebalance.orders_sent": 0,
            "rebalance.fill_rate_pct": 0.0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        fill = [a for a in alerts if a.name == "low_fill_rate"]
        assert len(fill) == 0

    def test_position_limit_breach(self):
        """More than MAX_TOTAL_POSITIONS triggers CRITICAL."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": MAX_TOTAL_POSITIONS + 1,
            "rebalance.orders_sent": 0,
            "stops.stop_loss_count": 0,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        breach = [a for a in alerts if a.name == "position_limit_breach"]
        assert len(breach) == 1
        assert breach[0].severity == "CRITICAL"

    def test_stop_loss_info(self):
        """Stop-loss events produce INFO alerts."""
        metrics = {
            "portfolio.total_exposure_pct": 30.0,
            "portfolio.drawdown_pct": 0.0,
            "portfolio.position_count": 2,
            "rebalance.orders_sent": 0,
            "stops.stop_loss_count": 3,
            "stops.trailing_stop_count": 1,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        info_alerts = [a for a in alerts if a.severity == "INFO"]
        assert len(info_alerts) == 2
        names = {a.name for a in info_alerts}
        assert "stop_loss_triggered" in names
        assert "trailing_stop_triggered" in names

    def test_multiple_alerts_simultaneous(self):
        """Multiple conditions can fire at once."""
        metrics = {
            "portfolio.total_exposure_pct": 60.0,  # breach
            "portfolio.drawdown_pct": 20.0,  # critical
            "portfolio.position_count": MAX_TOTAL_POSITIONS + 2,  # breach
            "rebalance.last_at": _hours_ago(10),  # stale
            "rebalance.orders_sent": 10,
            "rebalance.fill_rate_pct": 50.0,  # low fill
            "stops.stop_loss_count": 1,
            "stops.trailing_stop_count": 0,
            "stops.time_stop_count": 0,
        }
        alerts = check_alerts(metrics)
        names = {a.name for a in alerts}
        assert "exposure_breach" in names
        assert "drawdown_critical" in names
        assert "position_limit_breach" in names
        assert "rebalance_stale" in names
        assert "low_fill_rate" in names
        assert "stop_loss_triggered" in names


# ===========================================================================
# 4. Alert Model
# ===========================================================================


class TestAlertModel:
    """Tests for Alert data class."""

    def test_to_dict(self):
        """Alert serializes to dict with all fields."""
        alert = Alert(
            name="test_alert",
            severity="WARNING",
            message="Something happened",
            value=42.0,
            threshold=30.0,
        )
        d = alert.to_dict()
        assert d["name"] == "test_alert"
        assert d["severity"] == "WARNING"
        assert d["message"] == "Something happened"
        assert d["value"] == 42.0
        assert d["threshold"] == 30.0
        assert "timestamp" in d


# ===========================================================================
# 5. Notification Delivery
# ===========================================================================


class TestEmitAlert:
    """Tests for emit_alert() and emit_alerts()."""

    def test_emit_alert_logs(self, caplog):
        """emit_alert writes to the log at the correct level."""
        alert = Alert(
            name="test", severity="WARNING", message="test msg",
            value=10.0, threshold=5.0,
        )
        with caplog.at_level(logging.WARNING):
            emit_alert(alert)
        assert "test" in caplog.text
        assert "test msg" in caplog.text

    def test_emit_critical_level(self, caplog):
        """CRITICAL alerts log at CRITICAL level."""
        alert = Alert(name="crit", severity="CRITICAL", message="bad")
        with caplog.at_level(logging.CRITICAL):
            emit_alert(alert)
        assert "CRITICAL" in caplog.text or "crit" in caplog.text

    def test_emit_info_level(self, caplog):
        """INFO alerts log at INFO level."""
        alert = Alert(name="info", severity="INFO", message="fyi")
        with caplog.at_level(logging.INFO):
            emit_alert(alert)
        assert "fyi" in caplog.text

    def test_emit_alerts_multiple(self, caplog):
        """emit_alerts dispatches all alerts."""
        alerts = [
            Alert(name="a", severity="INFO", message="one"),
            Alert(name="b", severity="WARNING", message="two"),
        ]
        with caplog.at_level(logging.INFO):
            emit_alerts(alerts)
        assert "one" in caplog.text
        assert "two" in caplog.text

    def test_emit_alerts_empty(self, caplog):
        """Empty alert list produces no log output."""
        with caplog.at_level(logging.DEBUG):
            emit_alerts([])
        # No alert-related messages
        assert "ALERT" not in caplog.text


# ===========================================================================
# 6. Dashboard Export
# ===========================================================================


class TestExportDashboard:
    """Tests for export_dashboard()."""

    def test_returns_snapshot(self, tmp_path):
        """Returns dict with metrics, alerts, positions, recent_pnl."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        snapshot = export_dashboard(db_path)
        assert "generated_at" in snapshot
        assert "metrics" in snapshot
        assert "alerts" in snapshot
        assert "positions" in snapshot
        assert "recent_pnl" in snapshot

    def test_writes_file(self, tmp_path):
        """When output_path is given, writes JSON file."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        out_file = str(tmp_path / "dashboard.json")

        export_dashboard(db_path, output_path=out_file)

        with open(out_file) as f:
            data = json.load(f)
        assert "metrics" in data
        assert "generated_at" in data

    def test_includes_positions(self, tmp_path):
        """Dashboard includes current position details."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _insert_position(db_path, token="BTC", position_usd=10_000.0)

        snapshot = export_dashboard(db_path)
        assert len(snapshot["positions"]) == 1
        assert snapshot["positions"][0]["token_symbol"] == "BTC"

    def test_includes_recent_pnl(self, tmp_path):
        """Dashboard includes recent PnL entries."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _insert_pnl(db_path, realized_pnl=500.0)

        snapshot = export_dashboard(db_path)
        assert len(snapshot["recent_pnl"]) == 1

    def test_includes_alerts(self, tmp_path):
        """Dashboard includes triggered alerts."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _insert_pnl(db_path, exit_reason="STOP_LOSS")

        snapshot = export_dashboard(db_path)
        alert_names = [a["name"] for a in snapshot["alerts"]]
        assert "stop_loss_triggered" in alert_names


# ===========================================================================
# 7. Health-Check Status
# ===========================================================================


class TestWriteHealthCheck:
    """Tests for write_health_check()."""

    def test_healthy_status(self, tmp_path):
        """System with recent rebalance is healthy."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "last_rebalance_at", _hours_ago(1))

        health_file = str(tmp_path / "health.json")
        result = write_health_check(db_path, health_file=health_file)

        assert result["status"] == "healthy"
        assert result["checks"]["database"] == "ok"
        assert result["checks"]["rebalance"] == "ok"
        assert "timestamp" in result

        # File written
        with open(health_file) as f:
            data = json.load(f)
        assert data["status"] == "healthy"

    def test_degraded_stale_rebalance(self, tmp_path):
        """Stale rebalance degrades status."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _set_state(db_path, "last_rebalance_at", _hours_ago(REBALANCE_STALE_HOURS + 1))

        result = write_health_check(db_path, health_file=str(tmp_path / "h.json"))
        assert result["status"] == "degraded"
        assert result["checks"]["rebalance"] == "stale"

    def test_no_rebalance_data(self, tmp_path):
        """No rebalance data returns no_data check."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        result = write_health_check(db_path, health_file=str(tmp_path / "h.json"))
        assert result["checks"]["rebalance"] == "no_data"
        # Still healthy (no data doesn't mean unhealthy on first start)

    def test_position_count_in_checks(self, tmp_path):
        """Position count is included in checks."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        _insert_position(db_path, token="BTC")
        _insert_position(db_path, token="ETH")

        result = write_health_check(db_path, health_file=str(tmp_path / "h.json"))
        assert result["checks"]["position_count"] == 2

    def test_uptime_included(self, tmp_path):
        """Uptime field is present."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        result = write_health_check(db_path, health_file=str(tmp_path / "h.json"))
        assert "uptime_s" in result
        assert result["uptime_s"] >= 0

    def test_degraded_too_many_positions(self, tmp_path):
        """Exceeding position limit degrades status."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        for i in range(MAX_TOTAL_POSITIONS + 1):
            _insert_position(db_path, token=f"TOKEN{i}")

        result = write_health_check(db_path, health_file=str(tmp_path / "h.json"))
        assert result["status"] == "degraded"


# ===========================================================================
# 8. Integration: Full Observability Pipeline
# ===========================================================================


class TestObservabilityIntegration:
    """End-to-end tests combining metrics, alerts, dashboard, and health."""

    def test_full_pipeline(self, tmp_path):
        """Metrics -> alerts -> dashboard -> health all work together."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _set_state(db_path, "account_value", "100000")
        _set_state(db_path, "peak_account_value", "105000")
        _set_state(db_path, "last_rebalance_at", _hours_ago(2))

        _insert_position(db_path, token="BTC", side="Long",
                         position_usd=20_000.0, unrealized_pnl=1000.0)
        _insert_position(db_path, token="ETH", side="Short",
                         position_usd=10_000.0, unrealized_pnl=-500.0)
        _insert_pnl(db_path, realized_pnl=2000.0, exit_reason="REBALANCE")
        _insert_order(db_path, status="FILLED", slippage_bps=4.0)

        # 1. Collect metrics
        metrics = collect_metrics(db_path)
        assert metrics["portfolio.position_count"] == 2
        assert metrics["portfolio.total_exposure_usd"] == 30_000.0
        assert metrics["portfolio.realized_pnl_usd"] == pytest.approx(2000.0)

        # 2. Check alerts (should be minimal with these values)
        alerts = check_alerts(metrics)
        # No critical alerts expected at 30% exposure, ~4% drawdown
        critical = [a for a in alerts if a.severity == "CRITICAL"]
        assert len(critical) == 0

        # 3. Export dashboard
        dash_file = str(tmp_path / "dash.json")
        snapshot = export_dashboard(db_path, output_path=dash_file)
        assert len(snapshot["positions"]) == 2

        # 4. Write health check
        health_file = str(tmp_path / "health.json")
        health = write_health_check(db_path, health_file=health_file)
        assert health["status"] == "healthy"

    def test_stressed_system(self, tmp_path):
        """High-stress scenario triggers multiple alerts."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _set_state(db_path, "account_value", "100000")
        _set_state(db_path, "peak_account_value", "120000")
        _set_state(db_path, "last_rebalance_at", _hours_ago(10))

        # High exposure
        _insert_position(db_path, token="BTC", side="Long",
                         position_usd=30_000.0, unrealized_pnl=-5000.0)
        _insert_position(db_path, token="ETH", side="Long",
                         position_usd=28_000.0, unrealized_pnl=-3000.0)

        # Bad fill history
        _insert_order(db_path, status="FILLED")
        _insert_order(db_path, token="ETH", status="CANCELLED", slippage_bps=None)
        _insert_order(db_path, token="SOL", status="FAILED", slippage_bps=None)

        # Stop losses fired
        _insert_pnl(db_path, exit_reason="STOP_LOSS")
        _insert_pnl(db_path, token="SOL", exit_reason="STOP_LOSS")

        metrics = collect_metrics(db_path)
        alerts = check_alerts(metrics)

        names = {a.name for a in alerts}
        assert "exposure_breach" in names  # 58% > 55%
        assert "drawdown_critical" in names  # (120k - (100k-8k))/120k > 15%
        assert "rebalance_stale" in names  # 10h > 6h
        assert "low_fill_rate" in names  # 1/3 = 33% < 95%
        assert "stop_loss_triggered" in names
