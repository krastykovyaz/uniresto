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


def test_set_photo_returns_none_when_the_dish_had_no_photo_before(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    assert store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/abc.jpg") is None


def test_set_photo_returns_the_previous_path_when_replacing_one(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/old.jpg")
    previous = store.set_photo("altius", "Végétarien", "Salad'bar", "/static/dish_photos/new.jpg")
    assert previous == "/static/dish_photos/old.jpg"


# ---------------------------------------------------------------------------
# The same dish on another restaurant's menu shows the photo too
# ---------------------------------------------------------------------------


def test_a_photo_is_visible_to_the_other_restaurant_for_the_same_dish(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Snack à emporter", "Buddha bowl", "/static/dish_photos/a.jpg")
    assert store.photos_visible_to("brasserie-johns") == {"Snack à emporter": {"Buddha bowl": "/static/dish_photos/a.jpg"}}
    assert store.photos_visible_to("altius") == store.photos_for_restaurant("altius")


def test_the_restaurants_own_photo_wins(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Snack", "Bowl", "/static/dish_photos/altius.jpg")
    store.set_photo("brasserie-johns", "Snack", "Bowl", "/static/dish_photos/johns.jpg")
    assert store.photos_visible_to("brasserie-johns")["Snack"]["Bowl"] == "/static/dish_photos/johns.jpg"
    assert store.photos_visible_to("altius")["Snack"]["Bowl"] == "/static/dish_photos/altius.jpg"


def test_only_the_same_category_and_name_is_shared(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Snack", "Bowl", "/static/dish_photos/a.jpg")
    visible = store.photos_visible_to("brasserie-johns")
    assert "Other" not in visible and visible == {"Snack": {"Bowl": "/static/dish_photos/a.jpg"}}
    assert store.photos_visible_to("nowhere-else").get("Snack", {}).get("Different name") is None


def test_the_newest_other_photo_is_used_when_several_restaurants_have_one(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Snack", "Bowl", "/static/dish_photos/old.jpg")
    store.set_photo("third", "Snack", "Bowl", "/static/dish_photos/new.jpg")
    assert store.photos_visible_to("brasserie-johns")["Snack"]["Bowl"] == "/static/dish_photos/new.jpg"


def test_the_shared_photo_follows_the_source_when_it_is_replaced(tmp_path):
    store = DishPhotoStore(tmp_path / "orders.db")
    store.set_photo("altius", "Snack", "Bowl", "/static/dish_photos/1.jpg")
    store.set_photo("altius", "Snack", "Bowl", "/static/dish_photos/2.jpg")
    assert store.photos_visible_to("brasserie-johns")["Snack"]["Bowl"] == "/static/dish_photos/2.jpg"


# ---------------------------------------------------------------------------
# scripts/attach_dish_photo.py -- the admin attaching a photo directly
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402
import io  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

_spec = importlib.util.spec_from_file_location("attach_dish_photo", Path(__file__).resolve().parent.parent / "scripts" / "attach_dish_photo.py")
attach_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(attach_module)


def _png(colour=(200, 40, 40), size=(64, 48)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


def _webp_with_exif():
    exif = Image.Exif()
    exif[0x010F] = "SnoopPhone"
    exif[0x8825] = {1: "N", 2: (49.0, 30.0, 17.0), 3: "E", 4: (5.0, 56.0, 51.0)}
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 200, 10)).save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_attaching_makes_it_the_dishs_live_photo_at_that_restaurant_and_the_others(tmp_path):
    photo_dir = tmp_path / "photos"
    path = attach_module.attach_dish_photo(_png(), "altius", "Végan", "Potiron farci", tmp_path / "orders.db", photo_dir)
    assert path.startswith("/static/dish_photos/admin-") and path.endswith(".jpg")
    assert (photo_dir / Path(path).name).is_file()
    store = DishPhotoStore(tmp_path / "orders.db")
    assert store.photos_for_restaurant("altius") == {"Végan": {"Potiron farci": path}}
    assert store.photos_visible_to("brasserie-johns") == {"Végan": {"Potiron farci": path}}


def test_the_file_is_a_fresh_jpeg_without_exif(tmp_path):
    photo_dir = tmp_path / "photos"
    path = attach_module.attach_dish_photo(_webp_with_exif(), "altius", "C", "N", tmp_path / "orders.db", photo_dir)
    data = (photo_dir / Path(path).name).read_bytes()
    assert data.startswith(b"\xff\xd8") and b"SnoopPhone" not in data
    assert len(Image.open(io.BytesIO(data)).getexif()) == 0


def test_replacing_deletes_the_previous_file(tmp_path):
    photo_dir = tmp_path / "photos"
    first = attach_module.attach_dish_photo(_png(), "altius", "C", "N", tmp_path / "orders.db", photo_dir)
    second = attach_module.attach_dish_photo(_png((0, 0, 200)), "altius", "C", "N", tmp_path / "orders.db", photo_dir)
    assert first != second
    assert not (photo_dir / Path(first).name).exists() and (photo_dir / Path(second).name).is_file()
    assert DishPhotoStore(tmp_path / "orders.db").photos_for_restaurant("altius")["C"]["N"] == second


def test_a_non_image_is_refused_and_leaves_nothing_behind(tmp_path):
    photo_dir = tmp_path / "photos"
    with pytest.raises(ValueError):
        attach_module.attach_dish_photo(b"<script>alert(1)</script>", "altius", "C", "N", tmp_path / "orders.db", photo_dir)
    assert not photo_dir.exists() or list(photo_dir.iterdir()) == []
    assert DishPhotoStore(tmp_path / "orders.db").photos_for_restaurant("altius") == {}
