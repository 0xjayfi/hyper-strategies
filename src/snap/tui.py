"""Terminal UI display functions using rich."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import rich.box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from snap.database import get_connection

console = Console()

# State → Rich markup mapping for status bar
_STATE_STYLES: dict[str, str] = {
    "IDLE": "[dim]IDLE[/]",
    "REFRESHING": "[yellow]REFRESHING[/]",
    "REBALANCING": "[cyan]REBALANCING[/]",
    "MONITORING": "[green]MONITORING[/]",
    "INGESTING": "[blue]INGESTING[/]",
    "SHUTTING_DOWN": "[red]SHUTTING_DOWN[/]",
}

# Rank → Rich color for top-3 podium
_RANK_COLORS: dict[int, str] = {
    1: "#FFD700",  # gold
    2: "#C0C0C0",  # silver
    3: "#CD7F32",  # bronze
}


def _format_price(price: float | None) -> str:
    """Smart price formatting based on magnitude."""
    if price is None or price == 0:
        return "$0.00"
    abs_p = abs(price)
    if abs_p >= 1000:
        return f"${price:,.2f}"
    if abs_p >= 1:
        return f"${price:,.4f}"
    # sub-dollar: show enough significant digits
    if abs_p >= 0.01:
        return f"${price:.4f}"
    if abs_p >= 0.0001:
        return f"${price:.6f}"
    return f"${price:.8f}"


def _score_style(score: float) -> str:
    """Return Rich color tag for a composite score value."""
    if score >= 0.5:
        return "green"
    if score >= 0.3:
        return "yellow"
    return "dim"


def _leverage_style(lev: float) -> str:
    """Return Rich color tag for leverage risk level."""
    if lev <= 3:
        return "green"
    if lev <= 10:
        return "yellow"
    return "red"


def render_portfolio_table(db_path: str) -> Table:
    """Query our_positions and build a rich.Table.

    Columns: Token, Side, Size USD, PnL, PnL %, Leverage, Margin
    - PnL colored green (positive) / red (negative)
    - Show totals row at bottom
    - leverage column from DB (REAL DEFAULT 5.0)
    - margin = position_usd / leverage
    - PnL % = unrealized_pnl / margin * 100
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT token_symbol, side, position_usd, unrealized_pnl,
                      leverage, entry_price, current_price
               FROM our_positions ORDER BY position_usd DESC"""
        ).fetchall()
    finally:
        conn.close()

    table = Table(title="Portfolio", box=rich.box.SIMPLE_HEAVY, show_edge=False)
    table.add_column("Token", style="bold")
    table.add_column("Side")
    table.add_column("Size USD", justify="right")
    table.add_column("PnL", justify="right")
    table.add_column("PnL %", justify="right")
    table.add_column("Lev", justify="right")
    table.add_column("Margin", justify="right")

    total_size = 0.0
    total_pnl = 0.0
    total_margin = 0.0

    for r in rows:
        pos_usd = r["position_usd"] or 0.0
        pnl = r["unrealized_pnl"] or 0.0
        lev = r["leverage"] or 5.0
        margin = pos_usd / lev if lev > 0 else pos_usd
        pnl_pct = (pnl / margin * 100) if margin > 0 else 0.0

        pnl_color = "green" if pnl >= 0 else "red"
        side_color = "cyan" if r["side"] == "Long" else "magenta"

        lev_color = _leverage_style(lev)

        table.add_row(
            r["token_symbol"],
            f"[{side_color}]{r['side']}[/]",
            f"${pos_usd:,.0f}",
            f"[{pnl_color}]{pnl:+,.0f}[/]",
            f"[{pnl_color}]{pnl_pct:+.1f}%[/]",
            f"[{lev_color}]{lev:.1f}x[/]",
            f"${margin:,.0f}",
        )

        total_size += pos_usd
        total_pnl += pnl
        total_margin += margin

    # Totals row
    if rows:
        total_pnl_pct = (total_pnl / total_margin * 100) if total_margin > 0 else 0.0
        total_color = "green" if total_pnl >= 0 else "red"
        table.add_section()
        table.add_row(
            "[bold]Total[/]",
            "",
            f"[bold]${total_size:,.0f}[/]",
            f"[bold {total_color}]{total_pnl:+,.0f}[/]",
            f"[bold {total_color}]{total_pnl_pct:+.1f}%[/]",
            "",
            f"[bold]${total_margin:,.0f}[/]",
        )

    return table


def render_scores_table(db_path: str) -> Table:
    """Query latest trader_scores joined with traders, top 15 by score.

    Columns: Rank, Address (short 0x...abcd), Score, Style, ROI 30d,
    Win Rate, PF, Trades, Eligible
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT ts.address, t.label, ts.composite_score, ts.style,
                      ts.roi_30d, ts.win_rate, ts.profit_factor, ts.trade_count,
                      ts.is_eligible
               FROM trader_scores ts
               JOIN traders t ON ts.address = t.address
               WHERE ts.id IN (
                   SELECT MAX(id) FROM trader_scores GROUP BY address
               )
               ORDER BY ts.composite_score DESC
               LIMIT 15"""
        ).fetchall()
    finally:
        conn.close()

    table = Table(title="Trader Scores", box=rich.box.SIMPLE_HEAVY, show_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Address", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Style")
    table.add_column("ROI 30d", justify="right")
    table.add_column("WR", justify="right")
    table.add_column("PF", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Elig", justify="center")

    for i, r in enumerate(rows, 1):
        addr = r["address"]
        short_addr = f"{addr[:6]}..{addr[-4:]}" if len(addr) > 10 else addr
        label = r["label"] or ""
        display = f"{short_addr}" if not label else f"{short_addr} ({label})"

        score = r["composite_score"] or 0.0
        roi = r["roi_30d"] or 0.0
        wr = r["win_rate"] or 0.0
        pf = r["profit_factor"] or 0.0
        trades = r["trade_count"] or 0
        eligible = r["is_eligible"]

        roi_color = "green" if roi >= 0 else "red"
        elig_str = "[green]Y[/]" if eligible else "[dim]N[/]"

        # Top-3 rank highlighting
        rank_color = _RANK_COLORS.get(i)
        rank_str = f"[bold {rank_color}]{i}[/]" if rank_color else str(i)

        # Score gradient coloring
        sc_color = _score_style(score)

        table.add_row(
            rank_str,
            display,
            f"[{sc_color}]{score:.3f}[/]",
            r["style"] or "\u2014",
            f"[{roi_color}]{roi:+.1f}%[/]",
            f"{wr:.0%}",
            f"{pf:.1f}",
            str(trades),
            elig_str,
        )

    return table


def render_status_bar(
    state: str,
    mode: str,
    account_value: float,
    last_refresh: str | None = None,
    last_rebalance: str | None = None,
) -> Panel:
    """One-line status panel: state, mode, account value, time since last actions."""
    # Color-coded state
    styled_state = _STATE_STYLES.get(state, f"[bold]{state}[/]")

    # Mode badge with background highlight
    if mode.upper() == "PAPER":
        mode_badge = "[black on yellow] PAPER [/]"
    else:
        mode_badge = f"[black on red] {mode.upper()} [/]"

    parts = [
        mode_badge,
        f"State: {styled_state}",
        f"Acct: [bold]${account_value:,.0f}[/]",
    ]

    now = datetime.now(timezone.utc)
    if last_refresh:
        try:
            dt = datetime.strptime(last_refresh, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            hrs = (now - dt).total_seconds() / 3600
            parts.append(f"Refresh: {hrs:.1f}h ago")
        except (ValueError, TypeError):
            parts.append("Refresh: \u2014")
    else:
        parts.append("Refresh: \u2014")

    if last_rebalance:
        try:
            dt = datetime.strptime(last_rebalance, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            hrs = (now - dt).total_seconds() / 3600
            parts.append(f"Rebal: {hrs:.1f}h ago")
        except (ValueError, TypeError):
            parts.append("Rebal: \u2014")
    else:
        parts.append("Rebal: \u2014")

    line = "  \u2502  ".join(parts)
    return Panel(line, title="SNAP", border_style="blue")


def print_portfolio(db_path: str) -> None:
    """Print portfolio table to console."""
    table = render_portfolio_table(db_path)
    console.print(table)


def print_scores(db_path: str) -> None:
    """Print trader scores table to console."""
    table = render_scores_table(db_path)
    console.print(table)
