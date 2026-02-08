"""Tests for the main CLI entry point (Phase 9).

Covers:
1. Argument parsing (defaults, --paper, --live, --db-path, etc.)
2. Paper/live mode toggle logic
3. parse_args with various flag combinations
"""

from __future__ import annotations

import pytest

from snap.main import parse_args


# ===========================================================================
# 1. Argument Parsing Defaults
# ===========================================================================


class TestParseArgsDefaults:
    """Tests for default argument values."""

    def test_defaults_paper_mode(self):
        """Default mode is paper trade."""
        args = parse_args([])
        assert args.live is False
        assert args.paper is True

    def test_default_db_path(self):
        """Default db_path from config."""
        args = parse_args([])
        assert args.db_path is not None

    def test_default_account_value(self):
        """Default account value from config."""
        args = parse_args([])
        assert args.account_value > 0

    def test_default_log_file_none(self):
        """Default log_file is from config (may be None)."""
        args = parse_args([])
        # Just ensure it parses without error
        assert hasattr(args, "log_file")


# ===========================================================================
# 2. Paper/Live Mode Toggle
# ===========================================================================


class TestModeToggle:
    """Tests for paper/live mode flag logic."""

    def test_paper_flag(self):
        """--paper flag sets paper mode."""
        args = parse_args(["--paper"])
        assert args.live is False
        assert args.paper is True

    def test_live_flag(self):
        """--live flag enables live mode."""
        args = parse_args(["--live"])
        assert args.live is True

    def test_paper_and_live_mutually_exclusive(self):
        """--paper and --live cannot be used together."""
        with pytest.raises(SystemExit):
            parse_args(["--live", "--paper"])

    def test_paper_alone(self):
        """--paper alone keeps live=False."""
        args = parse_args(["--paper"])
        assert args.live is False


# ===========================================================================
# 3. Custom Arguments
# ===========================================================================


class TestCustomArgs:
    """Tests for custom argument values."""

    def test_custom_db_path(self):
        """--db-path sets custom database path."""
        args = parse_args(["--db-path", "/tmp/custom.db"])
        assert args.db_path == "/tmp/custom.db"

    def test_custom_account_value(self):
        """--account-value sets custom account value."""
        args = parse_args(["--account-value", "5000"])
        assert args.account_value == 5000.0

    def test_custom_log_file(self):
        """--log-file sets log file path."""
        args = parse_args(["--log-file", "/tmp/snap.log"])
        assert args.log_file == "/tmp/snap.log"

    def test_custom_dashboard_file(self):
        """--dashboard-file sets dashboard output path."""
        args = parse_args(["--dashboard-file", "/tmp/dash.json"])
        assert args.dashboard_file == "/tmp/dash.json"

    def test_custom_health_file(self):
        """--health-file sets health check path."""
        args = parse_args(["--health-file", "/tmp/health.json"])
        assert args.health_file == "/tmp/health.json"

    def test_all_custom_args(self):
        """All arguments can be set together."""
        args = parse_args([
            "--live",
            "--db-path", "/data/prod.db",
            "--account-value", "50000",
            "--log-file", "/var/log/snap.log",
            "--dashboard-file", "/tmp/dash.json",
            "--health-file", "/tmp/health.json",
        ])
        assert args.live is True
        assert args.db_path == "/data/prod.db"
        assert args.account_value == 50000.0
        assert args.log_file == "/var/log/snap.log"
        assert args.dashboard_file == "/tmp/dash.json"
        assert args.health_file == "/tmp/health.json"
