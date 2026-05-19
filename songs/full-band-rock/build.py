"""Build full-band-rock into a SQLite DB using the hallucinote layer.

Canary Wave 0 song (run #2). Exercises:
  - 8 main tracks (drums MIDI, bass MIDI, 2x guitar AUDIO placeholders,
    keys MIDI w/ third-party VST, backing-vox pad MIDI, lead vocal AUDIO,
    parallel-comp bus AUDIO routing target) + 3 returns + master.
  - Repeated sections in the arrangement: verse x2, chorus x3.
  - Master fade-out automation (mixer_volume envelope on master track).
  - Sidechain placeholder on lead vocal (DB has no sidechain-routing model;
    the routing intent is only in the snapshot's _note).
  - Third-party VST guessed on Keys (Spitfire LABS Soft Piano) — likely
    will fail to load at push time, surfacing W13-A's design need.

Section bar layout (1-based, half-open):
    intro     bars  1-  9   ( 8 bars / 32 beats) — drums + bass build
    verse #1  bars  9- 25   (16 bars / 64 beats) — + rhythm guitar (audio) + lead vocal (audio)
    chorus #1 bars 25- 33   ( 8 bars / 32 beats) — full band, backing-vox pad, lead-guitar fill
    verse #2  bars 33- 49   (16 bars / 64 beats) — repeat verse shape
    chorus #2 bars 49- 57   ( 8 bars / 32 beats) — repeat chorus
    bridge    bars 57- 65   ( 8 bars / 32 beats) — keys + lead vocal only
    chorus #3 bars 65- 73   ( 8 bars / 32 beats) — final chorus, all in
    outro     bars 73- 81   ( 8 bars / 32 beats) — chorus tag, master fade

Total: 80 bars / 320 beats. At 108 BPM: ~2:58.

Run:
    python3 songs/full-band-rock/build.py --reset
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.generators import bass, drums, harmony
from hallucinote.generators.envelopes import sidechain_trigger, volume_swell

DB_PATH = Path(__file__).parent / "full-band-rock.db"
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

# Section bar boundaries (1-based; end is the start of the next section).
INTRO_BAR    = 1
VERSE1_BAR   = 9
CHORUS1_BAR  = 25
VERSE2_BAR   = 33
CHORUS2_BAR  = 49
BRIDGE_BAR   = 57
CHORUS3_BAR  = 65
OUTRO_BAR    = 73
END_BAR      = 81

# E minor harmony — root notes (MIDI).
# E natural minor: E F# G A B C D
E1, B1 = 28, 35
E2, F2S, G2, A2, B2, C3, D3 = 40, 42, 43, 45, 47, 48, 50
E3, F3S, G3, A3, B3 = 52, 54, 55, 57, 59
E4, G4, B4 = 64, 67, 71

# Chord voicings (Em / G / D / C / B7 pattern — typical rock progression).
EM_PAD = [E3, G3, B3]        # i
G_PAD  = [G3, B3, 62]        # bIII (D=62)
D_PAD  = [62, F3S, A3]       # bVII
C_PAD  = [C3, E3, G3]        # bVI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _returns_by_name(conn, song_id: str) -> dict[str, str]:
    return {row["name"]: row["id"] for row in Q.get_returns_for_song(conn, song_id)}


def _apply_envelopes(conn, song_id, output, *, actor="generator", reason=None):
    """Persist every envelope spec in `output.envelopes` via mutators.

    Copied verbatim from solo-piano-ambient/build.py — there is no shared
    library helper. Same scaffold gap as Step 1 of the solo-piano-ambient
    runbook.
    """
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


def _build_intro(conn, song_id, tracks) -> dict:
    """Intro — 8 bars / 32 beats. Drums + bass building from sparse to full."""
    clips: dict[str, str] = {}

    # ---- Drums: hat-only first 2 bars, kick in bar 3, snare bar 5, full kit bar 7
    dn: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        # Hi-hat 8ths throughout, dynamics building.
        for t in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
            dn.append(_note(42, bs + t, 0.1, 45 + b * 5))
        if b >= 2:
            dn.append(_note(36, bs, 0.3, 100))        # kick beat 1
            dn.append(_note(36, bs + 2.0, 0.3, 90))   # kick beat 3
        if b >= 4:
            dn.append(_note(38, bs + 1.0, 0.3, 105))  # snare beat 2
            dn.append(_note(38, bs + 3.0, 0.3, 110))  # snare beat 4
        if b == 7:
            # Crash on the final beat to push into verse.
            dn.append(_note(49, bs + 3.5, 1.0, 115))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=1, length_beats=32.0,
        name="Intro Drums", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=dn)
    clips["01 Drums"] = cid

    # ---- Bass: low E drone (root pedal), building rhythmically.
    bn: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        if b < 2:
            bn.append(_note(E2, bs, 4.0, 70))
        elif b < 4:
            bn.append(_note(E2, bs, 2.0, 80))
            bn.append(_note(E2, bs + 2.0, 2.0, 80))
        else:
            # 8th-note drive on root.
            for t in [0.0, 1.0, 2.0, 3.0, 3.5]:
                bn.append(_note(E2, bs + t, 0.8, 95))
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=1, length_beats=32.0,
        name="Intro Bass", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bn)
    clips["02 Bass"] = cid

    return clips


def _build_verse(conn, song_id, tracks, *, occurrence: int) -> dict:
    """Verse — 16 bars / 64 beats. Same shape; occurrence distinguishes
    arrangement placement only.

    NOTE on repeated sections: the brief asks how the agent names repeated
    sections. The DB schema's `sections` table has NO uniqueness constraint
    on (song_id, name) — so multiple "verse" sections in the same song are
    legal. But CLIPS live on the track's slot lane (UNIQUE(track_id, slot)),
    so two verses can't both occupy the same clip slot. So in the session
    view we have to give the second verse its OWN slot. We name the slot
    "Verse 2" with section_role="verse" — the section_role stays semantic;
    the slot name disambiguates for session-view display.

    The ARRANGEMENT model just records (track, clip, start_bar, end_bar);
    placing the same clip twice in the arrangement DOES NOT round-trip
    cleanly because each arrangement entry has a unique start_bar but
    references one clip_id (so changes to the clip affect both placements).

    For the canary we build TWO distinct verse clips (slot 2 + slot 5),
    identical content. This is the workaround; whether it's intended is
    one of the open questions.
    """
    clips: dict[str, str] = {}
    slot = 2 if occurrence == 1 else 5
    label = f"Verse {occurrence}"

    # ---- Drums: backbeat throughout, simple fill on bar 16.
    dn: list[dict] = []
    for b in range(16):
        bs = b * 4.0
        dn.append(_note(36, bs, 0.3, 110))            # kick 1
        dn.append(_note(36, bs + 2.0, 0.3, 100))      # kick 3
        dn.append(_note(38, bs + 1.0, 0.3, 105))      # snare 2
        dn.append(_note(38, bs + 3.0, 0.3, 110))      # snare 4
        for t in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
            dn.append(_note(42, bs + t, 0.1, 70))     # hat 8ths
        if b == 15:
            # Tom fill into chorus.
            for i, p in enumerate([50, 50, 47, 47, 45, 45]):
                dn.append(_note(p, bs + 2.0 + i * 0.25, 0.15, 100))
            dn.append(_note(49, bs + 3.5, 1.0, 115))  # crash
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=slot, length_beats=64.0,
        name=f"{label} Drums", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=dn)
    clips["01 Drums"] = cid

    # ---- Bass: Em-G-D-C 4-bar progression, 4x = 16 bars.
    bn: list[dict] = []
    chord_roots = [E2, G2, 50, 48]  # Em, G, D, C
    for cycle in range(4):
        for i, root in enumerate(chord_roots):
            base = (cycle * 16 + i * 4)
            # Tresillo-ish bass: 1, +.75, +1.5, +3
            for t, dur, v in [(0.0, 0.5, 100), (0.75, 0.5, 95),
                              (1.5, 0.5, 90),  (3.0, 1.0, 85)]:
                bn.append(_note(root, base + t, dur, v))
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=slot, length_beats=64.0,
        name=f"{label} Bass", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bn)
    clips["02 Bass"] = cid

    return clips


def _build_chorus(conn, song_id, tracks, *, occurrence: int) -> dict:
    """Chorus — 8 bars / 32 beats. Full band + backing-vox pad + lead-guitar
    fill placeholder (lead guitar is audio, no notes — so this only emits the
    backing pad in addition to drums + bass).

    occurrence ∈ {1, 2, 3}. Same repeated-sections workaround as _build_verse.
    """
    clips: dict[str, str] = {}
    slot = 3 if occurrence == 1 else (6 if occurrence == 2 else 7)
    label = f"Chorus {occurrence}"

    # ---- Drums: harder backbeat with open hat lifts.
    dn: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        dn.append(_note(36, bs, 0.3, 118))            # kick 1
        dn.append(_note(36, bs + 2.0, 0.3, 110))      # kick 3
        dn.append(_note(38, bs + 1.0, 0.3, 115))      # snare 2
        dn.append(_note(38, bs + 3.0, 0.3, 118))      # snare 4
        for t in [0.0, 1.0, 2.0, 3.0]:
            dn.append(_note(42, bs + t, 0.1, 85))     # hat quarter
        for t in [0.5, 1.5, 2.5]:
            dn.append(_note(46, bs + t, 0.15, 80))    # open hat off-beats
        if b == 0:
            dn.append(_note(49, bs, 1.5, 110))         # crash bar 1
        if b == 4:
            dn.append(_note(57, bs, 1.5, 95))          # crash 2 bar 5
        if b == 7 and occurrence == 3:
            # Final-chorus end: ride bell into outro.
            dn.append(_note(53, bs + 3.5, 0.5, 100))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=slot, length_beats=32.0,
        name=f"{label} Drums", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=dn)
    clips["01 Drums"] = cid

    # ---- Bass: same Em-G-D-C, more drive (8ths on root).
    bn: list[dict] = []
    chord_roots = [E2, G2, 50, 48]  # Em, G, D, C
    for cycle in range(2):
        for i, root in enumerate(chord_roots):
            base = (cycle * 16 + i * 4)
            for t in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
                bn.append(_note(root, base + t, 0.4, 100))
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=slot, length_beats=32.0,
        name=f"{label} Bass", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bn)
    clips["02 Bass"] = cid

    # ---- Keys (Spitfire LABS Soft Piano): chord pad voicings.
    kn: list[dict] = []
    for cycle in range(2):
        for i, voicing in enumerate([EM_PAD, G_PAD, D_PAD, C_PAD]):
            base = (cycle * 16 + i * 4)
            kn.extend(harmony.chord_pad(
                voicing, start_beat=base, length_beats=4.0, velocity=70,
            ))
    cid = M.create_clip(
        conn, track_id=tracks["05 Keys"], slot=slot, length_beats=32.0,
        name=f"{label} Keys", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=kn)
    clips["05 Keys"] = cid

    # ---- Backing-vocal pad: held thirds/fifths matching the chord cycle.
    vn: list[dict] = []
    pad_voicings = [
        [B3, E4],  # over Em
        [62, G4],  # over G (D + G)
        [F3S, A3], # over D
        [E3, G3],  # over C
    ]
    for cycle in range(2):
        for i, voicing in enumerate(pad_voicings):
            base = (cycle * 16 + i * 4)
            for p in voicing:
                vn.append(_note(p, base, 4.0, 65))
    cid = M.create_clip(
        conn, track_id=tracks["06 Backing Vox Pad"], slot=slot,
        length_beats=32.0,
        name=f"{label} Backing Vox", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=vn)
    clips["06 Backing Vox Pad"] = cid

    return clips


def _build_bridge(conn, song_id, tracks) -> dict:
    """Bridge — 8 bars / 32 beats. Drop to keys + lead vocal only.

    Lead vocal is an AUDIO track placeholder — no notes. So the bridge
    produces ONE clip total (on keys). The audio-track surface area for
    bridge intent ("keys + lead vocal only") is entirely outside the DB.
    """
    clips: dict[str, str] = {}

    # ---- Keys: slow sustained chord progression (different colour from chorus).
    # Use a sad descending shape: Em / D / C / B7
    bridge_voicings = [
        [E3, G3, B3, E4],   # Em
        [62, F3S, A3, 62],  # D
        [C3, E3, G3, C4 if False else 60],  # C — keep C4=60
        [B2, F3S, A3, 59],  # B7-ish (no major 3rd to stay modal)
    ]
    kn: list[dict] = []
    for i, voicing in enumerate(bridge_voicings):
        base = i * 8.0  # 2 bars per chord
        # Each voice held for 8 beats with a slight stab on beat 5.
        for p in voicing:
            kn.append(_note(p, base, 8.0, 55))
        # Stab.
        for p in voicing:
            kn.append(_note(p, base + 4.0, 0.8, 78))
    cid = M.create_clip(
        conn, track_id=tracks["05 Keys"], slot=4, length_beats=32.0,
        name="Bridge Keys", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=kn)
    clips["05 Keys"] = cid

    return clips


def _build_outro(conn, song_id, tracks) -> dict:
    """Outro — 8 bars / 32 beats. Chorus tag with master fade automation.

    Uses chord pattern from chorus, but trimmed (4 bars Em-G-D-C, then 4 bars
    Em sustained). Fade-out is on the master via a separate envelope.
    """
    clips: dict[str, str] = {}

    # ---- Drums: chorus-style for 4 bars, then thin out.
    dn: list[dict] = []
    for b in range(8):
        bs = b * 4.0
        if b < 4:
            dn.append(_note(36, bs, 0.3, 110))
            dn.append(_note(38, bs + 1.0, 0.3, 110))
            dn.append(_note(38, bs + 3.0, 0.3, 110))
        else:
            # Only ride cymbal sustained — outro tail.
            dn.append(_note(51, bs, 4.0, 60 - (b - 4) * 10))
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=8, length_beats=32.0,
        name="Outro Drums", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=dn)
    clips["01 Drums"] = cid

    # ---- Bass: 8th-note Em-G-D-C, then Em pedal.
    bn: list[dict] = []
    chord_roots = [E2, G2, 50, 48]
    for i, root in enumerate(chord_roots):
        base = i * 4.0
        for t in [0.0, 1.0, 2.0, 3.0]:
            bn.append(_note(root, base + t, 0.8, 95))
    # Bars 5-8 Em pedal.
    bn.append(_note(E2, 16.0, 16.0, 80))
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=8, length_beats=32.0,
        name="Outro Bass", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bn)
    clips["02 Bass"] = cid

    return clips


# ---------------------------------------------------------------------------
# Arrangement + envelopes
# ---------------------------------------------------------------------------


def _arrange_section(conn, song_id, tracks, clips: dict[str, str],
                     *, start_bar: float, end_bar: float) -> None:
    for track_name, clip_id in clips.items():
        M.add_arrangement_clip(
            conn, song_id=song_id,
            track_id=tracks[track_name], clip_id=clip_id,
            start_bar=start_bar, end_bar=end_bar,
        )


def _author_envelopes(conn, song_id, tracks, returns) -> None:
    """Author the song's automation envelopes.

    Three demonstrations:
      1. MASTER FADE-OUT: mixer_volume envelope on the master track over the
         outro's first 4 bars (bars 73-77 = beats 288-304). This is the brief's
         central target — exercises whether master is a first-class envelope
         target. The master track was created by replay_capture with
         track_index=0 (sentinel). We look it up by name "Master".
      2. SIDECHAIN PLACEHOLDER on lead vocal (sidechain_trigger envelope on
         the lead-vocal track ducking by drum kick hits in chorus #3). The
         lead-vocal track is AUDIO — `mixer_volume` envelopes on an audio
         track are legal in the DB schema, but whether push routes them is
         a question.
      3. Verse-pad swell — skipped, the only "pad" is backing vox which
         doesn't need swell. (Omitted intentionally to keep the focus.)
    """
    # --- 1. Master fade-out (the brief's target) ---
    # bars 73-77 = beats 288-304 (4 bars at 4 beats/bar).
    outro_start_beat = (OUTRO_BAR - 1) * 4.0   # = 288.0
    fade_end_beat    = outro_start_beat + 16.0  # = 304.0 (4 bars of fade)
    master_id = tracks["Master"]
    fade_env = M.create_envelope(
        conn, song_id=song_id, target_kind="mixer_volume",
        target_track_id=master_id,
        actor="generator",
        reason="master fade-out at outro (canary target)",
    )
    M.replace_breakpoints(
        conn, envelope_id=fade_env, actor="generator",
        reason="linear fade from full to silent over 4 bars",
        breakpoints=[
            {"time_beats": outro_start_beat, "value": 0.82, "curve_kind": "linear"},
            {"time_beats": fade_end_beat,    "value": 0.00, "curve_kind": "linear"},
        ],
    )

    # --- 2. Sidechain placeholder: kick-synced ducking on lead vocal.
    # Chorus #3 (bar 65-73): kicks land on beat 1 of each bar (8 kicks over
    # 32 beats). Beat 0 of chorus #3 = (65-1)*4 = 256.
    # NOTE: same generator-emits-pre-attack issue as falling-walking; we shift
    # by attack_beats to keep the envelope inside the section.
    chorus3_start = (CHORUS3_BAR - 1) * 4.0  # = 256.0
    attack_beats = 0.02
    kick_beats = [chorus3_start + attack_beats + b * 4.0 for b in range(8)]
    duck = sidechain_trigger(
        target_track_id=tracks["07 Lead Vocal"],
        at_beats=kick_beats,
        rest_value=0.85, duck_value=0.55,
        attack_beats=attack_beats, recovery_beats=0.6,
    )
    _apply_envelopes(conn, song_id, duck,
                     reason="lead vocal sidechained to drum bus (placeholder)")


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id."""
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = init_db(DB_PATH)
    try:
        existing = Q.get_song_by_name(conn, "full-band-rock")
        if existing and not reset:
            print(f"song already exists (id={existing['id']}); use --reset to rebuild")
            return existing["id"]

        # Mix-half: replay the hand-authored snapshot.
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        song_id = replay_capture(
            conn, snapshot,
            song_name="full-band-rock",
            song_title="Full Band Rock",
            song_key="Em",
            actor="sync", reason="canary build #2 — hand-authored snapshot replay",
        )

        # Score-half.
        M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=108.0)
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
        )

        # Section markers — NOTE the repeated names. Schema has no UNIQUE
        # constraint on (song_id, name) so this is legal but means downstream
        # consumers looking up by name will hit ambiguity. We use bar ranges
        # to disambiguate but the section_role column on clips is shared.
        M.create_section(conn, song_id=song_id, name="intro",
                         start_bar=float(INTRO_BAR), end_bar=float(VERSE1_BAR),
                         notes_md="drums + bass building")
        M.create_section(conn, song_id=song_id, name="verse",
                         start_bar=float(VERSE1_BAR), end_bar=float(CHORUS1_BAR),
                         notes_md="verse #1 — first lyric")
        M.create_section(conn, song_id=song_id, name="chorus",
                         start_bar=float(CHORUS1_BAR), end_bar=float(VERSE2_BAR),
                         notes_md="chorus #1 — full band")
        M.create_section(conn, song_id=song_id, name="verse",
                         start_bar=float(VERSE2_BAR), end_bar=float(CHORUS2_BAR),
                         notes_md="verse #2 — lyric variation")
        M.create_section(conn, song_id=song_id, name="chorus",
                         start_bar=float(CHORUS2_BAR), end_bar=float(BRIDGE_BAR),
                         notes_md="chorus #2 — repeat")
        M.create_section(conn, song_id=song_id, name="bridge",
                         start_bar=float(BRIDGE_BAR), end_bar=float(CHORUS3_BAR),
                         notes_md="drop to keys + lead vocal")
        M.create_section(conn, song_id=song_id, name="chorus",
                         start_bar=float(CHORUS3_BAR), end_bar=float(OUTRO_BAR),
                         notes_md="chorus #3 — final, all in")
        M.create_section(conn, song_id=song_id, name="outro",
                         start_bar=float(OUTRO_BAR), end_bar=float(END_BAR),
                         notes_md="chorus tag, fade via master automation")

        # Cue points at every section boundary. NOTE: cue_points also has no
        # uniqueness constraint, so we can add multiple cues with name="chorus"
        # — same ambiguity question.
        for bar, name in [(INTRO_BAR, "intro"), (VERSE1_BAR, "verse"),
                          (CHORUS1_BAR, "chorus"), (VERSE2_BAR, "verse"),
                          (CHORUS2_BAR, "chorus"), (BRIDGE_BAR, "bridge"),
                          (CHORUS3_BAR, "chorus"), (OUTRO_BAR, "outro")]:
            M.add_cue_point(conn, song_id=song_id, position_bar=float(bar), name=name)

        tracks = _tracks_by_name(conn, song_id)
        returns = _returns_by_name(conn, song_id)

        # Build each section's clips. Audio tracks (03 Rhythm Guitar, 04 Lead
        # Guitar, 07 Lead Vocal, 08 Parallel Comp Bus) get NO clips — they're
        # placeholders for audio not modeled by the DB.
        intro_clips    = _build_intro(conn, song_id, tracks)
        verse1_clips   = _build_verse(conn, song_id, tracks, occurrence=1)
        chorus1_clips  = _build_chorus(conn, song_id, tracks, occurrence=1)
        verse2_clips   = _build_verse(conn, song_id, tracks, occurrence=2)
        chorus2_clips  = _build_chorus(conn, song_id, tracks, occurrence=2)
        bridge_clips   = _build_bridge(conn, song_id, tracks)
        chorus3_clips  = _build_chorus(conn, song_id, tracks, occurrence=3)
        outro_clips    = _build_outro(conn, song_id, tracks)

        # Arrangement.
        _arrange_section(conn, song_id, tracks, intro_clips,
                         start_bar=float(INTRO_BAR),   end_bar=float(VERSE1_BAR))
        _arrange_section(conn, song_id, tracks, verse1_clips,
                         start_bar=float(VERSE1_BAR),  end_bar=float(CHORUS1_BAR))
        _arrange_section(conn, song_id, tracks, chorus1_clips,
                         start_bar=float(CHORUS1_BAR), end_bar=float(VERSE2_BAR))
        _arrange_section(conn, song_id, tracks, verse2_clips,
                         start_bar=float(VERSE2_BAR),  end_bar=float(CHORUS2_BAR))
        _arrange_section(conn, song_id, tracks, chorus2_clips,
                         start_bar=float(CHORUS2_BAR), end_bar=float(BRIDGE_BAR))
        _arrange_section(conn, song_id, tracks, bridge_clips,
                         start_bar=float(BRIDGE_BAR),  end_bar=float(CHORUS3_BAR))
        _arrange_section(conn, song_id, tracks, chorus3_clips,
                         start_bar=float(CHORUS3_BAR), end_bar=float(OUTRO_BAR))
        _arrange_section(conn, song_id, tracks, outro_clips,
                         start_bar=float(OUTRO_BAR),   end_bar=float(END_BAR))

        # Master fade + sidechain ducking on lead vocal.
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
            print(f"  track {t['track_index']:>2}  {t['name']:<24} "
                  f"({t['kind']}, {len(clips)} clips)")
            for c in clips:
                notes = Q.get_notes_for_clip(conn, c["id"])
                total_notes += len(notes)
                print(f"      slot {c['slot']}  {c['name']:<24} "
                      f"{c['length_beats']:>6.1f}bt  {len(notes):>4} notes")
        print(f"total notes: {total_notes}")
        returns = Q.get_returns_for_song(conn, song_id)
        print(f"returns: {[r['name'] for r in returns]}")
        sections = Q.get_sections_for_song(conn, song_id)
        print(f"sections: {[s['name'] for s in sections]}")
        arr = Q.get_arrangement_for_song(conn, song_id)
        print(f"arrangement entries: {len(arr)}")
        envs = Q.get_envelopes_for_song(conn, song_id)
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
