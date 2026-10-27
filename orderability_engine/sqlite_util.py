"""One way to open the app's long-lived SQLite connections.

Two gunicorn workers share every database file. In SQLite's default rollback-journal mode a write blocks the other
worker's readers until it commits, and a wait longer than the busy timeout surfaces as "database is locked" (a 500).
So every file-backed store is opened with a 10 s busy timeout and in WAL mode (readers never wait for the writer; the
mode is stored in the file, so it only has to be switched once). `sqlite3 .backup` (scripts/backup_db.sh) is WAL-safe.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("uniresto.sqlite")

BUSY_TIMEOUT_SECONDS = 10.0


def connect(db_path: str | Path, check_same_thread: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread, timeout=BUSY_TIMEOUT_SECONDS)
    if str(db_path) != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            # The other worker is mid-write while this one starts; the mode is set by whoever gets in next, and
            # the busy timeout above already protects every statement.
            logger.warning("could not switch %s to WAL mode just now", db_path, exc_info=True)
    return conn
