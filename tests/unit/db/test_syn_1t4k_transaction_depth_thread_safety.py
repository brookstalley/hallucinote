"""SYN-1T4K: `_TRANSACTION_DEPTH` must not interleave across threads.

The reentrant `transaction()` helper tracks SAVEPOINT depth keyed by
`id(conn)`. When the backing store was a plain module-level dict, two
threads driving transactions concurrently shared one counter — a worker
thread opening a transaction would bump the depth another thread then
read, corrupting the BEGIN/SAVEPOINT bookkeeping. The fix backs the map
with `threading.local`, so each thread sees only its own depth.

These tests pin:
  1. Single-threaded behavior is byte-identical (the legacy contract in
     `test_transaction_nesting.py` still reads `.get(id(conn), 0)`).
  2. Two threads each running their own transaction on their own
     connection never see the other thread's depth bleed in.
"""
from __future__ import annotations

import threading

import pytest

from hallucinote.db import init_db
from hallucinote.db.connection import _TRANSACTION_DEPTH, transaction


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "txn_threadsafe.db")
    c.execute("CREATE TABLE IF NOT EXISTS tx_scratch (v INTEGER NOT NULL)")
    yield c
    c.close()


def test_single_thread_depth_unchanged(conn):
    """The legacy `.get(id(conn), 0)` contract still holds single-threaded."""
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0
    with transaction(conn):
        # Inside the outer block the calling thread's depth is 1.
        assert _TRANSACTION_DEPTH.get(id(conn), 0) == 1
        with transaction(conn):
            assert _TRANSACTION_DEPTH.get(id(conn), 0) == 2
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0


def test_depth_is_per_thread(tmp_path):
    """A worker thread's open transaction must not be visible to the main
    thread's depth view (and vice versa).

    The worker opens its OWN connection in-thread (SQLite forbids sharing a
    connection across threads), then publishes its `id` so the main thread
    can read the per-thread depth map for that key without touching the
    connection itself.
    """
    in_txn = threading.Event()
    release = threading.Event()
    worker_conn_id: list[int] = []
    error: list[BaseException] = []

    def worker() -> None:
        worker_conn = init_db(tmp_path / "worker.db")
        worker_conn.execute(
            "CREATE TABLE IF NOT EXISTS tx_scratch (v INTEGER NOT NULL)"
        )
        worker_conn_id.append(id(worker_conn))
        try:
            with transaction(worker_conn):
                # While THIS thread holds a transaction, the worker's view
                # of its own conn depth is 1...
                assert _TRANSACTION_DEPTH.get(id(worker_conn), 0) == 1
                in_txn.set()
                # ...wait for the main thread to take its own observation.
                release.wait(timeout=5)
        except BaseException as exc:  # pragma: no cover - surfaced via assert
            error.append(exc)
            in_txn.set()
        finally:
            worker_conn.close()

    t = threading.Thread(target=worker)
    t.start()
    assert in_txn.wait(timeout=5), "worker never entered its transaction"

    # The main thread has opened NO transaction. Its per-thread store must
    # report depth 0 for the worker's connection id — the worker's depth
    # of 1 lives only in the worker thread's local store.
    main_view = _TRANSACTION_DEPTH.get(worker_conn_id[0], 0)
    release.set()
    t.join(timeout=5)

    assert not error, f"worker raised: {error[0]!r}"
    assert main_view == 0
