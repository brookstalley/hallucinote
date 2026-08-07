"""Shape test for angle-of-the-light's build.py.

W12-A: build.py is a state-converger — re-running with no source changes
produces zero net state-change events. `test_build_is_idempotent_state_converger`
locks that promise; shape assertions lock what the build minimally produces.

Filename convention: per-song test names MUST be unique across all songs
(see pyproject.toml). Use `test_<slug>_build.py`, not bare `test_build.py`.
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
    spec = importlib.util.spec_from_file_location("angle_of_the_light_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "angle-of-the-light.db")
    return module


def test_build_runs_clean_and_produces_shape(build_module):
    """Running build(--reset) populates the scaffold's structure."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Sections — scaffold-defined; tighten as the song matures.
        sections = Q.get_sections_for_song(conn, song_id)
        section_names = [s["name"] for s in sections]
        assert section_names == ['intro', 'verse', 'riser', 'bridge', 'chorus', 'chorus-reprise', 'outro']

        # Twelve authored tracks + master. Each owns a section the others
        # cannot cover; see decisions/04-signal-chains.md.
        tracks = Q.get_tracks_for_song(conn, song_id)
        by_name = {t["name"] for t in tracks}
        assert {"Sub", "Bass", "Kit Rock", "Perc", "Machine", "Keys",
                "Brass Stab", "Brass Sustain", "Bells", "Pad", "Lead",
                "FX"} <= by_name, f"missing authored track(s): {by_name}"

        # Tempo + time signature points exist.
        tempo = Q.get_tempo_map(conn, song_id)
        assert len(tempo) >= 1
        assert tempo[0]["tempo_bpm"] == 144.0

        sig = Q.get_time_signature_map(conn, song_id)
        assert len(sig) >= 1
        assert (sig[0]["numerator"], sig[0]["denominator"]) == (1, 4)
    finally:
        conn.close()


def test_build_is_idempotent_state_converger(build_module):
    """W12-A: re-running the build over an existing DB produces zero net
    state-change events. The load-bearing converger promise."""
    from hallucinote.db import init_db

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        state_events_first = len([
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ])
    finally:
        conn.close()

    # Second build — no reset, expect zero new state-change events.
    song_id_2 = build_module.build(reset=False)
    assert song_id_2 == song_id

    conn = init_db(build_module.DB_PATH)
    try:
        state_events_after = len([
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ])
        assert state_events_after == state_events_first, (
            f"Re-running build produced {state_events_after - state_events_first} "
            f"extra state-change events — converger discipline broken."
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The thesis, as an executable assertion
#
# These do not test the ENGINE — they test that the song still means what it
# was written to mean. build.py's harmonic-spine comment promises exactly this
# assertion exists; a promise in a durable comment with no mechanism behind it
# is an assertion wearing the costume of a record.
# ---------------------------------------------------------------------------


def _pitch_classes(chord) -> set[int]:
    return {(chord.root_pc + i) % 12 for i in chord.intervals}


def test_doubt_and_triumph_are_the_same_pitch_class_set(build_module):
    """The whole song in one line.

    The intro's most stressful chord and the chorus's most radiant chord are
    the same five pitches; only the bass moves, by a tritone. If an edit ever
    breaks this, the piece has stopped arguing what it was written to argue —
    and nothing else in the suite would notice, because both chords would
    still be individually valid and the song would still build and play.
    """
    doubt = _pitch_classes(build_module.DOUBT)
    triumph = _pitch_classes(build_module.TRIUMPH)
    assert doubt == triumph == {0, 2, 3, 5, 8}, (  # C D Eb F Ab
        f"transfiguration broken: doubt={sorted(doubt)} "
        f"triumph={sorted(triumph)}"
    )
    # ...and they must not be the same CHORD — the bass is the whole move.
    assert build_module.DOUBT.root_pc != build_module.TRIUMPH.root_pc
    interval = (build_module.TRIUMPH.root_pc - build_module.DOUBT.root_pc) % 12
    assert interval == 6, f"the bass must move by tritone, moved {interval}"


def test_outro_reveal_reuses_the_chorus_voicing_note_for_note(build_module):
    """The reveal works only if the chord is literally unchanged.

    Re-voicing it 'to taste' would break the argument while sounding fine,
    which is exactly the kind of edit a listening test does not catch.
    """
    import inspect

    src = inspect.getsource(build_module._outro)
    assert "_TRIUMPH_VOICING" in src, (
        "the outro must reuse the chorus voicing object, not restate its "
        "pitches — a copy can drift, and the identity IS the point"
    )


def test_song_length_sits_inside_the_brief_window(build_module):
    """45-60 s was the brief. 110 beats at 144 BPM is 45.8 s."""
    beats = build_module.END_BAR - build_module.INTRO_BAR
    seconds = beats * 60.0 / 144.0
    assert beats == 110
    assert 45.0 <= seconds <= 60.0, f"{seconds:.1f}s is outside the brief"


def test_progression_covers_the_whole_song_with_no_gaps(build_module):
    """Every beat has a declared harmony, and the timeline ends where the
    song does. A gap here is a section composing against nothing."""
    changes = sorted(build_module.progression().changes,
                     key=lambda c: c.start_beat)
    assert changes[0].start_beat == 0.0
    cursor = 0.0
    for ch in changes:
        assert ch.start_beat <= cursor + 1e-6, (
            f"harmonic gap before beat {ch.start_beat}")
        cursor = max(cursor, ch.start_beat + ch.duration_beats)
    assert cursor == float(build_module.END_BAR - 1), (
        f"progression ends at {cursor}, song ends at "
        f"{build_module.END_BAR - 1}")


def test_bridge_is_exactly_quantized(build_module):
    """The bridge's inhumanity is load-bearing (decisions/03).

    Every other section is pushed or dragged; this one must sit dead on the
    grid, so a stray humanise pass here would quietly remove the contrast the
    section exists to create.
    """
    import inspect

    src = inspect.getsource(build_module._bridge)
    assert "push(" not in src, (
        "the bridge must contain no push() calls — the absence of a human "
        "hand is what makes it grim"
    )
