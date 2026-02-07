"""Shared pytest fixtures for the Snap test suite."""

from __future__ import annotations

import sqlite3

import pytest

from snap.database import init_db


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """Provide a fresh in-memory database with all tables created.

    The connection is closed automatically after the test finishes.
    """
    conn = init_db(":memory:")
    yield conn
    conn.close()
