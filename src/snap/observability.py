"""Observability, metrics, alerts, and health-check for the Snap system.

Implements Phase 7 of the specification:

1. ``setup_json_logging``   — Configure structured JSON log output.
2. ``collect_metrics``      — Gather current system metrics from the database.
3. ``check_alerts``         — Evaluate alert conditions and return triggered alerts.
4. ``emit_alert``           — Log / deliver alert notifications (MVP: log-based).
5. ``export_dashboard``     — Write a JSON snapshot for external dashboards.
6. ``write_health_check``   — Write a health status file for liveness probes.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from datetime import datetime, timezone
from typing import Any

from snap.config import (
    API_CONSECUTIVE_FAILURES,
    DIVERGENCE_WARNING_PCT,
    DRAWDOWN_CRITICAL_PCT,
    DRAWDOWN_WARNING_PCT,
    EXPOSURE_BREACH_PCT,
    FILL_RATE_WARNING_PCT,
    HEALTH_CHECK_FILE,
    MAX_TOTAL_EXPOSURE_PCT,
    MAX_TOTAL_POSITIONS,
    REBALANCE_STALE_HOURS,
)
from snap.database import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Structured JSON Logging
# ---------------------------------------------------------------------------


class _JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        # Merge any extra fields attached via ``extra=``
        for key in ("event", "rebalance_id", "alert_name", "severity", "details"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        return json.dumps(payload, default=str)


def setup_json_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
) -> None:
    """Configure the root logger to emit structured JSON.

    Parameters
    ----------
    level:
        Logging level (default ``INFO``).
    log_file:
        Optional path to a log file.  If ``None``, logs go to ``stderr``.
    """
    root = logging.getLogger()
    root.setLevel(level)

    formatter = _JSONFormatter()

    # Remove pre-existing handlers to avoid duplicate output
    for h in root.handlers[:]:
        root.removeHandler(h)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


# ---------------------------------------------------------------------------
# 2. Metrics Collection
# ---------------------------------------------------------------------------


def collect_metrics(
    db_path: str, *, data_db_path: str | None = None
) -> dict[str, Any]:
    """Gather current system metrics by querying the database.

    Parameters
    ----------
    db_path:
        Path to the strategy database (or single combined DB).
    data_db_path:
        Optional path to the data database.  When provided, the
        ``traders.blacklisted`` count is read from this DB instead.

    Returns a dict with keys matching the observability spec (Section 8.1).
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metrics: dict[str, Any] = {"measured_at": now_str}

    conn = get_connection(db_path)
    try:
        # -- Portfolio metrics --
        rows = conn.execute("SELECT * FROM our_positions").fetchall()
        positions = [dict(r) for r in rows]

        total_exposure = sum(abs(p.get("position_usd", 0.0)) for p in positions)
        long_usd = sum(
            abs(p.get("position_usd", 0.0))
            for p in positions
            if p.get("side") == "Long"
        )
        short_usd = sum(
            abs(p.get("position_usd", 0.0))
            for p in positions
            if p.get("side") == "Short"
        )
        unrealized_pnl = sum(p.get("unrealized_pnl", 0.0) for p in positions)

        # Account value from system_state
        acct_row = conn.execute(
            "SELECT value FROM system_state WHERE key = 'account_value'"
        ).fetchone()
        account_value = float(acct_row["value"]) if acct_row else 0.0

        metrics["portfolio.total_exposure_usd"] = total_exposure
        metrics["portfolio.long_exposure_usd"] = long_usd
        metrics["portfolio.short_exposure_usd"] = short_usd
        if account_value > 0:
            metrics["portfolio.long_exposure_pct"] = long_usd / account_value * 100
            metrics["portfolio.short_exposure_pct"] = short_usd / account_value * 100
            metrics["portfolio.total_exposure_pct"] = total_exposure / account_value * 100
        else:
            metrics["portfolio.long_exposure_pct"] = 0.0
            metrics["portfolio.short_exposure_pct"] = 0.0
            metrics["portfolio.total_exposure_pct"] = 0.0
        metrics["portfolio.position_count"] = len(positions)
        metrics["portfolio.unrealized_pnl_usd"] = unrealized_pnl
        metrics["portfolio.account_value"] = account_value

        # Realized PnL (cumulative)
        pnl_row = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) AS total FROM pnl_ledger"
        ).fetchone()
        metrics["portfolio.realized_pnl_usd"] = pnl_row["total"]

        # Drawdown — compute from peak account value
        peak_row = conn.execute(
            "SELECT value FROM system_state WHERE key = 'peak_account_value'"
        ).fetchone()
        peak_value = float(peak_row["value"]) if peak_row else account_value
        if peak_value > 0:
            current_equity = account_value + unrealized_pnl
            metrics["portfolio.drawdown_pct"] = max(
                0.0, (peak_value - current_equity) / peak_value * 100
            )
        else:
            metrics["portfolio.drawdown_pct"] = 0.0

        # -- Rebalance metrics --
        last_reb_row = conn.execute(
            "SELECT value FROM system_state WHERE key = 'last_rebalance_at'"
        ).fetchone()
        metrics["rebalance.last_at"] = last_reb_row["value"] if last_reb_row else None

        # Orders from most recent rebalance
        recent_orders = conn.execute(
            """SELECT status, slippage_bps FROM orders
               WHERE rebalance_id = (
                   SELECT rebalance_id FROM orders ORDER BY created_at DESC LIMIT 1
               )"""
        ).fetchall()
        if recent_orders:
            total_orders = len(recent_orders)
            filled = sum(1 for o in recent_orders if o["status"] in ("FILLED", "PARTIAL"))
            slippage_values = [
                o["slippage_bps"] for o in recent_orders if o["slippage_bps"] is not None
            ]
            metrics["rebalance.orders_sent"] = total_orders
            metrics["rebalance.orders_filled"] = filled
            metrics["rebalance.fill_rate_pct"] = (
                filled / total_orders * 100 if total_orders > 0 else 100.0
            )
            metrics["rebalance.slippage_bps_avg"] = (
                sum(slippage_values) / len(slippage_values) if slippage_values else 0.0
            )
        else:
            metrics["rebalance.orders_sent"] = 0
            metrics["rebalance.orders_filled"] = 0
            metrics["rebalance.fill_rate_pct"] = 100.0
            metrics["rebalance.slippage_bps_avg"] = 0.0

        # -- Trader metrics --
        eligible_row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM trader_scores
               WHERE is_eligible = 1"""
        ).fetchone()
        metrics["traders.eligible_count"] = eligible_row["cnt"]

        tracked_row = conn.execute(
            """SELECT COUNT(DISTINCT address) AS cnt FROM trader_scores
               WHERE is_eligible = 1"""
        ).fetchone()
        metrics["traders.tracked_count"] = tracked_row["cnt"]

        data_conn = get_connection(data_db_path) if data_db_path else conn
        try:
            blacklisted_row = data_conn.execute(
                "SELECT COUNT(*) AS cnt FROM traders WHERE blacklisted = 1"
            ).fetchone()
            metrics["traders.blacklisted_count"] = blacklisted_row["cnt"]
        finally:
            if data_db_path:
                data_conn.close()

        # -- Stop metrics (from pnl_ledger) --
        for reason in ("STOP_LOSS", "TRAILING_STOP", "TIME_STOP"):
            stop_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pnl_ledger WHERE exit_reason = ?",
                (reason,),
            ).fetchone()
            metrics[f"stops.{reason.lower()}_count"] = stop_row["cnt"]

    finally:
        conn.close()

    return metrics


# ---------------------------------------------------------------------------
# 3. Alert Conditions
# ---------------------------------------------------------------------------


class Alert:
    """Represents a triggered alert condition."""

    __slots__ = ("name", "severity", "message", "value", "threshold", "timestamp")

    def __init__(
        self,
        name: str,
        severity: str,
        message: str,
        value: float = 0.0,
        threshold: float = 0.0,
    ) -> None:
        self.name = name
        self.severity = severity  # "INFO", "WARNING", "CRITICAL"
        self.message = message
        self.value = value
        self.threshold = threshold
        self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp,
        }


def check_alerts(metrics: dict[str, Any]) -> list[Alert]:
    """Evaluate alert conditions against collected metrics.

    Returns a list of :class:`Alert` objects for conditions that are triggered.
    """
    alerts: list[Alert] = []

    # 1. Exposure breach
    exposure_pct = metrics.get("portfolio.total_exposure_pct", 0.0)
    if exposure_pct > EXPOSURE_BREACH_PCT:
        alerts.append(Alert(
            name="exposure_breach",
            severity="CRITICAL",
            message=f"Total exposure {exposure_pct:.1f}% exceeds {EXPOSURE_BREACH_PCT}%",
            value=exposure_pct,
            threshold=EXPOSURE_BREACH_PCT,
        ))

    # 2. Drawdown warnings
    drawdown = metrics.get("portfolio.drawdown_pct", 0.0)
    if drawdown > DRAWDOWN_CRITICAL_PCT:
        alerts.append(Alert(
            name="drawdown_critical",
            severity="CRITICAL",
            message=f"Drawdown {drawdown:.1f}% exceeds critical threshold {DRAWDOWN_CRITICAL_PCT}%",
            value=drawdown,
            threshold=DRAWDOWN_CRITICAL_PCT,
        ))
    elif drawdown > DRAWDOWN_WARNING_PCT:
        alerts.append(Alert(
            name="drawdown_warning",
            severity="WARNING",
            message=f"Drawdown {drawdown:.1f}% exceeds warning threshold {DRAWDOWN_WARNING_PCT}%",
            value=drawdown,
            threshold=DRAWDOWN_WARNING_PCT,
        ))

    # 3. Rebalance staleness
    last_reb = metrics.get("rebalance.last_at")
    if last_reb:
        try:
            last_dt = datetime.strptime(last_reb, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            hours_since = (
                datetime.now(timezone.utc) - last_dt
            ).total_seconds() / 3600
            if hours_since > REBALANCE_STALE_HOURS:
                alerts.append(Alert(
                    name="rebalance_stale",
                    severity="WARNING",
                    message=f"Last rebalance was {hours_since:.1f}h ago (threshold {REBALANCE_STALE_HOURS}h)",
                    value=hours_since,
                    threshold=REBALANCE_STALE_HOURS,
                ))
        except (ValueError, TypeError):
            pass

    # 4. Fill rate warning
    fill_rate = metrics.get("rebalance.fill_rate_pct", 100.0)
    orders_sent = metrics.get("rebalance.orders_sent", 0)
    if orders_sent > 0 and fill_rate < FILL_RATE_WARNING_PCT:
        alerts.append(Alert(
            name="low_fill_rate",
            severity="WARNING",
            message=f"Fill rate {fill_rate:.1f}% below threshold {FILL_RATE_WARNING_PCT}%",
            value=fill_rate,
            threshold=FILL_RATE_WARNING_PCT,
        ))

    # 5. Position limit breach
    pos_count = metrics.get("portfolio.position_count", 0)
    if pos_count > MAX_TOTAL_POSITIONS:
        alerts.append(Alert(
            name="position_limit_breach",
            severity="CRITICAL",
            message=f"{pos_count} positions exceed limit of {MAX_TOTAL_POSITIONS}",
            value=float(pos_count),
            threshold=float(MAX_TOTAL_POSITIONS),
        ))

    # 6. Stop-loss triggered (informational)
    for reason in ("stop_loss", "trailing_stop", "time_stop"):
        count = metrics.get(f"stops.{reason}_count", 0)
        if count > 0:
            alerts.append(Alert(
                name=f"{reason}_triggered",
                severity="INFO",
                message=f"{reason.replace('_', ' ').title()} triggered {count} time(s)",
                value=float(count),
                threshold=0.0,
            ))

    return alerts


# ---------------------------------------------------------------------------
# 4. Notification Delivery (MVP: log-based)
# ---------------------------------------------------------------------------


def emit_alert(alert: Alert) -> None:
    """Deliver an alert via structured logging (MVP).

    Future: webhook, Telegram, email, PagerDuty.
    """
    log_level = {
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "CRITICAL": logging.CRITICAL,
    }.get(alert.severity, logging.WARNING)

    logger.log(
        log_level,
        "ALERT [%s] %s: %s (value=%.2f threshold=%.2f)",
        alert.severity,
        alert.name,
        alert.message,
        alert.value,
        alert.threshold,
        extra={
            "event": "alert",
            "alert_name": alert.name,
            "severity": alert.severity,
        },
    )


def emit_alerts(alerts: list[Alert]) -> None:
    """Emit all triggered alerts."""
    for alert in alerts:
        emit_alert(alert)


# ---------------------------------------------------------------------------
# 5. Dashboard Data Export
# ---------------------------------------------------------------------------


def export_dashboard(
    db_path: str,
    output_path: str | None = None,
    *,
    data_db_path: str | None = None,
) -> dict[str, Any]:
    """Generate a JSON snapshot for external dashboard consumption.

    Parameters
    ----------
    db_path:
        Path to the strategy database (or single combined DB).
    output_path:
        If provided, write the JSON snapshot to this file path.
    data_db_path:
        Optional path to the data database for ``traders`` queries.

    Returns
    -------
    dict
        The complete dashboard snapshot.
    """
    metrics = collect_metrics(db_path, data_db_path=data_db_path)
    alerts = check_alerts(metrics)

    # Enrich with position details
    conn = get_connection(db_path)
    try:
        positions = [
            dict(r) for r in conn.execute("SELECT * FROM our_positions").fetchall()
        ]
        recent_pnl = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM pnl_ledger ORDER BY closed_at DESC LIMIT 20"
            ).fetchall()
        ]
    finally:
        conn.close()

    snapshot: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": metrics,
        "alerts": [a.to_dict() for a in alerts],
        "positions": positions,
        "recent_pnl": recent_pnl,
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)

    return snapshot


# ---------------------------------------------------------------------------
# 6. Health-Check Status File
# ---------------------------------------------------------------------------


def write_health_check(
    db_path: str,
    health_file: str = HEALTH_CHECK_FILE,
    *,
    data_db_path: str | None = None,
) -> dict[str, Any]:
    """Write a health-check JSON file for liveness/readiness probes.

    The file contains a minimal status payload so that external monitoring
    (systemd, Docker health check, K8s probe) can verify the system is alive.

    Parameters
    ----------
    db_path:
        Path to the strategy database (or single combined DB).
    health_file:
        Path to write the health JSON file (default from config).
    data_db_path:
        Optional path to the data database (unused currently, reserved
        for future health checks on data freshness).

    Returns
    -------
    dict
        The health payload that was written.
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    status = "healthy"
    checks: dict[str, Any] = {}

    conn = get_connection(db_path)
    try:
        # Check DB connectivity
        checks["database"] = "ok"

        # Check last rebalance
        reb_row = conn.execute(
            "SELECT value FROM system_state WHERE key = 'last_rebalance_at'"
        ).fetchone()
        if reb_row and reb_row["value"]:
            try:
                last_reb = datetime.strptime(
                    reb_row["value"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
                hours_since = (now - last_reb).total_seconds() / 3600
                checks["last_rebalance_hours_ago"] = round(hours_since, 2)
                if hours_since > REBALANCE_STALE_HOURS:
                    status = "degraded"
                    checks["rebalance"] = "stale"
                else:
                    checks["rebalance"] = "ok"
            except (ValueError, TypeError):
                checks["rebalance"] = "unknown"
        else:
            checks["rebalance"] = "no_data"

        # Check position count
        pos_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM our_positions"
        ).fetchone()["cnt"]
        checks["position_count"] = pos_count
        if pos_count > MAX_TOTAL_POSITIONS:
            status = "degraded"

    except Exception as exc:
        checks["database"] = f"error: {exc}"
        status = "unhealthy"
    finally:
        conn.close()

    payload: dict[str, Any] = {
        "status": status,
        "timestamp": now_str,
        "uptime_s": round(time.monotonic(), 2),
        "checks": checks,
    }

    try:
        os.makedirs(os.path.dirname(health_file) or ".", exist_ok=True)
        with open(health_file, "w") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        logger.warning("Could not write health-check file to %s", health_file)

    return payload
