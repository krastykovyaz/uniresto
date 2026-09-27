from orderability_engine.rate_limits import RateLimitStore


class FakeClock:
    def __init__(self, t=60 * 20_000):  # aligned to a 60s window boundary
        self.t = t

    def __call__(self):
        return self.t


def test_allows_up_to_the_limit_then_blocks(tmp_path):
    store = RateLimitStore(tmp_path / "rl.db", clock=FakeClock())
    results = [store.hit("k", limit=3, window_seconds=60)[0] for _ in range(4)]
    assert results == [True, True, True, False]


def test_reports_seconds_until_the_window_resets(tmp_path):
    clock = FakeClock(t=60 * 20_000 + 20)  # exactly 20s into a 60s window
    store = RateLimitStore(tmp_path / "rl.db", clock=clock)
    store.hit("k", 1, 60)
    allowed, retry_after = store.hit("k", 1, 60)
    assert allowed is False
    assert retry_after == 40


def test_a_new_window_starts_fresh(tmp_path):
    clock = FakeClock()
    store = RateLimitStore(tmp_path / "rl.db", clock=clock)
    store.hit("k", 1, 60)
    assert store.hit("k", 1, 60)[0] is False
    clock.t += 60
    assert store.hit("k", 1, 60)[0] is True


def test_keys_are_independent(tmp_path):
    store = RateLimitStore(tmp_path / "rl.db", clock=FakeClock())
    store.hit("a", 1, 60)
    assert store.hit("a", 1, 60)[0] is False
    assert store.hit("b", 1, 60)[0] is True


def test_limit_is_shared_across_store_instances(tmp_path):
    # Two gunicorn worker processes each construct their own store against
    # the same file -- the whole reason this isn't an in-memory counter.
    clock = FakeClock()
    worker_a = RateLimitStore(tmp_path / "rl.db", clock=clock)
    worker_b = RateLimitStore(tmp_path / "rl.db", clock=clock)
    assert worker_a.hit("k", 2, 60)[0] is True
    assert worker_b.hit("k", 2, 60)[0] is True
    assert worker_a.hit("k", 2, 60)[0] is False
    assert worker_b.hit("k", 2, 60)[0] is False


def test_old_windows_are_purged(tmp_path):
    clock = FakeClock()
    store = RateLimitStore(tmp_path / "rl.db", clock=clock)
    store.hit("old", 5, 60)
    clock.t += 3 * 24 * 3600
    store.hit("new", 5, 60)
    rows = store._conn.execute("SELECT key FROM rate_limits").fetchall()
    assert rows == [("new",)]
