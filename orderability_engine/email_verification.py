"""SQLite-backed store for email-verification codes (Part 27, moved off
an in-process dict in Part 62).

Originally an in-memory dict, on the reasoning that a code is only ever
meaningful for a few minutes so there's no value in surviving a process
restart. That reasoning missed a real consequence of this app's own
deployment: production runs gunicorn with multiple worker PROCESSES
(see the systemd unit's `-w 2`), each with its OWN Python interpreter
and so its OWN copy of any in-process dict -- nothing shares it between
them. A code issued by whichever worker handled /send-code is invisible
to a later /verify-code request the OS/gunicorn happens to route to a
DIFFERENT worker, which sees no code at all and reports "no_code_requested"
(read by a real user as "that code expired"), even seconds after a
correctly-typed code. Verified live: a real code, confirmed correct by
reading it out of the actual inbox, failed this way within minutes of
being issued.

SQLite (like OrderabilityCache/DeliverySubscriberStore elsewhere in this
package) is one file on disk every worker process opens independently,
so this now behaves the same regardless of which worker handles which
request -- while still expiring/self-cleaning the same way, and every
caller's own contract (issue/verify/seconds_until_resend_allowed)
unchanged. Defaults to an in-memory database (":memory:") when no path
is given, which is private to that one connection -- exactly the old
dict's isolation, useful for tests -- so ONLY the real app.py entry
points need to pass a real file path for this fix to take effect.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

CODE_TTL_SECONDS = 10 * 60  # 10 minutes
RESEND_COOLDOWN_SECONDS = 60  # minimum gap between two sends to the same address
MAX_ATTEMPTS = 5  # wrong-code guesses allowed before the code itself is invalidated

SCHEMA = """
CREATE TABLE IF NOT EXISTS email_verification_codes (
    email TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
"""


class EmailVerificationStore:
    def __init__(
        self,
        db_path: str | Path = ":memory:",
        code_ttl_seconds: int = CODE_TTL_SECONDS,
        resend_cooldown_seconds: int = RESEND_COOLDOWN_SECONDS,
    ):
        self._code_ttl = code_ttl_seconds
        self._resend_cooldown = resend_cooldown_seconds
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EmailVerificationStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def seconds_until_resend_allowed(self, email: str) -> int:
        """0 if a new code can be sent to `email` right now, otherwise
        how many whole seconds the caller must still wait -- a light
        rate limit so this endpoint can't be trivially used to spam an
        arbitrary address with repeated codes."""
        with self._lock:
            row = self._conn.execute("SELECT sent_at FROM email_verification_codes WHERE email = ?", (email,)).fetchone()
        if row is None:
            return 0
        sent_at = datetime.fromisoformat(row[0])
        elapsed = (datetime.now(timezone.utc) - sent_at).total_seconds()
        remaining = self._resend_cooldown - elapsed
        return max(0, round(remaining))

    def issue(self, email: str, code: str) -> None:
        """Records a freshly generated code against `email`, replacing
        any previous one. Generating the code itself and actually
        sending it are the caller's job (app.py / mailer.py) -- this
        method only tracks state, matching mailer.py's own separation
        (generate_verification_code() there is pure, this store is the
        only thing that remembers what was issued)."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._code_ttl)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO email_verification_codes (email, code, expires_at, sent_at, attempts)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(email) DO UPDATE SET code = excluded.code, expires_at = excluded.expires_at,
                    sent_at = excluded.sent_at, attempts = 0
                """,
                (email, code, expires_at.isoformat(), now.isoformat()),
            )
            self._conn.commit()

    def verify(self, email: str, code: str) -> tuple[bool, str | None]:
        """Returns (verified, reason). `reason` is a short CODE, never
        prose (this project's standing rule -- see e.g. pricing.py's own
        `reason` field -- the frontend translates it), one of
        "no_code_requested" / "code_expired" / "too_many_attempts" /
        "incorrect_code", or None on success. A successful verify
        consumes the entry (one-time use); so does hitting the attempt
        limit or an expiry, both of which also clear it so a stale entry
        never lingers to be retried against."""
        with self._lock:
            row = self._conn.execute(
                "SELECT code, expires_at, attempts FROM email_verification_codes WHERE email = ?", (email,)
            ).fetchone()
            if row is None:
                return False, "no_code_requested"
            stored_code, expires_at, attempts = row[0], datetime.fromisoformat(row[1]), row[2]
            if datetime.now(timezone.utc) >= expires_at:
                self._conn.execute("DELETE FROM email_verification_codes WHERE email = ?", (email,))
                self._conn.commit()
                return False, "code_expired"
            if attempts >= MAX_ATTEMPTS:
                self._conn.execute("DELETE FROM email_verification_codes WHERE email = ?", (email,))
                self._conn.commit()
                return False, "too_many_attempts"
            if code != stored_code:
                self._conn.execute(
                    "UPDATE email_verification_codes SET attempts = attempts + 1 WHERE email = ?", (email,)
                )
                self._conn.commit()
                return False, "incorrect_code"
            self._conn.execute("DELETE FROM email_verification_codes WHERE email = ?", (email,))
            self._conn.commit()
            return True, None
