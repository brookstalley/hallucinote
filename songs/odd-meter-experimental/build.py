"""Build odd-meter-experimental into a SQLite DB using the hallucinote layer.

CANARY NOTE (Wave 0 reliability harness): This song is the 7/8 + polyrhythm +
mid-section meter-ratchet stress canary. It is hand-authored from scratch (no
prior Live capture, no /new-song skill — see runbook). Author conventions
inherited from falling-walking, captured deliberately rather than assumed.

Beat encoding convention:
    The DB schema and library encode time in Live BEATS (quarter notes),
    regardless of meter. For 7/8 that means 7 * (4/8) = 3.5 beats per bar
    (see src/hallucinote/sync/push.py::_beats_per_bar). The CANARY BRIEF
    describes positions in "eighth-note beats" (e.g. "5-against-7 = notes at
    0, 1.4, 2.8, 4.2, 5.6 eighths"). To translate brief-units to DB-units we
    halve every eighth-offset.

Section layout (1-based bars in 7/8 unless otherwise noted; 7/8 -> 3.5 beats/bar):
    intro      bars  1- 8   ( 8 bars  ×  3.5  = 28.0 beats)
    lock       bars  9-24   (16 bars  ×  3.5  = 56.0 beats)
    bloom      bars 25-40   (16 bars  ×  3.5  = 56.0 beats)
    fracture   bars 41-48   ( 8 bars  meter ratchet, see _build_fracture)
                            cycle (7/8 7/8 5/8 5/8 6/8 6/8 7/8 7/8)
                            -> beats: (3.5 3.5 2.5 2.5 3.0 3.0 3.5 3.5) = 25.0 beats total
    release    bars 49-56   ( 8 bars  ×  3.5  = 28.0 beats)

    Total: 28+56+56+25+28 = 193 beats (~ 2:18 at 168bpm eighth, i.e. 84 BPM
    quarter pulse). Brief's "2 minute" target is approximate; the meter ratchet
    contracts the fracture section vs the chart's 56-eighth estimate (see
    runbook for note about chart vs ratchet-cycle arithmetic inconsistency).

Polyrhythm encoding (5-against-7):
    5 evenly-spaced notes per 7/8 bar. In eighth-note units: 0, 1.4, 2.8, 4.2,
    5.6 (i.e. 7/5 * k for k in 0..4). In DB-beat (quarter) units (divide by 2):
    0.0, 0.7, 1.4, 2.1, 2.8. These are NON-INTEGER positions stored as REAL —
    surfaces the canary's main question about precision.

Run:
    python songs/odd-meter-experimental/build.py
    python songs/odd-meter-experimental/build.py --reset
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.tempo import to_live_bpm

# Per-branch DB path so feature branches don't clobber each other's state.
# Convention matches `falling-walking/build.py`.
DB_PATH = resolve_db_path("odd-meter-experimental", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

# Live's beats-per-bar in 7/8.
BEATS_PER_BAR_7_8 = 7 * (4.0 / 8)   # 3.5
BEATS_PER_BAR_5_8 = 5 * (4.0 / 8)   # 2.5
BEATS_PER_BAR_6_8 = 6 * (4.0 / 8)   # 3.0

# Section bar boundaries (1-based).
INTRO_BAR     = 1
LOCK_BAR      = 9
BLOOM_BAR     = 25
FRACTURE_BAR  = 41
RELEASE_BAR   = 49
END_BAR       = 57

# Section beat lengths (computed for clarity; all in 7/8 except fracture).
INTRO_BEATS    = 8  * BEATS_PER_BAR_7_8   # 28.0
LOCK_BEATS     = 16 * BEATS_PER_BAR_7_8   # 56.0
BLOOM_BEATS    = 16 * BEATS_PER_BAR_7_8   # 56.0
RELEASE_BEATS  = 8  * BEATS_PER_BAR_7_8   # 28.0

# Fracture: 8 bars cycling 7/8 7/8 5/8 5/8 6/8 6/8 7/8 7/8.
# CANARY NOTE: brief charts "56 eighths" for fracture but the ratchet
# description doesn't sum to 56 in any natural pairing. I picked the cleanest
# 8-bar ratchet that includes both 5 and 6: (7,7,5,5,6,6,7,7) eighths
# = (3.5,3.5,2.5,2.5,3.0,3.0,3.5,3.5) beats = 25.0 beats total.
FRACTURE_METER_PATTERN = [
    (7, 8), (7, 8),
    (5, 8), (5, 8),
    (6, 8), (6, 8),
    (7, 8), (7, 8),
]
FRACTURE_BEAT_LENGTHS = [
    n * (4.0 / d) for (n, d) in FRACTURE_METER_PATTERN
]  # [3.5, 3.5, 2.5, 2.5, 3.0, 3.0, 3.5, 3.5]
FRACTURE_BEATS = sum(FRACTURE_BEAT_LENGTHS)  # 25.0

# Polyrhythm beat offsets within a 7/8 bar (5 evenly spaced notes).
# brief-units (eighths): 0, 1.4, 2.8, 4.2, 5.6 -> halve to Live beats.
POLY_5_AGAINST_7_OFFSETS = [
    (7.0 / 5) * k / 2.0 for k in range(5)
]  # [0.0, 0.7, 1.4, 2.1, 2.8]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


# ---------------------------------------------------------------------------
# Section authoring
# ---------------------------------------------------------------------------


def _build_intro(conn, tracks: dict[str, str]) -> dict:
    """Intro: click + bell only, establishing the 7-cycle. 8 bars × 3.5 = 28 beats."""
    clips: dict[str, str] = {}
    length = INTRO_BEATS

    # Perc click: every eighth-note (the 168 BPM pulse). 7 hits per bar.
    click_notes: list[dict] = []
    for bar in range(8):
        bar_start = bar * BEATS_PER_BAR_7_8
        for eighth in range(7):
            t = bar_start + eighth * 0.5  # 1 eighth = 0.5 beats
            vel = 95 if eighth == 0 else (62 if eighth % 2 == 0 else 48)
            click_notes.append(_note(60, t, 0.1, vel))   # C4 click
    cid = M.create_clip(
        conn, track_id=tracks["06 Perc Click"], slot=1,
        length_beats=length, name="Intro Click", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=click_notes)
    clips["06 Perc Click"] = cid

    # Bell accents: downbeat of every bar + bar 7 climax.
    bell_notes: list[dict] = []
    for bar in range(8):
        bar_start = bar * BEATS_PER_BAR_7_8
        bell_notes.append(_note(84, bar_start, 1.5, 80))  # C6
    bell_notes.append(_note(91, 6 * BEATS_PER_BAR_7_8 + 1.5, 1.0, 95))  # G6 mid-bar 7
    cid = M.create_clip(
        conn, track_id=tracks["05 Bell Accents"], slot=1,
        length_beats=length, name="Intro Bell", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["05 Bell Accents"] = cid

    return clips


def _build_lock(conn, tracks: dict[str, str]) -> dict:
    """Lock: add 5-against-7 polyrhythm bass. 16 bars × 3.5 = 56 beats.

    Drums enter with a simple 7-cycle kick/snare pattern; bass plays the
    5-against-7 ostinato across every bar.
    """
    clips: dict[str, str] = {}
    length = LOCK_BEATS

    # Drums: kick on bar downbeat, snare on eighth 4 (mid-bar accent).
    # 1 eighth = 0.5 beats, so eighth 4 = 2.0 beats from bar start.
    drum_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        drum_notes.append(_note(36, bs, 0.25, 110))           # kick on 1
        drum_notes.append(_note(38, bs + 2.0, 0.2, 95))       # snare on eighth 4
        # Hat sixteenths: 14 sixteenths per 7/8 bar.
        for sixt in range(14):
            t = bs + sixt * 0.25  # 1 sixteenth = 0.25 beats
            vel = 55 if sixt % 2 == 0 else 38
            drum_notes.append(_note(42, t, 0.1, vel))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=2,
        length_beats=length, name="Lock Drums", section_role="lock",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # POLYRHYTHM BASS: 5 evenly-spaced notes per 7/8 bar = 5-against-7.
    # Pitches cycle through a low D-minor figure: D1, A0, F1, A0, D1.
    # The KEY POSITIONS are 0.7-spaced fractional beats — non-integer storage.
    bass_pitches = [26, 21, 29, 21, 26]  # D1, A0, F1, A0, D1
    bass_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        for k, off in enumerate(POLY_5_AGAINST_7_OFFSETS):
            # Duration = 7/10 of a beat (slightly less than offset spacing for clarity).
            bass_notes.append(_note(bass_pitches[k], bs + off, 0.55, 92))
    cid = M.create_clip(
        conn, track_id=tracks["02 Polyrhythm Bass"], slot=2,
        length_beats=length, name="Lock Polyrhythm Bass", section_role="lock",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Polyrhythm Bass"] = cid

    # Click + bell continue at lower velocity to keep the 7-cycle audible.
    click_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        for eighth in range(7):
            t = bs + eighth * 0.5
            vel = 70 if eighth == 0 else (42 if eighth % 2 == 0 else 30)
            click_notes.append(_note(60, t, 0.1, vel))
    cid = M.create_clip(
        conn, track_id=tracks["06 Perc Click"], slot=2,
        length_beats=length, name="Lock Click", section_role="lock",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=click_notes)
    clips["06 Perc Click"] = cid

    bell_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        bell_notes.append(_note(84, bs, 1.5, 65))
    cid = M.create_clip(
        conn, track_id=tracks["05 Bell Accents"], slot=2,
        length_beats=length, name="Lock Bell", section_role="lock",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["05 Bell Accents"] = cid

    return clips


def _build_bloom(conn, tracks: dict[str, str]) -> dict:
    """Bloom: add harmonic pad (one chord per 14 eighths = 7 beats = 2 bars of 7/8).

    14 eighths is the "implied MM=72 dotted quarter" slow harmonic layer per
    the brief. 8 chord changes over the 16-bar (56-beat) section.
    """
    clips: dict[str, str] = {}
    length = BLOOM_BEATS

    # Drums + bass + click + bell carry over (same patterns as lock).
    # For canary brevity, only the pad is new here; other parts continue.
    # NOTE: I'm authoring NEW clips with the same content rather than reusing
    # the lock clips, because UNIQUE(track_id, slot) prevents the same clip
    # from being placed at two arrangement positions via shared clip_id
    # without further investigation. (Same friction as full-band-rock runbook.)
    drum_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        drum_notes.append(_note(36, bs, 0.25, 112))
        drum_notes.append(_note(38, bs + 2.0, 0.2, 95))
        for sixt in range(14):
            t = bs + sixt * 0.25
            vel = 58 if sixt % 2 == 0 else 40
            drum_notes.append(_note(42, t, 0.1, vel))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=3,
        length_beats=length, name="Bloom Drums", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    bass_pitches = [26, 21, 29, 21, 26]
    bass_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        for k, off in enumerate(POLY_5_AGAINST_7_OFFSETS):
            bass_notes.append(_note(bass_pitches[k], bs + off, 0.55, 95))
    cid = M.create_clip(
        conn, track_id=tracks["02 Polyrhythm Bass"], slot=3,
        length_beats=length, name="Bloom Polyrhythm Bass", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Polyrhythm Bass"] = cid

    # Harmonic pad: chord changes every 7 beats (= 14 eighths = 2 bars of 7/8).
    # 8 chord changes for a 56-beat section.
    chord_voicings = [
        [50, 53, 57],  # Dm (D3 F3 A3)
        [50, 53, 58],  # Dm6 / G7-ish
        [48, 52, 55],  # C (C3 E3 G3)
        [48, 52, 57],  # Cmaj7
        [46, 50, 53],  # Bb (Bb2 D3 F3)
        [46, 51, 53],  # Bbm-ish (chromatic shift)
        [45, 48, 53],  # A (A2 C3 F3)
        [43, 47, 50],  # G (G2 B2 D3)
    ]
    pad_notes: list[dict] = []
    for i, voicing in enumerate(chord_voicings):
        chord_start = i * 7.0  # 7 beats apart
        for pitch in voicing:
            pad_notes.append(_note(pitch, chord_start, 7.0, 70))
    cid = M.create_clip(
        conn, track_id=tracks["03 Harmonic Pad"], slot=3,
        length_beats=length, name="Bloom Pad", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    clips["03 Harmonic Pad"] = cid

    # Arpeggio: fast eighths arpeggiating the chord-of-the-moment.
    # 7 eighths/bar × 16 bars = 112 attacks.
    arp_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        chord_idx = bar // 2  # changes every 2 bars
        voicing_high = [p + 12 for p in chord_voicings[chord_idx]]  # one octave up
        for eighth in range(7):
            t = bs + eighth * 0.5
            pitch = voicing_high[eighth % 3]
            vel = 75 if eighth % 2 == 0 else 60
            arp_notes.append(_note(pitch, t, 0.4, vel))
    cid = M.create_clip(
        conn, track_id=tracks["04 Arpeggio"], slot=3,
        length_beats=length, name="Bloom Arp", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=arp_notes)
    clips["04 Arpeggio"] = cid

    # Click + bell continue.
    click_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        for eighth in range(7):
            t = bs + eighth * 0.5
            vel = 65 if eighth == 0 else (38 if eighth % 2 == 0 else 28)
            click_notes.append(_note(60, t, 0.1, vel))
    cid = M.create_clip(
        conn, track_id=tracks["06 Perc Click"], slot=3,
        length_beats=length, name="Bloom Click", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=click_notes)
    clips["06 Perc Click"] = cid

    bell_notes: list[dict] = []
    for bar in range(16):
        bs = bar * BEATS_PER_BAR_7_8
        bell_notes.append(_note(84, bs, 1.5, 62))
    cid = M.create_clip(
        conn, track_id=tracks["05 Bell Accents"], slot=3,
        length_beats=length, name="Bloom Bell", section_role="bloom",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["05 Bell Accents"] = cid

    return clips


def _build_fracture(conn, tracks: dict[str, str]) -> dict:
    """Fracture: 8-bar mid-section meter ratchet (7/8 7/8 5/8 5/8 6/8 6/8 7/8 7/8).

    THE CANARY'S CENTRAL TEST. Each bar has a different beat length; the
    section's overall length = 25.0 beats. Drums hit the downbeat of every
    bar regardless of length; polyrhythm bass is unable to maintain its 5-per-bar
    cycle because the bar lengths are inconsistent — instead the bass plays
    5 evenly-spaced notes PER BAR with the spacing relative to that bar's length.
    This forces the canary into FLOAT positions that depend on bar-meter, the
    hardest case.
    """
    clips: dict[str, str] = {}
    length = FRACTURE_BEATS  # 25.0

    # Drums: kick on each bar downbeat + snare on second beat (when bar long enough).
    drum_notes: list[dict] = []
    # Bell hits every downbeat too.
    bell_notes: list[dict] = []
    # Click: 1 hit per eighth in each bar — varies per bar's eighth count.
    click_notes: list[dict] = []
    # Polyrhythm bass: 5 evenly-spaced PER BAR (offsets depend on bar length).
    bass_notes: list[dict] = []
    bass_pitches = [26, 21, 29, 21, 26]

    cumulative = 0.0
    for bar_idx, (num, den) in enumerate(FRACTURE_METER_PATTERN):
        bar_beats = num * (4.0 / den)
        bar_eighths = num  # numerator counts eighths in n/8

        drum_notes.append(_note(36, cumulative, 0.25, 115))
        if bar_beats >= 2.0:
            drum_notes.append(_note(38, cumulative + bar_beats / 2.0, 0.2, 100))
        bell_notes.append(_note(84, cumulative, 1.0, 80))

        # Click: 1 hit per eighth.
        for eighth in range(bar_eighths):
            t = cumulative + eighth * 0.5
            vel = 80 if eighth == 0 else (50 if eighth % 2 == 0 else 35)
            click_notes.append(_note(60, t, 0.1, vel))

        # Polyrhythm bass: 5 evenly-spaced positions across THIS bar's length.
        # In eighths: 0, n/5, 2n/5, 3n/5, 4n/5. In beats: halve them.
        for k in range(5):
            off_eighths = (num / 5.0) * k
            off_beats = off_eighths / 2.0
            bass_notes.append(_note(bass_pitches[k], cumulative + off_beats, 0.4, 95))

        cumulative += bar_beats

    assert abs(cumulative - length) < 1e-9, f"fracture beats mismatch: {cumulative} != {length}"

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=4,
        length_beats=length, name="Fracture Drums", section_role="fracture",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    cid = M.create_clip(
        conn, track_id=tracks["05 Bell Accents"], slot=4,
        length_beats=length, name="Fracture Bell", section_role="fracture",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["05 Bell Accents"] = cid

    cid = M.create_clip(
        conn, track_id=tracks["06 Perc Click"], slot=4,
        length_beats=length, name="Fracture Click", section_role="fracture",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=click_notes)
    clips["06 Perc Click"] = cid

    cid = M.create_clip(
        conn, track_id=tracks["02 Polyrhythm Bass"], slot=4,
        length_beats=length, name="Fracture Bass", section_role="fracture",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Polyrhythm Bass"] = cid

    return clips


def _build_release(conn, tracks: dict[str, str]) -> dict:
    """Release: pad + bell only, slow fade. 8 bars × 3.5 = 28 beats."""
    clips: dict[str, str] = {}
    length = RELEASE_BEATS

    # Pad: one long Dm chord fading out.
    pad_notes = [_note(p, 0.0, length, 65) for p in [50, 53, 57]]
    cid = M.create_clip(
        conn, track_id=tracks["03 Harmonic Pad"], slot=5,
        length_beats=length, name="Release Pad", section_role="release",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    clips["03 Harmonic Pad"] = cid

    # Bell: one hit per bar, fading.
    bell_notes: list[dict] = []
    for bar in range(8):
        bs = bar * BEATS_PER_BAR_7_8
        vel = max(70 - bar * 8, 18)
        bell_notes.append(_note(84, bs, 2.0, vel))
    cid = M.create_clip(
        conn, track_id=tracks["05 Bell Accents"], slot=5,
        length_beats=length, name="Release Bell", section_role="release",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["05 Bell Accents"] = cid

    return clips


# ---------------------------------------------------------------------------
# Arrangement
# ---------------------------------------------------------------------------


def _arrange_section(conn, song_id: str, tracks: dict[str, str],
                     clips: dict[str, str], *, start_bar: float, end_bar: float) -> None:
    for track_name, clip_id in clips.items():
        M.add_arrangement_clip(
            conn, song_id=song_id,
            track_id=tracks[track_name], clip_id=clip_id,
            start_bar=start_bar, end_bar=end_bar,
        )


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


def _author_envelopes(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Add a single short envelope demonstrating the path is exercised.

    Reverb send swell on the pad through bloom — kept ENTIRELY within the
    bloom section's bar range so it doesn't trip the W4-B "spans multiple
    clips" planner skip we already know about from solo-piano-ambient.

    Envelope routes to send_level (target_track + target_send_return) — the
    DB requires both per schema CHECK.
    """
    reverb_return = next(
        r for r in Q.get_returns_for_song(conn, song_id) if r["name"] == "Reverb"
    )
    env_id = M.create_envelope(
        conn, song_id=song_id,
        target_kind="send_level",
        target_track_id=tracks["03 Harmonic Pad"],
        target_send_return_id=reverb_return["id"],
        actor="generator", reason="pad reverb swell across bloom",
    )
    # Bloom is bars 25-40; in beats from song start = 24 * 3.5 = 84.0 to 39 * 3.5 = 136.5.
    # Whether the planner can route this is one of the open questions.
    M.replace_breakpoints(
        conn, envelope_id=env_id,
        breakpoints=[
            {"time_beats": 84.0,  "value": 0.25, "curve_kind": "linear"},
            {"time_beats": 112.0, "value": 0.55, "curve_kind": "linear"},
            {"time_beats": 136.5, "value": 0.35, "curve_kind": "linear"},
        ],
        actor="generator", reason="pad reverb swell across bloom",
    )


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    conn = init_db(DB_PATH)
    try:
        existing = Q.get_song_by_name(conn, "odd-meter-experimental")
        if existing and not reset:
            print(f"song already exists (id={existing['id']}); use --reset to rebuild")
            return existing["id"]
        if reset and existing is not None:
            M.reset_song_content(conn, song_id=existing["id"])

        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        song_id = replay_capture(
            conn, snapshot,
            song_name="odd-meter-experimental",
            song_title="Odd Meter Experimental",
            song_key="Dm",
            actor="sync", reason="canary w0 capture replay",
        )

        M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
        # Notional tempo 168 BPM (eighth-note pulse). Live's "BPM" is the
        # quarter-note pulse; `to_live_bpm` does the conversion.
        M.add_tempo_point(
            conn, song_id=song_id, start_bar=1.0,
            tempo_bpm=to_live_bpm(168.0, "eighth"),
        )
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0, numerator=7, denominator=8,
        )

        # W10-H (post-Wave-0): the within-section meter ratchet that this
        # canary was designed to surface is REFUSED at the mutator layer in
        # v1 — Live 12.4's MCP has no `song_signature` automation target so
        # the ratchet can't reach Live. Per the user-locked policy
        # (2026-05-19), v1 ships loud refusal; v1.1 will explore the
        # per-bar-arrangement-clip workaround. The canary preserves the
        # 7/8 + polyrhythm work; fracture plays in global 7/8 (its bar
        # offsets are still computed against FRACTURE_METER_PATTERN for
        # the polyrhythmic content, but the meter map itself is bar-1-only).
        #
        # Original ratchet authoring (kept commented as v1.1 reference):
        # cum_bar = float(FRACTURE_BAR)
        # for (num, den) in FRACTURE_METER_PATTERN:
        #     M.add_time_signature_point(conn, song_id=song_id,
        #         start_bar=cum_bar, numerator=num, denominator=den)
        #     cum_bar += 1.0
        # M.add_time_signature_point(conn, song_id=song_id,
        #     start_bar=float(RELEASE_BAR), numerator=7, denominator=8)

        # Sections.
        M.create_section(conn, song_id=song_id, name="intro",
                         start_bar=float(INTRO_BAR), end_bar=float(LOCK_BAR),
                         notes_md="click + bell only, establishing the 7-cycle")
        M.create_section(conn, song_id=song_id, name="lock",
                         start_bar=float(LOCK_BAR), end_bar=float(BLOOM_BAR),
                         notes_md="add 5-against-7 polyrhythm bass")
        M.create_section(conn, song_id=song_id, name="bloom",
                         start_bar=float(BLOOM_BAR), end_bar=float(FRACTURE_BAR),
                         notes_md="harmonic pad enters (chord every 14 eighths = 7 beats)")
        M.create_section(conn, song_id=song_id, name="fracture",
                         start_bar=float(FRACTURE_BAR), end_bar=float(RELEASE_BAR),
                         notes_md="mid-section meter ratchet 7/8 5/8 6/8 7/8")
        M.create_section(conn, song_id=song_id, name="release",
                         start_bar=float(RELEASE_BAR), end_bar=float(END_BAR),
                         notes_md="pad + bell only, slow fade")

        # Cue points at section starts.
        for bar, name in [(INTRO_BAR, "intro"), (LOCK_BAR, "lock"),
                          (BLOOM_BAR, "bloom"), (FRACTURE_BAR, "fracture"),
                          (RELEASE_BAR, "release")]:
            M.add_cue_point(conn, song_id=song_id, position_bar=float(bar), name=name)

        tracks = _tracks_by_name(conn, song_id)

        intro    = _build_intro(conn, tracks)
        lock     = _build_lock(conn, tracks)
        bloom    = _build_bloom(conn, tracks)
        fracture = _build_fracture(conn, tracks)
        release  = _build_release(conn, tracks)

        _arrange_section(conn, song_id, tracks, intro,
                         start_bar=float(INTRO_BAR), end_bar=float(LOCK_BAR))
        _arrange_section(conn, song_id, tracks, lock,
                         start_bar=float(LOCK_BAR), end_bar=float(BLOOM_BAR))
        _arrange_section(conn, song_id, tracks, bloom,
                         start_bar=float(BLOOM_BAR), end_bar=float(FRACTURE_BAR))
        _arrange_section(conn, song_id, tracks, fracture,
                         start_bar=float(FRACTURE_BAR), end_bar=float(RELEASE_BAR))
        _arrange_section(conn, song_id, tracks, release,
                         start_bar=float(RELEASE_BAR), end_bar=float(END_BAR))

        _author_envelopes(conn, song_id, tracks)

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
            print(f"  track {t['track_index']:>2}  {t['name']:<22} "
                  f"({t['kind']}, {len(clips)} clips)")
            for c in clips:
                notes = Q.get_notes_for_clip(conn, c["id"])
                total_notes += len(notes)
                print(f"      slot {c['slot']}  {c['name']:<28} "
                      f"{c['length_beats']:>6.2f}bt  {len(notes):>4} notes")
        print(f"total notes: {total_notes}")
        sections = Q.get_sections_for_song(conn, song_id)
        print(f"sections: {[s['name'] for s in sections]}")
        arr = Q.get_arrangement_for_song(conn, song_id)
        print(f"arrangement entries: {len(arr)}")
        ts_pts = Q.get_time_signature_map(conn, song_id)
        print(f"time_signature_map: {len(ts_pts)} points")
        for p in ts_pts:
            print(f"  bar {p['start_bar']:>5.1f}  {p['numerator']}/{p['denominator']}")
        envs = Q.get_envelopes_for_song(conn, song_id)
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
