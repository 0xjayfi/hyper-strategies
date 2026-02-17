"""Tests for the TUI display module (Phase 4).

Covers:
1. render_portfolio_table — columns, row data, totals, PnL coloring, empty table
2. render_scores_table — columns, row data, address truncation, eligibility display
3. render_status_bar — panel content, timestamps, missing timestamps
4. print_portfolio / print_scores — smoke tests
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rich.panel import Panel
from rich.table import Table

from snap.database import init_db
from snap.tui import render_portfolio_table, render_scores_table, render_status_bar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_positions(db_path: str) -> None:
    """Insert sample positions into our_positions for testing."""
    conn = init_db(db_path)
    conn.execute(
        """INSERT INTO our_positions
           (token_symbol, side, size, entry_price, current_price,
            position_usd, unrealized_pnl, leverage, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("BTC", "Long", 0.05, 40000.0, 41000.0, 2050.0, 50.0, 5.0,
         "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        """INSERT INTO our_positions
           (token_symbol, side, size, entry_price, current_price,
            position_usd, unrealized_pnl, leverage, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ETH", "Short", 1.0, 3000.0, 3100.0, 3100.0, -100.0, 10.0,
         "2026-01-02T00:00:00Z"),
    )
    conn.commit()
    conn.close()


def _setup_scores(db_path: str) -> None:
    """Insert sample traders + trader_scores for testing."""
    conn = init_db(db_path)

    # Insert traders first (FK requirement)
    traders = [
        ("0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "Whale_A", 500000.0),
        ("0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "Whale_B", 300000.0),
        ("0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", None, 200000.0),
    ]
    for addr, label, val in traders:
        conn.execute(
            "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
            (addr, label, val),
        )

    # Insert scores
    scores = [
        ("0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 0.85, "trend",
         15.0, 0.65, 2.1, 120, 1),
        ("0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", 0.72, "scalper",
         8.5, 0.55, 1.5, 250, 1),
        ("0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", 0.30, "swing",
         -5.0, 0.40, 0.8, 30, 0),
    ]
    for addr, score, style, roi, wr, pf, trades, elig in scores:
        conn.execute(
            """INSERT INTO trader_scores
               (address, composite_score, style, roi_30d, win_rate,
                profit_factor, trade_count, is_eligible)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (addr, score, style, roi, wr, pf, trades, elig),
        )

    conn.commit()
    conn.close()


# ===========================================================================
# 1. render_portfolio_table
# ===========================================================================


class TestRenderPortfolioTable:
    """Tests for render_portfolio_table."""

    def test_returns_table(self, tmp_path):
        """Returns a rich.Table instance."""
        db_path = str(tmp_path / "test.db")
        _setup_positions(db_path)
        result = render_portfolio_table(db_path)
        assert isinstance(result, Table)

    def test_column_count(self, tmp_path):
        """Table has 7 columns: Token, Side, Size USD, PnL, PnL %, Lev, Margin."""
        db_path = str(tmp_path / "test.db")
        _setup_positions(db_path)
        table = render_portfolio_table(db_path)
        assert len(table.columns) == 7

    def test_column_names(self, tmp_path):
        """Columns have expected headers."""
        db_path = str(tmp_path / "test.db")
        _setup_positions(db_path)
        table = render_portfolio_table(db_path)
        headers = [col.header for col in table.columns]
        assert headers == ["Token", "Side", "Size USD", "PnL", "PnL %", "Lev", "Margin"]

    def test_row_count_with_totals(self, tmp_path):
        """Table has 2 data rows + 1 totals row = 3 total rows."""
        db_path = str(tmp_path / "test.db")
        _setup_positions(db_path)
        table = render_portfolio_table(db_path)
        assert table.row_count == 3

    def test_empty_portfolio(self, tmp_path):
        """Empty portfolio returns table with 0 rows."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path).close()
        table = render_portfolio_table(db_path)
        assert table.row_count == 0

    def test_title(self, tmp_path):
        """Table title is 'Portfolio'."""
        db_path = str(tmp_path / "test.db")
        _setup_positions(db_path)
        table = render_portfolio_table(db_path)
        assert table.title == "Portfolio"

    def test_single_position(self, tmp_path):
        """Table with one position has 2 rows (data + totals)."""
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        conn.execute(
            """INSERT INTO our_positions
               (token_symbol, side, size, entry_price, current_price,
                position_usd, unrealized_pnl, leverage, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("SOL", "Long", 10.0, 100.0, 110.0, 1100.0, 100.0, 3.0,
             "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        table = render_portfolio_table(db_path)
        assert table.row_count == 2  # 1 data + 1 total

    def test_zero_leverage_handled(self, tmp_path):
        """Zero leverage defaults to using position_usd as margin (no div-by-zero)."""
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        conn.execute(
            """INSERT INTO our_positions
               (token_symbol, side, size, entry_price, current_price,
                position_usd, unrealized_pnl, leverage, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("DOGE", "Long", 1000.0, 0.1, 0.11, 110.0, 10.0, 0.0,
             "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        # Should not raise
        table = render_portfolio_table(db_path)
        assert table.row_count == 2

    def test_null_fields_handled(self, tmp_path):
        """Null pnl/leverage values default gracefully."""
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        conn.execute(
            """INSERT INTO our_positions
               (token_symbol, side, opened_at)
               VALUES (?, ?, ?)""",
            ("ARB", "Long", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        table = render_portfolio_table(db_path)
        assert table.row_count == 2  # 1 data + 1 total


# ===========================================================================
# 2. render_scores_table
# ===========================================================================


class TestRenderScoresTable:
    """Tests for render_scores_table."""

    def test_returns_table(self, tmp_path):
        """Returns a rich.Table instance."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)
        result = render_scores_table(db_path)
        assert isinstance(result, Table)

    def test_column_count(self, tmp_path):
        """Table has 9 columns."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)
        table = render_scores_table(db_path)
        assert len(table.columns) == 9

    def test_column_names(self, tmp_path):
        """Columns have expected headers."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)
        table = render_scores_table(db_path)
        headers = [col.header for col in table.columns]
        assert headers == ["#", "Address", "Score", "Style", "ROI 30d", "WR", "PF", "Trades", "Elig"]

    def test_row_count(self, tmp_path):
        """Table has 3 rows for 3 traders."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)
        table = render_scores_table(db_path)
        assert table.row_count == 3

    def test_title(self, tmp_path):
        """Table title is 'Trader Scores'."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)
        table = render_scores_table(db_path)
        assert table.title == "Trader Scores"

    def test_empty_scores(self, tmp_path):
        """Empty scores table returns 0 rows."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path).close()
        table = render_scores_table(db_path)
        assert table.row_count == 0

    def test_ordered_by_score_desc(self, tmp_path):
        """Rows ordered by composite_score descending (rank #1 = highest)."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)
        table = render_scores_table(db_path)
        # First data row should be rank 1 (highest score = 0.85)
        # Rich stores rows as list of renderables
        assert table.row_count == 3

    def test_limits_to_15(self, tmp_path):
        """Table is capped at 15 rows even if more traders exist."""
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)

        # Insert 20 traders
        for i in range(20):
            addr = f"0x{i:040x}"
            conn.execute(
                "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
                (addr, f"T{i}", 100000.0),
            )
            conn.execute(
                """INSERT INTO trader_scores
                   (address, composite_score, style, roi_30d, win_rate,
                    profit_factor, trade_count, is_eligible)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (addr, 0.5 + i * 0.01, "trend", 10.0, 0.6, 1.5, 100, 1),
            )
        conn.commit()
        conn.close()

        table = render_scores_table(db_path)
        assert table.row_count == 15

    def test_latest_scores_only(self, tmp_path):
        """Only the most recent score per trader is shown."""
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)

        addr = "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD"
        conn.execute(
            "INSERT INTO traders (address, label, account_value) VALUES (?, ?, ?)",
            (addr, "Multi", 100000.0),
        )
        # Insert two scores for same trader (different ids due to AUTOINCREMENT)
        conn.execute(
            """INSERT INTO trader_scores
               (address, composite_score, style, roi_30d, win_rate,
                profit_factor, trade_count, is_eligible)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (addr, 0.30, "trend", 5.0, 0.5, 1.0, 50, 0),
        )
        conn.execute(
            """INSERT INTO trader_scores
               (address, composite_score, style, roi_30d, win_rate,
                profit_factor, trade_count, is_eligible)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (addr, 0.90, "scalper", 20.0, 0.7, 2.5, 100, 1),
        )
        conn.commit()
        conn.close()

        table = render_scores_table(db_path)
        # Only 1 row — latest score (id=2, score=0.90)
        assert table.row_count == 1

    def test_null_label_handled(self, tmp_path):
        """Trader with NULL label doesn't crash."""
        db_path = str(tmp_path / "test.db")
        _setup_scores(db_path)  # 3rd trader has label=None
        table = render_scores_table(db_path)
        assert table.row_count == 3


# ===========================================================================
# 3. render_status_bar
# ===========================================================================


class TestRenderStatusBar:
    """Tests for render_status_bar."""

    def test_returns_panel(self):
        """Returns a rich.Panel instance."""
        result = render_status_bar("IDLE", "PAPER", 10000.0)
        assert isinstance(result, Panel)

    def test_title_is_snap(self):
        """Panel title is 'SNAP'."""
        panel = render_status_bar("IDLE", "PAPER", 10000.0)
        assert panel.title == "SNAP"

    def test_contains_mode(self):
        """Panel renderable contains the mode string."""
        panel = render_status_bar("IDLE", "PAPER", 10000.0)
        text = str(panel.renderable)
        assert "PAPER" in text

    def test_contains_state(self):
        """Panel renderable contains the scheduler state."""
        panel = render_status_bar("REBALANCING", "PAPER", 10000.0)
        text = str(panel.renderable)
        assert "REBALANCING" in text

    def test_contains_account_value(self):
        """Panel renderable contains formatted account value."""
        panel = render_status_bar("IDLE", "PAPER", 10000.0)
        text = str(panel.renderable)
        assert "$10,000" in text

    def test_live_mode(self):
        """LIVE mode is shown correctly."""
        panel = render_status_bar("IDLE", "LIVE", 50000.0)
        text = str(panel.renderable)
        assert "LIVE" in text
        assert "$50,000" in text

    def test_no_timestamps(self):
        """When no timestamps provided, shows dashes."""
        panel = render_status_bar("IDLE", "PAPER", 10000.0)
        text = str(panel.renderable)
        assert "\u2014" in text  # em-dash for missing timestamp

    def test_with_refresh_timestamp(self):
        """Refresh timestamp is shown as hours ago."""
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        panel = render_status_bar(
            "IDLE", "PAPER", 10000.0, last_refresh=one_hour_ago
        )
        text = str(panel.renderable)
        assert "Refresh:" in text
        # Should show approximately 1.0h ago
        assert "h ago" in text

    def test_with_rebalance_timestamp(self):
        """Rebalance timestamp is shown as hours ago."""
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        panel = render_status_bar(
            "IDLE", "PAPER", 10000.0, last_rebalance=two_hours_ago
        )
        text = str(panel.renderable)
        assert "Rebal:" in text
        assert "h ago" in text

    def test_invalid_timestamp_shows_dash(self):
        """Invalid timestamp string falls back to em-dash."""
        panel = render_status_bar(
            "IDLE", "PAPER", 10000.0, last_refresh="not-a-date"
        )
        text = str(panel.renderable)
        assert "Refresh:" in text
        assert "\u2014" in text

    def test_border_style(self):
        """Panel has blue border."""
        panel = render_status_bar("IDLE", "PAPER", 10000.0)
        assert str(panel.border_style) == "blue"
