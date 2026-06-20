"""Persistent SQLite queue and service status storage."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .timeutil import utc_now, utc_timestamp


@dataclass(frozen=True)
class QueuedScan:
    """A pending scan row ready for delivery."""

    id: int
    barcode: str
    captured_at: str
    attempts: int


@dataclass(frozen=True)
class QueueSummary:
    """Aggregate persistent queue state for health output."""

    pending_count: int
    oldest_pending_at: str | None
    newest_pending_at: str | None
    max_attempts: int
    last_error: str | None
    last_error_at: str | None
    sent_count: int


class ScanStore:
    """SQLite-backed scan queue and status store."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        """Create database tables and indexes if needed."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    last_error_at TEXT,
                    sent_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scans_pending_due
                ON scans(status, next_attempt_at, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_status (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def enqueue_scan(self, barcode: str, captured_at: str | None = None) -> int:
        """Persist a scan for ordered delivery."""

        timestamp = captured_at or utc_timestamp()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO scans(barcode, captured_at, status)
                VALUES (?, ?, 'pending')
                """,
                (barcode, timestamp),
            )
            self.set_status_many(
                {
                    "last_scan_at": timestamp,
                    "last_scan_length": str(len(barcode)),
                },
                connection=conn,
            )
            return int(cursor.lastrowid)

    def fetch_next_due(self, now: str | None = None) -> QueuedScan | None:
        """Return the oldest pending scan due for delivery."""

        timestamp = now or utc_timestamp()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT id, barcode, captured_at, attempts
                FROM scans
                WHERE status = 'pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY id ASC
                LIMIT 1
                """,
                (timestamp,),
            ).fetchone()
        if row is None:
            return None
        return QueuedScan(
            id=int(row["id"]),
            barcode=str(row["barcode"]),
            captured_at=str(row["captured_at"]),
            attempts=int(row["attempts"]),
        )

    def mark_sent(self, scan_id: int, sent_at: str | None = None) -> None:
        """Mark a queued scan as delivered to the TCP socket."""

        timestamp = sent_at or utc_timestamp()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE scans
                SET status = 'sent',
                    sent_at = ?,
                    last_error = NULL,
                    last_error_at = NULL,
                    next_attempt_at = NULL
                WHERE id = ?
                """,
                (timestamp, scan_id),
            )
            self.set_status_many(
                {
                    "last_delivery_at": timestamp,
                    "last_delivery_scan_id": str(scan_id),
                },
                connection=conn,
            )

    def mark_failed(
        self,
        scan_id: int,
        error: str,
        retry_delay_seconds: float,
        failed_at: str | None = None,
    ) -> None:
        """Record a failed delivery attempt while keeping the scan pending."""

        timestamp = failed_at or utc_timestamp()
        retry_at = utc_timestamp(utc_now() + timedelta(seconds=retry_delay_seconds))
        clean_error = error[:500]
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE scans
                SET attempts = attempts + 1,
                    next_attempt_at = ?,
                    last_error = ?,
                    last_error_at = ?,
                    status = 'pending'
                WHERE id = ?
                """,
                (retry_at, clean_error, timestamp, scan_id),
            )
            self.set_status_many(
                {
                    "last_delivery_error": clean_error,
                    "last_delivery_error_at": timestamp,
                },
                connection=conn,
            )

    def queue_summary(self) -> QueueSummary:
        """Return queue counts and recent failure metadata."""

        with self._connection() as conn:
            pending = conn.execute(
                """
                SELECT
                    COUNT(*) AS pending_count,
                    MIN(captured_at) AS oldest_pending_at,
                    MAX(captured_at) AS newest_pending_at,
                    COALESCE(MAX(attempts), 0) AS max_attempts
                FROM scans
                WHERE status = 'pending'
                """
            ).fetchone()
            sent = conn.execute(
                "SELECT COUNT(*) AS sent_count FROM scans WHERE status = 'sent'"
            ).fetchone()
            last_error = conn.execute(
                """
                SELECT last_error, last_error_at
                FROM scans
                WHERE last_error IS NOT NULL
                ORDER BY last_error_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return QueueSummary(
            pending_count=int(pending["pending_count"]),
            oldest_pending_at=pending["oldest_pending_at"],
            newest_pending_at=pending["newest_pending_at"],
            max_attempts=int(pending["max_attempts"]),
            last_error=last_error["last_error"] if last_error else None,
            last_error_at=last_error["last_error_at"] if last_error else None,
            sent_count=int(sent["sent_count"]),
        )

    def cleanup_sent(self, retention_days: int) -> int:
        """Remove sent scan metadata older than the configured retention window."""

        if retention_days < 0:
            return 0
        cutoff = utc_timestamp(utc_now() - timedelta(days=retention_days))
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM scans WHERE status = 'sent' AND sent_at < ?",
                (cutoff,),
            )
            return int(cursor.rowcount)

    def set_status(self, key: str, value: str) -> None:
        """Set one service status key."""

        with self._connection() as conn:
            self.set_status_many({key: value}, connection=conn)

    def set_status_many(
        self, values: dict[str, str], connection: sqlite3.Connection | None = None
    ) -> None:
        """Set several service status keys atomically."""

        timestamp = utc_timestamp()

        def write(conn: sqlite3.Connection) -> None:
            conn.executemany(
                """
                INSERT INTO service_status(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                [(key, value, timestamp) for key, value in values.items()],
            )

        if connection is not None:
            write(connection)
            return
        with self._connection() as conn:
            write(conn)

    def status_snapshot(self) -> dict[str, dict[str, str]]:
        """Return all service status keys with values and update times."""

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at FROM service_status ORDER BY key"
            ).fetchall()
        return {
            str(row["key"]): {
                "value": str(row["value"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        }

    def heartbeat(self) -> None:
        """Update the service heartbeat timestamp."""

        self.set_status("heartbeat_at", utc_timestamp())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def queue_summary_to_dict(summary: QueueSummary) -> dict[str, Any]:
    """Convert QueueSummary to a JSON-friendly dictionary."""

    return {
        "pending_count": summary.pending_count,
        "oldest_pending_at": summary.oldest_pending_at,
        "newest_pending_at": summary.newest_pending_at,
        "max_attempts": summary.max_attempts,
        "last_error": summary.last_error,
        "last_error_at": summary.last_error_at,
        "sent_count": summary.sent_count,
    }
