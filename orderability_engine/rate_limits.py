"""Per-client rate limits for the ungated endpoints that fan out into a
notification or a stats counter (Part 77): order creation (admin
Telegram + courier emails + an email to whatever address was typed),
feedback (admin Telegram), claim/release/mark-delivered (admin Telegram,
customer email), and the page-view beacons (the admin's evening report).
This app deliberately has no accounts (see delivery_subscribers.py's own
docstring), so these routes stay open -- this only caps how hard one
client can lean on them.

Stored in SQLite, not in memory, for the same reason as
email_verification.py: gunicorn runs 2 worker PROCESSES, and a per-process
counter would give every client double the limit, split unpredictably
depending on which worker happened to serve each request. A fixed window
per (key, window) row; the INSERT ... ON CONFLICT and the read-back run
inside ONE transaction, so two processes can't both slip under the limit.

Keyed by request.remote_addr, which is the real client IP here: nginx
appends it via $proxy_add_x_forwarded_for and app.py's ProxyFix(x_for=1)
trusts only that last hop, so a client-sent X-Forwarded-For can't spoof it.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (key, window_start)
);
"""

# Rows older than this are purged on every hit -- comfortably longer than
# any window app.py uses, so a live window is never deleted under it.
_RETENTION_SECONDS = 2 * 24 * 3600


class RateLimitStore:
    def __init__(self, db_path: str | Path = "orders.db", clock: Callable[[], float] = time.time):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._clock = clock
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RateLimitStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Counts one request against `key`'s current window. Returns
        (allowed, retry_after_seconds) -- allowed while this window's
        count is still <= `limit`."""
        now = int(self._clock())
        window_start = now - now % window_seconds
        with self._lock:
            try:
                self._conn.execute("DELETE FROM rate_limits WHERE window_start < ?", (now - _RETENTION_SECONDS,))
                self._conn.execute(
                    "INSERT INTO rate_limits (key, window_start, count) VALUES (?, ?, 1) "
                    "ON CONFLICT(key, window_start) DO UPDATE SET count = count + 1",
                    (key, window_start),
                )
                count = self._conn.execute(
                    "SELECT count FROM rate_limits WHERE key = ? AND window_start = ?", (key, window_start)
                ).fetchone()[0]
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return count <= limit, window_start + window_seconds - now
