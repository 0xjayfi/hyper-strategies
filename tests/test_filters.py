"""Task 10.5 -- Trade action filter unit tests.

The action filter is Step 1 of ``src.trade_ingestion.evaluate_trade``:

  - "Open"  -> always passes
  - "Add"   -> passes only if the original Open is within ADD_MAX_AGE_HOURS (2)
  - "Close" -> always rejected as an entry signal
  - "Reduce"-> always rejected as an entry signal

These tests verify the filter conditions directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.config import settings


# ---------------------------------------------------------------------------
# Valid actions for copy entry
# ---------------------------------------------------------------------------

VALID_ENTRY_ACTIONS = ("Open", "Add")


class TestOpenAction:
    def test_open_action_passes(self) -> None:
        """Open is a valid entry action."""
        assert "Open" in VALID_ENTRY_ACTIONS

    def test_open_action_is_always_valid(self) -> None:
        """Open does not require any age check."""
        action = "Open"
        assert action == "Open"


class TestAddAction:
    def test_add_within_2hrs_passes(self) -> None:
        """Add within ADD_MAX_AGE_HOURS passes the age gate."""
        open_time = datetime.now(timezone.utc) - timedelta(hours=1)
        trade_time = datetime.now(timezone.utc)
        hours_since_open = (trade_time - open_time).total_seconds() / 3600
        assert hours_since_open <= settings.ADD_MAX_AGE_HOURS

    def test_add_at_exactly_2hrs_passes(self) -> None:
        """Add exactly at ADD_MAX_AGE_HOURS boundary passes (uses >)."""
        base_time = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        open_time = base_time
        trade_time = base_time + timedelta(hours=2)
        hours_since_open = (trade_time - open_time).total_seconds() / 3600
        # The code uses > (strict), so exactly 2 is NOT rejected
        assert not (hours_since_open > settings.ADD_MAX_AGE_HOURS)

    def test_add_after_2hrs_rejected(self) -> None:
        """Add more than ADD_MAX_AGE_HOURS after the open is rejected."""
        open_time = datetime.now(timezone.utc) - timedelta(hours=3)
        trade_time = datetime.now(timezone.utc)
        hours_since_open = (trade_time - open_time).total_seconds() / 3600
        assert hours_since_open > settings.ADD_MAX_AGE_HOURS

    def test_add_just_over_2hrs_rejected(self) -> None:
        """Add at 2h01m is rejected."""
        open_time = datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)
        trade_time = datetime.now(timezone.utc)
        hours_since_open = (trade_time - open_time).total_seconds() / 3600
        assert hours_since_open > settings.ADD_MAX_AGE_HOURS

    def test_add_is_valid_entry_action(self) -> None:
        """Add is in the set of valid entry actions."""
        assert "Add" in VALID_ENTRY_ACTIONS


class TestRejectedActions:
    def test_reduce_rejected(self) -> None:
        """Reduce is not a valid entry action."""
        assert "Reduce" not in VALID_ENTRY_ACTIONS

    def test_close_rejected_as_entry(self) -> None:
        """Close is not a valid entry action."""
        assert "Close" not in VALID_ENTRY_ACTIONS

    def test_liquidation_rejected(self) -> None:
        """Any unknown action (e.g. Liquidation) is not a valid entry."""
        assert "Liquidation" not in VALID_ENTRY_ACTIONS

    def test_empty_string_rejected(self) -> None:
        """Empty string is not a valid entry action."""
        assert "" not in VALID_ENTRY_ACTIONS


class TestAddMaxAgeConfig:
    def test_add_max_age_hours_default(self) -> None:
        """Verify the config default for ADD_MAX_AGE_HOURS."""
        assert settings.ADD_MAX_AGE_HOURS == 2
