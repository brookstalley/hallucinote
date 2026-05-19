"""Shape assertions for odd-meter-experimental build.py.

Stresses 7/8 base meter, 5-against-7 polyrhythm bass positions, mid-section
meter ratchet (7/8 -> 5/8 -> 6/8 -> 7/8 across the fracture section), and the
non-integer beat positions the polyrhythm produces. Specifically does NOT use
the falling-walking '4/4 = bars*4 = beats' implicit math.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

SONG_ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = SONG_ROOT / "build.py"


@pytest.fixture
def build_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("odd_meter_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "odd-meter-experimental.db")
    return module


def test_build_runs_clean_and_produces_canary_shape(build_module):
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Five sections in declared order.
        sections = Q.get_sections_for_song(conn, song_id)
        names = [s["name"] for s in sections]
        assert names == ["intro", "lock", "bloom", "fracture", "release"]

        # 6 MIDI tracks + master = 7.
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) == 7
        names_set = {t["name"] for t in tracks}
        for expected in [
            "01 Drums", "02 Polyrhythm Bass", "03 Harmonic Pad",
            "04 Arpeggio", "05 Bell Accents", "06 Perc Click",
        ]:
            assert expected in names_set, f"missing track {expected!r}"

        # One return (Reverb).
        returns = Q.get_returns_for_song(conn, song_id)
        assert [r["name"] for r in returns] == ["Reverb"]

        # Envelope exists with breakpoints.
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) >= 1
        for e in envs:
            bps = Q.get_breakpoints(conn, envelope_id=e["id"])
            assert bps, f"envelope {e['id']} has no breakpoints"
    finally:
        conn.close()


def test_time_signature_map_has_meter_ratchet(build_module):
    """The fracture section authors per-bar time_signature_map points.

    THIS IS THE CANARY for the v1 question: does the DB even MODEL within-section
    meter changes? Test asserts the DB rows exist; push planner skips them.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        ts_pts = Q.get_time_signature_map(conn, song_id)
        # Should have: bar 1 (7/8) + 8 fracture bars (varying) + bar 49 (7/8) = 10.
        assert len(ts_pts) >= 10, (
            f"expected >=10 time_signature_map rows for the meter ratchet, "
            f"got {len(ts_pts)}"
        )

        # Bar 1 = 7/8.
        bar1 = next(p for p in ts_pts if p["start_bar"] == 1.0)
        assert (bar1["numerator"], bar1["denominator"]) == (7, 8)

        # Fracture bars 41..48 cycle (7,7,5,5,6,6,7,7).
        expected_cycle = [(7, 8), (7, 8), (5, 8), (5, 8),
                          (6, 8), (6, 8), (7, 8), (7, 8)]
        for i, (en, ed) in enumerate(expected_cycle):
            bar = float(41 + i)
            p = next(p for p in ts_pts if p["start_bar"] == bar)
            assert (p["numerator"], p["denominator"]) == (en, ed), (
                f"bar {bar} expected {en}/{ed} got {p['numerator']}/{p['denominator']}"
            )

        # Release returns to 7/8 at bar 49.
        rel = next(p for p in ts_pts if p["start_bar"] == 49.0)
        assert (rel["numerator"], rel["denominator"]) == (7, 8)
    finally:
        conn.close()


