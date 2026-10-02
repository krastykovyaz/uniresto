"""Web push notifications (Profile > Notifications): which device gets what.

A device subscribes from the Notifications screen with a push subscription
(an endpoint the browser's push service gave it, plus two keys) and the kinds
it wants, under the verified email of the person using it. When something
happens to that person -- their order's status changes, a courier takes it,
they earn Luni -- app.py asks `notify()` to push it to every device they have
subscribed whose switch for that kind is on.

Nothing here can fail a request: a send is a fire-and-forget background thread,
errors are logged, and a subscription the push service says is gone (404/410)
is deleted so it isn't tried again. Without VAPID keys in the environment the
whole feature is simply off (`push_config()` is None, sends do nothing).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from orderability_engine.identity import canonical_identity

log = logging.getLogger("uniresto.push")

# The kinds a person can switch on or off; must match NOTIFICATION_EVENTS in
# static/notifications.js.
PUSH_KINDS = ("order", "courier", "newDelivery", "reminder", "luni", "favorite")

# The push services browsers actually use. A subscription's endpoint is a URL OUR SERVER posts
# to, so anything else would let a (verified) person aim the server at an arbitrary host --
# internal addresses included. Matched as the host itself or any subdomain of it.
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge, Brave, Opera, Android
    "updates.push.services.mozilla.com",  # Firefox
    "push.services.mozilla.com",
    "push.apple.com",  # Safari and the iPhone Home Screen app (web.push.apple.com)
    "notify.windows.com",  # legacy Edge / Windows
)

MAX_ENDPOINT_LENGTH = 1000
MAX_KEY_LENGTH = 200
MAX_SUBSCRIPTIONS_PER_EMAIL = 10  # phone + laptop + a few browsers; stops one account filling the table

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    prefs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS push_subscriptions_email ON push_subscriptions (email);
"""


def sanitize_prefs(prefs) -> dict[str, bool]:
    """Only the known kinds, only real booleans; anything missing is on."""
    prefs = prefs if isinstance(prefs, dict) else {}
    return {kind: prefs[kind] if isinstance(prefs.get(kind), bool) else True for kind in PUSH_KINDS}


def is_allowed_push_endpoint(endpoint) -> bool:
    """https only, on the default port, no credentials in the URL, and a host that is (a
    subdomain of) a known push service -- never an IP address."""
    if not isinstance(endpoint, str) or len(endpoint) > MAX_ENDPOINT_LENGTH:
        return False
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443) or not host:
        return False
    try:
        ipaddress.ip_address(host)
        return False  # an IP literal is never a push service
    except ValueError:
        pass
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_PUSH_HOSTS)


def valid_subscription(endpoint, p256dh, auth) -> bool:
    return (
        is_allowed_push_endpoint(endpoint)
        and isinstance(p256dh, str)
        and 0 < len(p256dh) <= MAX_KEY_LENGTH
        and isinstance(auth, str)
        and 0 < len(auth) <= MAX_KEY_LENGTH
    )


class PushSubscriptionStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self.db_path = str(db_path)
        self._shared = sqlite3.connect(":memory:") if self.db_path == ":memory:" else None
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One transaction per `with` block, with the connection closed afterwards."""
        if self._shared is not None:
            with self._shared:
                yield self._shared
            return
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def upsert(self, email: str, endpoint: str, p256dh: str, auth: str, prefs: dict) -> bool:
        """Subscribes this device for `email` (or moves/refreshes it). False if that
        person already has MAX_SUBSCRIPTIONS_PER_EMAIL other devices."""
        email = canonical_identity(email)
        with self._connect() as conn:
            others = conn.execute(
                "SELECT COUNT(*) FROM push_subscriptions WHERE email = ? AND endpoint != ?", (email, endpoint)
            ).fetchone()[0]
            if others >= MAX_SUBSCRIPTIONS_PER_EMAIL:
                return False
            conn.execute(
                """
                INSERT INTO push_subscriptions (endpoint, email, p256dh, auth, prefs_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET email = excluded.email, p256dh = excluded.p256dh,
                    auth = excluded.auth, prefs_json = excluded.prefs_json
                """,
                (endpoint, email, p256dh, auth, json.dumps(sanitize_prefs(prefs)), datetime.now(timezone.utc).isoformat()),
            )
        return True

    def set_prefs(self, email: str, endpoint: str, prefs: dict) -> bool:
        """Changes the switches of a device that belongs to `email`. False if it isn't theirs."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE push_subscriptions SET prefs_json = ? WHERE endpoint = ? AND email = ?",
                (json.dumps(sanitize_prefs(prefs)), endpoint, canonical_identity(email)),
            )
            return cur.rowcount > 0

    def remove(self, email: str, endpoint: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ? AND email = ?", (endpoint, canonical_identity(email))
            )
            return cur.rowcount > 0

    def delete_endpoint(self, endpoint: str) -> None:
        """For a subscription the push service reported gone."""
        with self._connect() as conn:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    def subscriptions_for(self, email: str, kind: str) -> list[dict]:
        """This person's devices whose switch for `kind` is on."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT endpoint, p256dh, auth, prefs_json FROM push_subscriptions WHERE email = ?",
                (canonical_identity(email),),
            ).fetchall()
        result = []
        for endpoint, p256dh, auth, prefs_json in rows:
            try:
                prefs = sanitize_prefs(json.loads(prefs_json))
            except ValueError:
                prefs = sanitize_prefs({})
            if prefs.get(kind, False):
                result.append({"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}})
        return result

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]


def push_config() -> dict | None:
    """The VAPID key pair from the environment, or None when push isn't set up."""
    private, public = os.environ.get("VAPID_PRIVATE_KEY", "").strip(), os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not private or not public:
        return None
    return {"private": private, "public": public, "subject": os.environ.get("VAPID_SUBJECT", "").strip() or "https://resto.unilu.space"}


