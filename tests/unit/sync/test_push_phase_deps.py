"""SYN-8Q3F Chunk 02: push phase ordering as a declared DAG.

The execution order stays the human-chosen tuple ``_PHASE_NAMES`` (behavior
preserving — byte-identical to the pre-SYN-8Q3F order); what's new is that the
ordering CONSTRAINTS live in ``_PHASE_DEPS`` (data, not prose) and
``validate_phase_order`` proves the tuple satisfies them at plan-construction
time. These tests pin: the historical order, the validator's teaching failures
(undeclared dep / unknown dep / dep-after-dependent / cycle), the stamped
``PushPhase.depends_on``, and the specific load-bearing edges the old docstring
asserted in prose.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync.push.plan import (
    PhaseOrderError,
    _PHASE_DEPS,
    _PHASE_NAMES,
    plan_push_song,
    validate_phase_order,
)

# The pre-SYN-8Q3F execution order, pinned literally: the DAG refactor is
# behavior-preserving, so the declared order must stay byte-identical to what
# the executor ran before the deps became data.
_HISTORICAL_ORDER = (
    "tempo_map",
    "time_signature_map",
    "tracks",
    "returns",
    "scenes",
    "clips",
    "mix",
    "devices",
    "routing",
    "device_sidechain",
    "envelopes",
    "performed_automation",
    "arrangement",
    "cues",
)


@pytest.fixture()
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture()
def song(conn):
    return M.create_song(conn, name="dag-song", key="Dm")


@pytest.fixture()
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def test_declared_order_is_byte_identical_to_historical_order():
    assert _PHASE_NAMES == _HISTORICAL_ORDER


def test_declared_order_satisfies_declared_deps():
    # The real graph + the real order: must validate silently.
    validate_phase_order(_PHASE_NAMES, _PHASE_DEPS)


def test_stable_topological_sort_of_deps_reproduces_declared_order():
    """Kahn's algorithm with 'earliest declared position wins' tie-break must
    reproduce _PHASE_NAMES exactly — i.e. the declared order IS a topological
    order of the declared graph (the 'executor topologically sorts' framing and
    the 'validate order against deps' framing agree)."""
    remaining = list(_PHASE_NAMES)
    placed: list[str] = []
    done: set[str] = set()
    while remaining:
        ready = next(
            n for n in remaining if _PHASE_DEPS[n] <= done
        )  # earliest declared position whose deps are satisfied
        placed.append(ready)
        done.add(ready)
        remaining.remove(ready)
    assert tuple(placed) == _PHASE_NAMES


def test_every_phase_declares_a_dependency_set():
    assert set(_PHASE_DEPS) == set(_PHASE_NAMES)


def test_load_bearing_edges_are_declared():
    """The constraints the old plan_push_song docstring carried in prose, now
    asserted against the data. Superset checks: new edges may be added, but
    these may never silently disappear."""
    assert {"tracks", "scenes"} <= _PHASE_DEPS["clips"]          # W3-C, SYN-4P2D
    assert {"tracks", "returns"} <= _PHASE_DEPS["mix"]
    assert {"tracks", "returns"} <= _PHASE_DEPS["devices"]
    assert {"tracks", "devices"} <= _PHASE_DEPS["routing"]       # RTE-2P9X
    # routing-after-mix is tuple-order convention (RTE-1K9T), NOT a declared
    # dep — the routing planner reads nothing the mix phase applies.
    assert "mix" not in _PHASE_DEPS["routing"]
    assert {"devices"} <= _PHASE_DEPS["device_sidechain"]        # SDC-7K3M
    assert {"clips", "devices"} <= _PHASE_DEPS["envelopes"]
    assert {"devices"} <= _PHASE_DEPS["performed_automation"]
    assert {"clips", "envelopes"} <= _PHASE_DEPS["arrangement"]  # W4-A
    assert {"arrangement"} <= _PHASE_DEPS["cues"]                # W3-I


def test_phases_carry_their_declared_deps(conn, song, session):
    phases = plan_push_song(conn, song_id=song, session_id=session)
    assert [p.name for p in phases] == list(_PHASE_NAMES)
    for p in phases:
        assert p.depends_on == _PHASE_DEPS[p.name]


def test_dep_after_dependent_is_rejected():
    # cues depends on arrangement; put cues before arrangement.
    names = list(_PHASE_NAMES)
    i, j = names.index("arrangement"), names.index("cues")
    names[i], names[j] = names[j], names[i]
    with pytest.raises(PhaseOrderError, match="'cues' depends on 'arrangement'"):
        validate_phase_order(tuple(names), _PHASE_DEPS)


def test_unknown_dependency_is_rejected():
    deps = dict(_PHASE_DEPS)
    deps["clips"] = frozenset({"tracks", "scenes", "warp_core"})
    with pytest.raises(PhaseOrderError, match="unknown phase 'warp_core'"):
        validate_phase_order(_PHASE_NAMES, deps)


def test_cycle_is_rejected():
    # A cycle can never be linearized: whichever way two mutually-dependent
    # phases are ordered, one edge points forward.
    names = ("a", "b")
    deps = {"a": frozenset({"b"}), "b": frozenset({"a"})}
    with pytest.raises(PhaseOrderError, match="depends on"):
        validate_phase_order(names, deps)
    with pytest.raises(PhaseOrderError):
        validate_phase_order(("b", "a"), deps)


def test_phase_with_no_declared_dependency_set_is_rejected():
    deps = dict(_PHASE_DEPS)
    del deps["cues"]
    with pytest.raises(PhaseOrderError, match="declare no dependency set"):
        validate_phase_order(_PHASE_NAMES, deps)


def test_stale_declaration_for_removed_phase_is_rejected():
    deps = dict(_PHASE_DEPS)
    deps["retired_phase"] = frozenset()
    with pytest.raises(PhaseOrderError, match="unknown phase"):
        validate_phase_order(_PHASE_NAMES, deps)


def test_duplicate_phase_name_is_rejected():
    names = _PHASE_NAMES + ("cues",)
    with pytest.raises(PhaseOrderError, match="duplicate"):
        validate_phase_order(names, _PHASE_DEPS)
