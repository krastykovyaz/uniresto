from orderability_engine.coming_soon_clicks import ComingSoonClickStore


def test_counts_empty_when_nothing_recorded(tmp_path):
    store = ComingSoonClickStore(tmp_path / "clicks.db")
    assert store.counts() == []


def test_record_increments_the_right_location(tmp_path):
    store = ComingSoonClickStore(tmp_path / "clicks.db")
    store.record("Food House")
    store.record("Food House")
    store.record("Food Café")
    assert store.counts() == [("Food House", 2), ("Food Café", 1)]


def test_every_click_recorded_not_deduplicated(tmp_path):
    # No account/session to dedupe by -- a raw interest count, not
    # unique visitors (see the module's own docstring).
    store = ComingSoonClickStore(tmp_path / "clicks.db")
    for _ in range(5):
        store.record("Food Lab")
    assert store.counts() == [("Food Lab", 5)]


def test_counts_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "clicks.db"
    ComingSoonClickStore(db_path).record("Food Zone")
    reopened = ComingSoonClickStore(db_path)
    assert reopened.counts() == [("Food Zone", 1)]
