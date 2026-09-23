"""In-memory store for email-verification codes (Part 27).

Deliberately NOT SQLite, unlike the menu cache (Part 22) or the
orderability-status cache: a code is only ever meaningful for a few
minutes, and a server restart mid-verification just means the user taps
"Send code" again -- there's no value in this surviving a restart the
way genuinely long-lived data does.

Thread-safe for the same reason OrderabilityCache is (see its own
docstring): Flask's dev server can dispatch requests concurrently, and
two people (or one impatient double-tap) requesting/verifying codes at
once must not corrupt each other's state.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

CODE_TTL_SECONDS = 10 * 60  # 10 minutes
RESEND_COOLDOWN_SECONDS = 60  # minimum gap between two sends to the same address
MAX_ATTEMPTS = 5  # wrong-code guesses allowed before the code itself is invalidated


class EmailVerificationStore:
    def __init__(self, code_ttl_seconds: int = CODE_TTL_SECONDS, resend_cooldown_seconds: int = RESEND_COOLDOWN_SECONDS):
        self._code_ttl = code_ttl_seconds
        self._resend_cooldown = resend_cooldown_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}  # email -> {"code", "expires_at", "sent_at", "attempts"}

    def seconds_until_resend_allowed(self, email: str) -> int:
        """0 if a new code can be sent to `email` right now, otherwise
        how many whole seconds the caller must still wait -- a light,
        in-memory-only rate limit so this endpoint can't be trivially
        used to spam an arbitrary uni.lu address with repeated codes."""
        with self._lock:
            entry = self._entries.get(email)
            if entry is None:
                return 0
            elapsed = (datetime.now(timezone.utc) - entry["sent_at"]).total_seconds()
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
        with self._lock:
            self._entries[email] = {
                "code": code,
                "expires_at": now + timedelta(seconds=self._code_ttl),
                "sent_at": now,
                "attempts": 0,
            }

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
            entry = self._entries.get(email)
            if entry is None:
                return False, "no_code_requested"
            if datetime.now(timezone.utc) >= entry["expires_at"]:
                del self._entries[email]
                return False, "code_expired"
            if entry["attempts"] >= MAX_ATTEMPTS:
                del self._entries[email]
                return False, "too_many_attempts"
            if code != entry["code"]:
                entry["attempts"] += 1
                return False, "incorrect_code"
            del self._entries[email]
            return True, None
