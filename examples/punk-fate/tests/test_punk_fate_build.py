"""Shape test for punk-fate's build.py.

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
    spec = importlib.util.spec_from_file_location("punk_fate_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "punk-fate.db")
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
        assert section_names == ['intro-fate', 'verse-cm', 'chorus-eb', 'break-ab', 'scherzo-cm', 'bridge-pedal', 'finale-cmaj', 'coda']

        # Tracks — 4 from synthetic snapshot + master.
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) >= 5  # 4 + master, more once you author

        # Tempo + time signature points exist.
        tempo = Q.get_tempo_map(conn, song_id)
        assert len(tempo) >= 1
        assert tempo[0]["tempo_bpm"] == 200.0

        sig = Q.get_time_signature_map(conn, song_id)
        assert len(sig) >= 1
        assert (sig[0]["numerator"], sig[0]["denominator"]) == (4, 4)
    finally:
        conn.close()


def test_performance_is_identical_across_SEPARATE_processes(tmp_path):
    """The build must produce byte-identical notes in a fresh interpreter.

    This has to run in subprocesses to mean anything. Python salts `hash()` per
    PROCESS, so a build that used `hash()` for its scatter would still be
    perfectly self-consistent within one interpreter — the idempotence test
    below would pass, and the state-converger promise would still be broken the
    moment anyone rebuilt tomorrow. `_rand`/`_seed` use blake2b precisely to
    avoid that, and only a cross-process comparison can catch a regression.

    PYTHONHASHSEED is varied between the two runs so a `hash()`-based
    implementation is guaranteed to diverge rather than coincidentally agree.
    """
    import os
    import subprocess
    import sys

    script = (
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('pf', {str(BUILD_PATH)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "m.DB_PATH = __import__('pathlib').Path(sys.argv[1])\n"
        "song_id = m.build(reset=True)\n"
        "from hallucinote.db import init_db, queries as Q\n"
        "conn = init_db(m.DB_PATH)\n"
        "rows = []\n"
        "for t in Q.get_tracks_for_song(conn, song_id):\n"
        "    for c in Q.get_clips_for_track(conn, t['id']):\n"
        "        for n in Q.get_notes_for_clip(conn, c['id']):\n"
        "            rows.append([t['name'], c['name'], n['pitch'],\n"
        "                         n['start_beats'], n['duration_beats'], n['velocity']])\n"
        "rows.sort()\n"
        "print(json.dumps(rows))\n"
    )

    def run(db_name: str, hashseed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / db_name)],
            capture_output=True, text=True, env=env, timeout=600,
        )
        assert proc.returncode == 0, f"build subprocess failed:\n{proc.stderr[-3000:]}"
        return proc.stdout.strip().splitlines()[-1]

    first = run("a.db", "0")
    second = run("b.db", "12345")
    assert first == second, (
        "two builds in separate interpreters produced different notes — the "
        "performance is not reproducible, so `build.py` is no longer a state "
        "converger. Most likely a scatter/seed source was changed to something "
        "process-dependent (e.g. the builtin `hash()`, `random` without a seed, "
        "or a timestamp)."
    )


def test_no_clip_double_triggers_the_same_pitch(build_module):
    """One drum, one hit at a time.

    Per-note timing scatter turned a latent collision into a real one: `_fill`
    and `_punk_beat` both write a snare on beat 3 of the fill bar, and once the
    two stopped landing on an identical tick they became a ~5 ms overlap. Live
    cannot hold two overlapping same-pitch notes in a clip, so it merged them
    and the push's arrangement integrity assert failed. `_one_hit_at_a_time`
    collapses those; this locks it, because the symptom appears only at push
    time and the build itself reports success either way.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        offenders = []
        for track in Q.get_tracks_for_song(conn, song_id):
            for clip in Q.get_clips_for_track(conn, track["id"]):
                by_pitch: dict[int, list[float]] = {}
                for note in Q.get_notes_for_clip(conn, clip["id"]):
                    by_pitch.setdefault(note["pitch"], []).append(note["start_beats"])
                for pitch, starts in by_pitch.items():
                    starts.sort()
                    for earlier, later in zip(starts, starts[1:]):
                        if later - earlier < build_module.MIN_RETRIGGER_BEATS:
                            offenders.append(
                                f"{clip['name']} pitch {pitch} at "
                                f"{earlier:.4f} + {later:.4f} "
                                f"({later - earlier:.4f} beats apart)"
                            )
        assert not offenders, (
            f"{len(offenders)} same-pitch note(s) retrigger within "
            f"{build_module.MIN_RETRIGGER_BEATS} beats — Live will merge these "
            "and the arrangement integrity assert will fail on push:\n  "
            + "\n  ".join(offenders[:10])
        )
    finally:
        conn.close()


def test_no_note_sounds_past_its_own_retrigger(build_module):
    """A note must end before the same pitch starts again.

    The duration half of "one hit at a time", and it needs its own test: the
    onset test above never reads `duration_beats`, so it passes identically
    whether `_no_same_pitch_overlap` runs or not.

    This is not cosmetic. A Live clip cannot hold two overlapping same-pitch
    notes — it truncates the earlier one — so an overlap the DB stores is a
    duration the renderer silently discards, and the DB stops describing what
    plays. `_chug` caps its duration scatter against the *authored* onset gap,
    but the performance breathing then moves adjacent onsets relative to each
    other, which can reopen an overlap the cap had closed; the guard runs after
    the breathing for that reason.
    """
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        offenders = []
        for track in Q.get_tracks_for_song(conn, song_id):
            for clip in Q.get_clips_for_track(conn, clip_track := track["id"]):
                by_pitch: dict[int, list[tuple[float, float]]] = {}
                for note in Q.get_notes_for_clip(conn, clip["id"]):
                    by_pitch.setdefault(note["pitch"], []).append(
                        (note["start_beats"], note["duration_beats"]))
                for pitch, events in by_pitch.items():
                    events.sort()
                    for (start, dur), (next_start, _) in zip(events, events[1:]):
                        if start + dur > next_start:
                            offenders.append(
                                f"{clip['name']} pitch {pitch}: note at {start:.4f} "
                                f"runs {dur:.4f} beats (ends {start + dur:.4f}) but "
                                f"the same pitch retriggers at {next_start:.4f}"
                            )
        assert not offenders, (
            f"{len(offenders)} note(s) still sounding when their own pitch "
            "retriggers — Live will truncate these, so the DB no longer "
            "describes what the renderer plays:\n  " + "\n  ".join(offenders[:10])
        )
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
