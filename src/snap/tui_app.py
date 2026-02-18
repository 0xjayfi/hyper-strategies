"""Textual-based TUI application for the Snap copytrading system.

Provides:
1. Onboarding wizard (strategy selection, start stage, customizable options)
2. Main dashboard with fixed layout (status bar, portfolio, scores, log panel)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Rule,
    Static,
)

from snap.config import (
    ACCOUNT_VALUE,
    MAX_POSITION_DURATION_HOURS,
    MAX_TOTAL_POSITIONS,
    MONITOR_INTERVAL_SECONDS,
    REBALANCE_INTERVAL_HOURS,
)
from snap.database import get_connection
from snap.variants import VARIANT_DESCRIPTIONS, VARIANT_LABELS, VARIANTS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Onboarding config dataclass
# ---------------------------------------------------------------------------


@dataclass
class OnboardingConfig:
    """Holds all user choices from the onboarding wizard."""

    variant_key: str = "V1"
    start_stage: str = "daily"  # "daily", "rebalance", "monitor"
    rebalance_interval_hours: int = REBALANCE_INTERVAL_HOURS
    max_hold_hours: int = MAX_POSITION_DURATION_HOURS
    monitor_interval_seconds: int = MONITOR_INTERVAL_SECONDS
    account_value: float = ACCOUNT_VALUE
    max_positions: int = MAX_TOTAL_POSITIONS


# ---------------------------------------------------------------------------
# CSS for the entire app
# ---------------------------------------------------------------------------

APP_CSS = """
/* ── Onboarding screens ─────────────────────────────────────── */

OnboardingIntro {
    align: center middle;
}

OnboardingIntro #intro-container {
    width: 96;
    height: auto;
    max-height: 95%;
    border: thick $accent;
    padding: 1 2;
    background: $surface;
}

OnboardingIntro #intro-container #title {
    text-align: center;
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}

OnboardingIntro #intro-container #step-indicator {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingIntro #intro-container #subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingIntro #intro-container .section-head {
    text-style: bold;
    color: $accent;
    margin-top: 1;
}

OnboardingIntro #intro-container .section-body {
    margin: 0 0 0 2;
    color: $text;
}

OnboardingIntro #intro-container #btn-row {
    align-horizontal: right;
    height: 3;
    margin-top: 1;
}

OnboardingStrategy {
    align: center middle;
}

OnboardingStrategy #strategy-container {
    width: 90;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    padding: 1 2;
    background: $surface;
}

OnboardingStrategy #strategy-container #title {
    text-align: center;
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}

OnboardingStrategy #strategy-container #step-indicator {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingStrategy #strategy-container #subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingStrategy #strategy-container RadioSet {
    width: 100%;
    margin: 0 0 1 0;
}

OnboardingStrategy #strategy-container #description-box {
    height: auto;
    min-height: 5;
    padding: 1;
    border: tall $primary;
    margin: 0 0 1 0;
    background: $boost;
}

OnboardingStrategy #strategy-container #btn-row {
    align-horizontal: right;
    height: 3;
}


OnboardingStage {
    align: center middle;
}

OnboardingStage #stage-container {
    width: 70;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    padding: 1 2;
    background: $surface;
}

OnboardingStage #stage-container #title {
    text-align: center;
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}

OnboardingStage #stage-container #step-indicator {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingStage #stage-container #subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingStage #stage-container RadioSet {
    width: 100%;
    margin: 0 0 1 0;
}

OnboardingStage #stage-container #stage-desc {
    height: 4;
    padding: 1;
    border: tall $primary;
    margin: 0 0 1 0;
    background: $boost;
}

OnboardingStage #stage-container #btn-row {
    align-horizontal: right;
    height: 3;
}


OnboardingOptions {
    align: center middle;
}

OnboardingOptions #options-container {
    width: 70;
    height: auto;
    max-height: 85%;
    border: thick $accent;
    padding: 1 2;
    background: $surface;
}

OnboardingOptions #options-container #title {
    text-align: center;
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}

OnboardingOptions #options-container #step-indicator {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingOptions #options-container #subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}

