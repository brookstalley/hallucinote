"""Build solo-piano-ambient into a SQLite DB using the hallucinote layer.

Canary Wave 0 song. Exercises:
  - Long-envelope authoring (send-A reverb ramp spans bloom+recede ~32 bars).
  - Empty-arrangement section (`silence` has no clips on any track).
  - Single-track sparsity (one MIDI track + two returns + master).
  - Slow tempo (60 BPM, MM=60).
  - Sustained whole-note chords with intentional overlap across bar lines.
  - Send-bus envelope on Send A.

Section bar layout (1-based, inclusive start / exclusive end):
    prelude  bars  1- 9   ( 8 bars / 32 beats)
    bloom    bars  9-33   (24 bars / 96 beats)
    recede   bars 33-49   (16 bars / 64 beats)
    silence  bars 49-57   ( 8 bars / 32 beats — intentional rest)

Run:
    python3 songs/solo-piano-ambient/build.py --reset
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.generators import harmony
from hallucinote.generators.envelopes import volume_swell
from hallucinote.generators.output import GeneratorOutput

# Per-branch DB path so feature branches don't clobber each other's state.
# Convention matches `falling-walking/build.py`.
DB_PATH = resolve_db_path("solo-piano-ambient", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

# Section bar boundaries (1-based; end is the start of the next section).
PRELUDE_BAR = 1
BLOOM_BAR   = 9
RECEDE_BAR  = 33
SILENCE_BAR = 49
END_BAR     = 57

# C Lydian pitches (C, D, E, F#, G, A, B). MIDI numbers.
# Voicing centers around C4 = 60.
C3, D3, E3, F3S, G3, A3, B3 = 48, 50, 52, 54, 55, 57, 59
C4, D4, E4, F4S, G4, A4, B4 = 60, 62, 64, 66, 67, 69, 71
C5, D5, E5, F5S, G5         = 72, 74, 76, 78, 79

# Long sustained chord voicings (open quartal-ish stacks in Lydian colour).
# Each chord is intentionally LONG (>= 4 beats / 1 bar) and may overlap bar
# boundaries via end > next chord's start, to exercise legato note handling.
CHORD_I       = [C3, G3, C4, E4, G4]            # C major (Lydian I)
CHORD_II      = [D3, A3, D4, F4S, A4]           # D major (Lydian II)
CHORD_V       = [G3, D4, G4, B4, D5]            # G major (Lydian V)
CHORD_LYDIAN  = [C3, F4S, G4, B4, E5]           # the #4 colour chord

# Sparse melodic motifs (Lydian noodling). Single notes separated by rests.
PRELUDE_MOTIF = [
    # (pitch, start_beat, duration_beats, velocity)
    (C5,  0.0,  4.0, 45),   # bar 1 beat 1, whole note
    (G4,  8.0,  3.0, 38),   # bar 3 beat 1, dotted-half
    (E4, 14.0,  2.0, 42),   # bar 4 beat 3, half note
    (F5S, 20.0, 4.0, 48),   # bar 6 beat 1, whole — the Lydian #4 colour
    (D5, 28.0,  3.0, 35),   # bar 8 beat 1, dotted-half — fades into bloom
]

RECEDE_MOTIF = [
    # Returning motifs, fading dynamics. (pitch, start_beat, duration, vel)
    (G5,   0.0,  2.0, 50),   # bar 33 — bright top
    (E5,   4.0,  4.0, 42),
    (C5,  12.0,  3.0, 36),
    (A4,  20.0,  4.0, 32),
    (F4S, 28.0,  6.0, 28),   # Lydian #4 fading
    (D4,  40.0,  8.0, 24),   # very quiet, long tail
    (C4,  56.0,  8.0, 20),   # final whisper bar 47-48
]


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _returns_by_name(conn, song_id: str) -> dict[str, str]:
    return {row["name"]: row["id"] for row in Q.get_returns_for_song(conn, song_id)}


def _apply_envelopes(conn, song_id: str, output: GeneratorOutput,
                     *, actor: str = "generator", reason: str | None = None) -> None:
    """Persist every envelope spec in `output.envelopes` via mutators."""
    for env_spec in output.envelopes:
        spec = dict(env_spec)
        bps = spec.pop("breakpoints", [])
        env_id = M.create_envelope(
            conn, song_id=song_id, actor=actor, reason=reason, **spec,
        )
        if bps:
            M.replace_breakpoints(
                conn, envelope_id=env_id, breakpoints=bps,
                actor=actor, reason=reason,
            )


# ---------------------------------------------------------------------------
# Section authoring
# ---------------------------------------------------------------------------


def _build_prelude(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Prelude — 8 bars / 32 beats. Sparse single-note motif, pp."""
    notes = [_note(p, s, d, v) for (p, s, d, v) in PRELUDE_MOTIF]

    cid = M.create_clip(
        conn, track_id=tracks["01 Piano"], slot=1, length_beats=32.0,
        name="Prelude", section_role="prelude",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=notes)
    return {"01 Piano": cid}


