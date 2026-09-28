"""Durable record of "this address has proven it can read mail sent to
it, at least once" (Part 83) -- backs the new requirement that placing
an order needs a verified customer_email, not just a well-formed one.

Deliberately a SEPARATE concept from EmailVerificationStore's own
per-purpose CODE isolation ("a code issued for customer checkout must
never also verify a courier registration" -- see that module's own
delivery-register docstring): that isolation is about a live 6-digit
code not being replayable across purposes, not about the downstream
FACT of whether an address is real. That fact is the same fact no
matter which of the three flows (University email, courier
registration, or checkout itself) first proved it -- forcing a
student to re-verify an address they already proved for one feature,
just because a different feature asks again, would be exactly the
kind of pointless friction this app avoids elsewhere. So this store is
shared: every successful verify-code call, from any of the three
flows, marks the address here, and order creation checks this ONE
place regardless of how the address got proven.

No expiry: once genuinely proven reachable, an address stays proven --
same "verify once, trust it" precedent as the University email and
delivery-subscriber registrations (neither of which re-checks
anything at usage time either), not a fresh security boundary that
needs to keep re-validating.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_emails (
    email TEXT PRIMARY KEY,
    verified_at TEXT NOT NULL
);
"""


class VerifiedEmailStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore by default -- one small extra table in
        # the same SQLite database, not a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "VerifiedEmailStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def mark_verified(self, email: str) -> None:
        """Idempotent -- marking an already-verified address again (e.g.
        proven via a second flow later) is a no-op, not an error, and
        keeps the ORIGINAL verified_at rather than overwriting it."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO verified_emails (email, verified_at) VALUES (?, ?) ON CONFLICT(email) DO NOTHING",
                (email, now),
            )
            self._conn.commit()

    def is_verified(self, email: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM verified_emails WHERE email = ?", (email,)).fetchone()
        return row is not None
