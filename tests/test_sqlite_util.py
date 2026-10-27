from orderability_engine.orders import OrderStore
from orderability_engine.sqlite_util import BUSY_TIMEOUT_SECONDS, connect


def test_a_file_database_is_opened_in_wal_mode_with_a_busy_timeout(tmp_path):
    conn = connect(tmp_path / "x.db")

    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == int(BUSY_TIMEOUT_SECONDS * 1000)


def test_an_in_memory_database_still_opens(tmp_path):
    conn = connect(":memory:")

    assert conn.execute("select 1").fetchone() == (1,)


def test_two_connections_can_read_while_one_is_writing(tmp_path):
    writer, reader = connect(tmp_path / "x.db"), connect(tmp_path / "x.db")
    writer.execute("create table t (v integer)")
    writer.commit()

    writer.execute("insert into t values (1)")  # open write transaction, not committed yet
    assert reader.execute("select count(*) from t").fetchone() == (0,)  # rollback-journal mode would block here
    writer.commit()
    assert reader.execute("select count(*) from t").fetchone() == (1,)


def test_the_order_store_uses_it(tmp_path):
    store = OrderStore(tmp_path / "orders.db")

    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
