"""Build missing into a SQLite DB using the hallucinote layer.

'missing' renders loss of purpose as a harmonic constraint: every chord is voiced without its root, so the tonal foundation is literally absent. In E harmonic minor (i-V-iv = Em-B7-Am, voiced rootless), the raised-7th leading tone D# pulls the ear toward an E that never arrives. The narrator is lost, searching for a ground that isn't there; the choruses, where pop form promises arrival, deny it twice. The break is a FALSE SUMMIT: the song slips into its own bright G-major illusion and the narrator believes they have found their purpose, until the pivot chord B7 reintroduces D#, collapses the illusion, and the last verse disabuses them. Only at the very end does the root return: a sub-oscillator E swells up from the empty bottom octave as the melody lands on E for the first time. Found, finally, meaning located rather than happy. Energetic (100 bpm, pulsing arp) with one structural wound. Theme is LOSS OF PURPOSE, not loss of a person.

Section bar layout (1-based, 4/4 throughout — adjust if non-4/4):
    intro        bars  1-8    (8 bars)
    verse1       bars  9-16   (8 bars)
    chorus1      bars 17-24   (8 bars)
    verse2       bars 25-32   (8 bars)
    chorus2      bars 33-40   (8 bars)
    break        bars 41-48   (8 bars)
    verse3       bars 49-56   (8 bars)
    finalchorus  bars 57-64   (8 bars)
    coda         bars 65-72   (8 bars)

Run:
    python songs/missing/build.py            # state-converger: re-run is no-op if nothing changed
    python songs/missing/build.py --reset    # drop + rebuild from scratch
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path

# Per-branch DB filename (W12-A): branch switches pick up the right DB
# silently; outside a repo / detached HEAD falls back to missing.db.
DB_PATH = resolve_db_path("missing", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"


# ---------------------------------------------------------------------------
# Section bar boundaries (1-based) — adjust as the song grows
# ---------------------------------------------------------------------------
INTRO_BAR = 1
VERSE1_BAR = 9
CHORUS1_BAR = 17
VERSE2_BAR = 25
CHORUS2_BAR = 33
BREAK_BAR = 41
VERSE3_BAR = 49
FINALCHORUS_BAR = 57
CODA_BAR = 65
END_BAR = 73


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id (UUID hex).

    W12-A: this is a state-converger. Re-running with no source changes is
    a no-op (zero net events). Mutators inside `build_session` are
    idempotent — second call with identical args returns kind='unchanged'.
    Build-owned rows from a prior build that aren't touched this run get
    tombstoned automatically at session exit. Pulled rows (actor='sync')
    and LLM-authored edits survive.

    `--reset` is a soft reset (W18-C): wipes rebuild-by-build.py content
    (clips, notes, arrangement, sections, tempo/meter maps, cue points,
    envelopes) but preserves the mix layout (tracks, returns, devices,
    sends) AND the Ableton projection (`ableton_sessions` + `ableton_links`).
    The session_id presented to a push session survives the natural
    compose-iterate loop. For a full clean slate (drop bindings too),
    delete the DB file directly.
    """
    conn = init_db(DB_PATH)
    try:
        if reset:
            song = Q.get_song_by_name(conn, "missing")
            if song is not None:
                M.reset_song_content(conn, song_id=song["id"])
        with M.build_session(conn, song_name="missing", owner="build.py"):
            # Mix-half: replay the captured (or synthetic) Ableton session.
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            song_id = replay_capture(
                conn, snapshot,
                song_name="missing",
                song_title="missing",
                song_key='Em',
                actor="sync", reason="initial capture replay",
            )

            # Score-half: tempo, meter, sections, cue points.
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(
                conn, song_id=song_id, start_bar=1.0, tempo_bpm=100.0,
            )
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0,
                numerator=4, denominator=4,
            )

            # Section markers.
            M.create_section(
                conn, song_id=song_id, name='intro',
                start_bar=float(INTRO_BAR),
                end_bar=float(VERSE1_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse1',
                start_bar=float(VERSE1_BAR),
                end_bar=float(CHORUS1_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='chorus1',
                start_bar=float(CHORUS1_BAR),
                end_bar=float(VERSE2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse2',
                start_bar=float(VERSE2_BAR),
                end_bar=float(CHORUS2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='chorus2',
                start_bar=float(CHORUS2_BAR),
                end_bar=float(BREAK_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='break',
                start_bar=float(BREAK_BAR),
                end_bar=float(VERSE3_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse3',
                start_bar=float(VERSE3_BAR),
                end_bar=float(FINALCHORUS_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='finalchorus',
                start_bar=float(FINALCHORUS_BAR),
                end_bar=float(CODA_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='coda',
                start_bar=float(CODA_BAR),
                end_bar=float(END_BAR),
            )

            # Cue points at every section boundary.
            for bar, name in [(INTRO_BAR, 'intro'), (VERSE1_BAR, 'verse1'), (CHORUS1_BAR, 'chorus1'), (VERSE2_BAR, 'verse2'), (CHORUS2_BAR, 'chorus2'), (BREAK_BAR, 'break'), (VERSE3_BAR, 'verse3'), (FINALCHORUS_BAR, 'finalchorus'), (CODA_BAR, 'coda')]:
                M.add_cue_point(
                    conn, song_id=song_id,
                    position_bar=float(bar), name=name,
                )

            tracks = _tracks_by_name(conn, song_id)

            # === Compose-half: author your clips here ===
            #
            # Use library generators where they fit (`hallucinote.generators.*`),
            # hand-author NoteDict lists where you need precision, then drop
            # them into clips via `M.create_clip(...)` + `M.replace_clip_notes(...)`.
            # Place clips in time with `M.add_arrangement_clip(...)`.
            #
            # See songs/falling-walking/build.py for a worked example —
            # but note that falling-walking is historical, not a literal
            # template. Generators accept a `beats_per_bar` kwarg (W14-B)
            # so bar iteration scales through non-4/4 sections; within-bar
            # layout still assumes a 4/4 shape, so hand-author non-4/4
            # patterns where that matters.

        return song_id
    finally:
        conn.close()


def report(song_id: str) -> None:
    """Print a summary of what got built."""
    conn = init_db(DB_PATH)
    try:
        song_row = Q.get_song(conn, song_id)
        tracks = Q.get_tracks_for_song(conn, song_id)
        print(f"song_id={song_id}, timing_mode={song_row['timing_mode']}, "
              f"tracks={len(tracks)}")
        total_notes = 0
        for t in tracks:
            clips = Q.get_clips_for_track(conn, t["id"])
            notes_in_track = sum(len(Q.get_notes_for_clip(conn, c["id"])) for c in clips)
            total_notes += notes_in_track
            print(f"  track {t['track_index']:>2}  {t['name']:<24} "
                  f"({t['kind']}, {len(clips)} clips, {notes_in_track} notes)")
        sections = [s["name"] for s in Q.get_sections_for_song(conn, song_id)]
        print(f"total notes: {total_notes}")
        print(f"sections: {sections}")
    finally:
        conn.close()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    song_id = build(reset=reset)
    report(song_id)
