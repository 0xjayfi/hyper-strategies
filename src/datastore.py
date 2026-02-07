"""SQLite data store for the PnL-Weighted Dynamic Allocation system.

Provides a single-file SQLite database with 7 tables covering traders,
leaderboard snapshots, trade metrics, composite scores, allocations,
blacklist entries, and position snapshots.  All methods are synchronous
and use parameterized queries.

Usage::

    with DataStore("data/pnl_weighted.db") as ds:
        ds.upsert_trader("0xABC", label="Whale")
        ds.insert_leaderboard_snapshot("0xABC", "2024-01-01", "2024-01-07", 5000.0, 12.5, 40000.0)
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from src.models import TradeMetrics


class DataStore:
    """Synchronous SQLite-backed store for the PnL-weighted allocation pipeline."""

    def __init__(self, db_path: str = "data/pnl_weighted.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> "DataStore":
        return self

    def __exit__(self, *args) -> None:  # noqa: ANN002
        self.close()

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        cur = self._conn.cursor()

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS traders (
                address         TEXT PRIMARY KEY,
                label           TEXT,
                first_seen      TEXT NOT NULL,
                is_active       INTEGER DEFAULT 1,
                style           TEXT,
                notes           TEXT
            );

            CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at     TEXT NOT NULL,
                date_from       TEXT NOT NULL,
                date_to         TEXT NOT NULL,
                address         TEXT NOT NULL REFERENCES traders(address),
                total_pnl       REAL,
                roi             REAL,
                account_value   REAL
            );

            CREATE TABLE IF NOT EXISTS trade_metrics (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                address         TEXT NOT NULL REFERENCES traders(address),
                computed_at     TEXT NOT NULL,
                window_days     INTEGER NOT NULL,
                total_trades    INTEGER,
                winning_trades  INTEGER,
                losing_trades   INTEGER,
                win_rate        REAL,
                gross_profit    REAL,
                gross_loss      REAL,
                profit_factor   REAL,
                avg_return      REAL,
                std_return      REAL,
                pseudo_sharpe   REAL,
                total_pnl       REAL,
                roi_proxy       REAL,
                max_drawdown_proxy REAL
            );

            CREATE TABLE IF NOT EXISTS trader_scores (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                address         TEXT NOT NULL REFERENCES traders(address),
                computed_at     TEXT NOT NULL,
                normalized_roi          REAL,
                normalized_sharpe       REAL,
                normalized_win_rate     REAL,
                consistency_score       REAL,
                smart_money_bonus       REAL,
                risk_management_score   REAL,
                style_multiplier        REAL,
                recency_decay           REAL,
                raw_composite_score     REAL,
                final_score             REAL,
                roi_tier_multiplier     REAL,
                passes_anti_luck        INTEGER
            );

            CREATE TABLE IF NOT EXISTS allocations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                computed_at     TEXT NOT NULL,
                address         TEXT NOT NULL REFERENCES traders(address),
                raw_weight      REAL,
                capped_weight   REAL,
                final_weight    REAL
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                address         TEXT NOT NULL REFERENCES traders(address),
                reason          TEXT NOT NULL,
                blacklisted_at  TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                PRIMARY KEY (address, blacklisted_at)
            );

            CREATE TABLE IF NOT EXISTS position_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                address         TEXT NOT NULL REFERENCES traders(address),
                captured_at     TEXT NOT NULL,
                token_symbol    TEXT NOT NULL,
                side            TEXT,
                position_value_usd REAL,
                entry_price     REAL,
                leverage_value  REAL,
                leverage_type   TEXT,
                liquidation_price REAL,
                unrealized_pnl  REAL,
                account_value   REAL
            );

            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_leaderboard_address
                ON leaderboard_snapshots(address);
            CREATE INDEX IF NOT EXISTS idx_leaderboard_captured
                ON leaderboard_snapshots(captured_at);
            CREATE INDEX IF NOT EXISTS idx_trade_metrics_address_window
                ON trade_metrics(address, window_days);
            CREATE INDEX IF NOT EXISTS idx_trade_metrics_computed
                ON trade_metrics(computed_at);
            CREATE INDEX IF NOT EXISTS idx_scores_address
                ON trader_scores(address);
            CREATE INDEX IF NOT EXISTS idx_scores_computed
                ON trader_scores(computed_at);
            CREATE INDEX IF NOT EXISTS idx_allocations_computed
                ON allocations(computed_at);
            CREATE INDEX IF NOT EXISTS idx_blacklist_address
                ON blacklist(address);
            CREATE INDEX IF NOT EXISTS idx_blacklist_expires
                ON blacklist(expires_at);
            CREATE INDEX IF NOT EXISTS idx_positions_address
                ON position_snapshots(address);
            CREATE INDEX IF NOT EXISTS idx_positions_captured
                ON position_snapshots(captured_at);
            CREATE INDEX IF NOT EXISTS idx_positions_token
                ON position_snapshots(address, token_symbol);
            """
        )

        self._conn.commit()

    # ------------------------------------------------------------------
    # Traders
    # ------------------------------------------------------------------

    def upsert_trader(
        self,
        address: str,
        label: Optional[str] = None,
        style: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Insert a new trader or update an existing one.

        On first insert ``first_seen`` is set to the current date.  On
        subsequent calls the existing ``first_seen`` value is preserved.
        ``is_active`` is always set to 1.
        """
        existing = self.get_trader(address)
        if existing is None:
            first_seen = datetime.utcnow().strftime("%Y-%m-%d")
            self._conn.execute(
                """
                INSERT INTO traders (address, label, first_seen, is_active, style, notes)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (address, label, first_seen, style, notes),
            )
        else:
            self._conn.execute(
                """
                UPDATE traders
                   SET label = COALESCE(?, label),
                       is_active = 1,
                       style = COALESCE(?, style),
                       notes = COALESCE(?, notes)
                 WHERE address = ?
                """,
                (label, style, notes, address),
            )
        self._conn.commit()

    def get_trader(self, address: str) -> Optional[dict]:
        """Return a trader row as a dict, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM traders WHERE address = ?", (address,)
        ).fetchone()
        return dict(row) if row else None

    def get_active_traders(self) -> list[str]:
        """Return addresses of all traders where ``is_active = 1``."""
        rows = self._conn.execute(
            "SELECT address FROM traders WHERE is_active = 1"
        ).fetchall()
        return [r["address"] for r in rows]

    def get_trader_label(self, address: str) -> Optional[str]:
        """Return the label for a trader, or ``None``."""
        row = self._conn.execute(
            "SELECT label FROM traders WHERE address = ?", (address,)
        ).fetchone()
        return row["label"] if row else None

    # ------------------------------------------------------------------
    # Leaderboard snapshots
    # ------------------------------------------------------------------

    def insert_leaderboard_snapshot(
        self,
        address: str,
        date_from: str,
        date_to: str,
        total_pnl: float,
        roi: float,
        account_value: float,
    ) -> None:
        """Insert a leaderboard snapshot row with ``captured_at`` set to now."""
        captured_at = datetime.utcnow().isoformat()
        self._conn.execute(
            """
            INSERT INTO leaderboard_snapshots
                (captured_at, date_from, date_to, address, total_pnl, roi, account_value)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (captured_at, date_from, date_to, address, total_pnl, roi, account_value),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Trade metrics
    # ------------------------------------------------------------------

    def insert_trade_metrics(self, address: str, metrics: TradeMetrics) -> None:
        """Insert a trade_metrics row from a :class:`TradeMetrics` model.

        ``computed_at`` is set automatically to the current UTC time.
        """
        computed_at = datetime.utcnow().isoformat()
        self._conn.execute(
            """
            INSERT INTO trade_metrics
                (address, computed_at, window_days, total_trades, winning_trades,
                 losing_trades, win_rate, gross_profit, gross_loss, profit_factor,
                 avg_return, std_return, pseudo_sharpe, total_pnl, roi_proxy,
                 max_drawdown_proxy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                address,
                computed_at,
                metrics.window_days,
                metrics.total_trades,
                metrics.winning_trades,
                metrics.losing_trades,
                metrics.win_rate,
                metrics.gross_profit,
                metrics.gross_loss,
                metrics.profit_factor,
                metrics.avg_return,
                metrics.std_return,
                metrics.pseudo_sharpe,
                metrics.total_pnl,
                metrics.roi_proxy,
                metrics.max_drawdown_proxy,
            ),
        )
        self._conn.commit()

    def get_latest_metrics(
        self, address: str, window_days: int
    ) -> Optional[TradeMetrics]:
        """Return the most recent :class:`TradeMetrics` for *address* and *window_days*.

        Returns ``None`` if no matching row exists.
        """
        row = self._conn.execute(
            """
            SELECT * FROM trade_metrics
             WHERE address = ? AND window_days = ?
             ORDER BY computed_at DESC
             LIMIT 1
            """,
            (address, window_days),
        ).fetchone()
        if row is None:
            return None
        return TradeMetrics(
            window_days=row["window_days"],
            total_trades=row["total_trades"],
            winning_trades=row["winning_trades"],
            losing_trades=row["losing_trades"],
            win_rate=row["win_rate"],
            gross_profit=row["gross_profit"],
            gross_loss=row["gross_loss"],
            profit_factor=row["profit_factor"],
            avg_return=row["avg_return"],
            std_return=row["std_return"],
            pseudo_sharpe=row["pseudo_sharpe"],
            total_pnl=row["total_pnl"],
            roi_proxy=row["roi_proxy"],
            max_drawdown_proxy=row["max_drawdown_proxy"],
        )

    # ------------------------------------------------------------------
    # Trader scores
    # ------------------------------------------------------------------

    _SCORE_FIELDS = (
        "normalized_roi",
        "normalized_sharpe",
        "normalized_win_rate",
        "consistency_score",
        "smart_money_bonus",
        "risk_management_score",
        "style_multiplier",
        "recency_decay",
        "raw_composite_score",
        "final_score",
        "roi_tier_multiplier",
        "passes_anti_luck",
    )

    def insert_score(self, address: str, score_data: dict) -> None:
        """Insert a trader_scores row.  ``computed_at`` is set automatically.

        *score_data* must contain keys matching the score column names.
        """
        computed_at = datetime.utcnow().isoformat()
        values = [address, computed_at] + [
            score_data[f] for f in self._SCORE_FIELDS
        ]
        placeholders = ", ".join(["?"] * (2 + len(self._SCORE_FIELDS)))
        columns = ", ".join(["address", "computed_at"] + list(self._SCORE_FIELDS))
        self._conn.execute(
            f"INSERT INTO trader_scores ({columns}) VALUES ({placeholders})",
            values,
        )
        self._conn.commit()

    def get_latest_score(self, address: str) -> Optional[dict]:
        """Return the most recent score row for *address* as a dict, or ``None``."""
        row = self._conn.execute(
            """
            SELECT * FROM trader_scores
             WHERE address = ?
             ORDER BY computed_at DESC
             LIMIT 1
            """,
            (address,),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Allocations
    # ------------------------------------------------------------------

    def insert_allocation(
        self,
        computed_at: str,
        address: str,
        raw_weight: float,
        capped_weight: float,
        final_weight: float,
    ) -> None:
        """Insert a single allocation row."""
        self._conn.execute(
            """
            INSERT INTO allocations
                (computed_at, address, raw_weight, capped_weight, final_weight)
            VALUES (?, ?, ?, ?, ?)
            """,
            (computed_at, address, raw_weight, capped_weight, final_weight),
        )
        self._conn.commit()

    def insert_allocations(self, allocations: dict[str, float]) -> None:
        """Bulk-insert allocations from ``{address: final_weight}``.

        For convenience the *raw_weight* and *capped_weight* columns are
        set equal to *final_weight*.  The full pipeline will call
        :meth:`insert_allocation` individually when distinct weights are
        available.  All rows share the same ``computed_at`` timestamp and
        are written inside a single transaction.
        """
        computed_at = datetime.utcnow().isoformat()
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO allocations
                    (computed_at, address, raw_weight, capped_weight, final_weight)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (computed_at, addr, weight, weight, weight)
                    for addr, weight in allocations.items()
                ],
            )

    def get_latest_allocations(self) -> dict[str, float]:
        """Return the most recent allocation batch as ``{address: final_weight}``.

        All rows sharing the maximum ``computed_at`` value are included.
        """
        row = self._conn.execute(
            "SELECT MAX(computed_at) AS max_ts FROM allocations"
        ).fetchone()
        if row is None or row["max_ts"] is None:
            return {}
        max_ts = row["max_ts"]
        rows = self._conn.execute(
            "SELECT address, final_weight FROM allocations WHERE computed_at = ?",
            (max_ts,),
        ).fetchall()
        return {r["address"]: r["final_weight"] for r in rows}

    # ------------------------------------------------------------------
    # Blacklist
    # ------------------------------------------------------------------

    def add_to_blacklist(
        self,
        address: str,
        reason: str,
        expires_at: Optional[str] = None,
    ) -> None:
        """Add an address to the blacklist.

        If *expires_at* is ``None`` a default expiry of 14 days from now
        is used.  ``blacklisted_at`` is set automatically.
        """
        blacklisted_at = datetime.utcnow().isoformat()
        if expires_at is None:
            expires_at = (datetime.utcnow() + timedelta(days=14)).isoformat()
        self._conn.execute(
            """
            INSERT INTO blacklist (address, reason, blacklisted_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (address, reason, blacklisted_at, expires_at),
        )
        self._conn.commit()

    def is_blacklisted(self, address: str) -> bool:
        """Return ``True`` if the address has an active (non-expired) blacklist entry."""
        now = datetime.utcnow().isoformat()
        row = self._conn.execute(
            """
            SELECT 1 FROM blacklist
             WHERE address = ? AND expires_at > ?
             LIMIT 1
            """,
            (address, now),
        ).fetchone()
        return row is not None

    def get_blacklist_entry(self, address: str) -> Optional[dict]:
        """Return the most recent *active* blacklist entry as a dict, or ``None``."""
        now = datetime.utcnow().isoformat()
        row = self._conn.execute(
            """
            SELECT * FROM blacklist
             WHERE address = ? AND expires_at > ?
             ORDER BY blacklisted_at DESC
             LIMIT 1
            """,
            (address, now),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Position snapshots
    # ------------------------------------------------------------------

    def insert_position_snapshot(
        self, address: str, positions: list[dict]
    ) -> None:
        """Bulk-insert position snapshot rows for *address*.

        Each dict in *positions* should contain keys: ``token_symbol``,
        ``side``, ``position_value_usd``, ``entry_price``,
        ``leverage_value``, ``leverage_type``, ``liquidation_price``,
        ``unrealized_pnl``, ``account_value``.

        ``captured_at`` is set automatically and shared across all rows.
        """
        captured_at = datetime.utcnow().isoformat()
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO position_snapshots
                    (address, captured_at, token_symbol, side, position_value_usd,
                     entry_price, leverage_value, leverage_type, liquidation_price,
                     unrealized_pnl, account_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        address,
                        captured_at,
                        p["token_symbol"],
                        p.get("side"),
                        p.get("position_value_usd"),
                        p.get("entry_price"),
                        p.get("leverage_value"),
                        p.get("leverage_type"),
                        p.get("liquidation_price"),
                        p.get("unrealized_pnl"),
                        p.get("account_value"),
                    )
                    for p in positions
                ],
            )

    def get_latest_position_snapshot(self, address: str) -> list[dict]:
        """Return the most recent position snapshot rows for *address*.

        All rows sharing the maximum ``captured_at`` for the given address
        are returned.  Returns an empty list when no snapshots exist.
        """
        row = self._conn.execute(
            """
            SELECT MAX(captured_at) AS max_ts
              FROM position_snapshots
             WHERE address = ?
            """,
            (address,),
        ).fetchone()
        if row is None or row["max_ts"] is None:
            return []
        max_ts = row["max_ts"]
        rows = self._conn.execute(
            """
            SELECT * FROM position_snapshots
             WHERE address = ? AND captured_at = ?
            """,
            (address, max_ts),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_position_history(
        self, address: str, token_symbol: str, lookback_hours: int = 24
    ) -> list[dict]:
        """Return position snapshots for *address* + *token_symbol* within the lookback window.

        Used by liquidation detection to compare current vs. recent
        positions.
        """
        cutoff = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
        rows = self._conn.execute(
            """
            SELECT * FROM position_snapshots
             WHERE address = ? AND token_symbol = ? AND captured_at >= ?
             ORDER BY captured_at ASC
            """,
            (address, token_symbol, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Activity helpers
    # ------------------------------------------------------------------

    def get_last_trade_time(self, address: str) -> Optional[str]:
        """Return the most recent ``computed_at`` from trade_metrics for *address*.

        This serves as a proxy for the last known trading activity.
        Returns an ISO datetime string or ``None``.
        """
        row = self._conn.execute(
            """
            SELECT MAX(computed_at) AS last_ts
              FROM trade_metrics
             WHERE address = ?
            """,
            (address,),
        ).fetchone()
        if row is None or row["last_ts"] is None:
            return None
        return row["last_ts"]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_expired_blacklist(self) -> None:
        """Delete all blacklist entries whose ``expires_at`` is in the past."""
        now = datetime.utcnow().isoformat()
        self._conn.execute("DELETE FROM blacklist WHERE expires_at < ?", (now,))
        self._conn.commit()

    def enforce_retention(self, days: int = 90) -> None:
        """Delete rows older than *days* from snapshot and metric tables.

        Affected tables and their timestamp columns:

        * ``leaderboard_snapshots`` -- ``captured_at``
        * ``trade_metrics`` -- ``computed_at``
        * ``trader_scores`` -- ``computed_at``
        * ``allocations`` -- ``computed_at``
        * ``position_snapshots`` -- ``captured_at``
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn:
            self._conn.execute(
                "DELETE FROM leaderboard_snapshots WHERE captured_at < ?", (cutoff,)
            )
            self._conn.execute(
                "DELETE FROM trade_metrics WHERE computed_at < ?", (cutoff,)
            )
            self._conn.execute(
                "DELETE FROM trader_scores WHERE computed_at < ?", (cutoff,)
            )
            self._conn.execute(
                "DELETE FROM allocations WHERE computed_at < ?", (cutoff,)
            )
            self._conn.execute(
                "DELETE FROM position_snapshots WHERE captured_at < ?", (cutoff,)
            )
