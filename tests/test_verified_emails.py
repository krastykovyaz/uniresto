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


def test_an_address_is_the_same_whatever_its_capitalisation(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    store.mark_verified("John.Doe@student.uni.lu")

    assert store.is_verified("john.doe@student.uni.lu") is True
    assert store.is_verified("  JOHN.DOE@STUDENT.UNI.LU ") is True


def test_marking_the_same_address_in_another_case_adds_no_second_row(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    store.mark_verified("Student@uni.lu")
    store.mark_verified("student@uni.lu")

    assert store._conn.execute("select count(*) from verified_emails").fetchone() == (1,)


def test_a_row_stored_before_normalisation_in_mixed_case_still_counts(tmp_path):
    store = VerifiedEmailStore(tmp_path / "orders.db")
    store._conn.execute("insert into verified_emails (email, verified_at) values ('Old.Row@uni.lu', '2026-10-01T00:00:00+00:00')")
    store._conn.commit()

    assert store.is_verified("old.row@uni.lu") is True
    store.mark_verified("old.row@uni.lu")  # must not add a duplicate
    assert store._conn.execute("select count(*) from verified_emails").fetchone() == (1,)