def test_polyrhythm_bass_positions_are_5_against_7(build_module):
    """Lock-section bass clip must have 5 notes per bar at non-integer beat positions.

    Stores the canonical 5-against-7 offsets (eighth-units: 0, 1.4, 2.8, 4.2, 5.6
    divided by 2 -> beats: 0.0, 0.7, 1.4, 2.1, 2.8). DB stores REAL — assert
    we can read them back within float tolerance.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        # Find the Lock Polyrhythm Bass clip.
        tracks = Q.get_tracks_for_song(conn, song_id)
        bass_track = next(t for t in tracks if t["name"] == "02 Polyrhythm Bass")
        clips = Q.get_clips_for_track(conn, bass_track["id"])
        lock_clip = next(c for c in clips if c["section_role"] == "lock")

        notes = Q.get_notes_for_clip(conn, lock_clip["id"])
        # 16 bars × 5 notes = 80 notes.
        assert len(notes) == 80, f"expected 80 polyrhythm notes, got {len(notes)}"

        # The first bar's 5 notes should be at the canonical offsets.
        notes_sorted = sorted(notes, key=lambda n: n["start_beats"])
        first_5 = notes_sorted[:5]
        expected_offsets = [0.0, 0.7, 1.4, 2.1, 2.8]
        for i, n in enumerate(first_5):
            assert math.isclose(n["start_beats"], expected_offsets[i], abs_tol=1e-9), (
                f"polyrhythm bass note {i} at {n['start_beats']!r}, "
                f"expected {expected_offsets[i]!r}"
            )

        # CANARY FINDING: In 7/8, beats-per-bar = 3.5 (non-integer). So even
        # the BAR DOWNBEATS land at non-integer cumulative-beat positions for
        # odd-numbered bars. Bar 0 starts at 0.0 (int). Bar 1 starts at 3.5
        # (non-int). Bar 2 starts at 7.0 (int). Bar 3 at 10.5 (non-int).
        # 16 bars / 2 = 8 even-bar downbeats. The 5-against-7 offsets (0.0,
        # 0.7, 1.4, 2.1, 2.8) added to those starts give back integer positions
        # only when the bar start is integer AND the offset is integer (offset 0).
        # Net result: EXACTLY 8 integer-beat notes — one per even bar's
        # downbeat. This is a significant finding for any UI / analysis tool
        # that assumes "downbeats land on integer beats" in non-4/4 meters.
        ints = sum(1 for n in notes if abs(n["start_beats"] - round(n["start_beats"])) < 1e-9)
        assert ints == 8, (
            f"expected exactly 8 integer-beat notes (one per EVEN bar's "
            f"downbeat — odd 7/8 bars start at non-integer cumulative beats), "
            f"got {ints}"
        )
    finally:
        conn.close()


def test_polyrhythm_bass_positions_round_trip_precision(build_module):
    """DB REAL storage must preserve 5-against-7 offsets to better than 1e-6.

    This is the precision question the canary brief flags: "What precision
    does the DB preserve when you query the notes back?" If REAL loses
    precision, 0.7 stored and re-read becomes 0.7000000000000001 or worse —
    still within 1e-6 for IEEE 754 doubles, but worth asserting explicitly.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        bass_track = next(t for t in tracks if t["name"] == "02 Polyrhythm Bass")
        clips = Q.get_clips_for_track(conn, bass_track["id"])
        lock_clip = next(c for c in clips if c["section_role"] == "lock")
        notes = sorted(
            Q.get_notes_for_clip(conn, lock_clip["id"]),
            key=lambda n: n["start_beats"],
        )

        # For every bar, the 5 notes should land at bar*3.5 + offsets exactly.
        # Half-open windowing [bar_start, bar_start + BEATS_PER_BAR) so the next
        # bar's downbeat doesn't bleed in.
        BEATS_PER_BAR = 3.5
        OFFSETS = [0.0, 0.7, 1.4, 2.1, 2.8]
        max_err = 0.0
        for bar in range(16):
            bar_start = bar * BEATS_PER_BAR
            bar_end = bar_start + BEATS_PER_BAR
            bar_notes = [n for n in notes
                         if bar_start - 1e-9 <= n["start_beats"] < bar_end - 1e-9]
            assert len(bar_notes) == 5, f"bar {bar}: expected 5, got {len(bar_notes)}"
            for i, n in enumerate(bar_notes):
                expected = bar_start + OFFSETS[i]
                err = abs(n["start_beats"] - expected)
                max_err = max(max_err, err)
        assert max_err < 1e-9, f"DB beat-position precision drift: max err = {max_err}"
    finally:
        conn.close()


