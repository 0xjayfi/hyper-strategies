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
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from snap.config import (
    ACCOUNT_VALUE,
    MAX_POSITION_DURATION_HOURS,
    MAX_TOTAL_POSITIONS,
    MIN_ACCOUNT_VALUE,
    MIN_PNL_30D,
    MONITOR_INTERVAL_SECONDS,
    POLL_LEADERBOARD_HOURS,
    REBALANCE_INTERVAL_HOURS,
)
from snap.database import get_connection
from snap.variants import VARIANT_DESCRIPTIONS, VARIANT_LABELS, VARIANTS, format_variant_details

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
    refresh_interval_hours: int = POLL_LEADERBOARD_HOURS  # trader refresh cadence
    max_hold_hours: int = MAX_POSITION_DURATION_HOURS
    monitor_interval_seconds: int = MONITOR_INTERVAL_SECONDS
    account_value: float = ACCOUNT_VALUE
    max_positions: int = MAX_TOTAL_POSITIONS
    custom_overrides: dict | None = None


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
    min-height: 14;
    padding: 1;
    border: tall $primary;
    margin: 0 0 1 0;
    background: $boost;
}

OnboardingStrategy #strategy-container #btn-row {
    align-horizontal: right;
    height: 3;
}

OnboardingStrategy #strategy-container #custom-form {
    height: auto;
    min-height: 14;
    max-height: 30;
    padding: 1;
    border: tall $primary;
    margin: 0 0 1 0;
    background: $boost;
}

OnboardingStrategy #custom-form .custom-section-head {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}

OnboardingStrategy #custom-form .custom-row {
    height: 3;
    margin: 0 0 0 0;
}

OnboardingStrategy #custom-form .custom-row Label {
    width: 26;
    padding: 1 1 0 0;
    text-align: right;
}

OnboardingStrategy #custom-form .custom-row Input {
    width: 1fr;
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

DashboardScreen #info-center {
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

DashboardScreen #traders-summary, DashboardScreen #rebalance-summary {
    height: 1fr;
    padding: 0 1;
    overflow-y: auto;
}

DashboardScreen .panel-title {
    text-style: bold;
    color: $text;
    padding: 0 1;
    background: $primary-background;
}

