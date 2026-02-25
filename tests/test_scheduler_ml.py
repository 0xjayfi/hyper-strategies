"""Tests for ML snapshot scheduling."""

from datetime import datetime, timedelta

import pytest

from snap.scheduler import SystemScheduler, SchedulerState


class TestMLSnapshotCadence:
    def test_snapshotting_ml_state_exists(self):
        """SchedulerState should have SNAPSHOTTING_ML."""
        assert hasattr(SchedulerState, 'SNAPSHOTTING_ML')

    def test_should_snapshot_ml_method_exists(self):
        """SystemScheduler should have _should_snapshot_ml method."""
        assert hasattr(SystemScheduler, '_should_snapshot_ml')

    def test_run_ml_snapshot_method_exists(self):
        """SystemScheduler should have _run_ml_snapshot method."""
        assert hasattr(SystemScheduler, '_run_ml_snapshot')
