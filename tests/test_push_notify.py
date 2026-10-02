import json
from unittest.mock import MagicMock

import pytest

from orderability_engine import push_notify
from orderability_engine.push_notify import PUSH_KINDS, PushSubscriptionStore, send_push

EP = "https://fcm.googleapis.com/fcm/send/abc"


@pytest.fixture
def store(tmp_path):
    return PushSubscriptionStore(tmp_path / "push.db")


@pytest.fixture
def vapid(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_SUBJECT", "https://resto.example")


def test_prefs_default_on_and_ignore_junk():
    assert push_notify.sanitize_prefs({}) == {k: True for k in PUSH_KINDS}
    prefs = push_notify.sanitize_prefs({"luni": False, "order": "no", "unknown": False})
    assert prefs["luni"] is False and prefs["order"] is True and "unknown" not in prefs
    assert push_notify.sanitize_prefs("junk") == {k: True for k in PUSH_KINDS}


def test_subscription_validation():
    assert push_notify.valid_subscription(EP, "p", "a")
    assert not push_notify.valid_subscription("http://insecure.example/x", "p", "a")
    assert not push_notify.valid_subscription(EP, "", "a")
    assert not push_notify.valid_subscription(EP, "p", "a" * 500)
    assert not push_notify.valid_subscription(None, "p", "a")


def test_subscribe_filters_by_kind_and_person(store):
    store.upsert("Name+tag@uni.lu", EP, "p", "a", {"luni": False})
    # the same person under any spelling of the address
    assert [s["endpoint"] for s in store.subscriptions_for("name@uni.lu", "order")] == [EP]
    assert store.subscriptions_for("name@uni.lu", "luni") == []
    assert store.subscriptions_for("someone@uni.lu", "order") == []


def test_one_device_can_move_to_another_person_but_never_duplicates(store):
    store.upsert("a@uni.lu", EP, "p", "a", {})
    store.upsert("b@uni.lu", EP, "p2", "a2", {})
    assert store.count() == 1
    assert store.subscriptions_for("a@uni.lu", "order") == []
    assert store.subscriptions_for("b@uni.lu", "order")[0]["keys"]["p256dh"] == "p2"


def test_set_prefs_and_remove_only_for_the_owner(store):
    store.upsert("a@uni.lu", EP, "p", "a", {})
    assert store.set_prefs("b@uni.lu", EP, {"order": False}) is False
    assert store.set_prefs("a@uni.lu", EP, {"order": False}) is True
    assert store.subscriptions_for("a@uni.lu", "order") == []
    assert store.remove("b@uni.lu", EP) is False
    assert store.remove("a@uni.lu", EP) is True
    assert store.count() == 0


def test_a_person_is_capped_at_ten_devices(store):
    for i in range(push_notify.MAX_SUBSCRIPTIONS_PER_EMAIL):
        assert store.upsert("a@uni.lu", f"https://fcm.googleapis.com/fcm/send/{i}", "p", "a", {})
    assert store.upsert("a@uni.lu", "https://fcm.googleapis.com/fcm/send/extra", "p", "a", {}) is False
    # refreshing one they already have is still fine
    assert store.upsert("a@uni.lu", "https://fcm.googleapis.com/fcm/send/0", "p", "a", {})


def test_send_push_delivers_the_payload(store, vapid):
    store.upsert("a@uni.lu", EP, "p", "a", {})
    fake = MagicMock()
    assert send_push(store, "a@uni.lu", "order", "Hi", "Body", "/x", "t", webpush_fn=fake) == 1
    sub, payload, config = fake.call_args[0]
    assert sub["endpoint"] == EP and config["subject"] == "https://resto.example"
    assert json.loads(payload) == {"title": "Hi", "body": "Body", "url": "/x", "tag": "t"}


def test_send_push_skips_off_kinds_unknown_kinds_and_missing_keys(store, vapid, monkeypatch):
    store.upsert("a@uni.lu", EP, "p", "a", {"luni": False})
    fake = MagicMock()
    assert send_push(store, "a@uni.lu", "luni", "t", "b", webpush_fn=fake) == 0
    assert send_push(store, "a@uni.lu", "nonsense", "t", "b", webpush_fn=fake) == 0
    monkeypatch.delenv("VAPID_PRIVATE_KEY")
    assert send_push(store, "a@uni.lu", "order", "t", "b", webpush_fn=fake) == 0
    fake.assert_not_called()


def test_a_gone_subscription_is_deleted_and_others_still_get_it(store, vapid):
    store.upsert("a@uni.lu", EP, "p", "a", {})
    store.upsert("a@uni.lu", "https://fcm.googleapis.com/fcm/send/second", "p", "a", {})

    class Gone(Exception):
        response = MagicMock(status_code=410)

    def fake(subscription, payload, config):
        if subscription["endpoint"] == EP:
            raise Gone()

    assert send_push(store, "a@uni.lu", "order", "t", "b", webpush_fn=fake) == 1
    assert [s["endpoint"] for s in store.subscriptions_for("a@uni.lu", "order")] == ["https://fcm.googleapis.com/fcm/send/second"]


def test_other_errors_are_swallowed_and_keep_the_subscription(store, vapid):
    store.upsert("a@uni.lu", EP, "p", "a", {})
    boom = MagicMock(side_effect=RuntimeError("network"))
    assert send_push(store, "a@uni.lu", "order", "t", "b", webpush_fn=boom) == 0
    assert store.count() == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/QGxyz",
        "https://wns2-par02p.notify.windows.com/?token=abc",
        "https://fcm.googleapis.com:443/fcm/send/abc",
    ],
)
def test_real_push_services_are_allowed(endpoint):
    assert push_notify.is_allowed_push_endpoint(endpoint)
    assert push_notify.valid_subscription(endpoint, "p", "a")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",  # not https
        "https://push.example.com/abc",  # not a push service
        "https://evil.com/fcm.googleapis.com",  # allowed name only in the path
        "https://fcm.googleapis.com.evil.com/x",  # allowed name only as a prefix
        "https://notfcm.googleapis.com.example/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/x",
        "https://localhost/x",
        "https://internal-host:8443/x",
        "https://fcm.googleapis.com:8443/x",  # unusual port
        "https://user:pass@fcm.googleapis.com/x",  # credentials in the URL
        "https:///x",
        "ftp://fcm.googleapis.com/x",
        "https://fcm.googleapis.com/" + "a" * 1000,  # too long
        None,
        42,
    ],
)
def test_anything_else_is_refused(endpoint):
    assert not push_notify.is_allowed_push_endpoint(endpoint)
    assert not push_notify.valid_subscription(endpoint, "p", "a")


