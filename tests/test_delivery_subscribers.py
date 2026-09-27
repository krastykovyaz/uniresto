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
