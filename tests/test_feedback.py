from orderability_engine.feedback import FeedbackStore


def test_list_recent_empty_when_nothing_recorded(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.db")
    assert store.list_recent() == []


def test_record_and_list_recent(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.db")
    store.record("Please add Belval restaurants", "student@uni.lu")
    entries = store.list_recent()
    assert len(entries) == 1
    assert entries[0]["message"] == "Please add Belval restaurants"
    assert entries[0]["contact_email"] == "student@uni.lu"
    assert entries[0]["created_at"]


def test_contact_email_is_optional(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.db")
    store.record("Love the app", None)
    assert store.list_recent()[0]["contact_email"] is None


def test_list_recent_is_newest_first(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.db")
    store.record("first", None)
    store.record("second", None)
    entries = store.list_recent()
    assert [e["message"] for e in entries] == ["second", "first"]


def test_list_recent_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "feedback.db"
    FeedbackStore(db_path).record("persisted", None)
    reopened = FeedbackStore(db_path)
    assert reopened.list_recent()[0]["message"] == "persisted"
