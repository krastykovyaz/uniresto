from orderability_engine.rewards import CLAIM_ALREADY_AWARDED, CLAIM_AWARDED, CLAIM_VALUE_ALREADY_USED, RewardStore


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


def test_award_once_pays_out_and_returns_true(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    paid = store.award_once("student@uni.lu", "university_email_verified", 3)
    assert paid is True
    assert store.get_points("student@uni.lu") == 3


def test_award_once_is_a_no_op_the_second_time(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.award_once("student@uni.lu", "university_email_verified", 3)
    paid_again = store.award_once("student@uni.lu", "university_email_verified", 3)
    assert paid_again is False
    assert store.get_points("student@uni.lu") == 3


def test_award_once_with_a_different_action_pays_again(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.award_once("student@uni.lu", "phone_number_added", 1)
    paid = store.award_once("student@uni.lu", "communication_email_added", 1)
    assert paid is True
    assert store.get_points("student@uni.lu") == 2


def test_award_once_with_a_repeatable_action_key_pays_per_distinct_id(tmp_path):
    # Repeatable actions (an order, a delivery, an approved photo) fold
    # the specific id into the action string -- ORDER 1 and ORDER 2 each
    # pay out once, independently.
    store = RewardStore(tmp_path / "orders.db")
    store.award_once("student@uni.lu", "order_placed:1", 1)
    store.award_once("student@uni.lu", "order_placed:2", 1)
    repeat = store.award_once("student@uni.lu", "order_placed:1", 1)
    assert repeat is False
    assert store.get_points("student@uni.lu") == 2


def test_award_once_is_scoped_per_email(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.award_once("a@uni.lu", "phone_number_added", 1)
    assert store.get_points("b@uni.lu") == 0
    paid = store.award_once("b@uni.lu", "phone_number_added", 1)
    assert paid is True


def test_balances_read_and_write_through_the_canonical_identity(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.add_points("Name+1@uni.lu", 4)
    assert store.get_points("name@uni.lu") == 4
    assert store.award_once("NAME@uni.lu", "x", 2) is True
    assert store.award_once("name+2@uni.lu", "x", 2) is False


def test_claim_value_pays_once_per_identity_and_once_per_value(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    assert store.claim_value("a@uni.lu", "phone_number_added", "621123456", 1) == CLAIM_AWARDED
    assert store.claim_value("a@uni.lu", "phone_number_added", "621123456", 1) == CLAIM_ALREADY_AWARDED
    assert store.claim_value("b@uni.lu", "phone_number_added", "621123456", 1) == CLAIM_VALUE_ALREADY_USED
    assert store.get_points("a@uni.lu") == 1
    assert store.get_points("b@uni.lu") == 0


def test_the_same_value_can_earn_under_a_different_action(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.claim_value("a@uni.lu", "phone_number_added", "x", 1)
    assert store.claim_value("b@uni.lu", "communication_email_added", "x", 1) == CLAIM_AWARDED


def test_a_refused_value_leaves_no_trace(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.claim_value("a@uni.lu", "phone_number_added", "621123456", 1)
    store.claim_value("b@uni.lu", "phone_number_added", "621123456", 1)
    assert store.claim_value("b@uni.lu", "phone_number_added", "691999888", 1) == CLAIM_AWARDED
