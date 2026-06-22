"""ARR-PROJ Chunk 3 — arrangement verification orchestration + push-time assert."""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync.arrangement_verify import (
    ArrangementIntegrityError,
    assert_arrangement_materialized,
    format_report,
    verify_song_arrangement,
)


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "v.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


class FakeResp:
    def __init__(self, ok=True, result=None, error=None):
        self.ok, self.result, self.error = ok, result, error


def make_send_fn(live_model):
    """live_model: {track_index: [{arrangement_clip_index, start_beats, notes, name?}]}.
    Notes are MCP note-API shape ({pitch, start_time, duration, velocity})."""
    def send(req):
        p = req.params
        if req.tool == "ableton_clip" and req.action == "list":
            clips = live_model.get(p["track_index"], [])
            return FakeResp(result={"clips": [
                {"arrangement_clip_index": c["arrangement_clip_index"],
                 "start_beats": c["start_beats"], "name": c.get("name", "")}
                for c in clips
            ]})
        if req.tool == "ableton_note" and req.action == "list":
            for c in live_model.get(p["track_index"], []):
                if c["arrangement_clip_index"] == p["clip_index"]:
                    return FakeResp(result={"notes": c.get("notes", [])})
            return FakeResp(ok=False, error="no such clip")
        return FakeResp(ok=False, error=f"unexpected {req.tool}.{req.action}")
    return send


def lnote(pitch, start, dur=1.0, vel=100):
    return {"pitch": pitch, "start_time": start, "duration": dur, "velocity": vel}


def _setup_one_placement(conn, song, session, *, db_notes, linked=True, start_bar=1.0):
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0, numerator=4, denominator=4)
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    if linked:
        M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1)
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="verse")
    if db_notes:
        M.insert_notes(conn, clip_id=cid, notes=db_notes)
    M.add_arrangement_clip(conn, song_id=song, track_id=tid, clip_id=cid,
                           start_bar=start_bar, end_bar=start_bar + 4.0)
    return tid, cid


def dbn(pitch, start, dur=1.0, vel=100):
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}


def test_faithful_materialization_reports_clean(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0), dbn(62, 1.0)])
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0,
                 "notes": [lnote(60, 0.0), lnote(62, 1.0)]}]}
    report = verify_song_arrangement(
        conn, song_id=song, session_id=session, send_fn=make_send_fn(live),
    )
    assert report.faithful
    assert all(r.status == "faithful" for r in report.results)


def test_wildness_stack_faithful_through_orchestration(conn, song, session):
    """The collapsed-set normalization survives end-to-end: a DB stack vs Live's
    one note reads faithful (not a false missing)."""
    _setup_one_placement(conn, song, session, db_notes=[
        dbn(60, 0.0, dur=1.0, vel=100), dbn(60, 0.0, dur=0.5, vel=120), dbn(62, 1.0),
    ])
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0,
                 "notes": [lnote(60, 0.0, dur=0.5, vel=120), lnote(62, 1.0)]}]}
    assert verify_song_arrangement(
        conn, song_id=song, session_id=session, send_fn=make_send_fn(live),
    ).faithful


def test_dropped_note_reads_diverged_and_assert_halts(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0), dbn(62, 1.0)])
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0,
                 "notes": [lnote(60, 0.0)]}]}  # 62 dropped
    send = make_send_fn(live)
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=send)
    assert not report.faithful
    diverged = report.divergences()
    assert len(diverged) == 1 and diverged[0].status == "diverged"
    assert [n.pitch for n in diverged[0].diff.missing] == [62]
    # The push-time assert HALTs.
    with pytest.raises(ArrangementIntegrityError) as exc:
        assert_arrangement_materialized(conn, song_id=song, session_id=session, send_fn=send)
    assert "integrity FAILED" in str(exc.value)


def test_orphan_note_reads_diverged(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)])
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0,
                 "notes": [lnote(60, 0.0), lnote(67, 3.0)]}]}  # orphan 67
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=make_send_fn(live))
    assert not report.faithful
    assert [n.pitch for n in report.divergences()[0].diff.extra] == [67]


def test_missing_clip_when_no_live_clip_at_position(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)])
    live = {1: []}  # the whole clip is gone
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=make_send_fn(live))
    assert not report.faithful
    assert report.divergences()[0].status == "missing_clip"


def test_extra_live_clip_with_no_db_placement(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)])
    live = {1: [
        {"arrangement_clip_index": 1, "start_beats": 0.0, "notes": [lnote(60, 0.0)]},
        {"arrangement_clip_index": 2, "start_beats": 100.0, "name": "orphan",
         "notes": [lnote(60, 0.0)]},  # no DB placement at beat 100
    ]}
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=make_send_fn(live))
    assert not report.faithful
    assert len(report.extra_live_clips) == 1
    assert report.extra_live_clips[0]["start_beats"] == 100.0


def test_track_unlinked_reported_not_crashed(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)], linked=False)
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=make_send_fn({}))
    assert not report.faithful
    assert report.divergences()[0].status == "track_unlinked"


def test_assert_returns_report_on_faithful(conn, song, session):
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)])
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0, "notes": [lnote(60, 0.0)]}]}
    report = assert_arrangement_materialized(
        conn, song_id=song, session_id=session, send_fn=make_send_fn(live),
    )
    assert report.faithful
    assert "OK" in format_report(report)


def test_assert_does_not_halt_on_track_unlinked(conn, song, session):
    """The push-time assert HALTs on SILENT corruption (drop/orphan), NOT on an
    already-alerted operational state like a track that was deliberately skipped
    (track_unlinked) — has_corruption() excludes it so a scoped run doesn't false-halt."""
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)], linked=False)
    # track_unlinked → not faithful, but NOT corruption → assert returns (no raise).
    report = assert_arrangement_materialized(
        conn, song_id=song, session_id=session, send_fn=make_send_fn({}),
    )
    assert not report.faithful
    assert not report.has_corruption()


def test_verify_arrangement_cli_exit_codes(tmp_path, monkeypatch, capsys):
    """The audit CLI exits 0 on a faithful set and non-zero on any divergence
    (the seeded-orphan acceptance). The orchestration is stubbed — its own logic
    is covered above; here we lock the CLI's exit-code + output contract."""
    from hallucinote.db import init_db, mutations as M
    from hallucinote.sync import verify_arrangement_cli as vcli
    from hallucinote.sync.arrangement_compare import ClipDiff, NoteLite
    from hallucinote.sync.arrangement_verify import ArrangementReport, PlacementResult

    db = tmp_path / "s.db"
    c = init_db(db)
    sid_song = M.create_song(c, name="t", key="Dm")
    sess = M.create_ableton_session(c, song_id=sid_song, name="draft")
    c.close()

    # Faithful → exit 0.
    monkeypatch.setattr(vcli, "verify_song_arrangement", lambda conn, **k: ArrangementReport())
    assert vcli.main(["--db", str(db), sess]) == 0
    assert "OK" in capsys.readouterr().out

    # Seeded orphan → diverged → exit 1.
    bad = ArrangementReport(results=[PlacementResult(
        "Drums", "verse", 0.0, "diverged",
        diff=ClipDiff(extra=[NoteLite(67, 3.0, 1.0, 100)]),
    )])
    monkeypatch.setattr(vcli, "verify_song_arrangement", lambda conn, **k: bad)
    assert vcli.main(["--db", str(db), sess]) == 1
    assert "diverged" in capsys.readouterr().out