OnboardingOptions .option-row {
    height: 3;
    margin: 0 0 1 0;
}

OnboardingOptions .option-row Label {
    width: 30;
    padding: 1 1 0 0;
    text-align: right;
}

OnboardingOptions .option-row Input {
    width: 1fr;
}

OnboardingOptions #options-container #btn-row {
    align-horizontal: right;
    height: 3;
    margin-top: 1;
}


/* ── Main dashboard ─────────────────────────────────────────── */

DashboardScreen {
    layout: grid;
    grid-size: 2 3;
    grid-rows: 3 1fr 14;
    grid-columns: 1fr 1fr;
    grid-gutter: 1;
    padding: 0 1;
}

DashboardScreen #status-bar {
    column-span: 2;
    height: 3;
    border: tall $accent;
    padding: 0 1;
    background: $boost;
}

DashboardScreen #portfolio-panel {
    border: tall $primary;
    height: 100%;
}

DashboardScreen #scores-panel {
    border: tall $primary;
    height: 100%;
}

DashboardScreen #log-panel {
    column-span: 2;
    border: tall $secondary;
    height: 14;
}

DashboardScreen DataTable {
    height: 1fr;
}

DashboardScreen RichLog {
    height: 1fr;
}

DashboardScreen .panel-title {
    text-style: bold;
    color: $text;
    padding: 0 1;
    background: $primary-background;
}
"""

# ---------------------------------------------------------------------------
# Onboarding: Step 0 – Intro / Welcome
# ---------------------------------------------------------------------------


class OnboardingIntro(Screen):
    """Welcome screen with workflow overview and scoring parameter definitions."""

    BINDINGS = [Binding("escape", "app.quit", "Quit")]

    def __init__(self, config: OnboardingConfig) -> None:
        super().__init__()
        self.ob_config = config

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="intro-container"):
            yield Static("SNAP — Hyperliquid Copytrading System", id="title")
            yield Static("Step 1 of 4  ● ○ ○ ○", id="step-indicator")
            yield Static(
                "Mirror the aggregate positioning of top perp traders via position snapshot rebalancing.",
                id="subtitle",
            )
            yield Rule()

            # ── Workflow ──
            yield Static("WORKFLOW", classes="section-head")
            yield Static(
                "1. Daily Refresh — Fetch the Nansen perp leaderboard, apply filters, "
                "score and rank traders, select top 15 eligible.",
                classes="section-body",
            )
            yield Static(
                "2. Rebalance (every 4h) — Snapshot tracked traders' live positions, "
                "compute score-weighted target portfolio, apply 6-step risk overlay, "
                "diff against current holdings, execute orders.",
                classes="section-body",
            )
            yield Static(
                "3. Monitor (every 60s) — Check stop-loss, trailing stop, and "
                "time-stop triggers on all open positions. Close breached positions.",
                classes="section-body",
            )
            yield Static(
                "4. Ingest (every 5m) — Fetch latest trade history for tracked "
                "traders to keep scoring data fresh.",
                classes="section-body",
            )

            yield Rule()

            # ── Scoring parameters ──
            yield Static("SCORING PARAMETERS", classes="section-head")
            yield Static(
                "Traders are scored using a weighted composite of six components:",
                classes="section-body",
            )
            yield Static(
                "  ROI (25%)          — Return on investment across 7d/30d/90d, "
                "normalized against the cohort.",
                classes="section-body",
            )
            yield Static(
                "  Sharpe (20%)       — Pseudo-Sharpe ratio estimated from trade-level "
                "PnL: mean(pnl) / stdev(pnl). Higher = better risk-adjusted returns.",
                classes="section-body",
            )
            yield Static(
                "  Consistency (20%)  — Multi-timeframe check: requires positive ROI "
                "on 7d, 30d, and 90d windows simultaneously.",
                classes="section-body",
            )
            yield Static(
                "  Win Rate (15%)     — Fraction of trades closed in profit. Bounded "
                "between 30%-95% to exclude bots and outliers.",
                classes="section-body",
            )
            yield Static(
                "  Smart Money (10%)  — Bonus for wallets flagged as smart money on "
                "Nansen (institutional, fund, or whale labels).",
                classes="section-body",
            )
            yield Static(
                "  Risk Mgmt (10%)    — Penalizes excessive leverage, rewards "
                "isolated margin usage and controlled position sizing.",
                classes="section-body",
            )

            yield Rule()

            yield Static("FILTER PIPELINE", classes="section-head")
            yield Static(
                "  Tier-1 Filter      — Minimum ROI and account value ($25K+).",
                classes="section-body",
            )
            yield Static(
                "  Consistency Gate   — Multi-timeframe profitability required.",
                classes="section-body",
            )
            yield Static(
                "  Quality Gate       — Min trade count, win rate range, profit factor.",
                classes="section-body",
            )
            yield Static(
                "  Recency Decay      — Recent performance weighted higher than old.",
                classes="section-body",
            )
            yield Static(
                "  Style Multiplier   — Trend, swing, and HFT traders scored differently.",
                classes="section-body",
            )

            with Horizontal(id="btn-row"):
                yield Button("Get Started →", variant="primary", id="btn-next")

    @on(Button.Pressed, "#btn-next")
    def _go_next(self, event: Button.Pressed) -> None:
        self.app.push_screen(OnboardingStrategy(self.ob_config))


# ---------------------------------------------------------------------------
# Onboarding: Step 1 – Strategy Selection
# ---------------------------------------------------------------------------

_VARIANT_KEYS = list(VARIANTS.keys())


class OnboardingStrategy(Screen):
    """Strategy selection screen."""

    BINDINGS = [Binding("escape", "app.quit", "Quit")]

    def __init__(self, config: OnboardingConfig) -> None:
        super().__init__()
        self.ob_config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="strategy-container"):
            yield Static("SNAP — Scoring Strategy", id="title")
            yield Static("Step 2 of 4  ● ● ○ ○", id="step-indicator")
            yield Static(
                "Choose which trader scoring strategy to use.", id="subtitle"
            )
            yield Rule()
            with RadioSet(id="strategy-radio"):
                for key in _VARIANT_KEYS:
                    label = f"{key}: {VARIANT_LABELS[key]}"
                    yield RadioButton(label, value=key == self.ob_config.variant_key)
            yield Static(
                VARIANT_DESCRIPTIONS.get(self.ob_config.variant_key, ""),
                id="description-box",
            )
            with Horizontal(id="btn-row"):
                yield Button("Next →", variant="primary", id="btn-next")

    @on(RadioSet.Changed, "#strategy-radio")
    def _strategy_changed(self, event: RadioSet.Changed) -> None:
        idx = event.radio_set.pressed_index
        if idx is not None and 0 <= idx < len(_VARIANT_KEYS):
            key = _VARIANT_KEYS[idx]
            self.ob_config.variant_key = key
            desc_widget = self.query_one("#description-box", Static)
            desc_widget.update(VARIANT_DESCRIPTIONS.get(key, ""))

    @on(Button.Pressed, "#btn-next")
    def _go_next(self, event: Button.Pressed) -> None:
        self.app.push_screen(OnboardingStage(self.ob_config))


# ---------------------------------------------------------------------------
# Onboarding: Step 2 – Start Stage
# ---------------------------------------------------------------------------

_STAGES = [
    ("daily", "Fresh Start (Daily Flow)", "Run the full pipeline from the beginning: fetch leaderboard, score traders, then rebalance and monitor."),
    ("rebalance", "From Rebalancing", "Skip trader refresh. Assumes traders are already scored in the database. Starts from position snapshot and rebalancing."),
    ("monitor", "Monitor Only", "Skip both refresh and rebalance. Only run the position monitor loop to check stop-loss and trailing stops on existing positions."),
]


class OnboardingStage(Screen):
    """Start stage selection screen."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    def __init__(self, config: OnboardingConfig) -> None:
        super().__init__()
        self.ob_config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="stage-container"):
            yield Static("SNAP — Starting Stage", id="title")
            yield Static("Step 3 of 4  ● ● ● ○", id="step-indicator")
            yield Static(
                "Where should the system start?", id="subtitle"
            )
            yield Rule()
            with RadioSet(id="stage-radio"):
                for key, label, _ in _STAGES:
                    yield RadioButton(
                        label, value=key == self.ob_config.start_stage
                    )
            current = next(
                (desc for k, _, desc in _STAGES if k == self.ob_config.start_stage),
                "",
            )
            yield Static(current, id="stage-desc")
            with Horizontal(id="btn-row"):
                yield Button("← Back", id="btn-back")
                yield Button("Next →", variant="primary", id="btn-next")

    @on(RadioSet.Changed, "#stage-radio")
    def _stage_changed(self, event: RadioSet.Changed) -> None:
        idx = event.radio_set.pressed_index
        if idx is not None and 0 <= idx < len(_STAGES):
            key, _, desc = _STAGES[idx]
            self.ob_config.start_stage = key
            self.query_one("#stage-desc", Static).update(desc)

    @on(Button.Pressed, "#btn-back")
    def _go_back(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-next")
    def _go_next(self, event: Button.Pressed) -> None:
        self.app.push_screen(OnboardingOptions(self.ob_config))

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Onboarding: Step 3 – Customizable Options
# ---------------------------------------------------------------------------


class OnboardingOptions(Screen):
    """Customizable parameters screen."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    def __init__(self, config: OnboardingConfig) -> None:
        super().__init__()
        self.ob_config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="options-container"):
            yield Static("SNAP — Configuration", id="title")
            yield Static("Step 4 of 4  ● ● ● ●", id="step-indicator")
            yield Static("Customize runtime parameters (or keep defaults).", id="subtitle")
            yield Rule()

            with Horizontal(classes="option-row"):
                yield Label("Account Value ($):")
                yield Input(
                    str(int(self.ob_config.account_value)),
                    id="inp-account",
                    type="number",
                )

            with Horizontal(classes="option-row"):
                yield Label("Rebalance Interval (hours):")
                yield Input(
                    str(self.ob_config.rebalance_interval_hours),
                    id="inp-rebal",
                    type="integer",
                )

            with Horizontal(classes="option-row"):
                yield Label("Max Hold Time (hours):")
                yield Input(
                    str(self.ob_config.max_hold_hours),
                    id="inp-hold",
                    type="integer",
                )

            with Horizontal(classes="option-row"):
                yield Label("Monitor Interval (seconds):")
                yield Input(
                    str(self.ob_config.monitor_interval_seconds),
                    id="inp-monitor",
                    type="integer",
                )

            with Horizontal(classes="option-row"):
                yield Label("Max Positions:")
                yield Input(
                    str(self.ob_config.max_positions),
                    id="inp-max-pos",
                    type="integer",
                )

            with Horizontal(id="btn-row"):
                yield Button("← Back", id="btn-back")
                yield Button("Launch ✓", variant="success", id="btn-launch")

    @on(Button.Pressed, "#btn-back")
    def _go_back(self, event: Button.Pressed) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-launch")
    def _launch(self, event: Button.Pressed) -> None:
        # Read input values
        try:
            val = self.query_one("#inp-account", Input).value
            self.ob_config.account_value = float(val) if val else ACCOUNT_VALUE
        except (ValueError, TypeError):
            pass
        try:
            val = self.query_one("#inp-rebal", Input).value
            self.ob_config.rebalance_interval_hours = int(val) if val else REBALANCE_INTERVAL_HOURS
        except (ValueError, TypeError):
            pass
        try:
            val = self.query_one("#inp-hold", Input).value
            self.ob_config.max_hold_hours = int(val) if val else MAX_POSITION_DURATION_HOURS
        except (ValueError, TypeError):
            pass
        try:
            val = self.query_one("#inp-monitor", Input).value
            self.ob_config.monitor_interval_seconds = int(val) if val else MONITOR_INTERVAL_SECONDS
        except (ValueError, TypeError):
            pass
        try:
            val = self.query_one("#inp-max-pos", Input).value
            self.ob_config.max_positions = int(val) if val else MAX_TOTAL_POSITIONS
        except (ValueError, TypeError):
            pass

        # Switch to dashboard — replace entire screen stack
        self.app.switch_screen(DashboardScreen(self.ob_config))

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Main Dashboard Screen
# ---------------------------------------------------------------------------

_STATE_COLORS: dict[str, str] = {
    "IDLE": "dim",
    "REFRESHING": "yellow",
    "REBALANCING": "cyan",
    "MONITORING": "green",
    "SHUTTING_DOWN": "red",
}


def _fmt_price(price: float) -> str:
    """Smart decimal formatting based on price magnitude."""
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:,.4f}"
    elif price >= 0.01:
        return f"${price:.6f}"
    else:
        return f"${price:.8f}"


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _render_sparkline(values: list[float], width: int = 8) -> str:
    """Render a list of floats as a unicode sparkline string."""
    if not values or len(values) < 2:
        return "─" * width
    recent = values[-width:]
    lo, hi = min(recent), max(recent)
    if hi == lo:
        return _SPARK_CHARS[3] * len(recent)
    chars = []
    for v in recent:
        idx = int((v - lo) / (hi - lo) * (len(_SPARK_CHARS) - 1))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars)


class TextualLogHandler(logging.Handler):
    """Route Python log records into a Textual RichLog widget."""

    def __init__(self, rich_log: RichLog) -> None:
        super().__init__()
        self.rich_log = rich_log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname
            if level == "ERROR" or level == "CRITICAL":
                style = "bold red"
            elif level == "WARNING":
                style = "yellow"
            elif level == "DEBUG":
                style = "dim"
            else:
                style = ""
            self.rich_log.write(Text(msg, style=style))
        except Exception:
            pass


class DashboardScreen(Screen):
    """Main operational dashboard with fixed layout panels."""

    BINDINGS = [
        Binding("r", "refresh_traders", "Refresh Traders"),
        Binding("b", "rebalance", "Rebalance"),
        Binding("m", "monitor", "Monitor"),
        Binding("s", "show_scores", "Refresh Scores"),
        Binding("p", "show_portfolio", "Refresh Portfolio"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, config: OnboardingConfig) -> None:
        super().__init__()
        self.ob_config = config
        self.scheduler = None
        self._log_handler: TextualLogHandler | None = None
        self._last_rebalance_time: datetime | None = None
        self._last_refresh_time: datetime | None = None
        self._current_state: str = "IDLE"
        self._pnl_history: dict[str, list[float]] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Status bar
        variant_label = VARIANT_LABELS.get(self.ob_config.variant_key, "?")
        status_text = (
            f"[black on yellow] PAPER [/]  │  Strategy: {self.ob_config.variant_key} ({variant_label})  │  "
            f"Acct: ${self.ob_config.account_value:,.0f}  │  "
            f"State: [dim]IDLE[/]  │  "
            f"Rebal: {self.ob_config.rebalance_interval_hours}h  │  "
            f"Hold: {self.ob_config.max_hold_hours}h"
        )
        yield Static(status_text, id="status-bar")

        # Row 2: Portfolio (left) | Scores (right)
        with Vertical(id="portfolio-panel"):
            yield Static(" Portfolio", classes="panel-title")
            yield DataTable(id="portfolio-table")

        with Vertical(id="scores-panel"):
            yield Static(" Trader Scores (Top 15)", classes="panel-title")
            yield DataTable(id="scores-table")

        # Row 3: Log panel (full width, bottom strip)
        with Vertical(id="log-panel"):
            yield Static(" Logs", classes="panel-title")
            yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)

        yield Footer()

    def on_mount(self) -> None:
        # Set up portfolio table columns
        ptable = self.query_one("#portfolio-table", DataTable)
        ptable.add_columns("Token", "Side", "Entry", "Live", "Size USD", "PnL", "PnL %", "Lev", "Margin", "Trend")
        ptable.cursor_type = "row"

        # Set up scores table columns
        stable = self.query_one("#scores-table", DataTable)
        stable.add_columns("#", "Address", "Score", "Style", "ROI 30d", "WR", "PF", "Trades", "Elig")
        stable.cursor_type = "row"

        # Install log handler
        log_view = self.query_one("#log-view", RichLog)
        self._log_handler = TextualLogHandler(log_view)
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(self._log_handler)
        root_logger.setLevel(logging.INFO)

        # Run DB migration before loading data (adds leverage column if missing)
        from snap.database import init_db

        try:
            conn = init_db(self.app.db_path)
            conn.close()
        except Exception as e:
            log_view.write(Text(f"DB init error: {e}", style="bold red"))

        # Initial data load
        log_view.write(Text("SNAP system starting...", style="bold green"))
        log_view.write(Text(
            f"Strategy: {self.ob_config.variant_key} ({VARIANT_LABELS.get(self.ob_config.variant_key, '')})  "
            f"Start: {self.ob_config.start_stage}  "
            f"Account: ${self.ob_config.account_value:,.0f}",
            style="bold",
        ))

        self._load_portfolio()
        self._load_scores()

        # Periodic countdown refresh
        self.set_interval(30, self._tick_status)

        self.notify("Dashboard ready", title="SNAP", severity="information")

        # Start the scheduler in background
        self._start_scheduler()

    def on_unmount(self) -> None:
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)

    # -- Data loading -------------------------------------------------------

    def _load_portfolio(self) -> None:
        """Load portfolio data from the database into the DataTable."""
        ptable = self.query_one("#portfolio-table", DataTable)
        ptable.clear()

        try:
            db_path = self.app.db_path
            conn = get_connection(db_path)
            try:
                rows = conn.execute(
                    """SELECT token_symbol, side, position_usd, unrealized_pnl,
                              leverage, entry_price, current_price
                       FROM our_positions ORDER BY position_usd DESC"""
                ).fetchall()
            finally:
                conn.close()

            total_size = 0.0
            total_pnl = 0.0
            total_margin = 0.0

            for r in rows:
                pos_usd = r["position_usd"] or 0.0
                pnl = r["unrealized_pnl"] or 0.0
                lev = r["leverage"] or 5.0
                margin = pos_usd / lev if lev > 0 else pos_usd
                pnl_pct = (pnl / margin * 100) if margin > 0 else 0.0

                pnl_style = "green" if pnl >= 0 else "red"
                side_style = "cyan" if r["side"] == "Long" else "magenta"

                entry = r["entry_price"] or 0.0
                live = r["current_price"] or 0.0

                lev_style = "green" if lev <= 3 else ("yellow" if lev <= 10 else "red")

                token = r["token_symbol"]
                self._pnl_history.setdefault(token, []).append(pnl)
                self._pnl_history[token] = self._pnl_history[token][-20:]

                spark = _render_sparkline(self._pnl_history.get(token, []))
                hist = self._pnl_history.get(token, [])
                if len(hist) >= 2:
                    trend_style = "green" if hist[-1] >= hist[0] else "red"
                else:
                    trend_style = "dim"

                ptable.add_row(
                    token,
                    Text(r["side"], style=side_style),
                    _fmt_price(entry),
                    _fmt_price(live),
                    f"${pos_usd:,.0f}",
                    Text(f"{pnl:+,.0f}", style=pnl_style),
                    Text(f"{pnl_pct:+.1f}%", style=pnl_style),
                    Text(f"{lev:.1f}x", style=lev_style),
                    f"${margin:,.0f}",
                    Text(spark, style=trend_style),
                )

                total_size += pos_usd
                total_pnl += pnl
                total_margin += margin

            if rows:
                total_pnl_pct = (total_pnl / total_margin * 100) if total_margin > 0 else 0.0
                total_style = "green" if total_pnl >= 0 else "red"
                ptable.add_row(
                    Text("Total", style="bold"),
                    "",
                    "",
                    "",
                    Text(f"${total_size:,.0f}", style="bold"),
                    Text(f"{total_pnl:+,.0f}", style=f"bold {total_style}"),
                    Text(f"{total_pnl_pct:+.1f}%", style=f"bold {total_style}"),
                    "",
                    Text(f"${total_margin:,.0f}", style="bold"),
                    "",
                )
            else:
                ptable.add_row(
                    Text("No positions yet — waiting for first rebalance", style="dim italic"),
                    "", "", "", "", "", "", "", "", "",
                )
        except Exception as e:
            logger.warning("Portfolio load failed: %s", e)

    def _load_scores(self) -> None:
        """Load trader scores from the database into the DataTable."""
        stable = self.query_one("#scores-table", DataTable)
        stable.clear()

        try:
            db_path = self.app.db_path
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

            for i, r in enumerate(rows, 1):
                addr = r["address"]
                short_addr = f"{addr[:6]}..{addr[-4:]}" if len(addr) > 10 else addr
                label = r["label"] or ""
                display = short_addr if not label else f"{short_addr} ({label})"

                score = r["composite_score"] or 0.0
                roi = r["roi_30d"] or 0.0
                wr = r["win_rate"] or 0.0
                pf = r["profit_factor"] or 0.0
                trades = r["trade_count"] or 0
                eligible = r["is_eligible"]

                # Top-3 rank styling
                if i == 1:
                    rank_cell = Text(str(i), style="bold yellow")
                elif i == 2:
                    rank_cell = Text(str(i), style="bold white")
                elif i == 3:
                    rank_cell = Text(str(i), style="bold rgb(205,127,50)")
                else:
                    rank_cell = Text(str(i))

                # Score color gradient
                if score > 0.5:
                    score_cell = Text(f"{score:.3f}", style="green")
                elif score >= 0.3:
                    score_cell = Text(f"{score:.3f}", style="yellow")
                else:
                    score_cell = Text(f"{score:.3f}", style="dim")

                roi_style = "green" if roi >= 0 else "red"
                elig_text = Text("Y", style="green") if eligible else Text("N", style="dim")

                stable.add_row(
                    rank_cell,
                    display,
                    score_cell,
                    r["style"] or "—",
                    Text(f"{roi:+.1f}%", style=roi_style),
                    f"{wr:.0%}",
                    f"{pf:.1f}",
                    str(trades),
                    elig_text,
                )

            if not rows:
                stable.add_row(
                    Text("No scores yet — press 'r' to refresh traders", style="dim italic"),
                    "", "", "", "", "", "", "", "",
                )
        except Exception as e:
            logger.warning("Scores load failed: %s", e)

    def _update_status(self, state: str = "IDLE") -> None:
        """Update the status bar text with live countdowns."""
        self._current_state = state
        variant_label = VARIANT_LABELS.get(self.ob_config.variant_key, "?")
        state_color = _STATE_COLORS.get(state, "dim")

        now = datetime.now(timezone.utc)

        # Compute next rebalance countdown
        if self._last_rebalance_time is not None:
            next_rebal = self._last_rebalance_time + timedelta(hours=self.ob_config.rebalance_interval_hours)
            remaining = next_rebal - now
            if remaining.total_seconds() <= 0:
                rebal_str = "now"
            else:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                rebal_str = f"{hours}h {minutes:02d}m"
        else:
            rebal_str = "pending"

        # Compute next refresh countdown
        if self._last_refresh_time is not None:
            next_refresh = self._last_refresh_time + timedelta(hours=24)
            remaining = next_refresh - now
            if remaining.total_seconds() <= 0:
                refresh_str = "now"
            else:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                refresh_str = f"{hours}h {minutes:02d}m"
        else:
            refresh_str = "pending"

        status_text = (
            f"[black on yellow] PAPER [/]  │  Strategy: {self.ob_config.variant_key} ({variant_label})  │  "
            f"Acct: ${self.ob_config.account_value:,.0f}  │  "
            f"State: [{state_color}]{state}[/]  │  "
            f"Next rebal: {rebal_str}  │  "
            f"Next refresh: {refresh_str}"
        )
        self.query_one("#status-bar", Static).update(status_text)

    def _tick_status(self) -> None:
        """Periodic callback to refresh the status bar countdown."""
        self._update_status(self._current_state)

    # -- Scheduler integration -----------------------------------------------

    @work(thread=False)
    async def _start_scheduler(self) -> None:
        """Initialize and start the system scheduler based on onboarding config."""
        from snap.config import NANSEN_API_KEY
        from snap.database import init_db
        from snap.execution import PaperTradeClient
        from snap.nansen_client import NansenClient
        from snap.scheduler import SystemScheduler, set_system_state

        db_path = self.app.db_path

        # Initialize DB
        conn = init_db(db_path)
        conn.close()

        # Set account value
        set_system_state(db_path, "account_value", str(self.ob_config.account_value))

        if not NANSEN_API_KEY:
            logger.error("NANSEN_API_KEY not set. Export it or add to .env file.")
            self.notify("NANSEN_API_KEY not set!", title="Config Error", severity="error")
            return

        client = PaperTradeClient(mark_prices={}, live_prices=True)
        nansen_client = NansenClient(api_key=NANSEN_API_KEY)

        scheduler = SystemScheduler(
            client=client,
            nansen_client=nansen_client,
            db_path=db_path,
        )
        scheduler.recover_state()
        self.scheduler = scheduler

        # Apply onboarding config to skip stages
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if self.ob_config.start_stage == "rebalance":
            # Pretend trader refresh just happened so scheduler skips it
            scheduler._last_trader_refresh = now
            set_system_state(
                db_path,
                "last_trader_refresh_at",
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            logger.info("Skipping daily refresh (starting from rebalance)")
        elif self.ob_config.start_stage == "monitor":
            # Pretend both refresh and rebalance just happened
            scheduler._last_trader_refresh = now
            scheduler._last_rebalance = now
            set_system_state(
                db_path,
                "last_trader_refresh_at",
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            set_system_state(
                db_path,
                "last_rebalance_at",
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            logger.info("Skipping daily refresh and rebalance (monitor only)")

        logger.info(
            "Scheduler starting — stage=%s variant=%s",
            self.ob_config.start_stage,
            self.ob_config.variant_key,
        )

        try:
            await scheduler.run()
        except asyncio.CancelledError:
            logger.info("Scheduler cancelled")
        finally:
            await nansen_client.close()

    # -- Key bindings --------------------------------------------------------

    def action_refresh_traders(self) -> None:
        if self.scheduler:
            self._update_status("REFRESHING")
            self._run_refresh()

    @work(thread=False)
    async def _run_refresh(self) -> None:
        if self.scheduler:
            await self.scheduler._run_trader_refresh()
            self._last_refresh_time = datetime.now(timezone.utc)
            self._update_status("IDLE")
            self._load_scores()
            self._load_portfolio()
            self.notify("Trader refresh complete", title="Refresh", severity="information")

    def action_rebalance(self) -> None:
        if self.scheduler:
            self._update_status("REBALANCING")
            self._run_rebalance()

    @work(thread=False)
    async def _run_rebalance(self) -> None:
        if self.scheduler:
            await self.scheduler._run_rebalance()
            self._last_rebalance_time = datetime.now(timezone.utc)
            self._update_status("IDLE")
            self._load_portfolio()
            self.notify("Rebalance cycle complete", title="Rebalance", severity="information")

    def action_monitor(self) -> None:
        if self.scheduler:
            self._update_status("MONITORING")
            self._run_monitor()

    @work(thread=False)
    async def _run_monitor(self) -> None:
        if self.scheduler:
            await self.scheduler._run_monitor()
            self._update_status("IDLE")
            self._load_portfolio()
            self.notify("Monitor check complete", title="Monitor", severity="information")

    def action_show_scores(self) -> None:
        self._load_scores()

    def action_show_portfolio(self) -> None:
        self._load_portfolio()

    def action_quit_app(self) -> None:
        if self.scheduler:
            self.scheduler.request_shutdown()
        self.app.exit()


# ---------------------------------------------------------------------------
# Main Textual App
# ---------------------------------------------------------------------------


class SnapApp(App):
    """The Snap copytrading Textual application."""

    TITLE = "SNAP"
    SUB_TITLE = "Hyperliquid Copytrading"
    CSS = APP_CSS
    BINDINGS = [Binding("q", "quit", "Quit", show=True)]

    def __init__(self, db_path: str = "snap.db", **kwargs) -> None:
        super().__init__(**kwargs)
        self.db_path = db_path
        self._onboarding_config = OnboardingConfig()

    def on_mount(self) -> None:
        # Push the first onboarding screen (intro)
        self.push_screen(OnboardingIntro(self._onboarding_config))
