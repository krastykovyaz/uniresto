from orderability_engine.verified_emails import VerifiedEmailStore


def test_is_verified_false_when_never_marked(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    assert store.is_verified("student@uni.lu") is False


def test_mark_verified_then_is_verified_true(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    store.mark_verified("student@uni.lu")
    assert store.is_verified("student@uni.lu") is True


def test_mark_verified_is_idempotent(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    store.mark_verified("student@uni.lu")
    store.mark_verified("student@uni.lu")  # must not raise
    assert store.is_verified("student@uni.lu") is True


def test_is_verified_is_per_address(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    store.mark_verified("a@uni.lu")
    assert store.is_verified("a@uni.lu") is True
    assert store.is_verified("b@uni.lu") is False


def test_survives_a_reopened_store(tmp_path):
    db_path = tmp_path / "orders.db"
    VerifiedEmailStore(db_path).mark_verified("student@uni.lu")
    reopened = VerifiedEmailStore(db_path)
    assert reopened.is_verified("student@uni.lu") is True
