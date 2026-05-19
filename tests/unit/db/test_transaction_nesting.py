"""Tests for `connection.transaction` reentrancy via SAVEPOINTs.

W7-A added nesting support so mutators that wrap their own atomic blocks
(`M.replace_breakpoints`, `M.replace_clip_notes`) compose correctly when
called from inside an outer pull/push transaction. Without it, the inner
`BEGIN` would fail with `cannot start a transaction within a transaction`.

These tests pin three invariants:

  1. Inner failure rolls back ONLY the inner block, not the outer.
  2. Outer failure rolls back everything (inner + outer writes).
  3. Depth tracking returns to zero across success + failure paths.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db
from hallucinote.db.connection import _TRANSACTION_DEPTH, transaction


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "txn.db")
    # Add a scratch table — we don't need the full schema for this test.
    c.execute("CREATE TABLE IF NOT EXISTS tx_scratch (v INTEGER NOT NULL)")
    yield c
    c.close()


def _rows(conn) -> list[int]:
    return [r[0] for r in conn.execute("SELECT v FROM tx_scratch ORDER BY v")]


def test_nested_commit_success(conn):
    with transaction(conn):
        conn.execute("INSERT INTO tx_scratch (v) VALUES (1)")
        with transaction(conn):
            conn.execute("INSERT INTO tx_scratch (v) VALUES (2)")
    assert _rows(conn) == [1, 2]
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0


def test_nested_inner_failure_preserves_outer(conn):
    with transaction(conn):
        conn.execute("INSERT INTO tx_scratch (v) VALUES (1)")
        with pytest.raises(ValueError):
            with transaction(conn):
                conn.execute("INSERT INTO tx_scratch (v) VALUES (2)")
                raise ValueError("boom inside savepoint")
        # Inner's INSERT was rolled back to savepoint, outer's INSERT survives.
        conn.execute("INSERT INTO tx_scratch (v) VALUES (3)")
    assert _rows(conn) == [1, 3]
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0


def test_nested_outer_failure_rolls_back_everything(conn):
    with pytest.raises(ValueError):
        with transaction(conn):
            conn.execute("INSERT INTO tx_scratch (v) VALUES (1)")
            with transaction(conn):
                conn.execute("INSERT INTO tx_scratch (v) VALUES (2)")
            # Even though the inner block committed (released the
            # SAVEPOINT), the outer ROLLBACK undoes everything.
            raise ValueError("boom outside savepoint")
    assert _rows(conn) == []
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0


def test_three_levels_deep(conn):
    """Depth tracking remains consistent across 3+ levels."""
    with transaction(conn):
        conn.execute("INSERT INTO tx_scratch (v) VALUES (1)")
        with transaction(conn):
            conn.execute("INSERT INTO tx_scratch (v) VALUES (2)")
            with transaction(conn):
                conn.execute("INSERT INTO tx_scratch (v) VALUES (3)")
        # After the deepest two close, we're back to depth=1.
    assert _rows(conn) == [1, 2, 3]
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0


def test_depth_resets_after_outer_exception(conn):
    """A failed outer transaction must not leave depth bookkeeping behind."""
    with pytest.raises(ValueError):
        with transaction(conn):
            raise ValueError("boom")
    assert _TRANSACTION_DEPTH.get(id(conn), 0) == 0
    # Subsequent transaction still works.
    with transaction(conn):
        conn.execute("INSERT INTO tx_scratch (v) VALUES (42)")
    assert _rows(conn) == [42]
