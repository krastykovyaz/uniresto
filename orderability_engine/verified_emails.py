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

import hashlib
import hmac
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_emails (
    email TEXT PRIMARY KEY,
    verified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signing_keys (
    name TEXT PRIMARY KEY,
    key TEXT NOT NULL
);
"""

# The identity proof handed to a browser right after it completes a
# send-code/verify-code round trip. "This address was verified once, by
# somebody" is NOT proof that THIS caller owns it -- the address is just
# a string anyone can type -- so every action that acts as an address
# (ordering, courier actions, Luni claims/reads, photo uploads) also has
# to present the token only the verifying browser was ever given.
_TOKEN_KEY_NAME = "identity-token-v1"


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

    def _signing_key(self) -> bytes:
        """Random, created on first use and kept in the same database as
        everything else (so a backup restores tokens together with the
        verified set). Never in .env, never sent to a client."""
        with self._lock:
            row = self._conn.execute("SELECT key FROM signing_keys WHERE name = ?", (_TOKEN_KEY_NAME,)).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO signing_keys (name, key) VALUES (?, ?)", (_TOKEN_KEY_NAME, secrets.token_hex(32))
                )
                self._conn.commit()
                row = self._conn.execute("SELECT key FROM signing_keys WHERE name = ?", (_TOKEN_KEY_NAME,)).fetchone()
        return row[0].encode("ascii")

    @staticmethod
    def _token_subject(email: str) -> bytes:
        return email.strip().lower().encode("utf-8")

    def issue_token(self, email: str) -> str:
        """Deterministic per address: proving the address again (another
        device, a lost localStorage) simply yields the same token, and
        nothing has to be stored per token."""
        return hmac.new(self._signing_key(), self._token_subject(email), hashlib.sha256).hexdigest()

    def token_valid(self, email: str, token: object) -> bool:
        if not isinstance(token, str) or not token:
            return False
        return hmac.compare_digest(self.issue_token(email), token)

    def is_verified(self, email: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM verified_emails WHERE email = ?", (email,)).fetchone()
        return row is not None