def test_a_stored_endpoint_that_is_not_a_push_service_is_dropped_never_posted_to(store, vapid):
    store.upsert("a@uni.lu", "https://169.254.169.254/latest/meta-data", "p", "a", {})  # bypasses the route's check
    fake = MagicMock()
    assert send_push(store, "a@uni.lu", "order", "t", "b", webpush_fn=fake) == 0
    fake.assert_not_called()
    assert store.count() == 0


def test_the_real_sender_never_follows_a_redirect(monkeypatch):
    import requests

    seen = {}

    def fake_request(self, method, url, **kwargs):
        seen["allow_redirects"] = kwargs.get("allow_redirects")
        raise RuntimeError("stop before any network")

    monkeypatch.setattr(requests.Session, "request", fake_request)
    with pytest.raises(Exception):
        push_notify._no_redirect_session().post("https://fcm.googleapis.com/x", data="y", allow_redirects=True)
    assert seen["allow_redirects"] is False


def test_notify_in_background_uses_a_bounded_pool(monkeypatch, vapid):
    import threading

    calls, threads = [], set()

    def fake_send(*args):
        threads.add(threading.current_thread().name)
        calls.append(args)

    monkeypatch.setattr(push_notify, "send_push", fake_send)
    store = object()
    for i in range(50):
        push_notify.notify_in_background(store, f"p{i}@uni.lu", "order", "t", "b")
    push_notify.wait_for_pending_pushes()
    assert len(calls) == 50
    assert len(threads) <= push_notify.POOL_WORKERS  # 50 sends, never more than the pool's few threads


def test_notify_in_background_does_nothing_without_vapid_keys(monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(push_notify, "send_push", MagicMock(side_effect=AssertionError("must not run")))
    push_notify.notify_in_background(object(), "a@uni.lu", "order", "t", "b")
    push_notify.wait_for_pending_pushes()


def test_a_full_queue_drops_instead_of_piling_up(monkeypatch, vapid):
    import threading

    release = threading.Event()
    ran = []
    monkeypatch.setattr(push_notify, "send_push", lambda *a: (release.wait(5), ran.append(a)))
    monkeypatch.setattr(push_notify, "MAX_PENDING", 3)
    for i in range(10):
        push_notify.notify_in_background(object(), f"p{i}@uni.lu", "order", "t", "b")
    release.set()
    push_notify.wait_for_pending_pushes()
    assert len(ran) == 3
