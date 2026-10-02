import json
from unittest.mock import MagicMock

import pytest

from orderability_engine import push_notify
from orderability_engine.push_notify import PUSH_KINDS, PushSubscriptionStore, send_push

EP = "https://push.example.com/abc"


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
        assert store.upsert("a@uni.lu", f"https://push.example.com/{i}", "p", "a", {})
    assert store.upsert("a@uni.lu", "https://push.example.com/extra", "p", "a", {}) is False
    # refreshing one they already have is still fine
    assert store.upsert("a@uni.lu", "https://push.example.com/0", "p", "a", {})


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
    store.upsert("a@uni.lu", "https://push.example.com/second", "p", "a", {})

    class Gone(Exception):
        response = MagicMock(status_code=410)

    def fake(subscription, payload, config):
        if subscription["endpoint"] == EP:
            raise Gone()

    assert send_push(store, "a@uni.lu", "order", "t", "b", webpush_fn=fake) == 1
    assert [s["endpoint"] for s in store.subscriptions_for("a@uni.lu", "order")] == ["https://push.example.com/second"]


def test_other_errors_are_swallowed_and_keep_the_subscription(store, vapid):
    store.upsert("a@uni.lu", EP, "p", "a", {})
    boom = MagicMock(side_effect=RuntimeError("network"))
    assert send_push(store, "a@uni.lu", "order", "t", "b", webpush_fn=boom) == 0
    assert store.count() == 1