def _build_bloom(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Bloom — 24 bars / 96 beats. Stacked chord pads (whole-notes), p -> mp.

    Chord changes every 4 bars (16 beats). Final chord intentionally extends
    PAST its 4-bar window via `duration_beats > 16` so the next chord overlaps
    its tail — exercises legato voice handling.
    """
    pad_notes: list[dict] = []

    # 6 chord changes over 24 bars; each chord lasts 16 beats but the LAST note
    # of each voicing extends 2 extra beats into the next chord (overlap).
    chord_sequence = [
        (0.0,  CHORD_I,      72),   # bars 1-4 of bloom (song bars 9-12)
        (16.0, CHORD_II,     76),   # bars 5-8
        (32.0, CHORD_LYDIAN, 80),   # bars 9-12 — the #4 colour arrives
        (48.0, CHORD_V,      84),   # bars 13-16
        (64.0, CHORD_LYDIAN, 88),   # bars 17-20
        (80.0, CHORD_I,      92),   # bars 21-24
    ]
    for start, voicing, base_vel in chord_sequence:
        # Each voice is a whole-note (or longer) chord block.
        # Top voice (last pitch) sustains a half-bar past the chord change.
        for i, p in enumerate(voicing):
            dur = 16.0 + (2.0 if i == len(voicing) - 1 else 0.0)
            pad_notes.append(_note(p, start, dur, base_vel))

    # Sparse melodic gesture on top — one bright Lydian #4 at bar 17 of bloom.
    pad_notes.append(_note(F5S, 64.0, 8.0, 70))

    cid = M.create_clip(
        conn, track_id=tracks["01 Piano"], slot=2, length_beats=96.0,
        name="Bloom", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    return {"01 Piano": cid}


def _build_recede(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Recede — 16 bars / 64 beats. Sparse motifs over fading pad."""
    notes: list[dict] = []

    # Fading pad: just a single Csus-like drone, decrescendo.
    notes.extend(harmony.chord_pad(
        [C3, G3, C4], start_beat=0.0, length_beats=48.0, velocity=55,
    ))
    notes.extend(harmony.chord_pad(
        [C3, G3], start_beat=48.0, length_beats=16.0, velocity=35,
    ))

    # Sparse motifs returning.
    notes.extend(_note(p, s, d, v) for (p, s, d, v) in RECEDE_MOTIF)

    cid = M.create_clip(
        conn, track_id=tracks["01 Piano"], slot=3, length_beats=64.0,
        name="Recede", section_role="recede",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=notes)
    return {"01 Piano": cid}


def _build_silence(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Silence — 8 bars / 32 beats. Intentionally empty.

    Returns an empty clips dict so the arrangement step skips this section
    entirely. This exercises the empty-section / hole case in the arrangement
    planner — there will be no `arrangement_clips` rows in this bar range.
    """
    return {}


# ---------------------------------------------------------------------------
# Arrangement + envelopes
# ---------------------------------------------------------------------------


def _arrange_section(conn, song_id: str, tracks: dict[str, str],
                     clips: dict[str, str], *, start_bar: float, end_bar: float) -> None:
    """Place every clip in `clips` on its track between start_bar and end_bar."""
    for track_name, clip_id in clips.items():
        M.add_arrangement_clip(
            conn, song_id=song_id,
            track_id=tracks[track_name], clip_id=clip_id,
            start_bar=start_bar, end_bar=end_bar,
        )


def _author_envelopes(conn, song_id: str, tracks: dict[str, str],
                      returns: dict[str, str]) -> None:
    """Author the song's automation envelopes.

    Long send-A reverb envelope across bloom + recede. Ramps reverb send from
    ~0.40 (resting) up to ~0.85 across bloom, holds, then back down through
    recede to ~0.30. This spans ~40 bars / 160 beats — exercises the long-
    envelope write path (W6) and round-trip robustness (W7).

    Also: a slow volume swell on the piano across bloom (p -> mp).
    """
    # --- Long send-A reverb envelope (the main canary target) ---
    # bloom = song bars 9-33 = beats 32-128
    # recede = song bars 33-49 = beats 128-192
    bloom_start  = (BLOOM_BAR  - 1) * 4.0   # = 32.0
    bloom_end    = (RECEDE_BAR - 1) * 4.0   # = 128.0
    recede_end   = (SILENCE_BAR - 1) * 4.0  # = 192.0

    # Hand-authored breakpoints — a long ramp with intermediate shaping points
    # to make the envelope a meaningful curve, not just two endpoints.
    reverb_bps = [
        {"time_beats": bloom_start,            "value": 0.40, "curve_kind": "linear"},
        {"time_beats": bloom_start + 24.0,     "value": 0.55, "curve_kind": "linear"},
        {"time_beats": bloom_start + 48.0,     "value": 0.68, "curve_kind": "linear"},
        {"time_beats": bloom_start + 72.0,     "value": 0.80, "curve_kind": "linear"},
        {"time_beats": bloom_end,              "value": 0.85, "curve_kind": "linear"},  # peak
        {"time_beats": bloom_end + 16.0,       "value": 0.70, "curve_kind": "linear"},
        {"time_beats": bloom_end + 32.0,       "value": 0.55, "curve_kind": "linear"},
        {"time_beats": bloom_end + 48.0,       "value": 0.42, "curve_kind": "linear"},
        {"time_beats": recede_end,             "value": 0.30, "curve_kind": "linear"},
    ]
    env_id = M.create_envelope(
        conn, song_id=song_id, target_kind="send_level",
        target_track_id=tracks["01 Piano"],
        target_send_return_id=returns["Reverb"],
        actor="generator",
        reason="long reverb send ramp across bloom + recede (canary target)",
    )
    M.replace_breakpoints(
        conn, envelope_id=env_id, breakpoints=reverb_bps,
        actor="generator",
        reason="long reverb send ramp across bloom + recede",
    )

    # --- Slow volume swell on the piano across bloom (p -> mp) ---
    swell = volume_swell(
        target_track_id=tracks["01 Piano"],
        start_beat=bloom_start, length_beats=bloom_end - bloom_start,
        peak_value=0.85, floor_value=0.55,
    )
    _apply_envelopes(conn, song_id, swell,
                     reason="piano volume swell across bloom")


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id."""
    conn = init_db(DB_PATH)
    try:
        existing = Q.get_song_by_name(conn, "solo-piano-ambient")
        if existing and not reset:
            print(f"song already exists (id={existing['id']}); use --reset to rebuild")
            return existing["id"]
        if reset and existing is not None:
            M.reset_song_content(conn, song_id=existing["id"])

        # Mix-half: replay the captured (hand-authored) Ableton session.
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        song_id = replay_capture(
            conn, snapshot,
            song_name="solo-piano-ambient",
            song_title="Solo Piano Ambient",
            song_key="C Lydian",
            actor="sync", reason="canary build — hand-authored snapshot replay",
        )

        # Score-half.
        M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=60.0)
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
        )

        # Section markers.
        M.create_section(conn, song_id=song_id, name="prelude",
                         start_bar=float(PRELUDE_BAR), end_bar=float(BLOOM_BAR),
                         notes_md="solitary single notes, MM=60, pp")
        M.create_section(conn, song_id=song_id, name="bloom",
                         start_bar=float(BLOOM_BAR), end_bar=float(RECEDE_BAR),
                         notes_md="stacked chord pads, MM=60, p -> mp via slow envelope")
        M.create_section(conn, song_id=song_id, name="recede",
                         start_bar=float(RECEDE_BAR), end_bar=float(SILENCE_BAR),
                         notes_md="sparse motifs return over fading pad, mp -> pp")
        M.create_section(conn, song_id=song_id, name="silence",
                         start_bar=float(SILENCE_BAR), end_bar=float(END_BAR),
                         notes_md="intentional 8 bars of rest — empty arrangement")

        # Cue points at every section boundary.
        for bar, name in [(PRELUDE_BAR, "prelude"), (BLOOM_BAR, "bloom"),
                          (RECEDE_BAR, "recede"), (SILENCE_BAR, "silence")]:
            M.add_cue_point(conn, song_id=song_id, position_bar=float(bar), name=name)

        tracks = _tracks_by_name(conn, song_id)
        returns = _returns_by_name(conn, song_id)

        # Build each section's clips.
        prelude_clips = _build_prelude(conn, song_id, tracks)
        bloom_clips   = _build_bloom(conn, song_id, tracks)
        recede_clips  = _build_recede(conn, song_id, tracks)
        silence_clips = _build_silence(conn, song_id, tracks)  # empty

        # Arrangement.
        _arrange_section(conn, song_id, tracks, prelude_clips,
                         start_bar=float(PRELUDE_BAR), end_bar=float(BLOOM_BAR))
        _arrange_section(conn, song_id, tracks, bloom_clips,
                         start_bar=float(BLOOM_BAR),   end_bar=float(RECEDE_BAR))
        _arrange_section(conn, song_id, tracks, recede_clips,
                         start_bar=float(RECEDE_BAR),  end_bar=float(SILENCE_BAR))
        # silence: deliberately no arrangement entries.

        # Envelopes: long send-A reverb ramp + piano volume swell.
        _author_envelopes(conn, song_id, tracks, returns)

        return song_id
    finally:
        conn.close()


