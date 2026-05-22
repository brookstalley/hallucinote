"""Build full-band-rock into a SQLite DB using the hallucinote layer.

Canary Wave 0 song (run #2). Exercises:
  - 8 main tracks (drums MIDI, bass MIDI, 2x guitar AUDIO placeholders,
    keys MIDI w/ third-party VST, backing-vox pad MIDI, lead vocal AUDIO,
    parallel-comp bus AUDIO routing target) + 3 returns + master.
  - Repeated sections in the arrangement: verse x2, chorus x3.
  - Originally targeted master fade-out automation + lead-vocal sidechain
    ducking. Wave 0 surfaced both as architectural blockers (Group D);
    W10-F (2026-05-20) refuses them at the DB-mutator layer with
    teaching errors pointing at the sub-bus group pattern. This canary
    no longer authors envelopes (see `_author_envelopes` docstring);
    the v1.1 sub-bus pattern demo is backlogged.
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
    outro     bars 73- 81   ( 8 bars / 32 beats) — chorus tag (v1.1: + master fade via sub-bus)

Total: 80 bars / 320 beats. At 108 BPM: ~2:58.

Run:
    python3 songs/full-band-rock/build.py --reset
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.generators import bass, drums, harmony

# Per-branch DB path so feature branches don't clobber each other's state.
# Convention matches `falling-walking/build.py`.
DB_PATH = resolve_db_path("full-band-rock", root=Path(__file__).parent.parent)
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
    """Outro — 8 bars / 32 beats. Chorus tag.

    Uses chord pattern from chorus, but trimmed (4 bars Em-G-D-C, then 4 bars
    Em sustained). The brief originally called for a master fade-out via
    `mixer_volume` envelope on the master track; W10-F refuses that target
    (D2 — no LOM path). The v1.1 sub-bus pattern would put the fade on a
    group track instead; until then the outro tag is structural only.
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
    """Envelope authoring — WAVE 0 FINDINGS REIFIED AT V1.

    The original canary brief named two envelope targets:
      1. Master fade-out (mixer_volume on the master track)
      2. Sidechain placeholder ducking lead vocal (mixer_volume on
         the `07 Lead Vocal` audio track)

    Wave 0 surfaced both as architectural blockers. The follow-up
    investigation (bug-triage-wave2 Group D) confirmed no LOM path
    exists in v1:
      - Master envelopes require a Clip; the master track cannot host
        clips. The supported pattern is a sub-bus GROUP track that the
        sources are routed into; the envelope rides the group's mixer.
      - Audio-track mixer/send envelopes require an audio session
        clip to host them; Hallucinote v1 models clips as MIDI-only.

    W10-F now refuses both at the DB-mutator AND planner layers with
    a teaching error pointing at the sub-bus workaround. Attempting
    either here would raise `ValueError` at `create_envelope`. Per
    the v1 canary's role (demonstrate the v1 surface a sophisticated
    user actually has), this function intentionally authors NO
    envelopes — the unreachable surfaces are documented in their
    docstrings + `docs/canary-songs/full-band-rock.md` + the
    `ableton://guides/gaps.md` Group-D entries.

    v1.1 enhancements (filed in backlog):
      - The full sub-bus pattern demo (requires adding a kind='midi'
        group track to the snapshot + routing audio tracks into it).
      - Audio-clip DB model so D3 can be lifted directly.
    """
    # Intentionally empty. See docstring — both Wave 0 envelope targets are
    # refused-with-teaching by W10-F; v1 surfaces no envelopes for this
    # canary. Variables retained for v1.1 sub-bus pattern integration.
    _ = (tracks, returns)


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id."""
    conn = init_db(DB_PATH)
    try:
        existing = Q.get_song_by_name(conn, "full-band-rock")
        if existing and not reset:
            print(f"song already exists (id={existing['id']}); use --reset to rebuild")
            return existing["id"]
        if reset and existing is not None:
            M.reset_song_content(conn, song_id=existing["id"])

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

        # No envelopes — Wave 0's master fade + lead-vocal sidechain are
        # refused by W10-F; see _author_envelopes docstring.
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
