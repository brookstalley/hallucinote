"""Shape assertions for full-band-rock build.

Canary Wave 0 song (run #2). Verifies the build produces the structure
described in `docs/canary-songs/full-band-rock.md`.
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
    spec = importlib.util.spec_from_file_location("full_band_rock_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "full-band-rock.db")
    return module


def test_build_runs_clean_and_produces_canary_shape(build_module):
    """Running build(--reset) produces the canary's full shape."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Sections — eight, in canonical order. Note repeated names.
        sections = Q.get_sections_for_song(conn, song_id)
        names = [s["name"] for s in sections]
        assert names == [
            "intro", "verse", "chorus",
            "verse", "chorus",
            "bridge", "chorus", "outro",
        ], names

        # Verify each section has a distinct (start_bar, end_bar) pair
        # — the DB lets us repeat names but spans must differ.
        spans = [(s["start_bar"], s["end_bar"]) for s in sections]
        assert len(set(spans)) == len(spans), f"duplicate spans: {spans}"

        # Tracks — 9 (master + 8 main). Returns are separate.
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) == 9, [t["name"] for t in tracks]
        tracks_by_name = {t["name"]: t for t in tracks}
        for expected_name in [
            "Master",
            "01 Drums", "02 Bass", "03 Rhythm Guitar", "04 Lead Guitar",
            "05 Keys", "06 Backing Vox Pad", "07 Lead Vocal",
            "08 Parallel Comp Bus",
        ]:
            assert expected_name in tracks_by_name, expected_name

        # Track kinds: MIDI for instruments, AUDIO for placeholders.
        kinds = {t["name"]: t["kind"] for t in tracks}
        assert kinds["01 Drums"] == "midi"
        assert kinds["02 Bass"] == "midi"
        assert kinds["03 Rhythm Guitar"] == "audio"
        assert kinds["04 Lead Guitar"] == "audio"
        assert kinds["05 Keys"] == "midi"
        assert kinds["06 Backing Vox Pad"] == "midi"
        assert kinds["07 Lead Vocal"] == "audio"
        assert kinds["08 Parallel Comp Bus"] == "audio"
        assert kinds["Master"] == "master"

        # AUDIO tracks have zero clips (DB doesn't model audio clips).
        for audio_name in ["03 Rhythm Guitar", "04 Lead Guitar",
                           "07 Lead Vocal", "08 Parallel Comp Bus"]:
            tid = tracks_by_name[audio_name]["id"]
            clips = Q.get_clips_for_track(conn, tid)
            assert clips == [] or len(clips) == 0, (
                f"audio track {audio_name!r} has clips: "
                f"{[c['name'] for c in clips]}"
            )

        # Returns — exactly three. Names stripped of slot prefix per
        # capture.strip_return_slot_prefix (same as solo-piano-ambient
        # Step 3 finding).
        returns = Q.get_returns_for_song(conn, song_id)
        return_names = sorted(r["name"] for r in returns)
        assert return_names == ["Bus Comp", "Drum Room", "Vocal Verb"], return_names

        # Drums track has clips for intro / verse / chorus / outro
        # — verse appears twice (occurrence=1, occurrence=2) and chorus
        # appears three times (occurrence=1, 2, 3) in DIFFERENT slots.
        drums_id = tracks_by_name["01 Drums"]["id"]
        drum_clips = Q.get_clips_for_track(conn, drums_id)
        roles = sorted([c["section_role"] for c in drum_clips])
        # 1 intro + 2 verse + 3 chorus + 1 outro = 7 clips
        assert len(drum_clips) == 7, [(c["name"], c["slot"]) for c in drum_clips]
        assert roles.count("verse") == 2, roles
        assert roles.count("chorus") == 3, roles
        assert roles.count("intro") == 1, roles
        assert roles.count("outro") == 1, roles

        # Arrangement entries: 8 sections * (varying track counts).
        # Each section places its participating tracks' clips. Intro: drums+bass=2.
        # Verse (each): drums+bass=2. Chorus (each): drums+bass+keys+backing_vox=4.
        # Bridge: keys only=1. Outro: drums+bass=2.
        # Total = 2 + 2 + 4 + 2 + 4 + 1 + 4 + 2 = 21.
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) == 21, [(a["start_bar"], a["end_bar"]) for a in arr]

        # Tempo + signature.
        tempo = Q.get_tempo_map(conn, song_id)
        assert len(tempo) == 1
        assert tempo[0]["tempo_bpm"] == 108.0

        sig = Q.get_time_signature_map(conn, song_id)
        assert len(sig) == 1
        assert sig[0]["numerator"] == 4 and sig[0]["denominator"] == 4

        # Cue points — 8 total, including 3 with name="chorus" and 2 named
        # "verse". This is the canary's repeated-name surface area for cues.
        cues = Q.get_cue_points(conn, song_id)
        assert len(cues) == 8
        cue_names = [c["name"] for c in cues]
        assert cue_names.count("chorus") == 3, cue_names
        assert cue_names.count("verse") == 2, cue_names

        # Envelopes — 0. The canary's brief named two envelope targets
        # (master fade-out + lead-vocal sidechain ducking) and Wave 0
        # surfaced both as architectural blockers. W10-F refuses these
        # at the DB-mutator layer (D2 master / D3 audio-track). The
        # build no longer attempts them; the v1 canary documents the
        # refusal via the build's docstrings + the ableton://guides/gaps
        # Group-D entries. v1.1 will demo the sub-bus workaround.
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) == 0, [e["target_kind"] for e in envs]

        # Total notes: reasonable upper bound (this is not a dense song).
        total = 0
        for t in tracks:
            for c in Q.get_clips_for_track(conn, t["id"]):
                total += len(Q.get_notes_for_clip(conn, c["id"]))
        assert total >= 100, f"expected >= 100 notes total, got {total}"
        assert total <= 5000, f"expected <= 5000 notes total, got {total}"
    finally:
        conn.close()


def test_repeated_sections_have_distinct_clip_slots(build_module):
    """Repeated verse/chorus sections use distinct clip slots — the canary's
    workaround for the (track_id, slot) uniqueness constraint."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        drums_id = next(t["id"] for t in tracks if t["name"] == "01 Drums")
        clips = Q.get_clips_for_track(conn, drums_id)
        # Slots used by drum clips. We expect:
        #   1 intro, 2 verse#1, 3 chorus#1, 5 verse#2, 6 chorus#2,
        #   7 chorus#3, 8 outro. (Slot 4 is reserved for bridge but drums
        #   don't play in bridge.)
        slots = sorted(c["slot"] for c in clips)
        # 7 distinct slots, no duplicates.
        assert len(slots) == len(set(slots)), f"slot collisions: {slots}"
        assert slots == [1, 2, 3, 5, 6, 7, 8], slots
    finally:
        conn.close()


def test_audio_tracks_have_no_clips_no_devices_no_problem(build_module):
    """Audio tracks (rhythm guitar, lead guitar, lead vocal, parallel-comp
    bus) exist as placeholders with NO clips. Verify the build doesn't
    crash and tracks remain queryable."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        audio_names = ["03 Rhythm Guitar", "04 Lead Guitar",
                       "07 Lead Vocal", "08 Parallel Comp Bus"]
        for name in audio_names:
            t = next((t for t in tracks if t["name"] == name), None)
            assert t is not None, f"missing audio track: {name}"
            assert t["kind"] == "audio"
            # No MIDI clips on audio tracks.
            assert Q.get_clips_for_track(conn, t["id"]) == [] \
                or len(Q.get_clips_for_track(conn, t["id"])) == 0
    finally:
        conn.close()
