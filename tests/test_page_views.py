from datetime import datetime, timedelta, timezone

import pytest

from orderability_engine.page_views import PageViewStore


def test_count_between_zero_when_nothing_recorded(tmp_path):
    store = PageViewStore(tmp_path / "views.db")
    now = datetime.now(timezone.utc)
    assert store.count_between("home", now - timedelta(days=1), now + timedelta(days=1)) == 0


def test_record_and_count_between(tmp_path):
    store = PageViewStore(tmp_path / "views.db")
    store.record("home")
    store.record("home")
    store.record("menu")
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(minutes=1), now + timedelta(minutes=1)
    assert store.count_between("home", start, end) == 2
    assert store.count_between("menu", start, end) == 1
    assert store.count_between("delivery", start, end) == 0


def test_count_between_excludes_events_outside_the_window(tmp_path):
    store = PageViewStore(tmp_path / "views.db")
    store.record("home")
    now = datetime.now(timezone.utc)
    # A window that ends before the event happened must not count it.
    assert store.count_between("home", now - timedelta(days=2), now - timedelta(days=1)) == 0


def test_record_rejects_an_unknown_event(tmp_path):
    store = PageViewStore(tmp_path / "views.db")
    with pytest.raises(ValueError):
        store.record("not_a_real_event")


def test_count_between_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "views.db"
    PageViewStore(db_path).record("delivery")
    reopened = PageViewStore(db_path)
    now = datetime.now(timezone.utc)
    assert reopened.count_between("delivery", now - timedelta(minutes=1), now + timedelta(minutes=1)) == 1
