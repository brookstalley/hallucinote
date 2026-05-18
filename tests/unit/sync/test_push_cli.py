"""Tests for ``push_cli`` (CLI bridge) + ``probe_and_link`` (Python helper).

The CLI tests invoke ``push_cli.main(argv)`` directly and capture
stdout via ``capsys`` — avoids subprocess + Python import overhead.
The probe-and-link tests exercise the Python helper directly.

End-to-end CLI drive simulates the skill's flow: probe-and-link →
enumerate phases → for each phase emit a plan + synthesize results +
apply. Exercises the full ten-phase loop through the CLI surface.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push, push_cli


_LINK_FIELDS: dict[str, str] = {
    "track": "track_index",
    "return": "return_index",
    "clip": "clip_index",
    "device": "device_index",
    "arrangement_clip": "arrangement_clip_index",
    "envelope": "envelope_index",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "psong.db"


@pytest.fixture
def conn(db_path):
    c = init_db(db_path)
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _synthesize_results(plan: push.PushPlan, counters: dict[str, int]) -> list[dict]:
    """Mirror of test_push_song's fake-apply: build synthetic ok results
    with monotonic indexes per link-kind."""
    results = []
    for call in plan.calls:
        kind = call.key.partition(":")[0]
        body: dict = {}
        if kind in _LINK_FIELDS:
            counters[kind] = counters.get(kind, 0) + 1
            body[_LINK_FIELDS[kind]] = counters[kind]
        results.append({
            "key": call.key, "ok": True, "tool": call.tool, "result": body,
        })
    return results


# ---------------------------------------------------------------------------
# probe_and_link (Python helper)
# ---------------------------------------------------------------------------


def test_probe_and_link_matches_track_by_name(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    live_tracks = [{"track_index": 3, "name": "Drums", "kind": "midi"}]
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=live_tracks, live_returns=[],
    )
    assert result.matched_tracks == [
        {"db_id": tid, "name": "Drums", "ableton_index": 3},
    ]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) == 3


def test_probe_and_link_skips_master_tracks(conn, song, session):
    """Live's ableton_track(action='list') never includes master. The
    DB's master row gets no link — master mixer state is reached via
    ableton_session(set_master_property), not by track index."""
    M.create_track(conn, song_id=song, track_index=0, name="Master", kind="master")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Master", "kind": "audio"}],
        live_returns=[],
    )
    assert result.matched_tracks == []
    assert result.unmatched_db_tracks == []


def test_probe_and_link_unmatched_db_track_listed(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Bass", "kind": "midi"}],
        live_returns=[],
    )
    assert result.matched_tracks == []
    assert result.unmatched_db_tracks == [{"db_id": tid, "name": "Drums"}]
    assert result.unmatched_live_tracks == [{"track_index": 1, "name": "Bass"}]


def test_probe_and_link_strips_return_slot_prefix(conn, song, session):
    """W4-C: DB stores suffix-only return names ('Reverb'); Live's
    list emits the slot-prefixed form ('A-Reverb'). Strip before matching."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    assert result.matched_returns == [
        {"db_id": rid, "name": "Reverb", "ableton_index": 1},
    ]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid,
    ) == 1


def test_probe_and_link_warns_on_duplicate_live_track_names(conn, song, session):
    """Two Live tracks with the same name → link to the first, note
    the ambiguity so the user can rename."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="FX", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[
            {"track_index": 1, "name": "FX", "kind": "midi"},
            {"track_index": 2, "name": "FX", "kind": "midi"},
        ],
        live_returns=[],
    )
    assert result.matched_tracks[0]["ableton_index"] == 1
    assert any("FX" in n and "match" in n for n in result.notes), result.notes


def test_probe_and_link_notes_kind_mismatch(conn, song, session):
    """DB midi vs Live audio with same name: link is still written
    (name match wins) but a kind-mismatch note surfaces. Push will
    still create+populate notes happily; if Live's audio track
    rejects MIDI clip writes, that's the next step's problem."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "audio"}],
        live_returns=[],
    )
    assert result.matched_tracks  # link still written
    assert any("kind" in n for n in result.notes), result.notes


