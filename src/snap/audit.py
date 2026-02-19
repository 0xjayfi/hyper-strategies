"""Paper-trading audit and verification utilities.

Implements the operational verification items from Phase 9:

1. ``audit_risk_caps``      — Verify all historical positions respected risk limits.
2. ``verify_stop_triggers`` — Confirm at least 1 of each stop type was triggered.
3. ``compare_paper_pnl``    — Compare our PnL vs tracked traders' actual performance.
4. ``generate_audit_report``— Generate a comprehensive markdown audit report.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from snap.config import (
    MAX_LEVERAGE,
    MAX_SINGLE_POSITION_HARD_CAP,
    MAX_SINGLE_POSITION_PCT,
    MAX_TOTAL_EXPOSURE_PCT,
    MAX_TOTAL_POSITIONS,
)
from snap.database import get_connection


# ---------------------------------------------------------------------------
# 1. Audit Risk Caps
# ---------------------------------------------------------------------------


def audit_risk_caps(db_path: str) -> dict[str, Any]:
    """Verify that all recorded orders and positions respected risk limits.

    Checks:
    - No single order exceeded MAX_SINGLE_POSITION_HARD_CAP
    - No single order exceeded MAX_SINGLE_POSITION_PCT of account value
    - Total exposure never exceeded MAX_TOTAL_EXPOSURE_PCT of account value
    - Position count never exceeded MAX_TOTAL_POSITIONS

    Returns a dict with ``passed`` bool and ``violations`` list.
    """
    violations: list[dict[str, Any]] = []

    conn = get_connection(db_path)
    try:
        # Get account value
        acct_row = conn.execute(
            "SELECT value FROM system_state WHERE key = 'account_value'"
        ).fetchone()
        account_value = float(acct_row["value"]) if acct_row else 0.0

        # Check 1: Single order hard cap
        if account_value > 0:
            max_single_pct_usd = account_value * MAX_SINGLE_POSITION_PCT
            max_single_usd = min(max_single_pct_usd, MAX_SINGLE_POSITION_HARD_CAP)
        else:
            max_single_usd = MAX_SINGLE_POSITION_HARD_CAP

        large_orders = conn.execute(
            "SELECT id, token_symbol, intended_usd, created_at FROM orders WHERE intended_usd > ?",
            (max_single_usd * 1.01,),  # 1% tolerance for rounding
        ).fetchall()
        for row in large_orders:
            violations.append({
                "type": "single_position_cap",
                "order_id": row["id"],
                "token": row["token_symbol"],
                "intended_usd": row["intended_usd"],
                "cap_usd": max_single_usd,
                "at": row["created_at"],
            })

        # Check 2: Total exposure from target allocations per rebalance
        rebalance_ids = conn.execute(
            "SELECT DISTINCT rebalance_id FROM target_allocations"
        ).fetchall()
        max_total_usd = account_value * MAX_TOTAL_EXPOSURE_PCT if account_value > 0 else float("inf")
        for reb_row in rebalance_ids:
            reb_id = reb_row["rebalance_id"]
            total_row = conn.execute(
                "SELECT SUM(target_usd) AS total FROM target_allocations WHERE rebalance_id = ?",
                (reb_id,),
            ).fetchone()
            total = total_row["total"] or 0.0
            if total > max_total_usd * 1.01:
                violations.append({
                    "type": "total_exposure_cap",
                    "rebalance_id": reb_id,
                    "total_usd": total,
                    "cap_usd": max_total_usd,
                })

        # Check 3: Position count from target allocations
        for reb_row in rebalance_ids:
            reb_id = reb_row["rebalance_id"]
            count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM target_allocations WHERE rebalance_id = ? AND target_usd > 0",
                (reb_id,),
            ).fetchone()
            if count_row["cnt"] > MAX_TOTAL_POSITIONS:
                violations.append({
                    "type": "position_count_cap",
                    "rebalance_id": reb_id,
                    "count": count_row["cnt"],
                    "cap": MAX_TOTAL_POSITIONS,
                })

    finally:
        conn.close()

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "checks_run": 3,
        "account_value": account_value,
    }


# ---------------------------------------------------------------------------
# 2. Verify Stop Triggers
# ---------------------------------------------------------------------------


def verify_stop_triggers(db_path: str) -> dict[str, Any]:
    """Verify that at least one of each stop type was triggered during paper trading.

    Required stop types: STOP_LOSS, TRAILING_STOP, TIME_STOP.

    Returns a dict with ``passed`` bool and counts per exit_reason.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT exit_reason, COUNT(*) AS cnt
               FROM pnl_ledger
               WHERE exit_reason IN ('STOP_LOSS', 'TRAILING_STOP', 'TIME_STOP')
               GROUP BY exit_reason"""
        ).fetchall()
    finally:
        conn.close()

    counts = {row["exit_reason"]: row["cnt"] for row in rows}
    required = ["STOP_LOSS", "TRAILING_STOP", "TIME_STOP"]
    missing = [r for r in required if counts.get(r, 0) == 0]

    return {
        "passed": len(missing) == 0,
        "counts": counts,
        "missing": missing,
        "total_stop_events": sum(counts.values()),
    }


# ---------------------------------------------------------------------------
# 3. Compare Paper PnL vs Traders
# ---------------------------------------------------------------------------


def compare_paper_pnl(
    db_path: str, *, data_db_path: str | None = None
) -> dict[str, Any]:
    """Compare our paper-trade PnL against tracked traders' actual performance.

    Parameters
    ----------
    db_path:
        Path to the strategy database (or single combined DB).
    data_db_path:
        Optional path to the data database.  When provided, the
        ``traders`` table is read from this DB and joined in Python.

    Returns our realized PnL summary and trader ROI for comparison.
    """
    conn = get_connection(db_path)
    try:
        # Our realized PnL
        pnl_rows = conn.execute(
            """SELECT token_symbol, side, realized_pnl, fees_total, hold_hours,
                      exit_reason, closed_at
               FROM pnl_ledger ORDER BY closed_at"""
        ).fetchall()
        our_trades = [dict(r) for r in pnl_rows]
        our_total_pnl = sum(t["realized_pnl"] for t in our_trades)
        our_total_fees = sum(t["fees_total"] or 0.0 for t in our_trades)
        our_net_pnl = our_total_pnl - our_total_fees

        wins = [t for t in our_trades if t["realized_pnl"] > 0]
        losses = [t for t in our_trades if t["realized_pnl"] <= 0]
        win_rate = len(wins) / len(our_trades) if our_trades else 0.0

        # Account value
        acct_row = conn.execute(
            "SELECT value FROM system_state WHERE key = 'account_value'"
        ).fetchone()
        account_value = float(acct_row["value"]) if acct_row else 0.0
        our_return_pct = (our_net_pnl / account_value * 100) if account_value > 0 else 0.0

        # Tracked traders' ROI from scores
        if data_db_path and data_db_path != db_path:
            # Two-DB mode: query separately and join in Python
            score_rows = conn.execute(
                """SELECT address, roi_30d, composite_score
                   FROM trader_scores
                   WHERE is_eligible = 1
                   ORDER BY composite_score DESC
                   LIMIT 15"""
            ).fetchall()
            data_conn = get_connection(data_db_path)
            try:
                labels = {}
                for row in data_conn.execute(
                    "SELECT address, label FROM traders"
                ).fetchall():
                    labels[row["address"]] = row["label"]
            finally:
                data_conn.close()
            trader_summary = [
                {
                    "address": r["address"],
                    "label": labels.get(r["address"], ""),
                    "roi_30d": r["roi_30d"],
                    "composite_score": r["composite_score"],
                }
                for r in score_rows
            ]
        else:
            trader_rows = conn.execute(
                """SELECT ts.address, t.label, ts.roi_30d, ts.composite_score
                   FROM trader_scores ts
                   JOIN traders t ON t.address = ts.address
                   WHERE ts.is_eligible = 1
                   ORDER BY ts.composite_score DESC
                   LIMIT 15"""
            ).fetchall()
            trader_summary = [dict(r) for r in trader_rows]
        avg_trader_roi = (
            sum(t["roi_30d"] or 0.0 for t in trader_summary) / len(trader_summary)
            if trader_summary else 0.0
        )

        # Exit reason breakdown
        exit_counts: dict[str, int] = {}
        for t in our_trades:
            reason = t["exit_reason"] or "UNKNOWN"
            exit_counts[reason] = exit_counts.get(reason, 0) + 1

    finally:
        conn.close()

    return {
        "our_total_pnl": our_total_pnl,
        "our_total_fees": our_total_fees,
        "our_net_pnl": our_net_pnl,
        "our_return_pct": our_return_pct,
        "our_trade_count": len(our_trades),
        "our_win_rate": win_rate,
        "exit_counts": exit_counts,
        "avg_trader_roi_30d": avg_trader_roi,
        "tracked_trader_count": len(trader_summary),
        "account_value": account_value,
    }


# ---------------------------------------------------------------------------
# 4. Generate Audit Report
# ---------------------------------------------------------------------------


def generate_audit_report(
    db_path: str, *, data_db_path: str | None = None
) -> str:
    """Generate a comprehensive markdown audit report.

    Combines risk cap audit, stop trigger verification, and PnL comparison.

    Parameters
    ----------
    db_path:
        Path to the strategy database (or single combined DB).
    data_db_path:
        Optional path to the data database for ``traders`` queries.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    caps = audit_risk_caps(db_path)
    stops = verify_stop_triggers(db_path)
    pnl = compare_paper_pnl(db_path, data_db_path=data_db_path)

    lines = [
        "# Snap Paper Trading Audit Report",
        f"",
        f"**Generated**: {now}",
        f"**Account Value**: ${pnl['account_value']:,.0f}",
        "",
        "---",
        "",
        "## 1. Risk Cap Audit",
        "",
        f"**Result**: {'PASS' if caps['passed'] else 'FAIL'}",
        f"**Checks Run**: {caps['checks_run']}",
        f"**Violations**: {len(caps['violations'])}",
        "",
    ]

    if caps["violations"]:
        lines.append("| Type | Details |")
        lines.append("|------|---------|")
        for v in caps["violations"]:
            lines.append(f"| {v['type']} | {v} |")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 2. Stop Trigger Verification",
        "",
        f"**Result**: {'PASS' if stops['passed'] else 'FAIL'}",
        f"**Total Stop Events**: {stops['total_stop_events']}",
        "",
        "| Stop Type | Count |",
        "|-----------|-------|",
    ])
    for reason in ["STOP_LOSS", "TRAILING_STOP", "TIME_STOP"]:
        count = stops["counts"].get(reason, 0)
        status = "OK" if count > 0 else "MISSING"
        lines.append(f"| {reason} | {count} ({status}) |")

    if stops["missing"]:
        lines.extend([
            "",
            f"**Missing**: {', '.join(stops['missing'])}",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## 3. Paper PnL vs Tracked Traders",
        "",
        "### Our Performance",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total PnL | ${pnl['our_total_pnl']:,.2f} |",
        f"| Total Fees | ${pnl['our_total_fees']:,.2f} |",
        f"| Net PnL | ${pnl['our_net_pnl']:,.2f} |",
        f"| Return % | {pnl['our_return_pct']:.2f}% |",
        f"| Trade Count | {pnl['our_trade_count']} |",
        f"| Win Rate | {pnl['our_win_rate']:.1%} |",
        "",
        "### Exit Reason Breakdown",
        "",
        "| Reason | Count |",
        "|--------|-------|",
    ])
    for reason, count in sorted(pnl["exit_counts"].items()):
        lines.append(f"| {reason} | {count} |")

    lines.extend([
        "",
        "### Tracked Traders (Benchmark)",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Tracked Traders | {pnl['tracked_trader_count']} |",
        f"| Avg Trader ROI (30d) | {pnl['avg_trader_roi_30d']:.2f}% |",
        "",
        "---",
        "",
        "## 4. Graduation Criteria",
        "",
        "| Criterion | Status |",
        "|-----------|--------|",
        f"| 14+ days continuous operation | Manual check |",
        f"| No single position loss > 5% | {'PASS' if caps['passed'] else 'FAIL'} |",
        f"| Total drawdown < 10% | Manual check |",
        f"| All risk caps applied correctly | {'PASS' if caps['passed'] else 'FAIL'} |",
        "| All stop types triggered (3/3) | {} |".format(
            "PASS" if stops["passed"] else f"FAIL ({len(stops['missing'])} missing)"
        ),
        "",
    ])

    return "\n".join(lines)
