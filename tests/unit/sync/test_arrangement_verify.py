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


def test_overlap_and_boundary_split_faithful_through_orchestration(conn, song, session):
    """ARR-CMPHALT end-to-end (Findings 1+2 together): a DB clip with a same-pitch
    OVERLAP and a start on a half-eps bucket boundary. Live truncates the overlap
    to the next same-pitch onset and round-trips the boundary start to a sub-ULP-
    different float that buckets adjacently. The materialization is faithful
    (every onset present) so the push-time assert must NOT halt — this is the
    exact false-HALT the comparator fix removes."""
    _setup_one_placement(conn, song, session, db_notes=[
        dbn(60, 0.0, dur=3.0),       # overlaps the next p60 onset → Live trims to 1.0
        dbn(60, 1.0, dur=1.0),
        dbn(62, 1.78249, dur=0.25),  # half-eps boundary start
    ])
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0, "notes": [
        lnote(60, 0.0, dur=1.0),       # Live's same-pitch overlap truncation (Finding 1)
        lnote(60, 1.0, dur=1.0),
        lnote(62, 1.78251, dur=0.25),  # round-trip noise across the bucket boundary (Finding 2)
    ]}]}
    send = make_send_fn(live)
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=send)
    assert report.faithful, [(r.status, r.diff.summary() if r.diff else None) for r in report.results]
    assert not report.has_corruption()
    # The push-time assert returns without raising (faithful) — no false HALT.
    assert_arrangement_materialized(conn, song_id=song, session_id=session, send_fn=send)


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


def test_coincident_placements_each_pair_to_own_clip(conn, song, session):
    """Cumulative-Critic W2: two DB placements sharing a start on one track ("rare
    but valid" per get_arrangement_for_song) must each pair to their OWN Live clip.
    Without consumed-index tracking, both matched the single closest clip and the
    twin Live clip fell into extra_live_clips, FALSE-halting a faithful build. The
    fix mirrors the per-track consumed-index discipline the removed SYN-4R7P
    reconcile used for exactly this case. (Pairing is positional, so the two clips
    carry the same notes here — content-distinct coincident clips are a deeper
    positional-matching limit, not what this regression locks.)"""
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0, numerator=4, denominator=4)
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1)
    cid_a = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
    cid_b = M.create_clip(conn, track_id=tid, slot=2, length_beats=16.0, name="B")
    M.insert_notes(conn, clip_id=cid_a, notes=[dbn(60, 0.0)])
    M.insert_notes(conn, clip_id=cid_b, notes=[dbn(60, 0.0)])
    M.add_arrangement_clip(conn, song_id=song, track_id=tid, clip_id=cid_a, start_bar=1.0, end_bar=5.0)
    M.add_arrangement_clip(conn, song_id=song, track_id=tid, clip_id=cid_b, start_bar=1.0, end_bar=5.0)
    # Live has BOTH coincident clips at beat 0.0, indices 1 and 2.
    live = {1: [
        {"arrangement_clip_index": 1, "start_beats": 0.0, "notes": [lnote(60, 0.0)]},
        {"arrangement_clip_index": 2, "start_beats": 0.0, "notes": [lnote(60, 0.0)]},
    ]}
    report = verify_song_arrangement(
        conn, song_id=song, session_id=session, send_fn=make_send_fn(live),
    )
    assert report.faithful, [(r.section, r.status) for r in report.results]
    assert not report.extra_live_clips
    assert not report.has_corruption()


def test_lane_probe_failure_is_corruption_and_assert_halts(conn, song, session):
    """ARR-ORPHAN2 regression — the witness bug, at the assert boundary.

    A whole-LANE probe failure (``ableton_clip(list, location='arrangement')``)
    is NOT the same as a per-clip note-read failure, and tolerating it is what
    let a track lose every placement while the phase printed "97/97 ok": the
    pusher plans its per-lane CLEAR from this same probe, so an unreadable lane
    was neither cleared nor rebuilt, and its surviving orphan was invisible
    (orphan detection needs the listing that just failed). The assert must HALT,
    and the report must say orphan detection did not run on that lane."""
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)])

    def send(req):
        if req.tool == "ableton_clip" and req.action == "list":
            return FakeResp(ok=False, error="simulated lane-probe failure")
        return FakeResp(ok=False, error="unexpected")

    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=send)
    assert [r.status for r in report.results] == ["lane_probe_failed"]
    assert not report.faithful
    assert report.has_corruption()
    assert len(report.lane_probe_failures) == 1
    assert report.lane_probe_failures[0]["track_index"] == 1
    # The push-time assert HALTs rather than reporting the phase ok.
    with pytest.raises(ArrangementIntegrityError) as exc:
        assert_arrangement_materialized(conn, song_id=song, session_id=session, send_fn=send)
    text = str(exc.value)
    assert "lane_unreadable" in text
    assert "ORPHAN DETECTION DID NOT RUN" in text


