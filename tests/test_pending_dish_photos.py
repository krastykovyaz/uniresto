from orderability_engine.pending_dish_photos import PendingDishPhotoStore


def test_get_returns_none_for_unknown_id(tmp_path):
    store = PendingDishPhotoStore(tmp_path / "orders.db")
    assert store.get(1) is None


def test_create_then_get_returns_the_full_row(tmp_path):
    store = PendingDishPhotoStore(tmp_path / "orders.db")
    pending_id = store.create("altius", "Végétarien", "Salad'bar", "/static/dish_photos/pending-abc.jpg")
    entry = store.get(pending_id)
    assert entry["slug"] == "altius"
    assert entry["category"] == "Végétarien"
    assert entry["name"] == "Salad'bar"
    assert entry["photo_path"] == "/static/dish_photos/pending-abc.jpg"
    assert entry["submitted_at"]


def test_create_returns_a_unique_id_each_time(tmp_path):
    store = PendingDishPhotoStore(tmp_path / "orders.db")
    first = store.create("altius", "Végétarien", "A", "/static/dish_photos/a.jpg")
    second = store.create("altius", "Végétarien", "B", "/static/dish_photos/b.jpg")
    assert first != second


def test_all_pending_lists_every_submission_oldest_first(tmp_path):
    store = PendingDishPhotoStore(tmp_path / "orders.db")
    first = store.create("altius", "Végétarien", "A", "/static/dish_photos/a.jpg")
    second = store.create("altius", "Végétarien", "B", "/static/dish_photos/b.jpg")
    entries = store.all_pending()
    assert [e["id"] for e in entries] == [first, second]


def test_delete_removes_the_row(tmp_path):
    store = PendingDishPhotoStore(tmp_path / "orders.db")
    pending_id = store.create("altius", "Végétarien", "Salad'bar", "/static/dish_photos/a.jpg")
    store.delete(pending_id)
    assert store.get(pending_id) is None
    assert store.all_pending() == []


def test_delete_of_unknown_id_does_not_raise(tmp_path):
    store = PendingDishPhotoStore(tmp_path / "orders.db")
    store.delete(999)  # must not raise


def test_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "orders.db"
    pending_id = PendingDishPhotoStore(db_path).create("altius", "Végétarien", "Salad'bar", "/static/dish_photos/a.jpg")
    reopened = PendingDishPhotoStore(db_path)
    assert reopened.get(pending_id)["name"] == "Salad'bar"
