"""sync/push/tuning_notice.py — gated push instruction + drift-warn (Chunk 3).

Three layers:
- :func:`reload_instruction` — the operator load-the-.ascl copy (Part 2).
- :func:`drift_warning` — the PURE warn/silent decision (Part 3), fully tested
  here without Live (the live *read* shapes it consumes are verify-api-confirmed;
  this pins the decision contract independently of the read).
- :func:`collect_tuning_notices` — the DB-read + live-read wiring, exercised with
  a fake ``send_fn`` (12-TET inert · nothing-loaded · match · drift · probe-fail).

The fake ``Request``/``Response`` shapes mirror ``hallucinote_mcp.wire`` (duck-
typed by the production code), so no MCP/Live dependency is touched.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync.push.tuning_notice import (
    LoadedTuning,
    collect_tuning_notices,
    drift_warning,
    reload_instruction,
)
from hallucinote.tuning.model import TuningData


def _blob(name="19-EDO", period=1200.0):
    return TuningData(
        name=name, step_count=19, period_cents=period, reference_note=60,
        step_cents=tuple(round(period * i / 19, 6) for i in range(1, 19))
        + (period,),
    ).to_blob()


# ---------------------------------------------------------------------------
# reload_instruction (Part 2)
# ---------------------------------------------------------------------------
def test_reload_instruction_names_song_relative_path():
    out = reload_instruction("micro-song", "tunings/19-edo.ascl")
    assert "micro-song" in out
    assert "tunings/19-edo.ascl" in out
    assert "Tuning section" in out
    assert "read-only" in out  # honest: push can't load it


# ---------------------------------------------------------------------------
# drift_warning (Part 3) — pure decision
# ---------------------------------------------------------------------------
def test_drift_warning_silent_on_match():
    loaded = LoadedTuning(name="19-EDO", period_cents=1200.0)
    assert drift_warning(_blob(), loaded) is None


def test_drift_warning_silent_on_match_within_period_tolerance():
    # Float noise from the LOM read / JSON round-trip must not read as drift.
    loaded = LoadedTuning(name="19-EDO", period_cents=1200.0 + 5e-3)
    assert drift_warning(_blob(period=1200.0), loaded) is None


def test_drift_warning_fires_when_nothing_loaded():
    out = drift_warning(_blob(), None)
    assert out is not None
    assert "NO tuning loaded" in out
    assert "19-EDO" in out


def test_drift_warning_fires_on_name_mismatch():
    loaded = LoadedTuning(name="31-EDO", period_cents=1200.0)
    out = drift_warning(_blob(name="19-EDO"), loaded)
    assert out is not None and "DRIFT" in out
    assert "31-EDO" in out and "19-EDO" in out


def test_drift_warning_fires_on_period_mismatch():
    # Same name, non-octave period drift (e.g. Bohlen-Pierce ≈ 1901.955¢).
    loaded = LoadedTuning(name="19-EDO", period_cents=1901.955)
    out = drift_warning(_blob(name="19-EDO", period=1200.0), loaded)
    assert out is not None and "DRIFT" in out


def test_drift_warning_soft_note_when_scalars_unreadable():
    out = drift_warning(_blob(), LoadedTuning(name=None, period_cents=None))
    assert out is not None
    assert "could not read" in out and "confirm by ear" in out
    assert "DRIFT" not in out  # honest: not asserting a mismatch we can't see


def test_drift_warning_soft_note_on_malformed_blob():
    out = drift_warning("{not valid json", LoadedTuning("x", 1200.0))
    assert out is not None and "could not verify" in out


def test_stored_blob_format_lock():
    """Lock the persisted-format keys the core re-parser reads by literal.

    The drift check parses ``name`` / ``period_cents`` straight out of the blob
    (to keep the core from importing the bolt-on). If ``TuningData`` ever renamed
    those keys, the check would silently degrade — so this builds the blob with
    the REAL model and asserts (a) the keys are present and (b) a matching
    LoadedTuning reads as silent through the real format. A rename breaks here."""
    import json

    blob = _blob(name="lock-tuning", period=1234.5)
    raw = json.loads(blob)
    assert "name" in raw and "period_cents" in raw, (
        "tuning_notice reads these keys by literal — a TuningData rename must "
        "fail a test, not silently break the drift check"
    )
    # The real format round-trips through the core re-parser to a silent match.
    assert drift_warning(blob, LoadedTuning(name="lock-tuning", period_cents=1234.5)) is None


# ---------------------------------------------------------------------------
# collect_tuning_notices — DB read + live read wiring
# ---------------------------------------------------------------------------
@dataclass
class _FakeResponse:
    ok: bool
    result: dict | None = None
    error: str | None = None


@dataclass
class _FakeRequest:
    tool: str
    action: str
    params: dict = field(default_factory=dict)
    allow_version_mismatch: bool = False


def _send_fn(*, tuning_system, name=None, period=None, fail_paths=frozenset()):
    """Build a fake send_fn answering ableton_probe gets by path.

    ``tuning_system`` is the {type,value} for ``song.tuning_system``; ``name`` /
    ``period`` answer the scalar sub-paths. Paths in ``fail_paths`` return ok=False.
    """
    sub = {
        "song.tuning_system.name": {"type": "str", "value": name},
        "song.tuning_system.pseudo_octave_in_cents": {"type": "float", "value": period},
    }

    def send(req):
        path = req.params["path"]
        if path in fail_paths:
            return _FakeResponse(ok=False, error="probe refused")
        if path == "song.tuning_system":
            return _FakeResponse(ok=True, result={"path": path, **tuning_system})
        return _FakeResponse(ok=True, result={"path": path, **sub[path]})

    return send


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "notice.db")
    yield c
    c.close()


def _song_with_tuning(conn, *, tuning_ref="tunings/19-edo.ascl", blob=None):
    song_id = M.create_song(conn, name="micro-song", key="C")
    M.set_song_tuning(
        conn, song_id=song_id,
        tuning_ref=tuning_ref, tuning_data=blob if blob is not None else _blob(),
    )
    return song_id


def test_collect_inert_for_12tet_song_no_live_read(conn):
    song_id = M.create_song(conn, name="plain", key="C")

    def boom(req):  # must not be called on the 12-TET path
        raise AssertionError("12-TET song must not trigger a Live read")

    assert collect_tuning_notices(
        conn, song_id=song_id, send_fn=boom, request_cls=_FakeRequest,
    ) == []


def test_collect_instruction_plus_drift_when_nothing_loaded(conn):
    song_id = _song_with_tuning(conn)
    notices = collect_tuning_notices(
        conn, song_id=song_id,
        send_fn=_send_fn(tuning_system={"type": "NoneType", "value": None}),
        request_cls=_FakeRequest,
    )
    assert len(notices) == 2
    assert "tunings/19-edo.ascl" in notices[0]
    assert "NO tuning loaded" in notices[1]


def test_collect_instruction_only_when_loaded_tuning_matches(conn):
    song_id = _song_with_tuning(conn, blob=_blob(name="19-EDO", period=1200.0))
    notices = collect_tuning_notices(
        conn, song_id=song_id,
        send_fn=_send_fn(
            tuning_system={"type": "TuningSystem", "value": {"__lom__": "TuningSystem"}},
            name="19-EDO", period=1200.0,
        ),
        request_cls=_FakeRequest,
    )
    # Drift is silent on match — only the load instruction remains.
    assert len(notices) == 1
    assert "micro-song" in notices[0] and "tunings/19-edo.ascl" in notices[0]


def test_collect_drift_when_different_tuning_loaded(conn):
    song_id = _song_with_tuning(conn, blob=_blob(name="19-EDO", period=1200.0))
    notices = collect_tuning_notices(
        conn, song_id=song_id,
        send_fn=_send_fn(
            tuning_system={"type": "TuningSystem", "value": {"__lom__": "TuningSystem"}},
            name="31-EDO", period=1200.0,
        ),
        request_cls=_FakeRequest,
    )
    assert len(notices) == 2
    assert "DRIFT" in notices[1] and "31-EDO" in notices[1]


def test_collect_degrades_to_soft_note_when_top_probe_fails(conn):
    song_id = _song_with_tuning(conn)
    notices = collect_tuning_notices(
        conn, song_id=song_id,
        send_fn=_send_fn(
            tuning_system={"type": "NoneType", "value": None},
            fail_paths={"song.tuning_system"},
        ),
        request_cls=_FakeRequest,
    )
    # Instruction still emitted; drift degrades to a soft "couldn't re-read" note.
    assert len(notices) == 2
    assert "could not re-read" in notices[1]


def test_collect_soft_note_when_scalar_subread_fails(conn):
    song_id = _song_with_tuning(conn)
    notices = collect_tuning_notices(
        conn, song_id=song_id,
        send_fn=_send_fn(
            tuning_system={"type": "TuningSystem", "value": {"__lom__": "TuningSystem"}},
            name="19-EDO", period=1200.0,
            fail_paths={"song.tuning_system.pseudo_octave_in_cents"},
        ),
        request_cls=_FakeRequest,
    )
    assert len(notices) == 2
    assert "could not read" in notices[1] and "confirm by ear" in notices[1]