def _no_redirect_session():
    """A requests session that never follows a redirect: the push service answers directly,
    and a redirect would be another way to steer the server to an arbitrary host."""
    import requests

    class _Session(requests.Session):
        def request(self, *args, **kwargs):
            kwargs["allow_redirects"] = False
            return super().request(*args, **kwargs)

    return _Session()


def _webpush(subscription: dict, payload: str, config: dict):
    """The real send, isolated so tests can replace it."""
    from pywebpush import webpush

    return webpush(
        subscription_info=subscription,
        data=payload,
        vapid_private_key=config["private"],
        vapid_claims={"sub": config["subject"]},
        timeout=10,
        ttl=3600,
        requests_session=_no_redirect_session(),
    )


def send_push(
    store: PushSubscriptionStore,
    email: str,
    kind: str,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
    *,
    webpush_fn: Callable = _webpush,
) -> int:
    """Pushes one notification to every device of `email` that wants `kind`.
    Returns how many were accepted by the push service. Never raises."""
    config = push_config()
    if config is None or kind not in PUSH_KINDS:
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, **({"tag": tag} if tag else {})})
    sent = 0
    for subscription in store.subscriptions_for(email, kind):
        if not is_allowed_push_endpoint(subscription["endpoint"]):
            # Stored before the allow-list existed, or written to the database directly: never post to it.
            store.delete_endpoint(subscription["endpoint"])
            log.warning("[PUSH] dropped a subscription whose endpoint is not a known push service")
            continue
        try:
            webpush_fn(subscription, payload, config)
            sent += 1
        except Exception as exc:  # noqa: BLE001 -- a bad subscription must not stop the others or fail the caller
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                store.delete_endpoint(subscription["endpoint"])
                log.info("[PUSH] dropped a subscription the push service says is gone (%s)", status)
            else:
                log.warning("[PUSH] send failed (%s): %s", status, exc)
    return sent


# One small pool per worker process instead of a thread per notification: a burst (many orders
# expiring at 13:30, a new order for every registered courier) used to start that many threads,
# each able to wait 10 s per device. Beyond MAX_PENDING queued sends, new ones are dropped and logged
# rather than piling up without limit.
POOL_WORKERS = 4
MAX_PENDING = 500
_pool_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None
_pending = 0


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=POOL_WORKERS, thread_name_prefix="push")
        return _pool


def _run_one(args: tuple) -> None:
    global _pending
    try:
        send_push(*args)
    except Exception:  # noqa: BLE001 -- send_push never raises, but a pool task must never die silently either
        log.warning("[PUSH] a queued send failed unexpectedly", exc_info=True)
    finally:
        with _pool_lock:
            _pending -= 1


def wait_for_pending_pushes() -> None:
    """Blocks until every queued send has finished (used by tests, and by a clean shutdown)."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=True)


def notify_in_background(store: PushSubscriptionStore, email: str, kind: str, title: str, body: str, url: str = "/", tag: str | None = None) -> None:
    """The app's real sender: send_push() on a small worker pool, so an order, a claim or a
    delivery never waits on a push service."""
    global _pending
    if push_config() is None:
        return
    with _pool_lock:
        if _pending >= MAX_PENDING:
            log.warning("[PUSH] queue full (%s waiting) -- dropping a %s push", _pending, kind)
            return
        _pending += 1
    _get_pool().submit(_run_one, (store, email, kind, title, body, url, tag))
