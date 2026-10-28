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


# --- tenths of a Luni (a shared link that somebody opened) ---

def test_a_tenth_of_a_luni_is_kept_exactly(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    for i in range(3):
        assert store.award_once("student@uni.lu", f"share_opened:visitor-{i}", 0.1)
    assert store.get_points("student@uni.lu") == 0.3


def test_ten_tenths_make_one_whole_luni_and_it_reads_back_as_an_int(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    for i in range(10):
        store.award_once("student@uni.lu", f"share_opened:v{i}", 0.1)
    assert store.get_points("student@uni.lu") == 1
    assert isinstance(store.get_points("student@uni.lu"), int)


def test_tenths_and_whole_luni_add_up(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.award_once("student@uni.lu", "order_placed:1", 1)
    store.award_once("student@uni.lu", "share_opened:a", 0.1)
    store.award_once("student@uni.lu", "university_email_verified", 3)
    assert store.get_points("student@uni.lu") == 4.1


def test_a_penalty_takes_whole_luni_off_a_fractional_balance_and_stops_at_zero(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.award_once("student@uni.lu", "share_opened:a", 0.1)
    store.award_once("student@uni.lu", "order_placed:1", 1)
    store.award_once("student@uni.lu", "order_not_confirmed:1", -1)
    assert store.get_points("student@uni.lu") == 0.1
    store.award_once("student@uni.lu", "order_not_confirmed:2", -1)
    assert store.get_points("student@uni.lu") == 0


def test_the_same_opener_pays_a_sharer_only_once(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    assert store.award_once("student@uni.lu", "share_opened:a", 0.1) is True
    assert store.award_once("student@uni.lu", "share_opened:a", 0.1) is False
    assert store.get_points("student@uni.lu") == 0.1


def test_a_daily_cap_stops_further_share_awards(tmp_path):
    from datetime import datetime, timedelta, timezone

    store = RewardStore(tmp_path / "orders.db")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    paid = [
        store.award_once_capped("student@uni.lu", f"share_opened:v{i}", 0.1, prefix="share_opened:", cap=0.3, since=since)
        for i in range(5)
    ]
    assert paid == [True, True, True, False, False]
    assert store.get_points("student@uni.lu") == 0.3


def test_the_cap_only_counts_share_awards_and_only_since_the_cutoff(tmp_path):
    from datetime import datetime, timedelta, timezone

    store = RewardStore(tmp_path / "orders.db")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)  # a cutoff after everything so far = a fresh day
    store.award_once("student@uni.lu", "order_placed:1", 1)  # not a share award: never counts against the cap
    assert store.award_once_capped("student@uni.lu", "share_opened:a", 0.1, prefix="share_opened:", cap=0.1, since=past)
    assert not store.award_once_capped("student@uni.lu", "share_opened:b", 0.1, prefix="share_opened:", cap=0.1, since=past)
    # yesterday's share awards do not count against today's cap
    assert store.award_once_capped("student@uni.lu", "share_opened:c", 0.1, prefix="share_opened:", cap=0.1, since=future)


def test_a_database_from_before_tenths_is_upgraded_in_place(tmp_path):
    import sqlite3

    db = tmp_path / "orders.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """CREATE TABLE rewards (email TEXT PRIMARY KEY, points INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
               CREATE TABLE reward_awards (email TEXT NOT NULL, action TEXT NOT NULL, points INTEGER NOT NULL, awarded_at TEXT NOT NULL, PRIMARY KEY (email, action));
               INSERT INTO rewards VALUES ('student@uni.lu', 7, '2026-01-01T00:00:00+00:00');"""
        )
    store = RewardStore(db)
    assert store.get_points("student@uni.lu") == 7
    store.award_once("student@uni.lu", "share_opened:a", 0.1)
    assert store.get_points("student@uni.lu") == 7.1


def test_a_share_code_is_stable_per_person_and_hides_the_address(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    code = store.share_code("Student@uni.lu", "visitor-aaaaaaaaaaaaaaaa")
    assert code == store.share_code("student@uni.lu")
    assert "student" not in code and "@" not in code
    assert store.share_code("other@uni.lu") != code
    assert store.share_owner(code) == ("student@uni.lu", "visitor-aaaaaaaaaaaaaaaa")
    assert store.share_owner("nobody-has-this") is None


def test_a_pending_open_is_handed_out_once(tmp_path):
    store = RewardStore(tmp_path / "orders.db")
    store.remember_share_open("code-a", "visitor-1111111111111")
    store.remember_share_open("code-a", "visitor-1111111111111")  # opened twice: still one
    store.remember_share_open("code-b", "visitor-1111111111111")
    assert store.take_pending_share_opens("visitor-1111111111111") == ["code-a", "code-b"]
    assert store.take_pending_share_opens("visitor-1111111111111") == []


def test_old_pending_opens_are_forgotten(tmp_path):
    import sqlite3

    store = RewardStore(tmp_path / "orders.db")
    with sqlite3.connect(tmp_path / "orders.db") as conn:
        conn.execute("INSERT INTO share_pending VALUES ('visitor-old-00000000', 'code-a', '2020-01-01T00:00:00+00:00')")
    assert store.take_pending_share_opens("visitor-old-00000000") == []
    store.remember_share_open("code-b", "visitor-2222222222222")  # each new open also prunes the old ones
    with sqlite3.connect(tmp_path / "orders.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM share_pending").fetchone()[0] == 1


def _hold_after(monkeypatch, sql_fragment, parties):
    """Makes every connection pause right after running a query containing `sql_fragment` until `parties` callers
    got there too (or 1.5 s passed): the worst interleaving of two workers, every time, instead of by luck."""
    import sqlite3
    import threading

    barrier = threading.Barrier(parties)

    class Pausing(sqlite3.Connection):
        def execute(self, sql, *args):
            cur = super().execute(sql, *args)
            if sql_fragment in sql:
                try:
                    barrier.wait(timeout=1.5)
                except threading.BrokenBarrierError:
                    pass  # the other caller is (correctly) blocked waiting for the write lock
            return cur

    real_connect = sqlite3.connect
    monkeypatch.setattr("orderability_engine.rewards.sqlite3.connect", lambda *a, **k: real_connect(*a, factory=Pausing, **k))


def _run_together(target, n):
    import threading

    threads = [threading.Thread(target=target, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_the_daily_cap_holds_when_two_processes_pay_at_the_same_moment(tmp_path, monkeypatch):
    """Two workers both at 0.9 earned: only one of them may pay the last tenth."""
    from datetime import datetime, timedelta, timezone

    db = tmp_path / "orders.db"
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(9):
        RewardStore(db).award_once_capped("s@uni.lu", f"share_opened:p{i}", 0.1, prefix="share_opened:", cap=1.0, since=since)
    _hold_after(monkeypatch, "SUM(points", 2)
    results = []
    _run_together(lambda n: results.append(
        RewardStore(db).award_once_capped("s@uni.lu", f"share_opened:race{n}", 0.1, prefix="share_opened:", cap=1.0, since=since)), 2)
    monkeypatch.undo()
    assert sorted(results) == [False, True]
    assert RewardStore(db).get_points("s@uni.lu") == 1


def test_a_first_share_code_request_from_two_processes_at_once_gives_one_code(tmp_path, monkeypatch):
    db = tmp_path / "orders.db"
    RewardStore(db)
    _hold_after(monkeypatch, "SELECT code FROM share_refs", 2)
    codes, errors = [], []

    def ask(_):
        try:
            codes.append(RewardStore(db).share_code("s@uni.lu"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    _run_together(ask, 2)
    assert errors == [] and len(codes) == 2 and len(set(codes)) == 1


def test_a_contact_detail_is_paid_once_when_two_processes_claim_it_together(tmp_path, monkeypatch):
    db = tmp_path / "orders.db"
    RewardStore(db)
    _hold_after(monkeypatch, "SELECT 1 FROM reward_awards", 2)
    outcomes = []
    _run_together(lambda n: outcomes.append(RewardStore(db).claim_value("s@uni.lu", "phone_number_added", "+352621000000", 1)), 2)
    monkeypatch.undo()
    assert sorted(outcomes) == sorted([CLAIM_AWARDED, CLAIM_ALREADY_AWARDED])
    assert RewardStore(db).get_points("s@uni.lu") == 1