def test_dropped_lane_with_surviving_orphan_halts(conn, song, session):
    """ARR-ORPHAN2 regression — the witness bug's other branch. When the lane IS
    readable at assert time, a track whose placements were dropped and whose
    orphan survived must fail the phase: every DB placement reads `missing_clip`
    and the unmatched Live clip reads as an orphan. Modeled on the observed
    `the-argument` Lead Gtr state (3 placements dropped, 1 orphan at beat 0)."""
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0, numerator=4, denominator=4)
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead Gtr")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid, ableton_index=4)
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="verse rock 2")
    M.insert_notes(conn, clip_id=cid, notes=[dbn(60, 0.0)])
    for start_bar in (57.0, 60.5, 66.5):  # beats 224 / 238 / 262
        M.add_arrangement_clip(conn, song_id=song, track_id=tid, clip_id=cid,
                               start_bar=start_bar, end_bar=start_bar + 4.0)
    # Live holds ONE clip, the orphan at beat 0 — none of the three placements.
    live = {4: [{"arrangement_clip_index": 1, "start_beats": 0.0,
                 "name": "Lead Gtr 2", "notes": []}]}
    send = make_send_fn(live)
    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=send)
    assert [r.status for r in report.results] == ["missing_clip"] * 3
    assert [c["start_beats"] for c in report.extra_live_clips] == [0.0]
    assert report.has_corruption()
    with pytest.raises(ArrangementIntegrityError):
        assert_arrangement_materialized(conn, song_id=song, session_id=session, send_fn=send)


def test_probe_failed_does_not_halt_but_is_not_faithful(conn, song, session):
    """Cumulative-Critic W1: a per-clip note re-probe FAILURE is not silent
    corruption — has_corruption() is False so the push-time assert must NOT HALT —
    but the placement went UNVERIFIED, so it is NOT faithful either. (The executor
    turns this into a benign warning so 'couldn't verify' reads distinctly from
    'verified OK'; see test_push_execute.)

    ARR-ORPHAN2 keeps this carve-out DELIBERATELY NARROW: it applies only when the
    lane listing SUCCEEDED, i.e. the clip is demonstrably at the right position and
    only its note contents could not be read. A failure of the lane listing itself
    is `lane_probe_failed` and DOES halt — see the test above."""
    _setup_one_placement(conn, song, session, db_notes=[dbn(60, 0.0)])

    def send(req):
        if req.tool == "ableton_clip" and req.action == "list":
            return FakeResp(result={"clips": [
                {"arrangement_clip_index": 1, "start_beats": 0.0, "name": ""},
            ]})
        if req.tool == "ableton_note" and req.action == "list":
            return FakeResp(ok=False, error="simulated note-probe failure")
        return FakeResp(ok=False, error="unexpected")

    report = verify_song_arrangement(conn, song_id=song, session_id=session, send_fn=send)
    assert [r.status for r in report.results] == ["probe_failed"]
    assert not report.has_corruption()  # does not halt
    assert not report.faithful          # but not a pass
    # The assert returns without raising (no corruption) — proving probe failure
    # is non-fatal at the assert boundary.
    assert_arrangement_materialized(conn, song_id=song, session_id=session, send_fn=send)


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


# ---------------------------------------------------------------------------
# Audio placements: presence is checked, only the NOTE compare is skipped
# ---------------------------------------------------------------------------


def _setup_one_audio_placement(conn, song, session, *, start_bar=1.0):
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0, numerator=4, denominator=4)
    tid = M.create_track(conn, song_id=song, track_index=1, name="Stems", kind="audio")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1)
    cid = M.create_audio_clip(
        conn, track_id=tid, slot=1, length_beats=16.0,
        audio_file="assets/line.wav", name="line",
    )
    M.add_arrangement_clip(conn, song_id=song, track_id=tid, clip_id=cid,
                           start_bar=start_bar, end_bar=start_bar + 4.0)
    return tid, cid


def test_dropped_audio_placement_is_missing_clip_not_clean(conn, song, session):
    """A DROPPED audio placement must halt the push-time assert.

    `skipped_audio` is a _CLEAN status, and the audio branch used to `continue`
    with it BEFORE the presence check — so `missing_clip` was unreachable for
    audio and a placement the per-lane clear removed and the rebuild failed to
    restore left `faithful` True. Audio placements now materialize through that
    same clear-then-rebuild projection, so this is a live failure mode, not a
    hypothetical: it is exactly how a track loses its timeline while the phase
    reports success.
    """
    _setup_one_audio_placement(conn, song, session)
    report = verify_song_arrangement(          # Live reports NO clips on the lane
        conn, song_id=song, session_id=session, send_fn=make_send_fn({1: []}),
    )
    assert [r.status for r in report.results] == ["missing_clip"]
    assert not report.faithful
    assert report.has_corruption()


def test_present_audio_placement_is_clean_without_a_note_compare(conn, song, session):
    """The other half: an audio clip that IS there stays clean. Skipping the
    note comparison is correct — an audio clip has no notes — and must not be
    confused with skipping the presence check."""
    _setup_one_audio_placement(conn, song, session)
    live = {1: [{"arrangement_clip_index": 1, "start_beats": 0.0, "notes": []}]}
    report = verify_song_arrangement(
        conn, song_id=song, session_id=session, send_fn=make_send_fn(live),
    )
    assert [r.status for r in report.results] == ["skipped_audio"]
    assert report.faithful
    assert not report.has_corruption()