def test_probe_and_link_is_idempotent(conn, song, session):
    """Second invocation with the same inputs no-ops (upsert by
    (session, db_kind, db_id))."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    live = [{"track_index": 5, "name": "Drums", "kind": "midi"}]
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=live, live_returns=[],
    )
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=live, live_returns=[],
    )
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM ableton_links WHERE session_id=? AND db_kind='track'",
        (session,),
    ).fetchone()
    assert rows["n"] == 1


# ---------------------------------------------------------------------------
# push_cli — argument plumbing
# ---------------------------------------------------------------------------


def test_cli_phases_emits_ten_phase_metadata(conn, song, session, db_path, capsys):
    push_cli.main([
        "phases", session, "--db", str(db_path),
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["song_id"] == song
    assert out["session_id"] == session
    assert [p["name"] for p in out["phases"]] == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "clips", "mix", "devices", "envelopes", "arrangement", "cues",
    ]
    for p in out["phases"]:
        assert p["description"], f"phase {p['name']!r} has empty description"


def test_cli_plan_emits_named_phase_plan(conn, song, session, db_path, capsys):
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    push_cli.main([
        "plan", "tracks", session, "--db", str(db_path),
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["phase"] == "tracks"
    assert out["song_id"] == song
    assert out["session_id"] == session
    assert len(out["calls"]) == 1
    assert out["calls"][0]["tool"] == "ableton_track"
    assert out["calls"][0]["args"]["action"] == "create"


def test_cli_plan_rejects_unknown_phase(conn, song, session, db_path):
    with pytest.raises(SystemExit, match="unknown phase 'bogus'"):
        push_cli.main([
            "plan", "bogus", session, "--db", str(db_path),
        ])


def test_cli_apply_writes_link_from_result(conn, song, session, db_path, tmp_path, capsys):
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    results = [{
        "key": f"track:{tid}", "ok": True, "tool": "ableton_track",
        "result": {"track_index": 7},
    }]
    rpath = tmp_path / "r.json"
    rpath.write_text(json.dumps(results))
    push_cli.main([
        "apply", session, "--db", str(db_path), "--results", str(rpath),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"applied": 1, "failed": 0, "details": []}
    # Re-open for fresh connection so the apply's transaction is visible.
    fresh = init_db(db_path)
    try:
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="track", db_id=tid,
        ) == 7
    finally:
        fresh.close()


def test_cli_apply_skips_link_when_result_lacks_index(
    conn, song, session, db_path, tmp_path, capsys,
):
    """`ableton_clip(action='replace_notes')` keys are `clip:<id>` but the
    response carries no `clip_index` (the clip already exists; no new
    link to record). apply_push_results must SKIP the link write rather
    than raise. Pin the silent-skip path so a future apply-side refactor
    that drops it surfaces loudly."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="loop")
    # No prior clip link — apply should not invent one.
    results = [{
        "key": f"clip:{cid}", "ok": True, "tool": "ableton_clip",
        "result": {},  # replace_notes returns no clip_index
    }]
    rpath = tmp_path / "r.json"
    rpath.write_text(json.dumps(results))
    push_cli.main([
        "apply", session, "--db", str(db_path), "--results", str(rpath),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"applied": 1, "failed": 0, "details": []}
    fresh = init_db(db_path)
    try:
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="clip", db_id=cid,
        ) is None  # No link written — replace_notes carried no index.
    finally:
        fresh.close()