DashboardScreen .panel-info {
    height: auto;
    max-height: 8;
    padding: 0 1;
    color: $text-muted;
    background: $surface;
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
_ALL_STRATEGY_KEYS = _VARIANT_KEYS + ["CUSTOM"]

# Custom form field definitions: (input_id, label, default_value, tooltip)
_CUSTOM_FILTER_FIELDS = [
    ("inp-filter-pct", "Filter Percentile", 0.50,
     "Percentile cutoff for the tier-1 filter. Traders below this ROI "
     "percentile are discarded. 0.50 = median (top 50%), 0.65 = stricter (top 35%)."),
    ("inp-wr-min", "Win Rate Min", 0.30,
     "Minimum win rate to pass the quality gate. Traders with a lower fraction "
     "of profitable trades are excluded. Typical range: 0.25-0.45."),
    ("inp-wr-max", "Win Rate Max", 0.95,
     "Maximum win rate allowed. Extremely high win rates (>95%) often indicate "
     "bots or wash trading. Set lower to be more conservative."),
    ("inp-trend-pf", "Trend Min PF", 2.5,
     "Minimum profit factor required for trend-following traders. Profit factor "
     "= gross profit / gross loss. Higher values demand more profitable trend traders."),
    ("inp-trend-wr", "Trend Max WR", 0.40,
     "Maximum win rate to classify a trader as trend-following style. Trend "
     "traders typically win less often but win big. Lower = stricter classification."),
    ("inp-hft-tpd", "HFT Trades/Day", 5.0,
     "Minimum trades per day to classify a trader as high-frequency (HFT). "
     "Traders above this threshold get HFT-specific scoring adjustments."),
    ("inp-hft-ahh", "HFT Avg Hold Hrs", 4.0,
     "Maximum average hold time (hours) to classify as HFT. Combined with "
     "trades/day to identify short-term scalpers and market makers."),
    ("inp-pos-mult", "Position Multiplier", 0.8,
     "Scales the copy position size relative to the trader's size. 0.8 = copy "
     "at 80% of the computed size. Lower = more conservative position sizing."),
]

_CUSTOM_WEIGHT_FIELDS = [
    ("inp-w-roi", "ROI Weight", 0.25,
     "Weight for return on investment in the composite score. Measures raw "
     "profitability across 7d/30d/90d windows, normalized against the cohort."),
    ("inp-w-sharpe", "Sharpe Weight", 0.20,
     "Weight for the pseudo-Sharpe ratio: mean(pnl) / stdev(pnl). Rewards "
     "traders with high risk-adjusted returns and penalizes volatile PnL."),
    ("inp-w-winrate", "Win Rate Weight", 0.15,
     "Weight for win rate in the composite score. Fraction of trades closed "
     "in profit, bounded by the min/max filters above."),
    ("inp-w-consistency", "Consistency Weight", 0.20,
     "Weight for multi-timeframe consistency. Checks that the trader is "
     "profitable on 7d, 30d, and 90d windows simultaneously."),
    ("inp-w-smart", "Smart Money Weight", 0.10,
     "Weight for smart money bonus. Awards extra score to wallets flagged as "
     "institutional, fund, or whale on Nansen's smart money labels."),
    ("inp-w-risk", "Risk Mgmt Weight", 0.10,
     "Weight for risk management score. Penalizes excessive leverage and "
     "rewards isolated margin usage and controlled position sizing."),
]


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
                for key in _ALL_STRATEGY_KEYS:
                    label = f"{key}: {VARIANT_LABELS[key]}"
                    yield RadioButton(label, value=key == self.ob_config.variant_key)
            yield Static(
                format_variant_details(self.ob_config.variant_key),
                id="description-box",
            )
            with VerticalScroll(id="custom-form"):
                yield Static("Filter Parameters", classes="custom-section-head")
                for inp_id, lbl, default, tip in _CUSTOM_FILTER_FIELDS:
                    with Horizontal(classes="custom-row"):
                        lbl_widget = Label(f"{lbl}:")
                        lbl_widget.tooltip = tip
                        yield lbl_widget
                        yield Input(str(default), id=inp_id, type="number")
                yield Rule()
                yield Static("Scoring Weights (must sum to 1.0)", classes="custom-section-head")
                for inp_id, lbl, default, tip in _CUSTOM_WEIGHT_FIELDS:
                    with Horizontal(classes="custom-row"):
                        lbl_widget = Label(f"{lbl}:")
                        lbl_widget.tooltip = tip
                        yield lbl_widget
                        yield Input(str(default), id=inp_id, type="number")
            with Horizontal(id="btn-row"):
                yield Button("Next →", variant="primary", id="btn-next")

    def on_mount(self) -> None:
        # Hide custom form initially (unless CUSTOM is already selected)
        is_custom = self.ob_config.variant_key == "CUSTOM"
        self.query_one("#custom-form").display = is_custom
        self.query_one("#description-box").display = not is_custom

    @on(RadioSet.Changed, "#strategy-radio")
    def _strategy_changed(self, event: RadioSet.Changed) -> None:
        idx = event.radio_set.pressed_index
        if idx is not None and 0 <= idx < len(_ALL_STRATEGY_KEYS):
            key = _ALL_STRATEGY_KEYS[idx]
            self.ob_config.variant_key = key
            if key == "CUSTOM":
                self.query_one("#description-box").display = False
                self.query_one("#custom-form").display = True
            else:
                self.query_one("#custom-form").display = False
                self.query_one("#description-box").display = True
                desc_widget = self.query_one("#description-box", Static)
                desc_widget.update(format_variant_details(key))

    @on(Button.Pressed, "#btn-next")
    def _go_next(self, event: Button.Pressed) -> None:
        if self.ob_config.variant_key == "CUSTOM":
            overrides = self._read_custom_form()
            if overrides is None:
                return  # validation failed, notification shown
            self.ob_config.custom_overrides = overrides
        self.app.push_screen(OnboardingStage(self.ob_config))

    def _read_custom_form(self) -> dict | None:
        """Read and validate custom form inputs. Returns overrides dict or None on error."""
        try:
            vals = {}
            for inp_id, _, _, _ in _CUSTOM_FILTER_FIELDS + _CUSTOM_WEIGHT_FIELDS:
                raw = self.query_one(f"#{inp_id}", Input).value
                vals[inp_id] = float(raw)
        except (ValueError, TypeError):
            self.notify("All fields must be valid numbers.", title="Validation Error", severity="error")
            return None

        # Check weight sum
        weight_sum = sum(vals[inp_id] for inp_id, _, _, _ in _CUSTOM_WEIGHT_FIELDS)
        if abs(weight_sum - 1.0) > 0.01:
            self.notify(
                f"Scoring weights sum to {weight_sum:.3f} — must be 1.0 (±0.01).",
                title="Validation Error",
                severity="error",
            )
            return None

        return {
            "FILTER_PERCENTILE": vals["inp-filter-pct"],
            "WIN_RATE_MIN": vals["inp-wr-min"],
            "WIN_RATE_MAX": vals["inp-wr-max"],
            "TREND_TRADER_MIN_PF": vals["inp-trend-pf"],
            "TREND_TRADER_MAX_WR": vals["inp-trend-wr"],
            "hft_tpd": vals["inp-hft-tpd"],
            "hft_ahh": vals["inp-hft-ahh"],
            "position_mult": vals["inp-pos-mult"],
            "weights": {
                "roi": vals["inp-w-roi"],
                "sharpe": vals["inp-w-sharpe"],
                "win_rate": vals["inp-w-winrate"],
                "consistency": vals["inp-w-consistency"],
                "smart_money": vals["inp-w-smart"],
                "risk_mgmt": vals["inp-w-risk"],
            },
        }


# ---------------------------------------------------------------------------
# Onboarding: Step 2 – Start Stage
# ---------------------------------------------------------------------------

_STAGES = [
    ("collect", "Collect Data Only", "Fetch leaderboard and trade data from Nansen API without scoring or trading. Use this to pre-cache data for strategy experiments."),
    ("daily", "Fresh Start (Daily Flow)", "Run the full pipeline from the beginning: fetch leaderboard, score traders, then rebalance and monitor."),
    ("score_cache", "Score & Rebalance (No API)", "Score traders from cached data (no API calls), then rebalance and monitor. Use when data is already collected."),
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
                yield Label("Trader Refresh Frequency:")
                yield Select(
                    [
                        ("Every 1 day (24h)", 24),
                        ("Every 3 days (72h)", 72),
                        ("Weekly (168h)", 168),
                    ],
                    value=self.ob_config.refresh_interval_hours,
                    id="sel-refresh-freq",
                    allow_blank=False,
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
            sel_val = self.query_one("#sel-refresh-freq", Select).value
            if sel_val is not None and sel_val != Select.BLANK:
                self.ob_config.refresh_interval_hours = int(sel_val)
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
    "REFRESHING_TRADERS": "yellow",
    "REBALANCING": "cyan",
    "INGESTING_TRADES": "blue",
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
        Binding("c", "score_cache", "Score from Cache"),
        Binding("b", "rebalance", "Rebalance"),
        Binding("m", "monitor", "Monitor"),
        Binding("s", "show_scores", "Refresh Scores"),
        Binding("p", "show_portfolio", "Refresh Portfolio"),
        Binding("v", "switch_variant", "Switch Variant"),
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
        self._refresh_progress: tuple[int, int] | None = None  # (current, total)
        self._fresh_start: bool = False
        self._pnl_history: dict[str, list[float]] = {}
        self._trader_count: int = 0
        self._data_age_str: str = "no data"
        self._last_data_check: datetime | None = None
        self._session_start: datetime = datetime.now(timezone.utc)
        self._row_tokens: list[str] = []
        self._position_tooltips: dict[str, str] = {}
        self._row_addresses: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Status bar
        variant_label = VARIANT_LABELS.get(self.ob_config.variant_key, "?")
        status_text = (
            f"[black on yellow] PAPER [/]  │  Strategy: {self.ob_config.variant_key} ({variant_label})  │  "
            f"Acct: ${self.ob_config.account_value:,.0f}  │  "
            f"State: [dim]IDLE[/]  │  "
            f"Data: loading...  │  "
            f"Rebal: {self.ob_config.rebalance_interval_hours}h  │  "
            f"Hold: {self.ob_config.max_hold_hours}h"
        )
        yield Static(status_text, id="status-bar")

        # Row 2: Portfolio (left) | Scores (right)
        with Vertical(id="portfolio-panel"):
            yield Static(" Portfolio", classes="panel-title")
            yield DataTable(id="portfolio-table")
            yield Static("", id="portfolio-info", classes="panel-info")

        with Vertical(id="scores-panel"):
            yield Static(" Eligible Traders", classes="panel-title")
            yield DataTable(id="scores-table")
            yield Static("", id="scores-info", classes="panel-info")

        # Row 3: Info center (full width, bottom strip)
        with TabbedContent(id="info-center"):
            with TabPane("Logs", id="tab-logs"):
                yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)
            with TabPane("Traders", id="tab-traders"):
                yield Static("Loading...", id="traders-summary")
            with TabPane("Rebalance", id="tab-rebalance"):
                yield Static("Loading...", id="rebalance-summary")

        yield Footer()

    def on_mount(self) -> None:
        # Set up portfolio table columns
        ptable = self.query_one("#portfolio-table", DataTable)
        ptable.add_columns("Token", "Side", "Entry", "Live", "Size USD", "PnL", "PnL %", "Lev", "Margin", "Trend")
        ptable.cursor_type = "row"

        # Watch hover coordinate for info bar updates
        self.watch(ptable, "hover_coordinate", self._on_portfolio_hover)

        # Set up scores table columns
        stable = self.query_one("#scores-table", DataTable)
        stable.add_columns("#", "Address", "Score", "Style", "ROI 30d", "WR", "PF", "Trades")
        stable.cursor_type = "row"

        # Watch hover coordinate for info bar updates
        self.watch(stable, "hover_coordinate", self._on_scores_hover)

        # Install log handler
        log_view = self.query_one("#log-view", RichLog)
        self._log_handler = TextualLogHandler(log_view)
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(self._log_handler)
        root_logger.setLevel(logging.INFO)

        # Run DB migration before loading data
        from snap.database import init_data_db, init_db, init_strategy_db

        try:
            if self.app.data_db_path != self.app.db_path:
                conn = init_data_db(self.app.data_db_path)
                conn.close()
                conn = init_strategy_db(self.app.db_path)
                conn.close()
            else:
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

        if self.ob_config.start_stage == "daily":
            # Fresh start: show "refreshing..." until the pipeline populates data.
            # Don't load stale portfolio/scores from previous run.
            self._data_age_str = "refreshing..."
            self._fresh_start = True
        else:
            self._refresh_data_freshness()
            self._load_portfolio()
            self._load_scores()
            self._fresh_start = False

        self._load_traders_summary()
        self._load_rebalance_summary()

        # Periodic countdown refresh
        self.set_interval(30, self._tick_status)
        self.set_interval(60, self._periodic_refresh)

        self.notify("Dashboard ready", title="SNAP", severity="information")

        # Start the scheduler in background
        self._start_scheduler()

    def on_unmount(self) -> None:
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)

    # -- Data loading -------------------------------------------------------

    def _load_portfolio(self) -> None:
        """Load portfolio data from the database into the DataTable."""
        if self._fresh_start:
            return  # Don't load stale data during fresh start
        ptable = self.query_one("#portfolio-table", DataTable)
        ptable.clear()
        self._row_tokens = []

        try:
            db_path = self.app.db_path
            conn = get_connection(db_path)
            try:
                rows = conn.execute(
                    """SELECT token_symbol, side, position_usd, unrealized_pnl,
                              leverage, entry_price, current_price,
                              opened_at, max_close_at, stop_loss_price,
                              trailing_stop_price, trailing_high
                       FROM our_positions ORDER BY position_usd DESC"""
                ).fetchall()
                self._build_position_tooltips(conn, rows)
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
                self._row_tokens.append(token)

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

    def _build_position_tooltips(self, conn, position_rows) -> None:
        """Build tooltip strings for each position from order history."""
        self._position_tooltips = {}
        for pos in position_rows:
            token = pos["token_symbol"]
            opened = pos["opened_at"] or "N/A"
            max_close = pos["max_close_at"] or "N/A"
            stop_loss = pos["stop_loss_price"]
            trailing = pos["trailing_stop_price"]
            trailing_hi = pos["trailing_high"]

            lines = [
                f"--- {token} ---",
                f"  Opened:        {opened[:16] if opened != 'N/A' else opened}",
                f"  Time Stop:     {max_close[:16] if max_close != 'N/A' else max_close}",
            ]
            if stop_loss:
                lines.append(f"  Stop Loss:     {_fmt_price(stop_loss)}")
            if trailing:
                lines.append(f"  Trailing Stop: {_fmt_price(trailing)}")
            if trailing_hi:
                lines.append(f"  Trailing High: {_fmt_price(trailing_hi)}")

            # Fetch recent 5 orders for this token
            orders = conn.execute(
                """SELECT side, order_type, status, intended_usd,
                          filled_avg_price, slippage_bps,
                          created_at, filled_at
                   FROM orders
                   WHERE token_symbol = ?
                   ORDER BY created_at DESC
                   LIMIT 5""",
                (token,),
            ).fetchall()

            if orders:
                lines.append("")
                lines.append("Recent Orders:")
                for o in orders:
                    ts = (o["filled_at"] or o["created_at"] or "?")[:16]
                    status = o["status"] or "?"
                    usd = o["intended_usd"] or 0
                    slip = o["slippage_bps"]
                    slip_str = f"  slip {slip:+.1f}bp" if slip else ""
                    lines.append(
                        f"  {ts}  {o['side']:5s} {o['order_type']:6s}  "
                        f"${usd:,.0f}  [{status}]{slip_str}"
                    )
            else:
                lines.append("")
                lines.append("No order history yet.")

            self._position_tooltips[token] = "\n".join(lines)

    def _on_portfolio_hover(self, coordinate) -> None:
        """Update portfolio info bar based on hovered row."""
        info = self.query_one("#portfolio-info", Static)
        row_idx = coordinate.row
        if 0 <= row_idx < len(self._row_tokens):
            token = self._row_tokens[row_idx]
            text = self._position_tooltips.get(token, "")
            info.update(text)
        else:
            info.update("")

    def _on_scores_hover(self, coordinate) -> None:
        """Update scores info bar to show full address on hover."""
        info = self.query_one("#scores-info", Static)
        row_idx = coordinate.row
        if 0 <= row_idx < len(self._row_addresses):
            info.update(self._row_addresses[row_idx])
        else:
            info.update("")

    def _load_scores(self) -> None:
        """Load trader scores from the database into the DataTable."""
        stable = self.query_one("#scores-table", DataTable)
        stable.clear()
        self._row_addresses = []

        try:
            db_path = self.app.db_path
            data_db_path = self.app.data_db_path
            conn = get_connection(db_path)
            try:
                if data_db_path != db_path:
                    # Two-DB mode: query separately and join in Python
                    score_rows = conn.execute(
                        """SELECT address, composite_score, style,
                                  roi_30d, win_rate, profit_factor, trade_count
                           FROM trader_scores
                           WHERE is_eligible = 1 AND id IN (
                               SELECT MAX(id) FROM trader_scores GROUP BY address
                           )
                           ORDER BY composite_score DESC
                           LIMIT 15"""
                    ).fetchall()
                    data_conn = get_connection(data_db_path)
                    try:
                        labels = {}
                        for r in data_conn.execute(
                            "SELECT address, label FROM traders"
                        ).fetchall():
                            labels[r["address"]] = r["label"]
                    finally:
                        data_conn.close()
                    rows = [
                        {
                            "address": r["address"],
                            "label": labels.get(r["address"], ""),
                            "composite_score": r["composite_score"],
                            "style": r["style"],
                            "roi_30d": r["roi_30d"],
                            "win_rate": r["win_rate"],
                            "profit_factor": r["profit_factor"],
                            "trade_count": r["trade_count"],
                        }
                        for r in score_rows
                    ]
                else:
                    rows = conn.execute(
                        """SELECT ts.address, t.label, ts.composite_score, ts.style,
                                  ts.roi_30d, ts.win_rate, ts.profit_factor, ts.trade_count
                           FROM trader_scores ts
                           JOIN traders t ON ts.address = t.address
                           WHERE ts.is_eligible = 1 AND ts.id IN (
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

                stable.add_row(
                    rank_cell,
                    display,
                    score_cell,
                    r["style"] or "—",
                    Text(f"{roi:+.1f}%", style=roi_style),
                    f"{wr:.0%}",
                    f"{pf:.1f}",
                    str(trades),
                )
                self._row_addresses.append(addr)

            if not rows:
                stable.add_row(
                    Text("No eligible traders yet — press 'r' to refresh", style="dim italic"),
                    "", "", "", "", "", "", "",
                )
        except Exception as e:
            logger.warning("Scores load failed: %s", e)

    def _refresh_data_freshness(self) -> None:
        """Query DB for trader count and last update time."""
        try:
            conn = get_connection(self.app.data_db_path)
            try:
                # Count only traders from the most recent leaderboard pull
                row = conn.execute(
                    """SELECT COUNT(*) as cnt, MAX(updated_at) as last_update
                       FROM traders
                       WHERE updated_at = (SELECT MAX(updated_at) FROM traders)"""
                ).fetchone()
            finally:
                conn.close()

            self._trader_count = row["cnt"] if row["cnt"] else 0
            last_update = row["last_update"]
            if last_update:
                try:
                    dt = datetime.strptime(last_update, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    age = datetime.now(timezone.utc) - dt
                    hours = int(age.total_seconds() / 3600)
                    if hours < 1:
                        mins = int(age.total_seconds() / 60)
                        self._data_age_str = f"{self._trader_count} traders ({mins}m ago)"
                    elif hours < 24:
                        self._data_age_str = f"{self._trader_count} traders ({hours}h ago)"
                    else:
                        days = hours // 24
                        self._data_age_str = f"{self._trader_count} traders ({days}d ago)"
                except (ValueError, TypeError):
                    self._data_age_str = f"{self._trader_count} traders"
            else:
                self._data_age_str = "no data"
            self._last_data_check = datetime.now(timezone.utc)
        except Exception:
            pass  # Don't crash the status bar over a DB error

    def _periodic_refresh(self) -> None:
        """Periodic callback combining portfolio + rebalance summary refresh."""
        self._load_portfolio()
        self._load_rebalance_summary()

    def _load_traders_summary(self) -> None:
        """Load trader scoring pipeline summary into the Traders tab."""
        widget = self.query_one("#traders-summary", Static)
        try:
            conn = get_connection(self.app.db_path)
            try:
                # Get latest scores per address
                total = conn.execute(
                    "SELECT COUNT(DISTINCT address) FROM trader_scores"
                ).fetchone()[0] or 0

                tier1 = conn.execute(
                    """SELECT COUNT(DISTINCT address) FROM trader_scores
                       WHERE passes_tier1 = 1 AND id IN (
                           SELECT MAX(id) FROM trader_scores GROUP BY address
                       )"""
                ).fetchone()[0] or 0

                consistency = conn.execute(
                    """SELECT COUNT(DISTINCT address) FROM trader_scores
                       WHERE passes_consistency = 1 AND id IN (
                           SELECT MAX(id) FROM trader_scores GROUP BY address
                       )"""
                ).fetchone()[0] or 0

                quality = conn.execute(
                    """SELECT COUNT(DISTINCT address) FROM trader_scores
                       WHERE passes_quality = 1 AND id IN (
                           SELECT MAX(id) FROM trader_scores GROUP BY address
                       )"""
                ).fetchone()[0] or 0

                eligible = conn.execute(
                    """SELECT COUNT(DISTINCT address) FROM trader_scores
                       WHERE is_eligible = 1 AND id IN (
                           SELECT MAX(id) FROM trader_scores GROUP BY address
                       )"""
                ).fetchone()[0] or 0

                # Style distribution of eligible
                style_rows = conn.execute(
                    """SELECT style, COUNT(*) as cnt FROM trader_scores
                       WHERE is_eligible = 1 AND id IN (
                           SELECT MAX(id) FROM trader_scores GROUP BY address
                       )
                       GROUP BY style ORDER BY cnt DESC"""
                ).fetchall()

                # Top 5 eligible by score
                top5 = conn.execute(
                    """SELECT address, composite_score, style FROM trader_scores
                       WHERE is_eligible = 1 AND id IN (
                           SELECT MAX(id) FROM trader_scores GROUP BY address
                       )
                       ORDER BY composite_score DESC LIMIT 5"""
                ).fetchall()

                # Last scored timestamp
                last_scored = conn.execute(
                    "SELECT MAX(scored_at) FROM trader_scores"
                ).fetchone()[0] or "never"

                # Fail reason distribution (top 5)
                fail_rows = conn.execute(
                    """SELECT fail_reason, COUNT(*) as cnt FROM trader_scores
                       WHERE is_eligible = 0 AND fail_reason IS NOT NULL
                       AND id IN (SELECT MAX(id) FROM trader_scores GROUP BY address)
                       GROUP BY fail_reason ORDER BY cnt DESC LIMIT 5"""
                ).fetchall()
            finally:
                conn.close()

            # Query data DB for trade-fetched count
            # Use latest collection batch (all traders share the same updated_at)
            # and fresh trade cache (within TTL) to avoid showing stale cumulative totals.
            try:
                data_conn = get_connection(self.app.data_db_path)
                try:
                    # Count traders from the most recent leaderboard pull only
                    trader_count = data_conn.execute(
                        """SELECT COUNT(*) FROM traders
                           WHERE updated_at = (SELECT MAX(updated_at) FROM traders)"""
                    ).fetchone()[0] or 0
                    # Count traders with fresh trade data (within cache TTL)
                    from snap.config import TRADE_CACHE_TTL_HOURS
                    cache_cutoff = (
                        datetime.now(timezone.utc) - timedelta(hours=TRADE_CACHE_TTL_HOURS)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                    fetched = data_conn.execute(
                        "SELECT COUNT(DISTINCT address) FROM trade_history WHERE fetched_at >= ?",
                        (cache_cutoff,),
                    ).fetchone()[0] or 0
                finally:
                    data_conn.close()
            except Exception:
                fetched = 0
                trader_count = 0

            min_acct_str = f"${MIN_ACCOUNT_VALUE:,.0f}"
            min_pnl_str = f"${MIN_PNL_30D:,.0f}"

            lines = []
            lines.append("[bold]Scoring Pipeline Funnel[/bold]")
            lines.append(f"  Collected:         {trader_count:>5}          [dim]Union of 7d/30d/90d leaderboards — API filter: acct >= {min_acct_str}[/dim]")
            lines.append(f"  Total scored:      {total:>5}          [dim]Scored from cache (latest run)[/dim]")
            lines.append(f"  Trades fetched:    {fetched:>5}          [dim]Acct >= {min_acct_str} AND 30d PnL >= {min_pnl_str} — trade history pulled from API[/dim]")
            t1_pct = f"({tier1*100//total}%)" if total > 0 else ""
            lines.append(f"  Tier-1 pass:       {tier1:>5} {t1_pct:<5}    [dim]30d ROI + acct value above dynamic percentile cutoff[/dim]")
            con_pct = f"({consistency*100//total}%)" if total > 0 else ""
            lines.append(f"  Consistency pass:  {consistency:>5} {con_pct:<5}    [dim]Positive ROI across all three windows (7d, 30d, 90d)[/dim]")
            q_pct = f"({quality*100//total}%)" if total > 0 else ""
            lines.append(f"  Quality pass:      {quality:>5} {q_pct:<5}    [dim]Min trades, win rate 30–95%, profit factor above cohort cutoff[/dim]")
            e_pct = f"({eligible*100//total}%)" if total > 0 else ""
            lines.append(f"  [green]Eligible:          {eligible:>5} {e_pct:<5}    All gates passed, not HFT — ranked by composite score[/green]")
            lines.append(f"  Last scored:       {last_scored[:16] if last_scored != 'never' else last_scored}")

            if style_rows:
                styles_str = ", ".join(f"{r['style'] or '?'}: {r['cnt']}" for r in style_rows)
                lines.append(f"\n[bold]Style Distribution:[/bold] {styles_str}")

            if top5:
                lines.append("\n[bold]Top 5 Eligible:[/bold]")
                for i, r in enumerate(top5, 1):
                    addr = r["address"]
                    short = f"{addr[:6]}..{addr[-4:]}" if len(addr) > 10 else addr
                    lines.append(f"  {i}. {short}  score={r['composite_score']:.3f}  [{r['style'] or '?'}]")

            if fail_rows:
                lines.append("\n[bold]Top Fail Reasons:[/bold]")
                for r in fail_rows:
                    lines.append(f"  {r['fail_reason']}: {r['cnt']}")

            widget.update("\n".join(lines))
        except Exception as e:
            widget.update(f"[red]Error loading trader summary: {e}[/red]")

    def _load_rebalance_summary(self) -> None:
        """Load latest rebalance details into the Rebalance tab."""
        widget = self.query_one("#rebalance-summary", Static)
        try:
            conn = get_connection(self.app.db_path)
            try:
                # Latest rebalance_id
                rebal_row = conn.execute(
                    """SELECT rebalance_id, MAX(computed_at) as computed_at
                       FROM target_allocations
                       GROUP BY rebalance_id
                       ORDER BY computed_at DESC LIMIT 1"""
                ).fetchone()

                # Current positions
                positions = conn.execute(
                    """SELECT COUNT(*) as cnt,
                              COALESCE(SUM(position_usd), 0) as total_exposure,
                              COALESCE(SUM(unrealized_pnl), 0) as total_pnl,
                              SUM(CASE WHEN side='Long' THEN position_usd ELSE 0 END) as long_usd,
                              SUM(CASE WHEN side='Short' THEN position_usd ELSE 0 END) as short_usd
                       FROM our_positions"""
                ).fetchone()

                # Closed positions from pnl_ledger
                closed = conn.execute(
                    """SELECT COUNT(*) as cnt,
                              COALESCE(SUM(realized_pnl), 0) as total_pnl
                       FROM pnl_ledger"""
                ).fetchone()

                exit_reasons = conn.execute(
                    """SELECT exit_reason, COUNT(*) as cnt
                       FROM pnl_ledger
                       WHERE exit_reason IS NOT NULL
                       GROUP BY exit_reason ORDER BY cnt DESC"""
                ).fetchall()

                # If we have a rebalance, get its details
                allocs = []
                orders = []
                if rebal_row and rebal_row["rebalance_id"]:
                    rid = rebal_row["rebalance_id"]
                    allocs = conn.execute(
                        """SELECT token_symbol, side, target_usd
                           FROM target_allocations
                           WHERE rebalance_id = ?
                           ORDER BY target_usd DESC""",
                        (rid,),
                    ).fetchall()
                    orders = conn.execute(
                        """SELECT token_symbol, side, order_type, intended_usd,
                                  filled_usd, slippage_bps, status
                           FROM orders
                           WHERE rebalance_id = ?
                           ORDER BY created_at DESC""",
                        (rid,),
                    ).fetchall()
            finally:
                conn.close()

            lines = []

            # Current positions
            pos_cnt = positions["cnt"] if positions else 0
            total_exp = positions["total_exposure"] if positions else 0
            total_pnl = positions["total_pnl"] if positions else 0
            long_usd = positions["long_usd"] or 0 if positions else 0
            short_usd = positions["short_usd"] or 0 if positions else 0
            pnl_style = "green" if total_pnl >= 0 else "red"

            lines.append("[bold]Current Positions[/bold]")
            lines.append(
                f"  Open: {pos_cnt}  │  Exposure: ${total_exp:,.0f}  │  "
                f"PnL: [{pnl_style}]{total_pnl:+,.0f}[/{pnl_style}]  │  "
                f"Long: ${long_usd:,.0f}  Short: ${short_usd:,.0f}"
            )

            # Closed positions
            closed_cnt = closed["cnt"] if closed else 0
            closed_pnl = closed["total_pnl"] if closed else 0
            cpnl_style = "green" if closed_pnl >= 0 else "red"
            exits_str = ", ".join(f"{r['exit_reason']}: {r['cnt']}" for r in exit_reasons) if exit_reasons else "none"
            lines.append(
                f"  Closed: {closed_cnt}  │  Realized PnL: [{cpnl_style}]{closed_pnl:+,.0f}[/{cpnl_style}]  │  Exits: {exits_str}"
            )

            # Latest rebalance
            if rebal_row and rebal_row["rebalance_id"]:
                rid = rebal_row["rebalance_id"]
                ts = rebal_row["computed_at"] or "?"
                lines.append(f"\n[bold]Latest Rebalance[/bold]  {rid[:8]}..  at {ts[:16]}")

                if allocs:
                    alloc_parts = [f"{a['token_symbol']} {a['side']} ${a['target_usd']:,.0f}" for a in allocs[:6]]
                    lines.append(f"  Targets: {' │ '.join(alloc_parts)}")

                if orders:
                    lines.append(f"  Orders ({len(orders)}):")
                    for o in orders[:5]:
                        slip = f"  slip {o['slippage_bps']:+.1f}bp" if o["slippage_bps"] else ""
                        filled = f"${o['filled_usd']:,.0f}" if o["filled_usd"] else "—"
                        lines.append(
                            f"    {o['token_symbol']:8s} {o['side']:5s} {o['order_type']:6s}  "
                            f"${o['intended_usd'] or 0:,.0f} → {filled}  [{o['status']}]{slip}"
                        )
            else:
                lines.append("\n[dim]No rebalance history yet — press 'b' to rebalance[/dim]")

            widget.update("\n".join(lines))
        except Exception as e:
            widget.update(f"[red]Error loading rebalance summary: {e}[/red]")

    def _update_status(self, state: str = "IDLE") -> None:
        """Update the status bar text with live countdowns."""
        self._current_state = state
        variant_label = VARIANT_LABELS.get(self.ob_config.variant_key, "?")
        state_color = _STATE_COLORS.get(state, "dim")

        now = datetime.now(timezone.utc)

        # Refresh data freshness every 5 minutes
        if self._last_data_check is None or (now - self._last_data_check).total_seconds() > 300:
            self._refresh_data_freshness()

        # Session uptime
        elapsed = now - self._session_start
        elapsed_h = int(elapsed.total_seconds() // 3600)
        elapsed_m = int((elapsed.total_seconds() % 3600) // 60)
        session_str = f"{elapsed_h}h {elapsed_m:02d}m"

        # Compute next rebalance countdown
        if self._last_rebalance_time is not None:
            next_rebal = self._last_rebalance_time + timedelta(hours=self.ob_config.rebalance_interval_hours)
            remaining = next_rebal - now
            if remaining.total_seconds() <= 0:
                rebal_str = "now"
            else:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                eta = now + remaining
                eta_str = eta.strftime("%H:%M UTC")
                rebal_str = f"{hours}h {minutes:02d}m (~{eta_str})"
        else:
            rebal_str = "pending"

        # Compute next refresh countdown
        if self._last_refresh_time is not None:
            next_refresh = self._last_refresh_time + timedelta(hours=self.ob_config.refresh_interval_hours)
            remaining = next_refresh - now
            if remaining.total_seconds() <= 0:
                refresh_str = "now"
            else:
                hours, rem = divmod(int(remaining.total_seconds()), 3600)
                minutes = rem // 60
                eta = now + remaining
                eta_str = eta.strftime("%H:%M UTC")
                refresh_str = f"{hours}h {minutes:02d}m (~{eta_str})"
        else:
            refresh_str = "pending"

        # Show progress percentage alongside REFRESHING state
        if state in ("REFRESHING_TRADERS", "REFRESHING") and self._refresh_progress:
            cur, tot = self._refresh_progress
            pct = int(100 * cur / tot) if tot > 0 else 0
            state_display = f"{state} ({pct}%)"
        else:
            state_display = state

        status_text = (
            f"[black on yellow] PAPER [/]  │  Strategy: {self.ob_config.variant_key} ({variant_label})  │  "
            f"Acct: ${self.ob_config.account_value:,.0f}  │  "
            f"State: [{state_color}]{state_display}[/]  │  "
            f"Session: {session_str}  │  "
            f"Data: {self._data_age_str}  │  "
            f"Next rebal: {rebal_str}  │  "
            f"Next refresh: {refresh_str}"
        )
        self.query_one("#status-bar", Static).update(status_text)

    def _on_refresh_progress(self, current: int, total: int) -> None:
        """Callback from collector to update refresh progress."""
        self._refresh_progress = (current, total)

    def _tick_status(self) -> None:
        """Periodic callback to refresh the status bar countdown."""
        if self.scheduler and hasattr(self.scheduler, "state"):
            new_state = self.scheduler.state.value
            if new_state != self._current_state:
                old = self._current_state
                self._current_state = new_state
                # Clear fresh_start whenever we leave REFRESHING_TRADERS,
                # regardless of what state we transition to (the normal flow
                # goes REFRESHING_TRADERS → REBALANCING, not directly to IDLE).
                if old in ("REFRESHING_TRADERS", "REFRESHING"):
                    self._refresh_progress = None
                    self._fresh_start = False
                    self._last_refresh_time = datetime.now(timezone.utc)
                    self._last_data_check = None
                    self._refresh_data_freshness()
                    self._load_scores()
                    self._load_traders_summary()
                if new_state == "REBALANCING":
                    logger.info("Rebalance cycle started (auto-scheduled)")
                    self.notify("Rebalancing in progress...", title="Rebalance", severity="information")
                elif new_state == "IDLE" and old == "REBALANCING":
                    logger.info("Rebalance cycle finished")
                    self._last_rebalance_time = datetime.now(timezone.utc)
                    self._fresh_start = False  # safety net
                    self._load_portfolio()
                    self._load_scores()
                    self._load_rebalance_summary()
        self._update_status(self._current_state)

    # -- Scheduler integration -----------------------------------------------

    @work(thread=False)
    async def _start_scheduler(self) -> None:
        """Initialize and start the system scheduler based on onboarding config."""
        from snap.config import NANSEN_API_KEY
        from snap.database import init_data_db, init_db, init_strategy_db
        from snap.execution import PaperTradeClient
        from snap.nansen_client import NansenClient
        from snap.scheduler import SystemScheduler, set_system_state

        db_path = self.app.db_path
        data_db_path = self.app.data_db_path

        # Initialize DBs
        if data_db_path != db_path:
            conn = init_data_db(data_db_path)
            conn.close()
            conn = init_strategy_db(db_path)
            conn.close()
        else:
            conn = init_db(db_path)
            conn.close()

        # Set account value (in strategy DB)
        set_system_state(db_path, "account_value", str(self.ob_config.account_value))

        if not NANSEN_API_KEY:
            logger.error("NANSEN_API_KEY not set. Export it or add to .env file.")
            self.notify("NANSEN_API_KEY not set!", title="Config Error", severity="error")
            return

        client = PaperTradeClient(mark_prices={}, live_prices=True)
        nansen_client = NansenClient(api_key=NANSEN_API_KEY)

        if self.ob_config.start_stage == "score_cache":
            # Score from cached data, then start scheduler from rebalance
            logger.info("Scoring from cached data (no API calls)")
            self._update_status("REFRESHING")
            try:
                from snap.scoring import score_from_cache

                if self.ob_config.variant_key == "CUSTOM":
                    overrides = self.ob_config.custom_overrides
                else:
                    overrides = VARIANTS.get(self.ob_config.variant_key)
                eligible = score_from_cache(
                    data_db_path,
                    overrides=overrides,
                    strategy_db_path=db_path,
                )
                logger.info("Score from cache complete: %d eligible traders", len(eligible))
                self.notify(
                    f"Scored from cache: {len(eligible)} eligible — starting rebalance",
                    title="Score Complete",
                    severity="information",
                )
                self._load_scores()
                self._load_traders_summary()
            except Exception as e:
                logger.exception("Score from cache failed")
                self.notify(f"Score from cache failed: {e}", title="Error", severity="error")
                await nansen_client.close()
                self._update_status("IDLE")
                return
            # Fall through to start scheduler from rebalance stage
            self.ob_config.start_stage = "rebalance"
            self._update_status("IDLE")

        if self.ob_config.start_stage == "collect":
            # Collection-only mode: fetch data, don't start scheduler
            logger.info("Running data collection only (no trading)")
            try:
                from snap.collector import collect_trader_data
                summary = await collect_trader_data(
                    nansen_client, data_db_path,
                    on_progress=self._on_refresh_progress,
                )
                logger.info("Collection complete: %s", summary)
                self.notify(
                    f"Traders: {summary.traders_fetched} | "
                    f"Trades: {summary.trades_fetched} new, {summary.trades_cached} cached | "
                    f"Errors: {summary.errors} | "
                    f"Duration: {summary.duration_seconds:.0f}s",
                    title="Collection Complete",
                    severity="information",
                )
            except Exception as e:
                logger.exception("Collection failed")
                self.notify(f"Collection failed: {e}", title="Error", severity="error")
            finally:
                await nansen_client.close()

            # Refresh the display with collected data
            self._load_scores()
            self._load_portfolio()
            self._load_traders_summary()
            self._load_rebalance_summary()
            return  # Don't start the scheduler loop

        if self.ob_config.variant_key == "CUSTOM":
            variant_overrides = self.ob_config.custom_overrides
        else:
            variant_overrides = VARIANTS.get(self.ob_config.variant_key)

        scheduler = SystemScheduler(
            client=client,
            nansen_client=nansen_client,
            db_path=data_db_path,
            strategy_db_path=db_path,
            scoring_overrides=variant_overrides,
        )
        scheduler.on_refresh_progress = self._on_refresh_progress
        scheduler.refresh_interval_hours = self.ob_config.refresh_interval_hours
        scheduler.recover_state()
        self.scheduler = scheduler

        # Apply onboarding config to control which stages run
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if self.ob_config.start_stage == "daily":
            # Fresh start: clear recovered timestamps so the full pipeline
            # runs from scratch (refresh → rebalance → monitor).
            # Cached trade data is still reused by the collector.
            scheduler._last_trader_refresh = None
            scheduler._last_rebalance = None
            logger.info("Fresh start: will run full pipeline (refresh → rebalance → monitor)")
        elif self.ob_config.start_stage == "rebalance":
            # Pretend trader refresh just happened so scheduler skips it
            scheduler._last_trader_refresh = now
            self._last_refresh_time = now  # sync TUI countdown display
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
            self._last_refresh_time = now  # sync TUI countdown display
            self._last_rebalance_time = now
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
            self._refresh_progress = None
            self._fresh_start = False
            self._last_refresh_time = datetime.now(timezone.utc)
            self._last_data_check = None  # Force data freshness update
            self._refresh_data_freshness()
            self._update_status("IDLE")
            self._load_scores()
            self._load_portfolio()
            self._load_traders_summary()
            self.notify("Trader refresh complete", title="Refresh", severity="information")

    def action_score_cache(self) -> None:
        """Score traders from cached data — no API calls."""
        self._update_status("REFRESHING")
        self._run_score_cache()

    @work(thread=False)
    async def _run_score_cache(self) -> None:
        from snap.scoring import score_from_cache
        from snap.variants import VARIANTS

        try:
            if self.ob_config.variant_key == "CUSTOM":
                overrides = self.ob_config.custom_overrides
            else:
                overrides = VARIANTS.get(self.ob_config.variant_key)
            eligible = score_from_cache(
                self.app.data_db_path,
                overrides=overrides,
                strategy_db_path=self.app.db_path,
            )
            self._update_status("IDLE")
            self._load_scores()
            self._load_portfolio()
            self._load_traders_summary()
            self.notify(
                f"Scored from cache: {len(eligible)} eligible",
                title="Score from Cache",
                severity="information",
            )
            logger.info("Score from cache complete: %d eligible traders", len(eligible))
        except Exception as e:
            logger.exception("Score from cache failed")
            self._update_status("IDLE")
            self.notify(f"Score from cache failed: {e}", title="Error", severity="error")

    def action_rebalance(self) -> None:
        if self.scheduler:
            self._update_status("REBALANCING")
            self._run_rebalance()

    @work(thread=False)
    async def _run_rebalance(self) -> None:
        if self.scheduler:
            await self.scheduler._run_rebalance()
            self._last_rebalance_time = datetime.now(timezone.utc)
            self._last_data_check = None  # Force data freshness update
            self._fresh_start = False
            self._update_status("IDLE")
            self._load_portfolio()
            self._load_rebalance_summary()
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
        self._fresh_start = False  # user explicitly requested portfolio
        self._load_portfolio()

    def action_switch_variant(self) -> None:
        """Cycle to the next scoring variant and re-score from cache.

        Skips CUSTOM in cycling since there's no preset to switch to.
        """
        cur = self.ob_config.variant_key
        if cur in _VARIANT_KEYS:
            idx = (_VARIANT_KEYS.index(cur) + 1) % len(_VARIANT_KEYS)
        else:
            # CUSTOM or unknown — start from V1
            idx = 0
        new_key = _VARIANT_KEYS[idx]

        self.ob_config.variant_key = new_key
        new_overrides = VARIANTS[new_key]

        # Update scheduler if running
        if self.scheduler:
            self.scheduler.set_scoring_overrides(new_overrides)

        # Re-score from cache (fast, no API calls)
        self._rescore_variant(new_key, new_overrides)

    @work(thread=False)
    async def _rescore_variant(self, variant_key: str, overrides: dict) -> None:
        """Re-score from cached data with new variant overrides."""
        from snap.scoring import score_from_cache

        try:
            eligible = score_from_cache(
                self.app.data_db_path,
                overrides=overrides,
                strategy_db_path=self.app.db_path,
            )
            label = VARIANT_LABELS.get(variant_key, "?")
            self._update_status(self._current_state)
            self._load_scores()
            self._load_traders_summary()
            self.notify(
                f"Switched to {variant_key} ({label}) — {len(eligible)} eligible",
                title="Variant Changed",
                severity="information",
            )
            logger.info("Variant switched to %s (%s): %d eligible", variant_key, label, len(eligible))
        except Exception as e:
            logger.exception("Failed to re-score with variant %s", variant_key)
            self.notify(f"Re-score failed: {e}", title="Error", severity="error")

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

    def __init__(
        self, db_path: str = "snap.db", *, data_db_path: str | None = None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.db_path = db_path  # strategy DB
        self.data_db_path = data_db_path or db_path  # data DB
        self._onboarding_config = OnboardingConfig()

    def on_mount(self) -> None:
        # Push the first onboarding screen (intro)
        self.push_screen(OnboardingIntro(self._onboarding_config))
