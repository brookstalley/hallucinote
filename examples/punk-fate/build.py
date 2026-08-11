"""Build Punk Fate into a SQLite DB using the hallucinote layer.

Beethoven's Fifth Symphony crammed into two minutes of basement punk. The whole
four-movement harmonic arc — C minor fate riff, the E-flat relative-major lift,
the A-flat andante as a half-time breakdown (with Beethoven's own C-major
foreshadow), the C minor scherzo, the great dominant-pedal transition, and the
C MAJOR finale with its hammering coda — played by drums, bass, lead guitar, and
a staccato mono-synth singing the vocal line.

The motif is the engine. Short-short-short-LONG is not quoted, it IS the riff:
it opens the song as G-G-G-E♭ and closes it as G-G-G-E♮. One semitone is the
whole symphony. See decisions/03-the-fate-motif-is-the-riff.md.

Section bar layout (1-based, 4/4 at 200 BPM — one bar = 1.20 s):
    intro-fate    bars  1-8    ( 8 bars)  Cm — the cell, with full-band holes
    verse-cm      bars  9-24   (16 bars)  Cm  Ab  Eb  G      (i ♭VI ♭III V)
    chorus-eb     bars 25-36   (12 bars)  Eb  Bb  Cm  Ab     (I V vi IV)
    break-ab      bars 37-48   (12 bars)  Ab — half-time, + a 2-bar C-major blaze
    scherzo-cm    bars 49-64   (16 bars)  Cm(4) Ab(2) G(2)   — hardcore skank
    bridge-pedal  bars 65-72   ( 8 bars)  C pedal under Ab → G → G7, crescendo
    finale-cmaj   bars 73-88   (16 bars)  C  F  G  C         (I IV V I)
    coda          bars 89-96   ( 8 bars)  C — hammered, ends on the major cell

Run:
    python examples/punk-fate/build.py            # state-converger: re-run is no-op if nothing changed
    python examples/punk-fate/build.py --reset    # drop + rebuild from scratch
    python examples/punk-fate/build.py --force-replay
        # consciously revert live edits pulled via /ableton-pull that are newer
        # than captured_session.json (replay otherwise refuses; the durable fix
        # is a re-capture via /song-snapshot — see StaleSnapshotError)
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

from hallucinote.authoring import arrange_section, run_build
from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.generators.primitives import (
    CRASH_1,
    HAT_CLOSED,
    HAT_OPEN,
    KICK,
    SNARE,
    TOM_HI,
    TOM_LO,
)
from hallucinote.melody import MelodicProfile, MelodyReport, SectionMelody, analyze_melody
from hallucinote.performance import PerformanceProfile, apply_profile
from hallucinote.theory.model import Progression

# Per-branch DB filename (W12-A): branch switches pick up the right DB
# silently; outside a repo / detached HEAD falls back to punk-fate.db.
DB_PATH = resolve_db_path("punk-fate", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"


# ---------------------------------------------------------------------------
# Section bar boundaries (1-based) — see decisions/02-tempo-and-the-section-budget.md
# ---------------------------------------------------------------------------
INTRO_FATE_BAR = 1
VERSE_CM_BAR = 9
CHORUS_EB_BAR = 25
BREAK_AB_BAR = 37
SCHERZO_CM_BAR = 49
BRIDGE_PEDAL_BAR = 65
FINALE_CMAJ_BAR = 73
CODA_BAR = 89
END_BAR = 97

BEATS = 4.0

TRACK_DRUMS = "01 Drums"
TRACK_BASS = "02 Bass"
TRACK_GUITAR = "03 Guitar"
TRACK_VOICE = "04 Voice"


# ---------------------------------------------------------------------------
# The four players — decisions/04-per-part-feel.md, extended by
# decisions/08-sloppy-but-enthusiastic.md.
#
# The guitar pulls the band forward, the bass refuses to be pulled, the snare
# leans into the backbeat, and the singer leans into the top of every phrase.
# The groove lives in the ~16-tick gap BETWEEN guitar and bass — that part was
# right and is unchanged.
#
# What it was missing is that a constant offset is not sloppiness. The
# generator layer's `apply_feel` keys its shift on the WITHIN-BAR POSITION, so
# every bar gets the identical offset at the identical place: a perfectly
# quantized part slid a few ticks early, which the performance lens correctly
# grades MECHANICAL. That is why this read as Beethoven-played-correctly.
#
# The fix is NOT a per-note random nudge — memoryless noise grades SLOPPY, the
# opposite failure (performance-model.md §3.8, §4.4). What reads human is 1/f
# CORRELATION, and it is magnitude-independent, so a punk-sized deviation can
# still read human. So each player declares a `PerformanceProfile` and
# `performance.apply_profile` realizes it over the finished part (`_perform`),
# on top of the authored drag/accents/rush this file still owns.
# ---------------------------------------------------------------------------


def _rand(*key) -> float:
    """Deterministic pseudo-random in [-1.0, 1.0), keyed by the note's identity.

    blake2b of the key, NOT the builtin ``hash()``: Python salts string hashing
    per process, so ``hash()`` would give two runs of the same build different
    timing and break the state-converger promise the shape test locks. Same
    note, same bar, same run or next week — same wobble.
    """
    digest = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 63) - 1.0


def _seed(*key) -> int:
    """A deterministic 31-bit seed from a key tuple, for ``apply_profile``."""
    return int.from_bytes(hashlib.blake2b(repr(key).encode(), digest_size=4).digest(),
                          "big") & 0x7FFFFFFF


class Player:
    """One human at one instrument.

    Three things are AUTHORED here — they are decisions, not noise, and none of
    them is expressible as a performance profile:

    ``drag``    constant offset in beats; negative is ahead of the grid. The
                band-pulls-against-its-anchor gap, kept from decisions/04.
    ``accents`` extra shift at named within-bar positions — the snare leaning
                into the backbeat, the singer leaning into a phrase start.
    ``rush``    beats of forward creep accumulated by the END of a bar. An
                excited player does not start early, they GET early, so the
                creep scales with position and resets at the downbeat. A
                deliberate accelerando, not a fluctuation. This is the
                "enthusiastic".

    The fourth thing — the breathing that makes a part read as a person rather
    than a grid — is NOT authored here. It is declared as a
    ``PerformanceProfile`` and realized by ``performance.apply_profile`` over
    the finished part, because *what makes deviation sound human is its
    correlation structure, not its size*: 1/f-correlated breathing reads human,
    memoryless white noise reads sloppy, and a constant offset reads mechanical
    (`.prawduct/artifacts/performance-model.md` §3.8, §4.4). Punk wants a large
    deviation, and magnitude is exactly the axis that does NOT change that
    verdict — so this song gets loud breathing with human structure rather than
    a hand-rolled scatter the project's own performance lens would grade as
    sloppy.

    ``heat`` at the call site scales ``rush``, and scales the profile's ``k`` at
    `_clip` time: the same four players, more worked up. The coda runs hot.
    """

    def __init__(self, tag: str, *, drag: float, rush: float,
                 profile: PerformanceProfile, accents: dict | None = None) -> None:
        self.tag = tag
        self.drag = drag
        self.rush = rush
        self.profile = profile
        self.accents = accents or {}

    def when(self, bar: int, pos: float, heat: float = 1.0) -> float:
        """Within-bar position with the AUTHORED feel applied. The breathing is
        added later, over the finished part, by :func:`_perform`."""
        creep = self.rush * (pos / BEATS) * heat
        return pos + self.drag + self.accents.get(pos, 0.0) - creep


# Guitarist: furthest ahead, loosest, and rushes hardest — the downstroke arm
# is the thing dragging this band forward.
GUITARIST = Player(
    "gtr", drag=-0.010, rush=0.014,
    profile=PerformanceProfile(name="punk-downstroke", timing_sigma=0.030,
                               velocity_sigma=12.0))
# Bassist: sits behind and stays there. Tightest of the four, because an anchor
# that also wobbles is not an anchor.
BASSIST = Player(
    "bass", drag=+0.006, rush=0.004,
    profile=PerformanceProfile(name="punk-anchor", timing_sigma=0.016,
                               velocity_sigma=7.0))
# Drummer: tight in time, wide in dynamics. Backbeat still leans in. One
# breathing stream for the whole kit — the limbs of one drummer are coupled
# (`_perform` records what splitting them measured).
DRUMMER = Player(
    "dru", drag=0.0, rush=0.007,
    profile=PerformanceProfile(name="punk-kit", timing_sigma=0.018,
                               velocity_sigma=11.0),
    accents={1.0: -0.012, 3.0: -0.012})
# Singer: a shouting human. Widest breathing, leans into every phrase start.
SINGER = Player(
    "syn", drag=0.0, rush=0.011,
    profile=PerformanceProfile(name="punk-shout", timing_sigma=0.032,
                               velocity_sigma=11.0),
    accents={0.0: -0.014, 0.5: -0.014, 2.0: -0.014, 2.5: -0.014})

PLAYER_FOR_TRACK = {
    TRACK_DRUMS: DRUMMER,
    TRACK_BASS: BASSIST,
    TRACK_GUITAR: GUITARIST,
    TRACK_VOICE: SINGER,
}



# ---------------------------------------------------------------------------
# Pitch vocabulary. MIDI: 12 * (octave + 1) + pitch_class, middle C = C4 = 60.
# ---------------------------------------------------------------------------
# Guitar power-chord roots, kept in the G2..F3 band so the riff moves the way a
# hand moves on a neck. The finale deliberately breaks the band upward (G3) so
# I-IV-V rises into the tonic instead of dropping into it.
G_C, G_Db, G_D, G_Eb, G_E, G_F, G_Fs, G_G, G_Ab, G_Bb = 48, 49, 50, 51, 52, 53, 54, 43, 44, 46
G_G_HI = 55   # G3 — the motif's repeated note, and the finale's V
G_Eb_HI = 51  # E♭3 — the motif's long note in the minor world
G_E_HI = 52   # E♮3 — the same note one semitone brighter (coda)

# Synth "vocal" register — a shouted-voice band, C4..G5.
S_Eb4, S_E4, S_F4, S_G4, S_Ab4, S_A4, S_Bb4, S_B4 = 63, 64, 65, 67, 68, 69, 70, 71
S_C5, S_Db5, S_D5, S_Eb5, S_E5, S_F5, S_G5 = 72, 73, 74, 75, 76, 77, 79
S_C4, S_G3 = 60, 55


def _n(pitch: int, start: float, dur: float, vel: int) -> dict:
    """One note. Absolute starts clamp at 0 — a push should not exist before the
    song does (the mutator refuses negative absolute starts)."""
    return {
        "pitch": int(pitch),
        "start_beats": round(max(0.0, start), 6),
        "duration_beats": round(dur, 6),
        "velocity": int(max(1, min(127, vel))),
    }


def _at(bar: int, pos: float, player: Player, heat: float = 1.0) -> float:
    """Absolute beat for within-bar position ``pos`` in 0-based ``bar``."""
    return bar * BEATS + player.when(bar, pos, heat)


def _hit(out: list, pitch: int, bar: int, pos: float, dur: float, vel: int,
         player: Player, heat: float = 1.0) -> None:
    out.append(_n(pitch, _at(bar, pos, player, heat), dur, vel))


def _power(out: list, root: int, bar: int, pos: float, dur: float, vel: int,
           player: Player = GUITARIST, heat: float = 1.0) -> None:
    """A power chord — root + 5th + octave, no third. Metal omits the third;
    punk omits it because a barred third at 200 BPM is a smear.

    The three notes do NOT land together. A downstroke is a pick sweeping
    across three strings, and through this much gain the sweep IS the attack —
    simultaneous power chords are the single most synthetic thing a programmed
    punk guitar does. The sweep widens with velocity, because hitting harder
    means swinging the arm faster and catching the strings further apart.
    """
    sweep = (0.005 + 0.005 * abs(_rand(player.tag, "sweep", bar, pos))) * heat
    t = _at(bar, pos, player, heat)
    out.append(_n(root, t, dur, vel))
    out.append(_n(root + 7, t + sweep, dur, vel - 6))
    out.append(_n(root + 12, t + 2 * sweep, dur, vel - 11))


def _chug(out: list, root: int, bar: int, *, dur: float = 0.22, vel: int = 104,
          accent: int = 8, subdiv: float = 0.5, heat: float = 1.0) -> None:
    """Downstrokes on one chord — the punk rhythm-guitar engine. ``subdiv`` 0.5
    is the full 8th-note wall; 1.0 is quarters, which is how the first half of
    the verse holds something back for the chorus to spend.

    Duration scatters as well as timing: a downstroke wall is a right hand
    muting inconsistently, so some chords choke early and some hang on.
    Uniform note lengths are the other half of why a programmed punk guitar
    sounds programmed.

    The scatter is capped just under the gap to the next hit. A same-pitch note
    that outlasts its successor's onset is not a longer note — Live truncates
    the overlap, so the DB would carry a duration the renderer cannot hold, and
    the audible half of the effect would be the choked notes only.
    """
    hits = int(4.0 / subdiv)
    ceiling = subdiv * 0.92
    for i in range(hits):
        pos = i * subdiv
        v = vel + accent if i == 0 else (vel + accent // 2 if pos == 2.0 else vel)
        ring = dur * (1.0 + 0.28 * _rand("mute", bar, pos, root) * heat)
        _power(out, root, bar, pos, min(ring, ceiling), v, GUITARIST, heat)


def _bass_8ths(out: list, root: int, bar: int, *, dur: float = 0.22, vel: int = 100,
               accent: int = 8, heat: float = 1.0) -> None:
    for i in range(8):
        pos = i * 0.5
        v = vel + accent if i == 0 else vel
        _hit(out, root, bar, pos, dur, v, BASSIST, heat)


def _motif(out: list, bar: int, short_pitch: int, long_pitch: int, *,
           vel: int, player, short_dur: float = 0.34, long_dur: float = 1.9,
           power: bool = False, upbeat: bool = True, heat: float = 1.0) -> None:
    """Short-short-short-LONG. ``upbeat`` places the three shorts on the 8ths
    after beat 1 and lands the long on beat 3 — Beethoven's own rest-first
    placement, which is also how half of hardcore is written.

    The three shorts accelerate. Every band that has ever played this figure
    rushes it — the shorts crowd toward the long because the long is the note
    everyone is aiming at. That is on top of the player's own scatter, so no
    two statements of the cell land the same way.
    """
    starts = (0.5, 1.0, 1.5) if upbeat else (0.0, 0.5, 1.0)
    long_pos = 2.0 if upbeat else 1.5
    long_len = long_dur if upbeat else long_dur + 0.5
    for n, pos in enumerate(starts):
        crowd = -0.008 * n * heat          # each short leans harder than the last
        if power:
            _power(out, short_pitch, bar, pos + crowd, short_dur, vel, player, heat)
        else:
            _hit(out, short_pitch, bar, pos + crowd, short_dur, vel, player, heat)
    if power:
        _power(out, long_pitch, bar, long_pos, long_len, vel + 6, player, heat)
    else:
        _hit(out, long_pitch, bar, long_pos, long_len, vel + 6, player, heat)


def _punk_beat(out: list, bar: int, *, vel: int = 110, hat: int = HAT_CLOSED,
               hat_vel: int = 70, crash: bool = False, kick_pickup: bool = False,
               heat: float = 1.0) -> None:
    """Kick 1+3, snare 2+4, 8ths on the hat. The whole genre in four lines.

    The garage is everything AROUND those four lines. What makes a kit sound
    like a person in a room is that the hands never stop moving between the
    backbeats (ghost notes), that the hat gets leaned on instead of closed, and
    that at this tempo one occasionally just doesn't happen. Programmed drums
    are recognisable precisely because every hat is present and identical — so
    the hole a dropped hat leaves does more work here than any amount of
    jitter. All of it is deterministic: same bar, same misses, every build.
    """
    _hit(out, KICK, bar, 0.0, 0.3, vel, DRUMMER, heat)
    _hit(out, KICK, bar, 2.0, 0.3, vel - 6, DRUMMER, heat)
    if kick_pickup:
        _hit(out, KICK, bar, 2.5, 0.3, vel - 12, DRUMMER, heat)
    _hit(out, SNARE, bar, 1.0, 0.3, vel + 4, DRUMMER, heat)
    _hit(out, SNARE, bar, 3.0, 0.3, vel + 6, DRUMMER, heat)

    for i in range(8):
        pos = i * 0.5
        if _rand("hatdrop", bar, pos) > 0.88:
            continue                                  # the hat that isn't there
        opened = (hat == HAT_CLOSED and pos in (1.5, 3.5)
                  and _rand("hatopen", bar, pos) > 0.72)
        _hit(out, HAT_OPEN if opened else hat, bar, pos,
             0.3 if opened else 0.12,
             hat_vel + (6 if i % 2 == 0 else 0) + (8 if opened else 0),
             DRUMMER, heat)

    # Ghost snares — the left hand still working between the backbeats.
        # Quiet enough to read as texture rather than a second backbeat.
    for pos in (0.75, 1.75, 2.75, 3.75):
        if _rand("ghost", bar, pos) > 0.45:
            continue
        _hit(out, SNARE, bar, pos, 0.1,
             34 + round(10 * abs(_rand("ghostvel", bar, pos))), DRUMMER, heat)
    # An extra kick where the foot gets ahead of itself.
    for pos in (1.5, 3.5):
        if _rand("kick2", bar, pos) > 0.62:
            _hit(out, KICK, bar, pos, 0.22, vel - 16, DRUMMER, heat)

    if crash:
        _hit(out, CRASH_1, bar, 0.0, 1.0, vel + 8, DRUMMER, heat)


def _fill(out: list, bar: int, *, vel: int = 112, start: float = 2.0,
          heat: float = 1.8) -> None:
    """Tom fill across the back half of a bar, landing the next section.

    Runs hot by default: a fill is the single most rushed thing a punk drummer
    does, because they are already hearing the downbeat that comes after it.
    """
    ladder = [TOM_HI, TOM_HI, TOM_LO, TOM_LO, SNARE, SNARE, SNARE, SNARE]
    steps = int((4.0 - start) / 0.25)
    for i in range(steps):
        _hit(out, ladder[i % len(ladder)], bar, start + i * 0.25, 0.18,
             vel - 10 + i * 3, DRUMMER, heat)


# A drum can be struck once at a time. ~9 ms at 200 BPM — below any hearable
# flam, and below the window where Live will hold two same-pitch notes at all.
MIN_RETRIGGER_BEATS = 0.03

# The sliver a truncated note must leave before the next same-pitch onset.
_MIN_GAP_BEATS = 0.005


def _no_same_pitch_overlap(notes: list) -> list:
    """Truncate a note that would still be sounding when the same pitch retriggers.

    A Live clip cannot hold two overlapping same-pitch notes: it truncates the
    earlier one. Doing it here keeps the DB describing what the renderer will
    actually play, instead of storing a duration that is silently discarded.

    This is a guard, not a style choice, and it has to run AFTER the breathing:
    `_chug` caps its duration scatter against the *authored* onset gap, but
    `_perform` then moves adjacent onsets by up to ~0.05 beats relative to each
    other, which can reopen an overlap the cap had closed.
    """
    out = sorted(notes, key=lambda n: (n["pitch"], n["start_beats"]))
    for earlier, later in zip(out, out[1:]):
        if earlier["pitch"] != later["pitch"]:
            continue
        room = later["start_beats"] - earlier["start_beats"] - _MIN_GAP_BEATS
        if earlier["duration_beats"] > room:
            earlier["duration_beats"] = round(max(_MIN_GAP_BEATS, room), 6)
    return out


def _one_hit_at_a_time(notes: list) -> list:
    """Drop same-pitch notes that retrigger within ``MIN_RETRIGGER_BEATS``.

    Runs over EVERY part, not just the kit: two hits 9 ms apart is not a flam,
    it is a double-trigger — no drummer's stick, no guitarist's pick and no
    singer's throat can do it. The drums are only where it currently bites. It stayed invisible while the feel
    was a constant offset: ``_fill`` and ``_punk_beat`` both write a snare on
    beat 3 of the fill bar, and with one shared shift the two landed on exactly
    the same tick, where the DB deduped them without comment. Once every note
    carries its own scatter they became a genuine overlap — and a Live clip
    cannot hold two overlapping same-pitch notes, so it merged them and the
    push's arrangement integrity assert caught the divergence.

    Keeps the louder of a colliding pair, which is the right one: the fill hit
    is the gesture, the backbeat underneath it is the one being replaced.
    """
    kept: list = []
    last: dict[int, float] = {}
    for note in sorted(notes, key=lambda n: (n["pitch"], n["start_beats"],
                                             -n["velocity"])):
        pitch, start = note["pitch"], note["start_beats"]
        if pitch in last and start - last[pitch] < MIN_RETRIGGER_BEATS:
            if note["velocity"] <= kept[-1]["velocity"]:
                continue
            kept.pop()          # this one hits harder; it wins the collision
        kept.append(note)
        last[pitch] = start
    return kept


def _breathe(notes: list, player: Player, *, k: float, tag: str) -> list:
    """Realize ``player``'s declared profile over one finished part.

    Applied to the WHOLE part at once, in time order, because that is what makes
    the deviation 1/f-correlated — a per-note draw taken at emission time would
    be memoryless white noise, which the performance lens grades as *sloppy*
    rather than *human*. Magnitude is free (``k``); structure is not.

    ``_n`` clamped starts at 0 on the way in, and the breathing can push the
    first onset back below it, so the clamp is re-applied on the way out — the
    mutator refuses a negative absolute start.
    """
    if not notes:
        return notes
    profile = replace(player.profile, k=player.profile.k * k)
    out = apply_profile(notes, profile, seed=_seed(player.tag, tag))
    for note in out:
        note["start_beats"] = round(max(0.0, note["start_beats"]), 6)
        note["velocity"] = int(max(1, min(127, note["velocity"])))
    return out


def _perform(notes: list, track_name: str, *, k: float, tag: str) -> list:
    """Breathe a part — ONE stream per player.

    The kit was briefly split into two streams, hats on one and kick/snare on
    the other, to model a hand wobbling more than a foot. It measured worse: the
    performance lens read the drums at **lag-1 acf 0.135 — `sloppy`** — while the
    other three parts read `human`, because interleaving two INDEPENDENT 1/f
    series in time order produces a combined series that is uncorrelated at
    lag 1. Two streams is two performers.

    A drummer's limbs are coupled — that coupling is most of why a kit sounds
    like a person — so the whole kit breathes on one stream. Re-measured after:
    acf 0.135 -> 0.623, `human`.
    """
    return _breathe(notes, PLAYER_FOR_TRACK[track_name], k=k, tag=tag)


def _clip(conn, tracks, track_name: str, slot: int, length: float, name: str,
          role: str, notes: list, clips: dict, k: float = 1.0) -> list:
    """Write one clip. RETURNS the notes actually written — breathed, collision-
    resolved and truncated — so a caller that needs to read the part back (the
    melody lens) sees what the build wrote rather than the pre-performance
    draft it started from."""
    breathed = _perform(notes, track_name, k=k, tag=name)
    resolved = _one_hit_at_a_time(breathed)
    if len(resolved) != len(breathed):
        _COLLISIONS[name] = len(breathed) - len(resolved)
    performed = _no_same_pitch_overlap(resolved)
    cid = M.create_clip(conn, track_id=tracks[track_name], slot=slot,
                        length_beats=length, name=name, section_role=role)
    M.replace_clip_notes(conn, clip_id=cid, notes=performed)
    clips[track_name] = cid
    return performed


# ---------------------------------------------------------------------------
# The harmonic plan. Authored, never inferred — these are rulers the parts
# compose against and the melody lens reads for harmony-fit.
# ---------------------------------------------------------------------------
PROG_INTRO = Progression.of(
    "C", "Minor", [("Cm", 8.0), ("G7", 8.0), ("Cm", 8.0), ("G7", 8.0)], functional=True)
PROG_VERSE = Progression.of(
    "C", "Minor", ["Cm", "Ab", "Eb", "G"], beats_per_chord=4.0, functional=True)
PROG_CHORUS = Progression.of(
    "Eb", "Major", ["Eb", "Bb", "Cm", "Ab"], beats_per_chord=4.0, functional=True)
PROG_BREAK = Progression.of(
    "Ab", "Major",
    [("Ab", 4.0), ("Db", 4.0), ("Eb", 4.0), ("Ab", 4.0),
     ("Ab", 4.0), ("Db", 4.0), ("Eb", 4.0), ("Ab", 4.0),
     ("C", 4.0), ("C", 4.0), ("Ab", 4.0), ("G7", 4.0)], functional=True)
PROG_SCHERZO = Progression.of(
    "C", "Minor", [("Cm", 16.0), ("Ab", 8.0), ("G", 8.0)], functional=True)
# Accelerating harmonic rhythm into the cadence — the transition's whole point.
PROG_BRIDGE = Progression.of(
    "C", "Minor", [("Ab", 8.0), ("G", 8.0), ("Ab", 4.0), ("G", 4.0), ("G7", 8.0)],
    functional=True)
PROG_FINALE = Progression.of(
    "C", "Major", ["C", "F", "G", "C"], beats_per_chord=4.0, functional=True)
PROG_CODA = Progression.of("C", "Major", [("C", 4.0)], functional=True)


# ---------------------------------------------------------------------------
# intro-fate — 8 bars. The cell twice, each answered by a full-band hole, then
# the band arrives. Bars 1 and 3 (0-based) are literally empty in every part:
# that is the mvt-I fermata, rendered the one way punk already owns.
# ---------------------------------------------------------------------------
def _build_intro(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    for bar, (short_g, long_g, short_s, long_s) in [
        (0, (G_G_HI, G_Eb_HI, S_G4, S_Eb4)),
        (2, (G_F, G_D, S_F4, S_D5 - 12)),      # F-F-F-D, the cell's own answer
    ]:
        _motif(gtr, bar, short_g, long_g, vel=112, player=GUITARIST, power=True)
        _motif(bas, bar, short_g - 12, long_g - 12, vel=110, player=BASSIST)
        _motif(syn, bar, short_s, long_s, vel=104, player=SINGER)
        for pos in (0.5, 1.0, 1.5):
            _hit(dru, KICK, bar, pos, 0.25, 118, DRUMMER)
            _hit(dru, SNARE, bar, pos, 0.25, 116, DRUMMER)
        _hit(dru, CRASH_1, bar, 2.0, 2.0, 122, DRUMMER)
        _hit(dru, KICK, bar, 2.0, 0.3, 122, DRUMMER)
    # bars 1 and 3: the hole. No notes. Deliberate.

    for bar, root in [(4, G_C), (5, G_C), (6, G_G), (7, G_G)]:
        _chug(gtr, root, bar, vel=106)
        _bass_8ths(bas, root - 12, bar, vel=102)
        _punk_beat(dru, bar, vel=112, hat_vel=72, crash=(bar == 4))
    _fill(dru, 7, vel=118)

    _clip(conn, tracks, TRACK_DRUMS, 1, 32.0, "Intro Drums", "intro", dru, clips)
    _clip(conn, tracks, TRACK_BASS, 1, 32.0, "Intro Bass", "intro", bas, clips)
    _clip(conn, tracks, TRACK_GUITAR, 1, 32.0, "Intro Guitar", "intro", gtr, clips)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 1, 32.0, "Intro Voice", "intro", syn, clips)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# verse-cm — 16 bars. Cm Ab Eb G under a 4-bar vocal phrase that walks the cell
# through the progression, rising each bar to the leading tone and falling back.
# ---------------------------------------------------------------------------
VERSE_ROOTS = [G_C, G_Ab, G_Eb, G_G]
# (short, long) per bar of the phrase — the cell re-harmonized four ways.
VERSE_CELL = [(S_G4, S_Eb4), (S_Ab4, S_F4), (S_Bb4, S_G4), (S_D5, S_B4)]


def _build_verse(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    for bar in range(16):
        root = VERSE_ROOTS[bar % 4]
        # First half: the guitar plays quarters while the bass keeps the 8ths.
        # The engine never stops; the guitar ARRIVES at bar 9 — and the chorus
        # then has somewhere left to go. (Subtract before you add.)
        _chug(gtr, root, bar, vel=104 + (bar // 4) * 2,
              subdiv=1.0 if bar < 8 else 0.5,
              dur=0.34 if bar < 8 else 0.22)
        _bass_8ths(bas, root - 12, bar, vel=100 + (bar // 4) * 2)
        _punk_beat(dru, bar, vel=112, hat_vel=68 + (bar // 4) * 3,
                   crash=bar in (0, 8), kick_pickup=bar % 4 == 3)
        if bar % 4 == 3 and bar != 15:
            _hit(dru, HAT_OPEN, bar, 3.5, 0.4, 88, DRUMMER)

        short, long = VERSE_CELL[bar % 4]
        vel = [96, 102, 108, 114][bar // 4]
        if bar == 15:
            # The phrase refuses to fall back this time — it climbs into E♭.
            _motif(syn, bar, S_D5, S_Eb5, vel=118, player=SINGER)
        else:
            _motif(syn, bar, short, long, vel=vel, player=SINGER)
        if bar == 11:
            # A 16th-note pickup: the singer getting impatient with the loop.
            for i, p in enumerate((S_G4, S_Ab4, S_Bb4)):
                _hit(syn, p, bar, 3.25 + i * 0.25, 0.2, 110 + i * 4, SINGER)

    _fill(dru, 15, vel=120, start=2.0)

    _clip(conn, tracks, TRACK_DRUMS, 2, 64.0, "Verse Drums", "verse", dru, clips)
    _clip(conn, tracks, TRACK_BASS, 2, 64.0, "Verse Bass", "verse", bas, clips)
    _clip(conn, tracks, TRACK_GUITAR, 2, 64.0, "Verse Guitar", "verse", gtr, clips)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 2, 64.0, "Verse Voice", "verse", syn, clips)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# chorus-eb — 12 bars. The relative major arrives. The lift is written into the
# ARTICULATION as much as the harmony: the guitar stops palm-muting (0.22 →
# 0.45 beats a hit) and the drums leave the closed hat for an open wash.
# ---------------------------------------------------------------------------
CHORUS_ROOTS = [G_Eb, G_Bb, G_C, G_Ab]
CHORUS_CELL = [(S_Bb4, S_Eb5), (S_D5, S_Bb4), (S_Eb5, S_C5), (S_C5, S_Ab4)]


def _build_chorus(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    for bar in range(12):
        root = CHORUS_ROOTS[bar % 4]
        _chug(gtr, root, bar, dur=0.45, vel=112)
        _bass_8ths(bas, root - 12, bar, dur=0.45, vel=108)
        _punk_beat(dru, bar, vel=116, hat=HAT_OPEN, hat_vel=78,
                   crash=bar % 4 == 0)

        short, long = CHORUS_CELL[bar % 4]
        _motif(syn, bar, short, long, vel=114, player=SINGER)
        # The chorus is where the hook OPENS UP: the vocal doubles an octave
        # below, the way a room full of people shouting a chorus does. It widens
        # the register rather than just adding notes, so the chorus arrives
        # instead of merely continuing the verse. The melody lens still reads the
        # top voice, so the line's shape is unchanged — only its size is.
        _motif(syn, bar, short - 12, long - 12, vel=100, player=SINGER)
        if bar % 4 == 3:
            _hit(syn, S_Bb4, bar, 3.5, 0.3, 108, SINGER)   # pickup back round

    _fill(dru, 11, vel=122, start=2.5)

    _clip(conn, tracks, TRACK_DRUMS, 3, 48.0, "Chorus Drums", "chorus", dru, clips)
    _clip(conn, tracks, TRACK_BASS, 3, 48.0, "Chorus Bass", "chorus", bas, clips)
    _clip(conn, tracks, TRACK_GUITAR, 3, 48.0, "Chorus Guitar", "chorus", gtr, clips)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 3, 48.0, "Chorus Voice", "chorus", syn, clips)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# break-ab — 12 bars, half-time. The andante. Then bars 8-9 blaze in C MAJOR:
# Beethoven puts C-major fanfares inside the A-flat movement, so the finale
# arrives early, for two bars, and gets snuffed out. That is the song's plot.
# ---------------------------------------------------------------------------
BREAK_ROOTS = [G_Ab, G_Db, G_Eb, G_Ab, G_Ab, G_Db, G_Eb, G_Ab, G_C, G_C, G_Ab, G_G]

# The mvt-II theme, as the synth sings it. (pitch, pos, dur) per bar of a 4-bar
# phrase — longer values than anything else in the song, still staccato.
BREAK_LINE = [
    [(S_Ab4, 0.0, 0.8), (S_Bb4, 1.0, 0.4), (S_C5, 1.5, 0.4), (S_Db5, 2.0, 0.8), (S_C5, 3.0, 0.8)],
    [(S_Bb4, 0.0, 0.8), (S_Ab4, 1.0, 1.3), (S_F4, 2.5, 0.4), (S_Ab4, 3.0, 0.8)],
    [(S_Bb4, 0.0, 0.8), (S_C5, 1.0, 0.8), (S_Bb4, 2.0, 0.8), (S_G4, 3.0, 0.8)],
    [(S_Ab4, 0.0, 2.0), (S_Eb4, 3.0, 0.8)],
]


def _build_break(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    for bar in range(8):
        root = BREAK_ROOTS[bar]
        if bar == 7:
            # Everything stops halfway through bar 8 — the hole before the blaze.
            _power(gtr, root, bar, 0.0, 1.8, 96)
            _hit(bas, root - 12, bar, 0.0, 1.8, 94, BASSIST)
            _hit(dru, KICK, bar, 0.0, 0.3, 104, DRUMMER)
            _hit(dru, SNARE, bar, 1.0, 0.3, 100, DRUMMER)
            for p, pos, dur in [(S_Ab4, 0.0, 1.8)]:
                _hit(syn, p, bar, pos, dur, 92, SINGER)
            continue
        # Half-time: two ringing guitar hits a bar, snare on 3 only.
        _power(gtr, root, bar, 0.0, 2.3, 94)
        _power(gtr, root, bar, 2.5, 1.3, 88)
        _hit(bas, root - 12, bar, 0.0, 2.3, 96, BASSIST)
        _hit(bas, root - 12, bar, 2.5, 1.3, 92, BASSIST)
        _hit(dru, KICK, bar, 0.0, 0.3, 106, DRUMMER)
        _hit(dru, KICK, bar, 2.5, 0.3, 98, DRUMMER)
        _hit(dru, SNARE, bar, 2.0, 0.4, 110, DRUMMER)
        for i in range(4):
            _hit(dru, HAT_CLOSED, bar, float(i), 0.12, 62 + (5 if i % 2 == 0 else 0), DRUMMER)
        for p, pos, dur in BREAK_LINE[bar % 4]:
            _hit(syn, p, bar, pos, dur, 92 + (bar // 4) * 6, SINGER)

    # bars 8-9 — the C-major blaze. Full band, the cell, in the major.
    for bar, (s_short, s_long) in [(8, (S_G4, S_E5)), (9, (S_C5, S_G5))]:
        _motif(gtr, bar, G_G_HI, G_C, vel=118, player=GUITARIST, power=True)
        _motif(bas, bar, G_G_HI - 12, G_C - 12, vel=116, player=BASSIST)
        _motif(syn, bar, s_short, s_long, vel=120, player=SINGER)
        for pos in (0.5, 1.0, 1.5):
            _hit(dru, KICK, bar, pos, 0.25, 120, DRUMMER)
            _hit(dru, SNARE, bar, pos, 0.25, 118, DRUMMER)
        _hit(dru, CRASH_1, bar, 2.0, 2.0, 124, DRUMMER)
        _hit(dru, KICK, bar, 2.0, 0.3, 124, DRUMMER)

    # bar 10 — snuffed out, back to A-flat, quiet and dark.
    _power(gtr, G_Ab, 10, 0.0, 3.6, 82)
    _hit(bas, G_Ab - 12, 10, 0.0, 3.6, 84, BASSIST)
    _hit(syn, S_Ab4, 10, 0.0, 3.6, 78, SINGER)
    _hit(dru, KICK, 10, 0.0, 0.3, 92, DRUMMER)
    _hit(dru, HAT_CLOSED, 10, 2.0, 0.2, 60, DRUMMER)

    # bar 11 — the dominant, then a roll into the scherzo.
    _power(gtr, G_G, 11, 0.0, 1.5, 100)
    _hit(bas, G_G - 12, 11, 0.0, 1.5, 100, BASSIST)
    _hit(syn, S_B4, 11, 0.0, 1.5, 96, SINGER)
    _hit(dru, KICK, 11, 0.0, 0.3, 108, DRUMMER)
    _fill(dru, 11, vel=124, start=2.0)

    _clip(conn, tracks, TRACK_DRUMS, 4, 48.0, "Break Drums", "breakdown", dru, clips)
    _clip(conn, tracks, TRACK_BASS, 4, 48.0, "Break Bass", "breakdown", bas, clips)
    _clip(conn, tracks, TRACK_GUITAR, 4, 48.0, "Break Guitar", "breakdown", gtr, clips)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 4, 48.0, "Break Voice", "breakdown", syn, clips)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# scherzo-cm — 16 bars, the meanest thing here. The drums switch to a hardcore
# skank (kick on the quarters, snare on every off-beat) so the section reads at
# double speed without touching the tempo. Bass + synth play mvt III's rising
# cello arpeggio in unison; the guitar chugs underneath, then all three hammer
# the horn theme — which is the fate cell again, on repeated notes.
# ---------------------------------------------------------------------------
ARPEGGIO_BASS = [36, 43, 48, 51, 55, 51, 48, 43]          # C2 G2 C3 E♭3 G3 E♭3 C3 G2
ARPEGGIO_SYN = [S_C4, S_G4, S_C5, S_Eb5, S_G5, S_Eb5, S_C5, S_G4]


def _build_scherzo(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    for bar in range(16):
        half = bar // 8              # 0 = first pass, 1 = second (louder)
        local = bar % 8
        boost = half * 5

        # --- the skank
        for i in range(4):
            _hit(dru, KICK, bar, float(i), 0.25, 116 + boost, DRUMMER)
            _hit(dru, HAT_CLOSED, bar, float(i), 0.12, 74, DRUMMER)
            _hit(dru, SNARE, bar, i + 0.5, 0.22, 112 + boost, DRUMMER)
        if local == 0:
            _hit(dru, CRASH_1, bar, 0.0, 1.5, 124, DRUMMER)

        if local < 4:
            # --- the rising arpeggio (bass + synth in unison, two octaves apart)
            root = G_C
            _chug(gtr, root, bar, dur=0.18, vel=106 + boost)
            for i in range(8):
                _hit(bas, ARPEGGIO_BASS[i], bar, i * 0.5, 0.22, 104 + boost, BASSIST)
                _hit(syn, ARPEGGIO_SYN[i], bar, i * 0.5, 0.2, 100 + boost, SINGER)
        else:
            # --- the horn theme: the cell, hammered, on repeated notes
            if local in (4, 5):
                g_root, b_root = G_Ab, G_Ab - 12
                s_short = S_C5
                s_long = S_Ab4 if local == 4 else S_Eb5
            else:
                g_root, b_root = G_G, G_G - 12
                s_short = S_D5
                s_long = S_B4 if local == 6 else S_G5
            _motif(gtr, bar, g_root, g_root, vel=114 + boost, player=GUITARIST,
                   power=True, upbeat=False)
            _motif(bas, bar, b_root, b_root, vel=112 + boost, player=BASSIST,
                   upbeat=False)
            _motif(syn, bar, s_short, s_long, vel=112 + boost, player=SINGER,
                   upbeat=False)

    _fill(dru, 15, vel=126, start=2.0)

    _clip(conn, tracks, TRACK_DRUMS, 5, 64.0, "Scherzo Drums", "verse", dru, clips)
    _clip(conn, tracks, TRACK_BASS, 5, 64.0, "Scherzo Bass", "verse", bas, clips)
    _clip(conn, tracks, TRACK_GUITAR, 5, 64.0, "Scherzo Guitar", "verse", gtr, clips)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 5, 64.0, "Scherzo Voice", "verse", syn, clips)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# bridge-pedal — 8 bars. The great transition. The bass pedals low C for the
# whole section while the harmony above it slides A♭ → G → G7 with an
# accelerating harmonic rhythm; drums and bass subdivide quarters → 8ths →
# 16ths; the synth climbs a sixth. Bar 8 beat 4 is a total hole, and then the
# key changes.
# ---------------------------------------------------------------------------
BRIDGE_TOP = [G_Ab, G_Ab, G_G, G_G, G_Ab, G_G, G_G, G_G]
BRIDGE_CLIMB = [S_Ab4, S_C5, S_D5, S_Eb5, S_F5, S_F5, S_G5, S_G5]
BRIDGE_SUBDIV = [1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.25, 0.25]
PEDAL_C = 36


def _build_bridge(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    for bar in range(8):
        vel = 76 + bar * 7                       # the crescendo, written as velocity
        step = BRIDGE_SUBDIV[bar]
        last = bar == 7

        # --- bass: the pedal. One note, C, for eight bars, subdividing.
        n = int((3.0 if last else 4.0) / step)
        for i in range(n):
            _hit(bas, PEDAL_C, bar, i * step, min(step * 0.8, 0.3), vel + 6, BASSIST)

        # --- guitar: the harmony sliding above the pedal
        if bar < 4:
            _power(gtr, BRIDGE_TOP[bar], bar, 0.0, 3.6, vel)
        elif bar < 6:
            _power(gtr, BRIDGE_TOP[bar], bar, 0.0, 1.8, vel)
            _power(gtr, BRIDGE_TOP[bar], bar, 2.0, 1.8, vel + 3)
        else:
            hits = 8 if bar == 6 else 6
            for i in range(hits):
                _power(gtr, BRIDGE_TOP[bar], bar, i * 0.5, 0.4, vel + i * 2)

        # --- drums: floor tom, then snare, then a 16th roll
        if bar < 2:
            for i in range(4):
                _hit(dru, TOM_LO, bar, float(i), 0.3, vel, DRUMMER)
                _hit(dru, KICK, bar, float(i), 0.3, vel + 4, DRUMMER)
        elif bar < 4:
            for i in range(8):
                _hit(dru, TOM_LO, bar, i * 0.5, 0.2, vel - 4 + i, DRUMMER)
                _hit(dru, KICK, bar, i * 0.5, 0.2, vel, DRUMMER)
        elif bar < 6:
            for i in range(8):
                _hit(dru, SNARE, bar, i * 0.5, 0.2, vel - 6 + i * 2, DRUMMER)
                _hit(dru, KICK, bar, i * 0.5, 0.2, vel, DRUMMER)
        else:
            steps = 16 if bar == 6 else 12
            for i in range(steps):
                _hit(dru, SNARE, bar, i * 0.25, 0.12, min(127, vel - 8 + i * 3), DRUMMER)
                if i % 2 == 0:
                    _hit(dru, KICK, bar, i * 0.25, 0.2, vel, DRUMMER)
            if bar == 6:
                _hit(dru, CRASH_1, bar, 0.0, 1.0, vel, DRUMMER)

        # --- synth: the climb
        if last:
            for i in range(6):
                _hit(syn, BRIDGE_CLIMB[bar], bar, i * 0.5, 0.22, 116 + i * 2, SINGER)
        else:
            _hit(syn, BRIDGE_CLIMB[bar], bar, 0.0, 3.6, vel + 4, SINGER)

    # bar 8 beat 4 is empty in every part. Nothing is written there on purpose.

    _clip(conn, tracks, TRACK_DRUMS, 6, 32.0, "Bridge Drums", "bridge", dru, clips)
    _clip(conn, tracks, TRACK_BASS, 6, 32.0, "Bridge Bass", "bridge", bas, clips)
    _clip(conn, tracks, TRACK_GUITAR, 6, 32.0, "Bridge Guitar", "bridge", gtr, clips)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 6, 32.0, "Bridge Voice", "bridge", syn, clips)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# finale-cmaj — 16 bars in C MAJOR. I-IV-V-I, the most triumphant and most
# punk-playable progression in the repertoire. The guitar stops muting entirely
# (0.5-beat hits — open chords), the hats open, and the vocal opens with the
# mvt-IV fanfare before settling into the cell, now in the major.
# ---------------------------------------------------------------------------
FINALE_ROOTS = [G_C, G_F, G_G_HI, G_C]
FINALE_CELL = [None, (S_A4, S_F5), (S_B4, S_D5), (S_C5, S_E5)]


def _build_finale(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    # The destination, and the band knows it — this is the loosest the song
    # gets until the coda comes apart entirely.
    heat = 1.3

    for bar in range(16):
        root = FINALE_ROOTS[bar % 4]
        _chug(gtr, root, bar, dur=0.5, vel=116, heat=heat)
        _bass_8ths(bas, root - 12, bar, dur=0.4, vel=112, heat=heat)
        _punk_beat(dru, bar, vel=118, hat=HAT_OPEN, hat_vel=80,
                   crash=bar % 4 == 0, kick_pickup=True, heat=heat)

        cell = FINALE_CELL[bar % 4]
        if cell is None:
            # The mvt-IV fanfare: a C major arpeggio, straight up.
            for i, p in enumerate((S_G4, S_C5, S_E5)):
                _hit(syn, p, bar, i * 0.5, 0.34, 116 + i * 2, SINGER, heat)
                _hit(syn, p - 12, bar, i * 0.5, 0.34, 104 + i * 2, SINGER, heat)
            _hit(syn, S_G5, bar, 1.5, 2.4, 122, SINGER, heat)
            _hit(syn, S_G5 - 12, bar, 1.5, 2.4, 108, SINGER, heat)
        else:
            # The gang vocal, introduced at the chorus, returns here in the
            # major — the device comes back where the song actually arrives.
            short, long = (S_C5, S_G5) if bar == 15 else cell
            vel = 122 if bar == 15 else 118
            _motif(syn, bar, short, long, vel=vel, player=SINGER,
                   upbeat=False, heat=heat)
            _motif(syn, bar, short - 12, long - 12, vel=vel - 14, player=SINGER,
                   upbeat=False, heat=heat)

    _fill(dru, 15, vel=127, start=3.0)

    _clip(conn, tracks, TRACK_DRUMS, 7, 64.0, "Finale Drums", "chorus", dru, clips, k=heat)
    _clip(conn, tracks, TRACK_BASS, 7, 64.0, "Finale Bass", "chorus", bas, clips, k=heat)
    _clip(conn, tracks, TRACK_GUITAR, 7, 64.0, "Finale Guitar", "chorus", gtr, clips, k=heat)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 7, 64.0, "Finale Voice", "chorus", syn, clips, k=heat)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# coda — 8 bars of hammered C major, exactly as absurd as Beethoven's own. The
# last bar is the thesis, not an outro: the identical rhythm and the identical
# repeated G that opened the song, resolving to E NATURAL instead of E flat.
# Short and abrupt on purpose. Do not fade this.
# ---------------------------------------------------------------------------
CODA_LONG = [S_E5, S_C5, S_G5, S_E5]


def _build_coda(conn, tracks) -> tuple[dict, list]:
    clips: dict[str, str] = {}
    gtr: list = []
    bas: list = []
    syn: list = []
    dru: list = []

    # The coda is where the band stops holding it together — the hottest the
    # song runs. Bar 7 deliberately does NOT get this; see below.
    HOT = 1.5

    def _stab_bar(bar: int, s_short: int, s_long: int, vel: int) -> None:
        _motif(gtr, bar, G_G_HI, G_C, vel=vel, player=GUITARIST, power=True,
               heat=HOT)
        _motif(bas, bar, G_G_HI - 12, G_C - 12, vel=vel - 2, player=BASSIST,
               heat=HOT)
        _motif(syn, bar, s_short, s_long, vel=vel, player=SINGER, heat=HOT)
        for pos in (0.5, 1.0, 1.5):
            _hit(dru, KICK, bar, pos, 0.25, vel + 4, DRUMMER, HOT)
            _hit(dru, SNARE, bar, pos, 0.25, vel + 2, DRUMMER, HOT)
        _hit(dru, CRASH_1, bar, 2.0, 2.0, min(127, vel + 8), DRUMMER, HOT)
        _hit(dru, KICK, bar, 2.0, 0.3, min(127, vel + 8), DRUMMER, HOT)

    for bar in range(4):
        short = S_C5 if bar == 2 else S_G4
        _stab_bar(bar, short, CODA_LONG[bar], 118 + bar * 2)

    # bars 4-6: straight 8th hammering on the tonic, cut dead in bar 7.
    for bar in (4, 5, 6):
        limit = 6 if bar == 6 else 8
        for i in range(limit):
            pos = i * 0.5
            _power(gtr, G_C, bar, pos, 0.22, 122, GUITARIST, HOT)
            _hit(bas, G_C - 12, bar, pos, 0.22, 118, BASSIST, HOT)
            _hit(syn, (S_C5, S_E5, S_G5)[i % 3], bar, pos, 0.2, 118, SINGER, HOT)
            _hit(dru, KICK, bar, pos, 0.22, 120, DRUMMER, HOT)
            if i % 4 in (2,):
                _hit(dru, SNARE, bar, pos, 0.25, 122, DRUMMER, HOT)
        _hit(dru, SNARE, bar, 1.0, 0.25, 122, DRUMMER, HOT)
        _hit(dru, SNARE, bar, 3.0, 0.25, 122, DRUMMER, HOT)
        if bar == 4:
            _hit(dru, CRASH_1, bar, 0.0, 1.5, 126, DRUMMER, HOT)
    # bar 6 beats 3-4: silence. The band drops out before the last word.

    # bar 7 — the thesis. G-G-G-E natural. Left at heat 1.0 while everything
    # around it runs at 1.5: the band has been coming apart for seven bars and
    # locks together for the last gesture. Scattering this one would soften the
    # payoff the whole song is built to deliver (decisions/03), and a band
    # aiming at a final stab hits it together — the tightening IS the ending.
    _motif(gtr, 7, G_G_HI, G_C, vel=127, player=GUITARIST, power=True, long_dur=2.0)
    _motif(bas, 7, G_G_HI - 12, G_C - 12, vel=125, player=BASSIST, long_dur=2.0)
    _motif(syn, 7, S_G4, S_E5, vel=127, player=SINGER, long_dur=2.0)
    for pos in (0.5, 1.0, 1.5):
        _hit(dru, KICK, 7, pos, 0.25, 127, DRUMMER)
        _hit(dru, SNARE, 7, pos, 0.25, 127, DRUMMER)
    _hit(dru, CRASH_1, 7, 2.0, 2.0, 127, DRUMMER)
    _hit(dru, KICK, 7, 2.0, 0.3, 127, DRUMMER)

    _clip(conn, tracks, TRACK_DRUMS, 8, 32.0, "Coda Drums", "outro", dru, clips, k=HOT)
    _clip(conn, tracks, TRACK_BASS, 8, 32.0, "Coda Bass", "outro", bas, clips, k=HOT)
    _clip(conn, tracks, TRACK_GUITAR, 8, 32.0, "Coda Guitar", "outro", gtr, clips, k=HOT)
    syn_performed = _clip(conn, tracks, TRACK_VOICE, 8, 32.0, "Coda Voice", "outro", syn, clips, k=HOT)
    return clips, syn_performed


# ---------------------------------------------------------------------------
# The vocal line AS WRITTEN — the performed notes `_clip` returned, not the
# pre-breathing draft, so `melody_report` reads exactly what the build put in
# the DB rather than re-deriving or approximating it.
# ---------------------------------------------------------------------------
_VOICE_LINES: dict[str, list] = {}

# What `_one_hit_at_a_time` removed this build, per clip. A guard that silently
# deletes notes is indistinguishable from a part that was never written; `report`
# prints the total so a jump is visible rather than inferred.
_COLLISIONS: dict[str, int] = {}

SECTION_SPECS = [
    ("intro-fate", INTRO_FATE_BAR, VERSE_CM_BAR, 32.0, PROG_INTRO),
    ("verse-cm", VERSE_CM_BAR, CHORUS_EB_BAR, 64.0, PROG_VERSE),
    ("chorus-eb", CHORUS_EB_BAR, BREAK_AB_BAR, 48.0, PROG_CHORUS),
    ("break-ab", BREAK_AB_BAR, SCHERZO_CM_BAR, 48.0, PROG_BREAK),
    ("scherzo-cm", SCHERZO_CM_BAR, BRIDGE_PEDAL_BAR, 64.0, PROG_SCHERZO),
    ("bridge-pedal", BRIDGE_PEDAL_BAR, FINALE_CMAJ_BAR, 32.0, PROG_BRIDGE),
    ("finale-cmaj", FINALE_CMAJ_BAR, CODA_BAR, 64.0, PROG_FINALE),
    ("coda", CODA_BAR, END_BAR, 32.0, PROG_CODA),
]

BUILDERS = {
    "intro-fate": _build_intro,
    "verse-cm": _build_verse,
    "chorus-eb": _build_chorus,
    "break-ab": _build_break,
    "scherzo-cm": _build_scherzo,
    "bridge-pedal": _build_bridge,
    "finale-cmaj": _build_finale,
    "coda": _build_coda,
}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(reset: bool = False, force_replay: bool = False) -> str:
    """Build the song. Returns the song_id (UUID hex)."""
    def compose(conn):
        # Mix-half: replay the captured (or synthetic) Ableton session.
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        song_id = replay_capture(
            conn, snapshot,
            song_name="punk-fate",
            song_title="Punk Fate",
            song_key='Cm',
            actor="sync", reason="initial capture replay",
            allow_stale_snapshot=force_replay,
        )

        # Score-half: tempo, meter, sections, cue points.
        M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=200.0)
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
        )

        for name, start, end, _len, _prog in SECTION_SPECS:
            M.create_section(conn, song_id=song_id, name=name,
                             start_bar=float(start), end_bar=float(end))
            M.add_cue_point(conn, song_id=song_id,
                            position_bar=float(start), name=name)

        tracks = Q.tracks_by_name(conn, song_id)

        # === Compose-half ===
        _VOICE_LINES.clear()
        _COLLISIONS.clear()
        for name, start, end, _len, _prog in SECTION_SPECS:
            clips, voice = BUILDERS[name](conn, tracks)
            _VOICE_LINES[name] = voice
            arrange_section(conn, song_id, tracks, clips,
                            start_bar=float(start), end_bar=float(end))

        return song_id

    return run_build(DB_PATH, "punk-fate", compose, reset=reset)


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
        bars = END_BAR - 1
        print(f"length: {bars} bars @ 200 BPM = {bars * 4 * 60 / 200:.1f} s")
        if _COLLISIONS:
            total = sum(_COLLISIONS.values())
            detail = ", ".join(f"{k} x{v}" for k, v in sorted(_COLLISIONS.items()))
            print(f"double-triggers collapsed: {total} ({detail})")
    finally:
        conn.close()


# The "vocal" is a synth SINGING — graded as a hook, not a solo.
#
# The contour is `free` and the step appetite is `low` BY DESIGN, not by drift:
# this line is the fate cell, and the fate cell is a repeated note followed by a
# drop of a third. It leaps because Beethoven's motif leaps. Its shape per
# section is whatever the cell's re-harmonization makes it (descending in the
# intro, level where it loops, ascending where the song climbs out of C minor),
# so declaring a single arch would be declaring a line this song doesn't have.
# The first pass declared arch/moderate and the lens correctly asked about it
# eight times — the DECLARATION was wrong, not the notes.
VOICE_PROFILE = MelodicProfile(
    name="shouted-hook",
    contour_intent="free",
    step_appetite="low",
    harmonic_freedom="low",
    repetition_appetite="high",
)


def melody_report() -> MelodyReport:
    """Read the vocal-synth line section by section, against each section's own
    declared progression (`/compose-review`, `hallucinote.tools.melody_lens`)."""
    if not _VOICE_LINES:
        build()
    sections = [
        SectionMelody(
            name=name,
            length_beats=length,
            layers={"Voice": _VOICE_LINES.get(name, [])},
            progression=prog,
            melody_layers=("Voice",),
        )
        for name, _start, _end, length, prog in SECTION_SPECS
    ]
    return analyze_melody(sections, song_slug="punk-fate",
                          profiles={"Voice": VOICE_PROFILE})


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    force_replay = "--force-replay" in sys.argv
    song_id = build(reset=reset, force_replay=force_replay)
    report(song_id)
