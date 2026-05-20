"""Shape assertions for solo-piano-ambient build.

Canary Wave 0 song — verifies the build produces the structure described in
`docs/canary-songs/solo-piano-ambient.md`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SONG_ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = SONG_ROOT / "build.py"


@pytest.fixture
def build_module(tmp_path, monkeypatch):
    """Import build.py with DB_PATH redirected to a temp file."""
    spec = importlib.util.spec_from_file_location("solo_piano_ambient_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "solo-piano-ambient.db")
    return module


def test_build_runs_clean_and_produces_canary_shape(build_module):
    """Running build(--reset) produces the canary's full shape."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Sections — four, in canonical order.
        sections = Q.get_sections_for_song(conn, song_id)
        names = [s["name"] for s in sections]
        assert names == ["prelude", "bloom", "recede", "silence"], names

        # Tracks — 2 (master + 1 piano). Returns are separate.
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) == 2, [t["name"] for t in tracks]
        tracks_by_name = {t["name"]: t for t in tracks}
        assert "01 Piano" in tracks_by_name
        assert "Master" in tracks_by_name

        # Returns — exactly two. Names are STRIPPED of the Live slot prefix
        # ("A-Reverb" -> "Reverb") by capture.strip_return_slot_prefix on
        # replay. See friction log: this is non-obvious for hand-authored
        # snapshots since the snapshot field reads "A-Reverb".
        returns = Q.get_returns_for_song(conn, song_id)
        return_names = sorted(r["name"] for r in returns)
        assert return_names == ["Delay", "Reverb"], return_names

        # The piano track has clips for prelude / bloom / recede only — NOT silence.
        piano_id = tracks_by_name["01 Piano"]["id"]
        clips = Q.get_clips_for_track(conn, piano_id)
        clip_roles = sorted(c["section_role"] for c in clips)
        assert clip_roles == ["bloom", "prelude", "recede"], clip_roles

        # Arrangement entries: one per non-silence section (3 total), all on
        # the piano track. Silence has ZERO arrangement entries.
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) == 3, [(a["start_bar"], a["end_bar"]) for a in arr]
        # Silence bar range (49-57) is intentionally absent.
        for a in arr:
            assert not (a["start_bar"] >= 49.0), (
                f"silence section (bars 49-57) should have no arrangement "
                f"entries, but found one at {a['start_bar']}-{a['end_bar']}"
            )

        # Tempo + signature points (bar-1 only for now per the brief).
        tempo = Q.get_tempo_map(conn, song_id)
        assert len(tempo) == 1
        assert tempo[0]["tempo_bpm"] == 60.0

        sig = Q.get_time_signature_map(conn, song_id)
        assert len(sig) == 1
        assert sig[0]["numerator"] == 4 and sig[0]["denominator"] == 4

        # Cue points — one per section boundary (4).
        cues = Q.get_cue_points(conn, song_id)
        cue_names = [c["name"] for c in cues]
        assert cue_names == ["prelude", "bloom", "recede", "silence"], cue_names

        # Envelopes — at least two: the long reverb send + the volume swell.
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) >= 2, [e["target_kind"] for e in envs]
        kinds = {e["target_kind"] for e in envs}
        assert "send_level" in kinds, kinds
        assert "mixer_volume" in kinds, kinds

        # The reverb send envelope is LONG — at least 5 breakpoints and spans
        # at least 100 beats end-to-end.
        send_envs = [e for e in envs if e["target_kind"] == "send_level"]
        assert len(send_envs) == 1
        bps = Q.get_breakpoints(conn, envelope_id=send_envs[0]["id"])
        assert len(bps) >= 5, len(bps)
        span = bps[-1]["time_beats"] - bps[0]["time_beats"]
        assert span >= 100.0, f"reverb envelope span {span} beats, expected >= 100"

        # Every envelope has breakpoints.
        for e in envs:
            ebps = Q.get_breakpoints(conn, envelope_id=e["id"])
            assert ebps, f"envelope {e['id']} has no breakpoints"

        # Note total: this is a SPARSE piece (single track, lots of rests +
        # silence section). Should be tens-to-low-hundreds, not thousands.
        total = sum(
            len(Q.get_notes_for_clip(conn, c["id"]))
            for c in clips
        )
        assert total >= 20, f"expected >= 20 notes total, got {total}"
        assert total <= 200, f"expected <= 200 notes total (sparse), got {total}"
    finally:
        conn.close()


def test_bloom_has_overlapping_chord_voicings(build_module):
    """The bloom section intentionally overlaps chord tails — exercises legato."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        piano_id = next(t["id"] for t in tracks if t["name"] == "01 Piano")
        clips = Q.get_clips_for_track(conn, piano_id)
        bloom_clip = next(c for c in clips if c["section_role"] == "bloom")
        notes = Q.get_notes_for_clip(conn, bloom_clip["id"])

        # Find at least one pair (a, b) where a starts before b but a's end is
        # after b's start — that's the overlap signature.
        overlaps = 0
        for a in notes:
            for b in notes:
                if a is b:
                    continue
                if (a["start_beats"] < b["start_beats"]
                        and a["start_beats"] + a["duration_beats"]
                            > b["start_beats"]):
                    overlaps += 1
                    break
            if overlaps:
                break
        assert overlaps, "expected at least one overlapping voicing in bloom"
    finally:
        conn.close()
