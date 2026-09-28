from orderability_engine.rewards import RewardStore


def test_get_points_is_zero_for_an_unknown_email(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    assert store.get_points("student@uni.lu") == 0


def test_add_points_creates_the_row_starting_from_zero(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    total = store.add_points("student@uni.lu", 10)
    assert total == 10
    assert store.get_points("student@uni.lu") == 10


def test_add_points_accumulates(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.add_points("student@uni.lu", 10)
    total = store.add_points("student@uni.lu", 5)
    assert total == 15
    assert store.get_points("student@uni.lu") == 15


def test_add_points_can_go_negative_delta(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.add_points("student@uni.lu", 10)
    total = store.add_points("student@uni.lu", -3)
    assert total == 7


def test_points_are_scoped_per_email(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.add_points("a@uni.lu", 10)
    assert store.get_points("b@uni.lu") == 0


def test_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "orders.db"
    RewardStore(db_path).add_points("student@uni.lu", 10)
    reopened = RewardStore(db_path)
    assert reopened.get_points("student@uni.lu") == 10