def test_cli_apply_reports_failed_calls(
    conn, song, session, db_path, tmp_path, capsys,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    results = [{
        "key": f"track:{tid}", "ok": False, "tool": "ableton_track",
        "error": "boom",
    }]
    rpath = tmp_path / "r.json"
    rpath.write_text(json.dumps(results))
    push_cli.main([
        "apply", session, "--db", str(db_path), "--results", str(rpath),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary["applied"] == 0
    assert summary["failed"] == 1
    assert summary["details"][0]["error"] == "boom"


def test_cli_probe_and_link_via_snapshot_file(
    conn, song, session, db_path, tmp_path, capsys,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    snap = {
        "tracks": [{"track_index": 4, "name": "Drums", "kind": "midi"}],
        "returns": [{"return_index": 2, "name": "A-Reverb"}],
    }
    spath = tmp_path / "snap.json"
    spath.write_text(json.dumps(snap))
    push_cli.main([
        "probe-and-link", session, "--db", str(db_path), "--snapshot", str(spath),
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["matched_tracks"][0]["ableton_index"] == 4
    assert out["matched_returns"][0]["ableton_index"] == 2
    fresh = init_db(db_path)
    try:
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="track", db_id=tid,
        ) == 4
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="return", db_id=rid,
        ) == 2
    finally:
        fresh.close()


def test_cli_song_slug_resolves_to_canonical_path(tmp_path, monkeypatch, capsys):
    """``--song <slug>`` resolves to ``songs/<slug>/<slug>.db``. Verify
    by chdir'ing into a tmp dir with that layout."""
    songs_dir = tmp_path / "songs" / "demo"
    songs_dir.mkdir(parents=True)
    db_path = songs_dir / "demo.db"
    conn = init_db(db_path)
    try:
        song = M.create_song(conn, name="t", key="Dm")
        session = M.create_ableton_session(conn, song_id=song, name="draft")
    finally:
        conn.close()
    monkeypatch.chdir(tmp_path)
    push_cli.main(["phases", session, "--song", "demo"])
    out = json.loads(capsys.readouterr().out)
    assert out["session_id"] == session


def test_cli_missing_db_raises_actionable_error(tmp_path):
    with pytest.raises(SystemExit, match="DB not found"):
        push_cli.main([
            "phases", "fake-session-id", "--db", str(tmp_path / "nope.db"),
        ])


def test_cli_unknown_session_raises_actionable_error(conn, db_path):
    with pytest.raises(SystemExit, match="no ableton_sessions row"):
        push_cli.main([
            "phases", "definitely-not-a-real-id", "--db", str(db_path),
        ])


# ---------------------------------------------------------------------------
# End-to-end CLI drive
# ---------------------------------------------------------------------------


@pytest.fixture
def filled_song(conn, song, session):
    """Same shape as test_push_song.filled_song so the CLI drive
    asserts the same emission counts. Returns metadata for assertions."""
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=120.0)
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    drums = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    bass = M.create_track(conn, song_id=song, track_index=2, name="Bass", kind="midi")
    reverb = M.create_return(conn, song_id=song, name="Reverb", position=1)

    drums_clip = M.create_clip(
        conn, track_id=drums, slot=1, length_beats=8.0, name="drums_loop",
    )
    M.insert_notes(
        conn, clip_id=drums_clip,
        notes=[{"pitch": 36, "start_beats": 0.0, "duration_beats": 0.25,
                "velocity": 110, "tags": ["kick"]}],
    )
    bass_clip = M.create_clip(
        conn, track_id=bass, slot=1, length_beats=8.0, name="bass_loop",
    )
    M.insert_notes(
        conn, clip_id=bass_clip,
        notes=[{"pitch": 40, "start_beats": 0.0, "duration_beats": 0.5,
                "velocity": 100, "tags": ["root"]}],
    )

    M.add_arrangement_clip(
        conn, song_id=song, track_id=drums, clip_id=drums_clip,
        start_bar=1.0, end_bar=3.0,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=bass, clip_id=bass_clip,
        start_bar=1.0, end_bar=3.0,
    )
    M.set_send_level(conn, from_track_id=drums, to_return_id=reverb, level=0.4)
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")

    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=drums,
    )
    M.add_breakpoint(
        conn, envelope_id=eid, time_beats=0.0, value=0.4, curve_kind="linear",
    )
    M.add_breakpoint(
        conn, envelope_id=eid, time_beats=4.0, value=0.7, curve_kind="linear",
    )
    return {
        "drums_id": drums,
        "bass_id": bass,
        "reverb_id": reverb,
        "drums_clip_id": drums_clip,
        "bass_clip_id": bass_clip,
    }


def test_cli_end_to_end_drive_links_everything(
    conn, song, session, db_path, tmp_path, filled_song, capsys,
):
    """Simulate the skill: probe-and-link with an empty snapshot
    (fresh Live set), then for each phase invoke plan → synthesize
    results → apply. Pin per-phase emission counts and final link
    state to detect regressions in the CLI-to-orchestrator wiring.

    This is the strong pre-real-Live signal that the wire-up is
    correct — the only difference from the real-Live smoke test is
    the source of MCP results (synthesized here, agent-executed there).
    """
    # Step 1: probe-and-link with empty snapshot (no pre-existing Live
    # tracks/returns) — every DB entity goes into unmatched, no links
    # written yet. Subsequent phases will create them.
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps({"tracks": [], "returns": []}))
    push_cli.main([
        "probe-and-link", session, "--db", str(db_path),
        "--snapshot", str(snap_path),
    ])
    pl = json.loads(capsys.readouterr().out)
    assert pl["matched_tracks"] == []
    assert pl["matched_returns"] == []
    assert len(pl["unmatched_db_tracks"]) == 2  # drums, bass
    assert len(pl["unmatched_db_returns"]) == 1  # reverb

    # Step 2: enumerate phases.
    push_cli.main(["phases", session, "--db", str(db_path)])
    phase_list = json.loads(capsys.readouterr().out)["phases"]
    assert [p["name"] for p in phase_list] == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "clips", "mix", "devices", "envelopes", "arrangement", "cues",
    ]

    # Step 3: drive each phase. We share counters across the loop so
    # successive applies emit monotonic indexes per kind.
    counters: dict[str, int] = {}
    emit_counts: dict[str, int] = {}
    for phase in phase_list:
        push_cli.main([
            "plan", phase["name"], session, "--db", str(db_path),
        ])
        plan_doc = json.loads(capsys.readouterr().out)
        emit_counts[phase["name"]] = len(plan_doc["calls"])
        # Synthesize: instead of going through the runtime PushPlan,
        # we walk the serialized call list to mimic what the agent
        # produces. The result shape is identical.
        results = []
        for call in plan_doc["calls"]:
            kind = call["key"].partition(":")[0]
            body: dict = {}
            if kind in _LINK_FIELDS:
                counters[kind] = counters.get(kind, 0) + 1
                body[_LINK_FIELDS[kind]] = counters[kind]
            results.append({
                "key": call["key"], "ok": True, "tool": call["tool"],
                "result": body,
            })
        rpath = tmp_path / f"r-{phase['name']}.json"
        rpath.write_text(json.dumps(results))
        push_cli.main([
            "apply", session, "--db", str(db_path), "--results", str(rpath),
        ])
        capsys.readouterr()  # discard apply summary; tested separately

    # Pin emission shape per phase (matches the test_push_song e2e).
    assert emit_counts["tempo_map"] == 1
    assert emit_counts["tracks"] == 2
    assert emit_counts["returns"] == 1
    assert emit_counts["clips"] == 2
    assert emit_counts["devices"] == 0
    assert emit_counts["envelopes"] == 1
    assert emit_counts["arrangement"] == 2
    assert emit_counts["cues"] == 1

    # Final link state.
    fresh = init_db(db_path)
    try:
        for db_id in (filled_song["drums_id"], filled_song["bass_id"]):
            assert Q.get_ableton_link(
                fresh, session_id=session, db_kind="track", db_id=db_id,
            ) is not None
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="return",
            db_id=filled_song["reverb_id"],
        ) is not None
    finally:
        fresh.close()
