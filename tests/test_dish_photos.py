from orderability_engine.dish_photos import DishPhotoStore


def test_photos_for_restaurant_is_empty_when_nothing_stored(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    assert store.photos_for_restaurant("altius") == {}


def test_set_photo_then_photos_for_restaurant_returns_it(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/abc.jpg")
    assert store.photos_for_restaurant("altius") == {"Végétarien": {"Salad'bar": "/static/dish_photos/abc.jpg"}}


def test_set_photo_twice_replaces_the_path(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/old.jpg")
    store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/new.jpg")
    assert store.photos_for_restaurant("altius") == {"Végétarien": {"Salad'bar": "/static/dish_photos/new.jpg"}}


def test_photos_are_scoped_per_restaurant(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/altius.jpg")
    assert store.photos_for_restaurant("other-restaurant") == {}


def test_photos_are_grouped_by_category(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Végétarien", "Riz sauté", "/static/dish_photos/rice.jpg")
    store.set_photo("altius", "Végan", "Riz sauté au tofu", "/static/dish_photos/tofu.jpg")
    photos = store.photos_for_restaurant("altius")
    assert photos == {
        "Végétarien": {"Riz sauté": "/static/dish_photos/rice.jpg"},
        "Végan": {"Riz sauté au tofu": "/static/dish_photos/tofu.jpg"},
    }


def test_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "orders.db"
    DishPhotoStore(db_path).set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/abc.jpg")
    reopened = DishPhotoStore(db_path)
    assert reopened.photos_for_restaurant("altius") == {"Végétarien": {"Salad'bar": "/static/dish_photos/abc.jpg"}}