def test_fracture_clip_lengths_match_meter_ratchet(build_module):
    """The fracture section's clip length must equal the sum of bar lengths
    in the meter ratchet (NOT the naive 8 * 3.5 = 28.0 a 4/4-thinker would expect)."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        drums = next(t for t in tracks if t["name"] == "01 Drums")
        fracture_clip = next(
            c for c in Q.get_clips_for_track(conn, drums["id"])
            if c["section_role"] == "fracture"
        )
        # Ratchet sum: (7+7+5+5+6+6+7+7)/2 = 50/2 = 25.0 beats.
        expected = 25.0
        assert math.isclose(fracture_clip["length_beats"], expected, abs_tol=1e-9), (
            f"fracture clip length: {fracture_clip['length_beats']}, expected {expected}"
        )

        # NOT the naive 8 bars * 3.5 = 28.0 (which would be true if the
        # fracture stayed in 7/8).
        assert fracture_clip["length_beats"] != 28.0
    finally:
        conn.close()


def test_fracture_bass_offsets_depend_on_each_bars_length(build_module):
    """In the fracture section, the polyrhythm bass plays 5 notes per bar but
    the spacing depends on each bar's meter (since bars are different lengths).

    Asserts that the bass note at offset 2 of bar 3 (a 5/8 bar) sits at
    cumulative_beats(bars_0..2) + (5/5)*2*(0.5) = cum + 1.0 — NOT cum + 1.4.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        bass = next(t for t in tracks if t["name"] == "02 Polyrhythm Bass")
        fracture_bass_clip = next(
            c for c in Q.get_clips_for_track(conn, bass["id"])
            if c["section_role"] == "fracture"
        )
        notes = sorted(
            Q.get_notes_for_clip(conn, fracture_bass_clip["id"]),
            key=lambda n: n["start_beats"],
        )
        # 8 bars × 5 notes = 40.
        assert len(notes) == 40, f"expected 40 fracture bass notes, got {len(notes)}"

        # Bar 0 (7/8): offsets 0.0, 0.7, 1.4, 2.1, 2.8 (cumulative starts at 0).
        # Bar 1 (7/8): cum=3.5, offsets +0, +0.7, +1.4, +2.1, +2.8.
        # Bar 2 (5/8): cum=7.0, offsets +0, (5/5)*0.5=0.5, 1.0, 1.5, 2.0.
        # Bar 3 (5/8): cum=9.5, offsets +0, +0.5, +1.0, +1.5, +2.0.
        # Bar 4 (6/8): cum=12.0, offsets +0, (6/5)*0.5=0.6, 1.2, 1.8, 2.4.
        bar_starts = [0.0, 3.5, 7.0, 9.5, 12.0, 15.0, 18.0, 21.5]
        eighths_per_bar = [7, 7, 5, 5, 6, 6, 7, 7]

        for bar_idx, bar_start in enumerate(bar_starts):
            ne = eighths_per_bar[bar_idx]
            bar_notes = [
                n for n in notes
                if bar_start - 1e-9 <= n["start_beats"] < bar_start + ne * 0.5 - 1e-9
            ]
            assert len(bar_notes) == 5, (
                f"fracture bar {bar_idx} ({ne}/8): expected 5 bass notes, got {len(bar_notes)}"
            )
            for k, n in enumerate(bar_notes):
                expected = bar_start + (ne / 5.0) * k * 0.5
                assert math.isclose(n["start_beats"], expected, abs_tol=1e-9), (
                    f"fracture bar {bar_idx} ({ne}/8), note {k}: "
                    f"got {n['start_beats']}, expected {expected}"
                )
    finally:
        conn.close()


def test_does_NOT_assume_4_4_bars_times_4_equals_beats(build_module):
    """Counter-test calling out the implicit 4/4 assumption in falling-walking's test.

    falling-walking's tests use patterns like `bars * 4 == beats`. In 7/8 that
    is wrong: bars * 3.5 == beats. This test documents the canary-side
    convention by asserting the WRONG identity is false.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, song_id)
        click = next(t for t in tracks if t["name"] == "06 Perc Click")
        intro_click = next(
            c for c in Q.get_clips_for_track(conn, click["id"])
            if c["section_role"] == "intro"
        )
        # 8 bars * 7 eighths each = 56 hits = 56 notes.
        notes = Q.get_notes_for_clip(conn, intro_click["id"])
        assert len(notes) == 56

        # And the clip's length is 28.0 beats — NOT 32.0 (which would be
        # 8 * 4.0 under a 4/4 mental model).
        assert intro_click["length_beats"] == 28.0
        assert intro_click["length_beats"] != 32.0
    finally:
        conn.close()