def report(song_id: str) -> None:
    conn = init_db(DB_PATH)
    try:
        song_row = Q.get_song(conn, song_id)
        tracks = Q.get_tracks_for_song(conn, song_id)
        print(f"song_id={song_id}, timing_mode={song_row['timing_mode']}, "
              f"tracks={len(tracks)}")
        total_notes = 0
        for t in tracks:
            clips = Q.get_clips_for_track(conn, t["id"])
            print(f"  track {t['track_index']:>2}  {t['name']:<16} "
                  f"({t['kind']}, {len(clips)} clips)")
            for c in clips:
                notes = Q.get_notes_for_clip(conn, c["id"])
                total_notes += len(notes)
                print(f"      slot {c['slot']}  {c['name']:<16} "
                      f"{c['length_beats']:>6.1f}bt  {len(notes):>4} notes")
        print(f"total notes: {total_notes}")
        sections = Q.get_sections_for_song(conn, song_id)
        print(f"sections: {[s['name'] for s in sections]}")
        arr = Q.get_arrangement_for_song(conn, song_id)
        print(f"arrangement entries: {len(arr)}")
        envs = Q.get_envelopes_for_song(conn, song_id) if hasattr(Q, "get_envelopes_for_song") else []
        if envs:
            print(f"envelopes: {len(envs)}")
            for e in envs:
                bps = Q.get_breakpoints(conn, envelope_id=e["id"])
                print(f"  {e['target_kind']:<14} {len(bps)} breakpoints")
    finally:
        conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="drop + rebuild")
    args = p.parse_args()
    sid = build(reset=args.reset)
    report(sid)
