from unittest.mock import patch

from orderability_engine.delivery_subscribers import DeliverySubscriberStore


def test_migrate_survives_another_worker_adding_the_column_first(tmp_path):
    # Two gunicorn workers boot together: both read the columns as missing,
    # one adds them, the other's ALTER then hits "duplicate column name".
    # Simulated by making this store's column check stale.
    db = tmp_path / "subs.db"
    DeliverySubscriberStore(db)  # "the other worker"
    with patch.object(DeliverySubscriberStore, "_existing_columns", return_value=set()):
        store = DeliverySubscriberStore(db)  # must not raise
    assert "lang" in store._existing_columns()


def test_campus_defaults_to_all_and_filters_the_notification_list(tmp_path):
    store = DeliverySubscriberStore(tmp_path / "subs.db")
    store.add("everywhere@uni.lu", "en")
    store.add("kb@uni.lu", "fr", "kirchberg")
    store.add("bv@uni.lu", "de", "belval")
    assert store.get_campus("everywhere@uni.lu") == "all"
    assert [e for e, _ in store.list_subscribers()] == ["everywhere@uni.lu", "kb@uni.lu", "bv@uni.lu"]
    assert [e for e, _ in store.list_subscribers("kirchberg")] == ["everywhere@uni.lu", "kb@uni.lu"]
    assert [e for e, _ in store.list_subscribers("belval")] == ["everywhere@uni.lu", "bv@uni.lu"]


def test_registering_again_without_a_campus_keeps_the_earlier_choice(tmp_path):
    store = DeliverySubscriberStore(tmp_path / "subs.db")
    store.add("bv@uni.lu", "en", "belval")
    store.add("bv@uni.lu", "fr")  # a new device, language changed, no campus given
    assert store.get_campus("bv@uni.lu") == "belval"
    store.add("bv@uni.lu", "fr", "nonsense")  # unknown value is ignored, not stored
    assert store.get_campus("bv@uni.lu") == "belval"


def test_set_campus_rejects_unknown_values_and_unregistered_addresses(tmp_path):
    store = DeliverySubscriberStore(tmp_path / "subs.db")
    store.add("a@uni.lu", "en")
    assert store.set_campus("a@uni.lu", "belval") is True
    assert store.set_campus("a@uni.lu", "mars") is False
    assert store.set_campus("nobody@uni.lu", "belval") is False
    assert store.get_campus("a@uni.lu") == "belval"


def test_a_database_from_before_campuses_gets_everyone_as_all(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE delivery_subscribers (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, lang TEXT NOT NULL DEFAULT 'en')")
    conn.execute("INSERT INTO delivery_subscribers (email, created_at) VALUES ('old@uni.lu', '2026-10-01')")
    conn.commit()
    conn.close()
    store = DeliverySubscriberStore(db)
    assert store.get_campus("old@uni.lu") == "all"
    assert [e for e, _ in store.list_subscribers("belval")] == ["old@uni.lu"]
