"""Shared pytest fixtures for the Snap test suite."""

from __future__ import annotations

import sqlite3

import pytest

from snap.database import init_data_db, init_db, init_strategy_db


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """Provide a fresh in-memory database with all tables created.

    The connection is closed automatically after the test finishes.
    """
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture()
def data_db_conn() -> sqlite3.Connection:
    """Provide an in-memory database with only data tables."""
    conn = init_data_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture()
def strategy_db_conn() -> sqlite3.Connection:
    """Provide an in-memory database with only strategy tables."""
    conn = init_strategy_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture()
def dual_db(tmp_path):
    """Provide separate data and strategy DB paths for cross-DB tests.

    Yields a tuple ``(data_db_path, strategy_db_path)`` backed by real
    files (required for cross-connection queries).
    """
    data_path = str(tmp_path / "data.db")
    strategy_path = str(tmp_path / "strategy.db")
    data_conn = init_data_db(data_path)
    data_conn.close()
    strategy_conn = init_strategy_db(strategy_path)
    strategy_conn.close()
    yield data_path, strategy_path
