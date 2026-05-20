"""Build falling-walking into a SQLite DB using the hallucinote layer.

Chunk 5 milestone: the legacy `gen_notes.py` is deleted; every clip in the song
flows through generator → mutator → DB. Library generators handle reusable
patterns; this file inlines NoteDict lists where the part is song-specific
(verse bass detailed playing, intro chiptune hook melody, etc.).

Section bar layout (1-based):
    intro       bars  1-17    (16 bars / 64 beats)
    verse       bars 17-32    (15 bars / 60 beats)
    chorus      bars 32-40    ( 8 bars / 32 beats)
    chorus C3'  bars 40-48    ( 8 bars / 32 beats — alt voicing twist)
    bridge      bars 48-56    ( 8 bars / 32 beats)
    tag         bars 56-60    ( 4 bars / 16 beats)
    outro       bars 60-68    ( 8 bars / 32 beats)

Run:
    python songs/falling-walking/build.py
    python songs/falling-walking/build.py --reset    # drop + rebuild
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.generators import GeneratorOutput, bass, drums, harmony
from hallucinote.generators.envelopes import sidechain_trigger, volume_swell

# W12-A: per-branch DB filename. Branch switches pick up the right DB
# silently; outside a repo / detached HEAD falls back to falling-walking.db.
DB_PATH = resolve_db_path("falling-walking", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

# Chord roots (MIDI).
D2, F2, C2, G2, BB1, A1 = 38, 41, 36, 43, 34, 33

# Pad voicings (F3=53, A3=57, D4=62, etc.)
DM_PAD = [53, 57, 62]
GM_PAD = [55, 58, 62]
BB_PAD = [53, 58, 62]

# Section bar boundaries (1-based).
INTRO_BAR  = 1
VERSE_BAR  = 17
CHORUS_BAR = 32
TWIST_BAR  = 40
BRIDGE_BAR = 48
TAG_BAR    = 56
OUTRO_BAR  = 60
END_BAR    = 68

LAZY = 0.04  # Lay-back amount carried over from the prototype.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


def _sub_from_bass(bass_notes, *, vel_factor: float = 0.85) -> list[dict]:
    """Sub-bass = bass notes one octave down, slightly softer."""
    return [
        {"pitch": max(n["pitch"] - 12, 0),
         "start_beats": n["start_beats"],
         "duration_beats": n["duration_beats"],
         "velocity": int(n["velocity"] * vel_factor)}
        for n in bass_notes
    ]


def _apply_envelopes(conn, song_id: str, output: GeneratorOutput,
                     *, actor: str = "generator", reason: str | None = None) -> None:
    """Persist every envelope spec in `output.envelopes` via mutators."""
    for env_spec in output.envelopes:
        spec = dict(env_spec)  # don't mutate caller's dict
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


def _build_intro(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Intro — 16 bars / 64 beats. Returns {track_name: clip_id} for the section."""
    clips: dict[str, str] = {}

    # ---- Drums: progressive hat journey + kick from bar 13 + snare from bar 15 ----
    drum_notes: list[dict] = []
    # Bars 1-4: single hat tick on beat 1 (very sparse).
    for b in range(4):
        bs = b * 4.0
        drum_notes.append(_note(42, bs, 0.1, 50 + b * 3))
    # Bars 5-8: bossa shaker (16ths with accents), fading in.
    drum_notes.extend(drums.bossa_shaker(4, start_beat=16.0))
    # Bars 9-12: tresillo hats, gradually louder.
    drum_notes.extend(drums.tresillo_hats(4, start_beat=32.0))
    # Bars 13-16: trip-hop 8ths + kick stumble + snare from bar 15.
    drum_notes.extend(drums.trip_hop_hats(4, start_beat=48.0))
    drum_notes.extend(drums.kick_stumble(4, start_beat=48.0))
    drum_notes.extend(drums.lazy_snare(2, start_beat=56.0))
    # Open hat lift on the final 16th to push into the verse.
    drum_notes.append(_note(46, 63.5, 0.5, 95))

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=1, length_beats=64.0,
        name="Intro Drums", section_role="intro",
        generator_call={"fn": "intro composed", "kwargs": {"bars": 16}},
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # ---- Sub bass: single low D1 sustained the whole intro ----
    cid = M.create_clip(
        conn, track_id=tracks["02 Sub Bass"], slot=1, length_beats=64.0,
        name="Intro Sub", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=[_note(26, 0.0, 64.0, 75)])
    clips["02 Sub Bass"] = cid

    # ---- Pad: Dm chord blocks rising in velocity 60 → 88 ----
    pad_notes: list[dict] = []
    for i, start in enumerate([0.0, 16.0, 32.0, 48.0]):
        vel = 60 + i * 10  # 60, 70, 80, 90
        pad_notes.extend(harmony.chord_pad(
            DM_PAD, start_beat=start, length_beats=16.0, velocity=vel,
        ))
    cid = M.create_clip(
        conn, track_id=tracks["04 Verse Pad"], slot=1, length_beats=64.0,
        name="Intro Pad", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    clips["04 Verse Pad"] = cid

    # ---- Arp on the Chorus Pluck track: foreshadows verse harmony ----
    arp: list[dict] = []
    # Bars 1-4 (sparse Dm): D4 + A3 on beats 1 and 3.
    for b in range(4):
        bs = b * 4.0
        arp.append(_note(62, bs, 1.0, 65))
        arp.append(_note(57, bs + 2.0, 1.0, 60))
    # Bars 5-8 (Dm 8ths).
    for b in range(4, 8):
        bs = b * 4.0
        for t, p, v in [(0.0, 62, 75), (0.5, 65, 70), (1.0, 69, 78), (1.5, 65, 70),
                        (2.0, 62, 75), (2.5, 65, 70), (3.0, 69, 78), (3.5, 65, 70)]:
            arp.append(_note(p, bs + t, 0.4, v + (b - 4) * 2))
    # Bars 9-12 (Gm reveal).
    for b in range(8, 12):
        bs = b * 4.0
        for t, p, v in [(0.0, 67, 80), (0.5, 70, 75), (1.0, 74, 82), (1.5, 70, 75),
                        (2.0, 67, 80), (2.5, 70, 75), (3.0, 74, 82), (3.5, 70, 75)]:
            arp.append(_note(p, bs + t, 0.4, v))
    # Bars 13-14 (Bb 16ths).
    for b in range(12, 14):
        bs = b * 4.0
        pitches = [70, 74, 77, 74]
        for sixteenth in range(16):
            t = sixteenth * 0.25
            arp.append(_note(pitches[sixteenth % 4], bs + t, 0.2,
                             78 + (sixteenth % 4) * 3))
    # Bar 15: A held, bar 16 silent.
    arp.append(_note(69, 56.0, 4.0, 88))

    cid = M.create_clip(
        conn, track_id=tracks["05 Chorus Pluck"], slot=1, length_beats=64.0,
        name="Intro Arp", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=arp)
    clips["05 Chorus Pluck"] = cid

    # ---- Bell: sparse high arpeggio bars 5-8 ----
    bell_notes = [
        _note(74, 16.0, 2.0, 70), _note(77, 22.0, 2.0, 65),
        _note(81, 26.0, 2.0, 75), _note(74, 30.0, 2.0, 60),
    ]
    cid = M.create_clip(
        conn, track_id=tracks["06 Bell"], slot=1, length_beats=64.0,
        name="Intro Bell", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["06 Bell"] = cid

    # ---- Chiptune lead: hook fragment bars 9-12, full hook bars 13-16 ----
    lead_notes = (
        # Fragment.
        [_note(p, s, d, 70) for s, p, d in
         [(32.0, 69, 1.0), (33.0, 65, 0.5), (33.5, 62, 1.0), (35.0, 67, 1.0)]]
        # Full hook.
        + [_note(p, s, d, 90) for s, p, d in [
            (48.0, 69, 1.0), (49.0, 65, 0.5), (49.5, 62, 1.0), (51.0, 67, 1.0),
            (52.0, 65, 0.75), (53.0, 64, 0.75), (54.0, 62, 2.0),
            (57.0, 69, 0.5), (57.75, 65, 0.75), (58.5, 62, 1.5),
            (60.0, 70, 1.0), (61.0, 69, 1.0), (62.0, 65, 1.0), (63.0, 64, 1.0),
        ]]
    )
    cid = M.create_clip(
        conn, track_id=tracks["08 Chiptune Lead"], slot=1, length_beats=64.0,
        name="Intro Lead", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["08 Chiptune Lead"] = cid

    return clips


def _build_verse(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Verse — 15 bars / 60 beats. Trip-hop drums + Dm pad + walking bass."""
    clips: dict[str, str] = {}

    # ---- Drums: trip-hop with fills on bars 4/8/12 + bar 15 fill ----
    # Per-part feel (W17-E): nudge the off-beat hats slightly late for a
    # subtle trip-hop drag on top of the snare's intrinsic lay_back. Verse
    # only — chorus drums below stay canonical so the section contrast is
    # audible. Demonstrates the per-part-per-clip granularity from
    # docs/song-authoring-conventions.md "Per-part feel".
    verse_feel = {0.5: 0.01, 1.5: 0.01, 2.5: 0.01, 3.5: 0.01}
    verse_drum_notes = drums.trip_hop_drum_pattern(
        bars=14, fill_bars=[3, 7, 11], feel=verse_feel,
    )
    # Bar 15: real fill (toms + snare roll + crash).
    bs = 56.0
    verse_drum_notes.extend([
        _note(36, bs + 0.0, 0.25, 115),
        _note(38, bs + 1.0, 0.15, 100),
        _note(47, bs + 1.5, 0.15, 92),
        _note(47, bs + 1.75, 0.15, 96),
        _note(50, bs + 2.0, 0.15, 102),
        _note(50, bs + 2.25, 0.15, 108),
    ])
    # 32nd-note snare roll into beat 4.
    for i in range(8):
        verse_drum_notes.append(_note(38, bs + 2.5 + i * 0.125, 0.08, min(90 + i * 4, 122)))
    # Crash on beat 4.
    verse_drum_notes.append(_note(49, bs + 3.5, 1.0, 110))
    # Soft chord-change crash bar 9.
    verse_drum_notes.append(_note(49, 32.0, 1.5, 75))
    # Splash bar 13 (Bb arrival).
    verse_drum_notes.append(_note(55, 48.0, 1.0, 70))

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=2, length_beats=60.0,
        name="Verse Drums", section_role="verse",
        generator_call={"fn": "drums.trip_hop_drum_pattern",
                        "kwargs": {"bars": 14, "fill_bars": [3, 7, 11]}},
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=verse_drum_notes)
    clips["01 Drums"] = cid

    # ---- Bass: detailed bass-player part with embellishments + walks ----
    # The detailed embellishments are song-specific; inlined here.
    verse_bass: list[dict] = []
    def _vb(p, t, dur, v):
        verse_bass.append(_note(p, t, dur, v))

    # Bars 1-8 Dm.
    _vb(38, 0.0, 1.5, 105); _vb(38, 2.75, 0.75, 88)
    _vb(38, 4.0, 0.5, 100); _vb(33, 4.5, 0.3, 70)
    _vb(38, 6.0, 1.5, 92); _vb(50, 7.5, 0.4, 80)
    _vb(38, 8.0, 1.5, 102); _vb(38, 10.75, 0.4, 88); _vb(41, 11.25, 0.5, 78); _vb(38, 11.75, 0.25, 70)
    _vb(38, 12.0, 1.5, 100); _vb(38, 14.0, 0.75, 90); _vb(33, 14.875, 0.125, 50); _vb(36, 15.5, 0.25, 78); _vb(38, 15.75, 0.25, 85)
    _vb(38, 16.0, 1.0, 105); _vb(50, 17.0, 0.5, 78); _vb(38, 18.75, 0.75, 88)
    _vb(38, 20.0, 0.4, 98); _vb(38, 20.5, 0.125, 45); _vb(38, 22.0, 1.0, 92); _vb(45, 23.5, 0.4, 80)
    _vb(38, 24.0, 1.0, 102); _vb(41, 25.0, 0.5, 80); _vb(38, 26.75, 0.5, 88); _vb(40, 27.5, 0.5, 75)
    _vb(38, 28.0, 1.5, 100); _vb(38, 30.0, 0.5, 92); _vb(41, 30.5, 0.5, 90); _vb(42, 31.5, 0.5, 95)
    # Bars 9-12 Gm.
    _vb(43, 32.0, 1.5, 110); _vb(43, 34.75, 0.75, 90)
    _vb(43, 36.0, 0.5, 100); _vb(38, 36.875, 0.125, 55); _vb(43, 38.0, 1.0, 92); _vb(46, 39.5, 0.4, 82)
    _vb(43, 40.0, 1.0, 102); _vb(46, 41.0, 0.5, 82); _vb(43, 42.75, 0.5, 88); _vb(50, 43.5, 0.4, 80)
    _vb(43, 44.0, 1.0, 100); _vb(43, 46.0, 0.5, 90); _vb(44, 46.5, 0.5, 78); _vb(45, 47.0, 0.5, 88); _vb(34, 47.5, 0.5, 95)
    # Bars 13-14 Bb.
    _vb(34, 48.0, 1.5, 105); _vb(34, 50.75, 0.75, 88); _vb(41, 51.5, 0.5, 80)
    _vb(34, 52.0, 1.0, 102); _vb(38, 53.0, 0.5, 88); _vb(41, 54.0, 0.5, 92); _vb(38, 54.5, 0.5, 85); _vb(34, 55.0, 0.5, 88); _vb(34, 55.5, 0.25, 92); _vb(33, 55.75, 0.25, 100)
    # Bar 15 A — 8th-note drive with octave punctuation + chromatic neighbor.
    for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]):
        p = 45 if i in (3, 6) else 33
        _vb(p, 56.0 + t, 0.4, 95 + i * 2)
    _vb(34, 59.5, 0.25, 92); _vb(33, 59.75, 0.25, 110)

    cid = M.create_clip(
        conn, track_id=tracks["03 Synth Bass"], slot=1, length_beats=60.0,
        name="Verse Bass", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=verse_bass)
    clips["03 Synth Bass"] = cid

    # ---- Sub bass: octave below the verse bass ----
    cid = M.create_clip(
        conn, track_id=tracks["02 Sub Bass"], slot=2, length_beats=60.0,
        name="Verse Sub", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=_sub_from_bass(verse_bass))
    clips["02 Sub Bass"] = cid

    # ---- Pad: Dm sustained with inner-voice walk + chord stabs ----
    pad: list[dict] = []
    # Bars 1-8 Dm: F3, A3 sustained 32 beats; top voice walks D4 -> E4 -> F4 -> E4.
    pad.append(_note(53, 0.0, 32.0, 80))
    pad.append(_note(57, 0.0, 32.0, 80))
    pad.append(_note(62, 0.0, 16.0, 82))   # D4 bars 1-4
    pad.append(_note(64, 16.0, 8.0, 85))   # E4 bars 5-6
    pad.append(_note(65, 24.0, 4.0, 88))   # F4 bar 7
    pad.append(_note(64, 28.0, 4.0, 85))   # E4 bar 8
    # Stabs on bars 4/8 beat 4.
    pad.extend(harmony.chord_stab([53, 57, 62], start_beat=14.0))
    pad.extend(harmony.chord_stab([53, 57, 64], start_beat=30.0))
    # Bars 9-12 Gm sustained.
    pad.extend(harmony.chord_pad([55, 58, 62], start_beat=32.0, length_beats=16.0, velocity=84))
    pad.extend(harmony.chord_stab([55, 58, 62], start_beat=46.0, velocity=100))
    # Bars 13-14 Bb sustained.
    pad.extend(harmony.chord_pad([53, 58, 62], start_beat=48.0, length_beats=8.0, velocity=88))
    # Bar 15 A: stabs on beats 1, 2, 3, 4.
    for t in [0.0, 1.0, 2.0, 3.0]:
        pad.extend(harmony.chord_stab([57, 61, 64], start_beat=56.0 + t, velocity=95, duration=0.6))

    cid = M.create_clip(
        conn, track_id=tracks["04 Verse Pad"], slot=2, length_beats=60.0,
        name="Verse Pad", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad)
    clips["04 Verse Pad"] = cid

    return clips


def _build_chorus(conn, song_id: str, tracks: dict[str, str],
                  *, twist: bool = False) -> dict:
    """Chorus — 8 bars / 32 beats. `twist` swaps the final chord (G → Bb)."""
    clips: dict[str, str] = {}
    suffix = " (C3')" if twist else ""
    slot_base = 4 if twist else 3
    role = "chorus_twist" if twist else "chorus"

    # Chord cycle. Last chord differs in the twist.
    last_root = BB1 if twist else G2
    walk_back = [BB1, 38, 41, 33] if twist else [G2, 47, 50, 45]
    last_pluck = "Bb" if twist else "G"
    last_pad_voicing = [53, 57, 58, 62] if twist else [55, 59, 62]

    # ---- Drums: half-time pattern (kick 1 / snare 3) with tresillo-flavored hats ----
    # Song-specific composition: 8-bar phrase with alt-bar embellishments.
    drum_notes: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        # Kick on beat 1; extra late kick + soft ghost on alternate bars for texture.
        drum_notes.append(_note(36, bs, 0.3, 118))
        if b % 2 == 1:
            drum_notes.append(_note(36, bs + 3.5, 0.2, 70))
        if b % 4 == 2:
            drum_notes.append(_note(36, bs + 1.5, 0.15, 55))
        # Snare on beat 3 + a soft ghost just before it.
        drum_notes.append(_note(38, bs + 2.0, 0.35, 115))
        drum_notes.append(_note(38, bs + 2.75, 0.1, 42))
        if b % 2 == 1:
            drum_notes.append(_note(38, bs + 2.875, 0.08, 38))
        # Hat tresillo cell, six hits per bar.
        for t, v in [(0.0, 75), (0.75, 95), (1.5, 95), (2.0, 75), (2.75, 95), (3.5, 90)]:
            drum_notes.append(_note(42, bs + t, 0.1, v))
        # Open-hat lift to mark the alternate bar.
        if b % 2 == 1:
            drum_notes.append(_note(46, bs + 3.75, 0.25, 80))
    # Soft crash on chorus arrival.
    drum_notes.append(_note(49, 0.0, 1.5, 88))
    # Snare flick on bar 8 final 16ths — pushes into next section.
    drum_notes.append(_note(38, 31.5, 0.1, 70))
    drum_notes.append(_note(38, 31.75, 0.1, 88))
    if twist:
        # Multi-flavor crashes mark the C3' twist.
        drum_notes.extend([
            _note(49, 0.0, 1.0, 115),
            _note(55, 8.0, 0.5, 90),
            _note(57, 16.0, 1.0, 100),
            _note(52, 24.0, 1.0, 110),
            _note(49, 31.5, 1.0, 115),
        ])
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=slot_base, length_beats=32.0,
        name=f"Chorus Drums{suffix}", section_role=role,
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # ---- Bass: tresillo + chord-tone embellishment per 2-bar chord ----
    chorus_bass = (
        bass.tresillo_bass(D2, bars=1, start_beat=0.0)
        + bass.chord_tone_embellishment(D2, third_offset=3, fifth_offset=7,
                                        octave_offset=12, start_beat=4.0,
                                        walk_to_next=40)
        + bass.tresillo_bass(F2, bars=1, start_beat=8.0)
        + bass.chord_tone_embellishment(F2, third_offset=4, fifth_offset=7,
                                        octave_offset=12, start_beat=12.0,
                                        walk_to_next=38)
        + bass.tresillo_bass(C2, bars=1, start_beat=16.0)
        + bass.chord_tone_embellishment(C2, third_offset=4, fifth_offset=7,
                                        octave_offset=12, start_beat=20.0,
                                        walk_to_next=41)
        + bass.tresillo_bass(last_root, bars=1, start_beat=24.0)
        + bass.chord_tone_embellishment(last_root, third_offset=4, fifth_offset=7,
                                        octave_offset=12, start_beat=28.0,
                                        walk_to_next=walk_back[3])
    )
    cid = M.create_clip(
        conn, track_id=tracks["03 Synth Bass"], slot=slot_base, length_beats=32.0,
        name=f"Chorus Bass{suffix}", section_role=role,
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=chorus_bass)
    clips["03 Synth Bass"] = cid

    # ---- Sub bass: root on beat 1 of each bar (two attacks per chord) ----
    chord_roots = [(0.0, D2), (8.0, F2), (16.0, C2), (24.0, last_root)]
    sub_notes: list[dict] = []
    for chord_start, p in chord_roots:
        for bar_offset in [0.0, 4.0]:
            sub_notes.append(_note(p - 12, chord_start + bar_offset, 3.5, 88))
    cid = M.create_clip(
        conn, track_id=tracks["02 Sub Bass"], slot=slot_base, length_beats=32.0,
        name=f"Chorus Sub{suffix}", section_role=role,
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=sub_notes)
    clips["02 Sub Bass"] = cid

    # ---- Pad: 7th-chord sustains (8 beats each, gap at chord change) ----
    pad_chords = [
        (0.0,  [53, 57, 60, 62]),   # Dm7
        (8.0,  [53, 57, 60, 64]),   # Fmaj7
        (16.0, [52, 55, 59, 60]),   # Cmaj7
        (24.0, last_pad_voicing),    # G or Bbmaj7
    ]
    pad_notes: list[dict] = []
    for start, voicing in pad_chords:
        pad_notes.extend(harmony.chord_pad(
            voicing, start_beat=start, length_beats=7.5, velocity=78,
        ))
    cid = M.create_clip(
        conn, track_id=tracks["04 Verse Pad"], slot=slot_base, length_beats=32.0,
        name=f"Chorus Pad{suffix}", section_role=role,
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    clips["04 Verse Pad"] = cid

    # ---- Pluck: calypso tresillo cycling through voicings ----
    pluck_voicings = {
        "Dm": [62, 65, 69], "F": [65, 69, 72], "C": [60, 64, 67],
        "G": [62, 67, 71], "Bb": [65, 70, 74],
    }
    pluck_notes: list[dict] = []
    for sect_start, chord in [(0, "Dm"), (8, "F"), (16, "C"), (24, last_pluck)]:
        pluck_notes.extend(harmony.tresillo_pluck(
            pluck_voicings[chord], bars=2, start_beat=float(sect_start),
        ))
    cid = M.create_clip(
        conn, track_id=tracks["05 Chorus Pluck"], slot=slot_base, length_beats=32.0,
        name=f"Chorus Pluck{suffix}", section_role=role,
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pluck_notes)
    clips["05 Chorus Pluck"] = cid

    # ---- Bell: sparse top-of-chord arpeggio per 8-beat section ----
    bell_notes: list[dict] = []
    for sect_start, chord in [(0, "Dm"), (8, "F"), (16, "C"), (24, last_pluck)]:
        bell_notes.extend(harmony.sparse_bell_top(
            pluck_voicings[chord], start_beat=float(sect_start),
            section_length_beats=8.0,
        ))
    cid = M.create_clip(
        conn, track_id=tracks["06 Bell"], slot=slot_base, length_beats=32.0,
        name=f"Chorus Bell{suffix}", section_role=role,
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bell_notes)
    clips["06 Bell"] = cid

    return clips


def _build_bridge(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Bridge — 8 bars / 32 beats in Bb major. Walking bossa feel."""
    clips: dict[str, str] = {}

    # ---- Drums: walking bossa pattern (kick on 1+2.5+3+3.5, conga ghost, hat 16ths) ----
    drum_notes: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        for t, v in [(0.0, 95), (1.5, 78), (2.0, 88), (3.5, 75)]:
            drum_notes.append(_note(36, bs + t, 0.2, v))
        if b % 2 == 0:
            for t, v in [(0.0, 78), (1.5, 72), (2.5, 78)]:
                drum_notes.append(_note(37, bs + t, 0.12, v))  # 37 = side stick
        else:
            for t, v in [(1.0, 75), (2.0, 80)]:
                drum_notes.append(_note(37, bs + t, 0.12, v))
        for sixteenth in range(16):
            v = 42 if sixteenth % 4 == 0 else 30
            drum_notes.append(_note(42, bs + sixteenth * 0.25, 0.08, v))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=5, length_beats=32.0,
        name="Bridge Drums", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # ---- Bass: walking bossa through Bb / G / C / F changes ----
    walks = [
        (0.0,  [34, 36, 38, 41]),   # Bb chord
        (8.0,  [31, 34, 36, 38]),   # G chord
        (16.0, [36, 39, 41, 43]),   # C chord
        (24.0, [41, 45, 48, 50]),   # F chord
    ]
    bridge_bass: list[dict] = []
    for start, walk in walks:
        for bar in range(2):
            bridge_bass.extend(bass.walking_bass_to_next_chord(
                walk=walk, start_beat=start + bar * 4.0, bar_count=1,
            ))
    cid = M.create_clip(
        conn, track_id=tracks["03 Synth Bass"], slot=5, length_beats=32.0,
        name="Bridge Bass", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bridge_bass)
    clips["03 Synth Bass"] = cid

    # ---- Sub: root held under each chord (8 beats per chord) ----
    sub_notes = [_note(walk[0] - 12, start, 8.0, 82) for start, walk in walks]
    cid = M.create_clip(
        conn, track_id=tracks["02 Sub Bass"], slot=5, length_beats=32.0,
        name="Bridge Sub", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=sub_notes)
    clips["02 Sub Bass"] = cid

    # ---- EP comping: held 7th voicings per chord ----
    ep_voicings = [
        [58, 62, 65, 69],   # Bbmaj7
        [55, 58, 62, 65],   # Gm7
        [60, 63, 67, 70],   # Cm7
        [53, 57, 60, 63],   # F7
    ]
    ep_notes: list[dict] = []
    for i, voicing in enumerate(ep_voicings):
        ep_notes.extend(harmony.chord_pad(
            voicing, start_beat=i * 8.0, length_beats=8.0, velocity=80,
        ))
    cid = M.create_clip(
        conn, track_id=tracks["07 Bridge EP"], slot=1, length_beats=32.0,
        name="Bridge EP", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=ep_notes)
    clips["07 Bridge EP"] = cid

    return clips


def _build_tag(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Tag — 4 bars / 16 beats. Cooldown into the outro."""
    clips: dict[str, str] = {}

    # ---- Drums: half-time fade with 16th hat ride at the end ----
    drum_notes: list[dict] = []
    for b in range(4):
        bs = b * 4.0
        if b < 2:
            drum_notes.append(_note(36, bs, 0.3, 110))
            drum_notes.append(_note(38, bs + 2.0, 0.35, 105))
            for t, v in [(0.0, 70), (0.75, 85), (1.5, 85), (2.0, 70), (2.75, 85), (3.5, 80)]:
                drum_notes.append(_note(42, bs + t, 0.1, v))
        else:
            drum_notes.append(_note(36, bs, 0.25, 80))
            for sixteenth in range(16):
                v = 35 if sixteenth % 4 == 0 else 25
                drum_notes.append(_note(42, bs + sixteenth * 0.25, 0.08, v))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=6, length_beats=16.0,
        name="Tag Drums", section_role="tag",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # ---- Pad: Dm7 fading to Dm with Bb upper neighbor ----
    pad_notes = (
        harmony.chord_pad([53, 57, 60, 62], start_beat=0.0, length_beats=12.0, velocity=75)
        + harmony.chord_pad([53, 57, 58, 62], start_beat=12.0, length_beats=4.0, velocity=80)
    )
    cid = M.create_clip(
        conn, track_id=tracks["04 Verse Pad"], slot=6, length_beats=16.0,
        name="Tag Pad", section_role="tag",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    clips["04 Verse Pad"] = cid

    return clips


def _build_outro(conn, song_id: str, tracks: dict[str, str]) -> dict:
    """Outro — 8 bars / 32 beats. Fades out."""
    clips: dict[str, str] = {}

    # ---- Drums: fading kick + snare for first 4 bars, hat ticks throughout ----
    drum_notes: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        if b < 4:
            drum_notes.append(_note(36, bs, 0.25, max(95 - b * 15, 50)))
            if b < 2 and b % 2 == 0:
                drum_notes.append(_note(36, bs + 2.75, 0.25, 75))
        if b < 2:
            drum_notes.append(_note(38, bs + 1.0 + LAZY, 0.25, 90 - b * 15))
            drum_notes.append(_note(38, bs + 3.0 + LAZY, 0.25, 95 - b * 15))
        for t in [0.0, 1.0, 2.0, 3.0]:
            drum_notes.append(_note(42, bs + t, 0.1, max(75 - b * 8, 22)))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=7, length_beats=32.0,
        name="Outro Drums", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # ---- Sub: single low D1 held the whole outro ----
    cid = M.create_clip(
        conn, track_id=tracks["02 Sub Bass"], slot=7, length_beats=32.0,
        name="Outro Sub", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=[_note(26, 0.0, 32.0, 65)])
    clips["02 Sub Bass"] = cid

    # ---- Pad: Dm chord sustained 32 beats with a midway stab ----
    pad_notes = (
        harmony.chord_pad(DM_PAD, start_beat=0.0, length_beats=32.0, velocity=70)
        + harmony.chord_stab(DM_PAD, start_beat=16.0, velocity=80)
    )
    cid = M.create_clip(
        conn, track_id=tracks["04 Verse Pad"], slot=7, length_beats=32.0,
        name="Outro Pad", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=pad_notes)
    clips["04 Verse Pad"] = cid

    # ---- Lead: hook variation fading into the void ----
    lead_notes = [_note(p, s, d, 75) for s, p, d in [
        (0.0, 69, 1.0), (1.0, 65, 0.5), (1.5, 62, 1.0), (3.0, 67, 1.0),
        (4.0, 65, 0.75), (5.0, 64, 0.75), (6.0, 62, 4.0),
        (12.0, 69, 0.5), (12.75, 65, 0.75), (13.5, 62, 6.0),
    ]]
    cid = M.create_clip(
        conn, track_id=tracks["08 Chiptune Lead"], slot=2, length_beats=32.0,
        name="Outro Lead", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["08 Chiptune Lead"] = cid

    return clips


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


def _author_envelopes(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Author the song's automation envelopes.

    Two demonstrations of the new GeneratorOutput envelope pathway:
      1. Verse pad volume swell: rises from quiet to full across bars 17-24.
      2. Synth bass sidechain ducking: tracks the chorus kick hits to make room.
    """
    # Volume swell on the verse pad (8 bars in song-space ≈ beats 64-96).
    swell = volume_swell(
        target_track_id=tracks["04 Verse Pad"],
        start_beat=64.0, length_beats=32.0,
        peak_value=0.85, floor_value=0.45,
    )
    _apply_envelopes(conn, song_id, swell,
                     reason="verse pad swell into the chorus")

    # Sidechain ducking on the synth bass synced to the chorus kick downbeats.
    # Chorus kicks land on beat 1 of each bar (8 hits over 32 beats).
    #
    # W4-B routing: the duck envelope rides the chorus's Synth Bass session
    # clip (placed at beats [124, 156]). The generator emits a small pre-attack
    # window (``attack_beats``) before each hit; shifting EVERY kick by
    # ``attack_beats`` keeps the first attack_start aligned with chorus_start
    # so the envelope's beat range fits inside the chorus placement and the
    # planner can route it through the session clip.
    #
    # Trade-off: each kick shifts ~5ms late at 132bpm (attack_beats=0.02 * 60/132).
    # Build-site fix chosen over a generator-level clamp for minimal-diff
    # reasons; the principled fix (an ``envelope_start_beats`` parameter on
    # ``sidechain_trigger`` that floors attack_start at the section boundary)
    # is filed as a backlog item.
    chorus_start = 124.0  # bar 32 = beat 124 (32 - 1) * 4
    attack_beats = 0.02
    kick_beats = [
        chorus_start + attack_beats + b * 4.0
        for b in range(8)
    ]
    duck = sidechain_trigger(
        target_track_id=tracks["03 Synth Bass"],
        at_beats=kick_beats,
        rest_value=0.85, duck_value=0.55,
        attack_beats=attack_beats, recovery_beats=0.6,
    )
    _apply_envelopes(conn, song_id, duck,
                     reason="kick-synced ducking on the synth bass")


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id (UUID hex).

    W12-A: this is a state-converger. Re-running with no changes is a no-op
    (zero net events). Mutators inside the `build_session` are idempotent —
    second call with identical args returns kind='unchanged' and emits no
    event. Build-owned rows from a prior build that aren't touched this run
    get tombstoned automatically at session exit. Pulled rows (actor='sync')
    and LLM-authored edits survive.

    `--reset` remains an escape hatch for "wipe the DB and start fresh" but
    is no longer required in the normal flow.
    """
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = init_db(DB_PATH)
    try:
        with M.build_session(conn, song_name="falling-walking",
                              owner="build.py"):
            # Mix-half: replay the captured Ableton session.
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            song_id = replay_capture(
                conn, snapshot,
                song_name="falling-walking",
                song_title="Falling, Walking",
                song_key="Dm",
                actor="sync", reason="chunk-5 capture replay",
            )

            # Score-half.
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=132.0)
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
            )

            # Section markers.
            M.create_section(conn, song_id=song_id, name="intro",
                             start_bar=float(INTRO_BAR), end_bar=float(VERSE_BAR),
                             notes_md="progressive hat journey + chord block crescendo")
            M.create_section(conn, song_id=song_id, name="verse",
                             start_bar=float(VERSE_BAR), end_bar=float(CHORUS_BAR),
                             notes_md="trip-hop drums + Dm pad with detailed bass embellishments")
            M.create_section(conn, song_id=song_id, name="chorus",
                             start_bar=float(CHORUS_BAR), end_bar=float(TWIST_BAR),
                             notes_md="tresillo bass walking Dm-F-C-G")
            M.create_section(conn, song_id=song_id, name="chorus_twist",
                             start_bar=float(TWIST_BAR), end_bar=float(BRIDGE_BAR),
                             notes_md="C3' variant — walks to Bb instead of G")
            M.create_section(conn, song_id=song_id, name="bridge",
                             start_bar=float(BRIDGE_BAR), end_bar=float(TAG_BAR),
                             notes_md="walking bossa through Bb major (Bbmaj7 / Gm7 / Cm7 / F7)")
            M.create_section(conn, song_id=song_id, name="tag",
                             start_bar=float(TAG_BAR), end_bar=float(OUTRO_BAR),
                             notes_md="cooldown into the outro")
            M.create_section(conn, song_id=song_id, name="outro",
                             start_bar=float(OUTRO_BAR), end_bar=float(END_BAR),
                             notes_md="fade out — pad + sub + lead hook variation")

            # Cue points at every section boundary.
            for bar, name in [(INTRO_BAR, "intro"), (VERSE_BAR, "verse"),
                              (CHORUS_BAR, "chorus"), (TWIST_BAR, "chorus_twist"),
                              (BRIDGE_BAR, "bridge"), (TAG_BAR, "tag"),
                              (OUTRO_BAR, "outro")]:
                M.add_cue_point(conn, song_id=song_id, position_bar=float(bar), name=name)

            tracks = _tracks_by_name(conn, song_id)

            # Build each section's clips.
            intro   = _build_intro(conn, song_id, tracks)
            verse   = _build_verse(conn, song_id, tracks)
            chorus  = _build_chorus(conn, song_id, tracks, twist=False)
            twist   = _build_chorus(conn, song_id, tracks, twist=True)
            bridge_ = _build_bridge(conn, song_id, tracks)
            tag     = _build_tag(conn, song_id, tracks)
            outro   = _build_outro(conn, song_id, tracks)

            # Arrangement: every section drops its clips at its bar range.
            _arrange_section(conn, song_id, tracks, intro,   start_bar=float(INTRO_BAR),  end_bar=float(VERSE_BAR))
            _arrange_section(conn, song_id, tracks, verse,   start_bar=float(VERSE_BAR),  end_bar=float(CHORUS_BAR))
            _arrange_section(conn, song_id, tracks, chorus,  start_bar=float(CHORUS_BAR), end_bar=float(TWIST_BAR))
            _arrange_section(conn, song_id, tracks, twist,   start_bar=float(TWIST_BAR),  end_bar=float(BRIDGE_BAR))
            _arrange_section(conn, song_id, tracks, bridge_, start_bar=float(BRIDGE_BAR), end_bar=float(TAG_BAR))
            _arrange_section(conn, song_id, tracks, tag,     start_bar=float(TAG_BAR),    end_bar=float(OUTRO_BAR))
            _arrange_section(conn, song_id, tracks, outro,   start_bar=float(OUTRO_BAR),  end_bar=float(END_BAR))

            # Automation envelopes demonstrate the new envelope pathway end-to-end.
            _author_envelopes(conn, song_id, tracks)

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
            mixer = []
            if t["volume"] is not None:
                mixer.append(f"v={t['volume']:.3f}")
            if t["pan"] is not None and t["pan"] != 0:
                mixer.append(f"p={t['pan']:+.2f}")
            mixer_str = f" [{', '.join(mixer)}]" if mixer else ""
            clips = Q.get_clips_for_track(conn, t["id"])
            print(f"  track {t['track_index']:>2}  {t['name']:<16} "
                  f"({t['kind']}, {len(clips)} clips){mixer_str}")
            for c in clips:
                notes = Q.get_notes_for_clip(conn, c["id"])
                total_notes += len(notes)
                print(f"      slot {c['slot']}  {c['name']:<28} "
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
