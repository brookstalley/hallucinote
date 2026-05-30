"""hallucinote.theory.model — the harmonic substrate (rulers, not stamps).

Carries harmonic BOOKKEEPING — chord identity, the pitch-class arithmetic of a
voicing, a progression's change-timeline (its *harmonic rhythm*), and the
key/mode center a section sits in — so the composer spends attention on the
*music* (which chords, what they mean, how they resolve) and not on semitone
math. See `.prawduct/artifacts/arrangement-model.md` for the design foundation
(harmony is a first-class structural axis co-equal to energy).

This layer is **genre-general**: it serves functional harmony (classical/jazz:
cadences, secondary dominants, modulation, key-areas — `Progression.functional
= True`), modal harmony (reggae/metal/rock/folk: a static center, color from the
mode — the default), and legitimately-static music (minimalism, much rap: one
declared chord, no movement). The vocabulary is deliberately rich (power chords,
extensions, borrowed/Neapolitan chords, slash bass, the polymodal "both-at-once"
split) so a composer can reach for sophistication by default — but **nothing here
makes a musical decision**. A helper that *picked* chords for you would be a
stamp; these only carry what you authored and hand back the arithmetic. The
composer authors every chord; the generators voice them; a read-side lens
(`theory.lint`) verifies the notes match what was declared.

Primitives:

  ``Mode``         a named interval-set (Dorian, Phrygian, Major, ...) — the
                   pitch-class palette a section's harmony draws from
  ``Chord``        a root + quality, optional slash ``bass``, optional polymodal
                   ``split`` extras, optional Roman/function ``label``
  ``Change``       one chord placed on the harmonic-rhythm timeline (start, dur)
  ``Progression``  a timeline of changes over a key/mode center — the authored
                   harmonic structure a section's parts compose against

MIDI convention throughout: pitch number ``= 12 * (octave + 1) + pitch_class``
(so middle C = C4 = 60, E3 = 52, E2 = 40) — matching
``generators.primitives.chord_tones``, which ``Chord.voicing`` delegates to.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from hallucinote.generators.primitives import chord_tones

# ---------------------------------------------------------------------------
# Pitch-class names <-> integers (0..11). C = 0.
# ---------------------------------------------------------------------------

_NOTE_PCS: dict[str, int] = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "FB": 4,
    "E#": 5, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11, "CB": 11, "B#": 0,
}

# Canonical spelling per pitch class (sharps), for reporting only.
_PC_NAMES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)


def pitch_class(name: str) -> int:
    """Parse a note name (``"C"``, ``"F#"``, ``"Bb"``, ``"Eb"``) to 0..11.

    Case-insensitive. Raises ``ValueError`` on an unknown name — fail loud, the
    same discipline the rest of the substrate uses, so a typo'd key never
    silently parses to the wrong center.
    """
    key = name.strip().upper()
    if key not in _NOTE_PCS:
        raise ValueError(
            f"unknown note name {name!r}; expected one of C D E F G A B "
            f"with optional # or b (e.g. 'F#', 'Bb')"
        )
    return _NOTE_PCS[key]


def pc_name(pc: int) -> str:
    """Canonical (sharp) spelling of a pitch class, for reporting."""
    return _PC_NAMES[pc % 12]


# ---------------------------------------------------------------------------
# Modes — the genre-general interval palettes.
#
# These are canonical music theory (semitones from the modal tonic). The names
# and intervals for the modes Live also knows are kept in lock-step with Live's
# scale dictionary (`reference/scales.json`) by a parity test
# (`tests/unit/theory/test_scales_parity.py`) — the theory layer owns the
# definition (it needs modes Live may not expose), and the test prevents drift
# rather than a fragile cross-package import at module load. `Ionian`/`Aeolian`
# are provided as aliases of `Major`/`Minor` (Live names them the latter).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mode:
    """A named interval-set: the pitch-class palette rooted at a tonic.

    A ruler — it answers "which pitch classes belong to E Dorian" so the lint
    lens can check conformance. It makes no decision about *which* mode a piece
    is in; the composer declares that on the ``Progression``.
    """

    name: str
    intervals: tuple[int, ...]  # semitones from the modal tonic

    def pitch_classes(self, tonic_pc: int) -> frozenset[int]:
        """The mode's pitch-class set rooted at ``tonic_pc`` (0..11)."""
        return frozenset((tonic_pc + i) % 12 for i in self.intervals)


_MODE_DEFS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("Major", (0, 2, 4, 5, 7, 9, 11)),
    ("Minor", (0, 2, 3, 5, 7, 8, 10)),
    ("Ionian", (0, 2, 4, 5, 7, 9, 11)),       # = Major
    ("Dorian", (0, 2, 3, 5, 7, 9, 10)),
    ("Phrygian", (0, 1, 3, 5, 7, 8, 10)),
    ("Lydian", (0, 2, 4, 6, 7, 9, 11)),
    ("Mixolydian", (0, 2, 4, 5, 7, 9, 10)),
    ("Aeolian", (0, 2, 3, 5, 7, 8, 10)),       # = Minor
    ("Locrian", (0, 1, 3, 5, 6, 8, 10)),
    ("Harmonic Minor", (0, 2, 3, 5, 7, 8, 11)),
    ("Melodic Minor", (0, 2, 3, 5, 7, 9, 11)),
    ("Phrygian Dominant", (0, 1, 4, 5, 7, 8, 10)),  # 5th mode of harmonic minor
    ("Major Pentatonic", (0, 2, 4, 7, 9)),
    ("Minor Pentatonic", (0, 3, 5, 7, 10)),
    ("Blues", (0, 3, 5, 6, 7, 10)),
    ("Whole Tone", (0, 2, 4, 6, 8, 10)),
    ("Half-Whole Dim", (0, 1, 3, 4, 6, 7, 9, 10)),
    ("Whole-Half Dim", (0, 2, 3, 5, 6, 8, 9, 11)),
    ("Chromatic", tuple(range(12))),
)

MODES: dict[str, Mode] = {name: Mode(name, ivals) for name, ivals in _MODE_DEFS}


def mode(name: str) -> Mode:
    """Look up a ``Mode`` by name (case-insensitive). Raises with the known set."""
    for key, m in MODES.items():
        if key.lower() == name.strip().lower():
            return m
    raise ValueError(
        f"unknown mode {name!r}; known: {sorted(MODES)}"
    )


# ---------------------------------------------------------------------------
# Chord qualities — named interval-sets (semitones from the chord root).
# Discovered on demand, never speculative; add a quality when a song needs it.
# `"5"` (power chord) is first-class and deliberately third-less, so the lint
# lens never flags a metal power chord for a "missing third".
# ---------------------------------------------------------------------------

QUALITIES: dict[str, tuple[int, ...]] = {
    "": (0, 4, 7),            # major triad (bare symbol, e.g. "F")
    "maj": (0, 4, 7),
    "m": (0, 3, 7),           # minor triad
    "min": (0, 3, 7),
    "5": (0, 7),              # POWER CHORD — root + 5th, no 3rd
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "7": (0, 4, 7, 10),       # dominant 7th
    "maj7": (0, 4, 7, 11),
    "m7": (0, 3, 7, 10),
    "m9": (0, 3, 7, 10, 14),
    "maj9": (0, 4, 7, 11, 14),
    "9": (0, 4, 7, 10, 14),
    "add9": (0, 4, 7, 14),
    "madd9": (0, 3, 7, 14),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "dim": (0, 3, 6),
    "dim7": (0, 3, 6, 9),
    "m7b5": (0, 3, 6, 10),    # half-diminished
    "aug": (0, 4, 8),
}

# A chord symbol: root note, then quality token, then optional /bass.
#   "Em7"  -> root E, quality m7
#   "F"    -> root F, quality "" (major)
#   "E5"   -> root E, quality 5 (power chord)
#   "Em/C#" -> root E, quality m, slash bass C#
_SYMBOL_RE = re.compile(
    r"^\s*(?P<root>[A-Ga-g][#b]?)(?P<quality>[^/\s]*)(?:/(?P<bass>[A-Ga-g][#b]?))?\s*$"
)


@dataclass(frozen=True)
class Chord:
    """A chord as harmonic identity — a ruler, never a voicing decision.

    ``root_pc`` + ``intervals`` (semitones from root) are the chord. ``bass_pc``
    is a slash bass (``Em/C#``); critically, ``Em/C#`` vs ``Em/C`` differ by ONE
    semitone in the bass and that single move is how a song can pivot between E
    Dorian (C#, the bright 6th) and E Phrygian (C, the dark ♭6) over an
    unchanging Em — the bass "votes" for the mode. ``split`` carries extra
    pitch-classes for the polymodal "both-at-once" sonority (a chord deliberately
    containing both F# *and* F — the fusion-climax sound). ``label`` is a
    FREE-FORM harmonic-function annotation the composer attaches — any analysis
    they want: plain Roman (``"i"``, ``"V"``), applied/secondary (``"V7/V"``),
    chromatic (``"bII"``/``"N6"``, ``"Ger+6"``, ``"III+"``), figured-bass
    shorthand, a passing-chord note. The model deliberately CARRIES the analysis
    rather than enumerating techniques: there is no ``neapolitan()`` or
    ``tritone_sub()`` helper (those would be stamps, and the composer already
    knows them) — the full harmonic vocabulary is what these few primitives
    (arbitrary quality, slash bass, split, label, harmonic rhythm, mode/key)
    COMPOSE INTO, never a catalog. The label is documentation the lens echoes,
    never something a helper infers.

    ``.tones()`` and ``.voicing()`` return pitch *classes* / a default octave
    layout respectively — voicing stays the composer's job. ``.voicing`` is a
    dumb close-position fallback the composer is expected to override; it must
    never grow into a voice-leading engine (that is the ruler/stamp boundary).
    """

    root_pc: int
    intervals: tuple[int, ...]
    bass_pc: int | None = None
    split: tuple[int, ...] = ()      # extra absolute pitch-classes (polymodal)
    label: str | None = None         # Roman/function annotation (documentation)
    symbol: str | None = None        # the parsed source symbol, for reporting

    def __post_init__(self) -> None:
        if not (0 <= self.root_pc <= 11):
            raise ValueError(f"root_pc must be 0..11, got {self.root_pc}")
        if not self.intervals:
            raise ValueError("a chord needs at least one interval (got none)")
        if self.bass_pc is not None and not (0 <= self.bass_pc <= 11):
            raise ValueError(f"bass_pc must be 0..11 or None, got {self.bass_pc}")
        for pc in self.split:
            if not (0 <= pc <= 11):
                raise ValueError(f"split pitch classes must be 0..11, got {pc}")

    # -- constructors ------------------------------------------------------

    @classmethod
    def parse(cls, symbol: str, *, label: str | None = None) -> "Chord":
        """Parse a chord symbol (``"Em7"``, ``"F"``, ``"E5"``, ``"Em/C#"``).

        Pure symbol arithmetic — no key context, no guessing. Raises loudly on an
        unknown quality token (listing the known ones) so a typo fails at author
        time, not as a wrong note three layers down.
        """
        m = _SYMBOL_RE.match(symbol)
        if m is None:
            raise ValueError(
                f"cannot parse chord symbol {symbol!r}; expected "
                f"<root><quality>[/<bass>], e.g. 'Em7', 'F', 'E5', 'Em/C#'"
            )
        root_pc = pitch_class(m.group("root"))
        quality = m.group("quality") or ""
        if quality not in QUALITIES:
            raise ValueError(
                f"unknown chord quality {quality!r} in {symbol!r}; known: "
                f"{sorted(q for q in QUALITIES if q)}  (bare symbol = major)"
            )
        bass = m.group("bass")
        bass_pc = pitch_class(bass) if bass else None
        return cls(
            root_pc=root_pc,
            intervals=QUALITIES[quality],
            bass_pc=bass_pc,
            label=label,
            symbol=symbol.strip(),
        )

    @classmethod
    def of(
        cls,
        root_pc: int,
        quality: str | Sequence[int],
        *,
        bass_pc: int | None = None,
        split: Sequence[int] = (),
        label: str | None = None,
    ) -> "Chord":
        """Explicit constructor — root pitch-class + a named-or-raw quality."""
        if isinstance(quality, str):
            if quality not in QUALITIES:
                raise ValueError(
                    f"unknown chord quality {quality!r}; known: "
                    f"{sorted(q for q in QUALITIES if q)}"
                )
            intervals = QUALITIES[quality]
        else:
            intervals = tuple(quality)
        return cls(
            root_pc=root_pc % 12,
            intervals=intervals,
            bass_pc=None if bass_pc is None else bass_pc % 12,
            split=tuple(pc % 12 for pc in split),
            label=label,
        )

    @classmethod
    def split_chord(cls, a: "Chord", b: "Chord", *, label: str | None = None) -> "Chord":
        """The polymodal "both-at-once" sonority: ONE chord containing both
        ``a`` and ``b``'s pitch classes (e.g. an Em carrying both F# *and* F).

        ``a`` is primary (its root/quality/bass anchor the chord); ``b``'s pitch
        classes that ``a`` doesn't already have become ``split`` extras. The lens
        then accepts notes from EITHER world as in-chord — without this, the
        fusion sonority would read as half its notes "out of chord". The composer
        builds this deliberately for the climax; it is never auto-generated.
        """
        extra = sorted(b.pitch_classes() - a.pitch_classes())
        sym = None
        if a.symbol and b.symbol:
            sym = f"{a.symbol}+{b.symbol}"
        return cls(
            root_pc=a.root_pc,
            intervals=a.intervals,
            bass_pc=a.bass_pc,
            split=tuple(extra),
            label=label,
            symbol=sym,
        )

    # -- ruler helpers (pitch CLASSES — register-blind) --------------------

    def tones(self) -> tuple[int, ...]:
        """The chord-tone pitch classes from the root (no octave), in order."""
        seen: list[int] = []
        for i in self.intervals:
            pc = (self.root_pc + i) % 12
            if pc not in seen:
                seen.append(pc)
        return tuple(seen)

    def pitch_classes(self) -> frozenset[int]:
        """Every sounding pitch class — chord tones + slash bass + split extras.

        This is the lint lens's truth set: a note conforms to the chord iff its
        pitch class is in here.
        """
        pcs = set(self.tones())
        if self.bass_pc is not None:
            pcs.add(self.bass_pc)
        pcs.update(self.split)
        return frozenset(pcs)

    # -- the one register-aware convenience (the ruler/stamp boundary) -----

    def voicing(self, register: int = 4) -> list[int]:
        """A DEFAULT close-position MIDI voicing in octave ``register`` (root at
        ``12*(register+1)+root_pc``, chord tones + split extras stacked above).

        A dumb fallback so generators have pitches to place; the composer can
        always pass their own note list instead. Deliberately NOT a voice-leading
        engine — it never spreads, drops, omits, or voice-leads between changes.
        ``bass_pc`` is intentionally NOT folded in here: the slash bass is the
        bass part's job (it reads ``chord.bass_pc`` directly), so a chordal part
        voicing ``Em/C#`` plays Em up top while the bass plays the C#.
        """
        base = 12 * (register + 1) + self.root_pc
        offsets = sorted({i % 12 for i in self.intervals}
                         | {(pc - self.root_pc) % 12 for pc in self.split})
        return chord_tones(base, offsets)


# ---------------------------------------------------------------------------
# Progression — the authored harmonic-rhythm timeline.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One chord placed on the harmonic-rhythm timeline (0-based beats)."""

    chord: Chord
    start_beat: float
    duration_beats: float

    def __post_init__(self) -> None:
        if self.duration_beats <= 0:
            raise ValueError(
                f"change duration must be > 0, got {self.duration_beats}"
            )
        if self.start_beat < 0:
            raise ValueError(f"change start_beat must be >= 0, got {self.start_beat}")


# A spec item is either a bare symbol ("Em7") or a (symbol, duration) pair.
SpecItem = "str | tuple[str, float]"


@dataclass(frozen=True)
class Progression:
    """A timeline of chord changes over a ``key_pc + mode`` center.

    The authored harmonic STRUCTURE a section's parts compose against. The
    ``changes`` carry the **harmonic rhythm** (when chords change) — itself an
    expressive parameter (slow = stasis, accelerating into a cadence =
    intensification), independent of and co-equal with energy. ``functional``
    is the mode toggle: ``True`` declares a tension/resolution idiom (V–I,
    secondary dominants, cadences); ``False`` (default) declares modal harmony
    (a static center, color from the mode, no dominant engine) — the reggae/
    metal/rock/folk case. The toggle is metadata the review lens reads; it never
    changes how notes are voiced.

    ``chord_at`` is **cyclic** (modulo the cycle length), so a short authored
    cycle loops cleanly across however many bars a section spans — generators
    call ``chord_at(local_beat)`` per hit and tiling falls out, tiling-safe by
    construction (a per-beat lookup, like the per-note variation ops).
    """

    key_pc: int
    mode: Mode
    changes: tuple[Change, ...]
    functional: bool = False

    def __post_init__(self) -> None:
        if not self.changes:
            raise ValueError("a progression needs at least one change")
        if not (0 <= self.key_pc <= 11):
            raise ValueError(f"key_pc must be 0..11, got {self.key_pc}")

    # -- authoring ---------------------------------------------------------

    @classmethod
    def of(
        cls,
        key: str,
        mode_name: str,
        spec: Sequence,
        *,
        beats_per_chord: float | None = None,
        functional: bool = False,
    ) -> "Progression":
        """Author a progression from a compact spec.

        ``spec`` is a list of either bare symbols (even harmonic rhythm — pass
        ``beats_per_chord``) or ``(symbol, duration_beats)`` pairs (explicit
        harmonic rhythm — the expressive case, e.g. accelerating into a cadence).
        Mixing the two forms in one spec is rejected (ambiguous rhythm).

            Progression.of("E", "Dorian", ["Em7", "A7", "Em7", "Bm7"],
                           beats_per_chord=4.0)
            Progression.of("E", "Phrygian",
                           [("F", 8.0), ("Em", 4.0), ("Bb", 2.0), ("Em", 2.0)])
        """
        items = list(spec)
        if not items:
            raise ValueError("progression spec is empty")
        is_pair = [isinstance(it, tuple) for it in items]
        if any(is_pair) and not all(is_pair):
            raise ValueError(
                "progression spec mixes bare symbols and (symbol, duration) "
                "pairs — pick one form (bare + beats_per_chord, or all pairs)"
            )
        changes: list[Change] = []
        t = 0.0
        if all(is_pair):
            for sym, dur in items:
                changes.append(Change(Chord.parse(sym), t, float(dur)))
                t += float(dur)
        else:
            if beats_per_chord is None:
                raise ValueError(
                    "bare-symbol spec needs beats_per_chord (the harmonic rhythm)"
                )
            for sym in items:
                changes.append(Change(Chord.parse(sym), t, float(beats_per_chord)))
                t += float(beats_per_chord)
        return cls(
            key_pc=pitch_class(key),
            mode=mode(mode_name),
            changes=tuple(changes),
            functional=functional,
        )

    # -- read-side rulers the generators / lens consume --------------------

    @property
    def cycle_beats(self) -> float:
        """The progression's full length (one cycle before it loops)."""
        return max(c.start_beat + c.duration_beats for c in self.changes)

    def chord_at(self, beat: float) -> Chord:
        """The chord sounding at ``beat`` (0-based), CYCLIC modulo the cycle.

        Tiling-safe: call it per hit for any beat in a section and a short cycle
        loops automatically. Finds the change with the largest start <= the
        wrapped beat (robust to any change layout).
        """
        t = beat % self.cycle_beats
        # last change whose start <= t (changes are authored in time order)
        current = self.changes[0]
        for c in self.changes:
            if c.start_beat <= t + 1e-9:
                current = c
            else:
                break
        return current.chord

    def tiled(self, length_beats: float) -> "Progression":
        """Repeat the cycle to explicitly cover ``[0, length_beats)``.

        A convenience that materializes the cyclic timeline into concrete
        changes (useful for slicing and for windowed analysis). Built on the same
        cyclic semantics as ``chord_at`` — a single declared cycle, repeated.
        """
        if length_beats <= 0:
            raise ValueError(f"length_beats must be > 0, got {length_beats}")
        cycle = self.cycle_beats
        out: list[Change] = []
        base = 0.0
        while base < length_beats - 1e-9:
            for c in self.changes:
                start = base + c.start_beat
                if start >= length_beats - 1e-9:
                    break
                dur = min(c.duration_beats, length_beats - start)
                out.append(Change(c.chord, start, dur))
            base += cycle
        return Progression(self.key_pc, self.mode, tuple(out), self.functional)

    def slice(self, start_beat: float, length_beats: float) -> "Progression":
        """The sub-timeline over ``[start_beat, start_beat+length_beats)``,
        rebased to 0 — how a song-level plan is sliced per section.
        """
        if length_beats <= 0:
            raise ValueError(f"length_beats must be > 0, got {length_beats}")
        full = self.tiled(start_beat + length_beats)
        out: list[Change] = []
        for c in full.changes:
            end = c.start_beat + c.duration_beats
            if end <= start_beat + 1e-9 or c.start_beat >= start_beat + length_beats - 1e-9:
                continue
            new_start = max(c.start_beat, start_beat) - start_beat
            new_end = min(end, start_beat + length_beats) - start_beat
            out.append(Change(c.chord, new_start, new_end - new_start))
        if not out:  # window fell before the first change — shouldn't happen, fail loud
            raise ValueError(
                f"slice [{start_beat}, {start_beat + length_beats}) produced no changes"
            )
        return Progression(self.key_pc, self.mode, tuple(out), self.functional)

    @property
    def distinct_chords(self) -> int:
        """How many DISTINCT chords the timeline declares — the denominator the
        lint lens uses for the harmonic-stasis check (declared > 1 but sounded
        == 1 is the one-chord bug)."""
        return len({_chord_key(c.chord) for c in self.changes})

    @property
    def harmonic_rhythm(self) -> tuple[float, ...]:
        """The sequence of change durations — the expressive parameter the
        review lens reads derivatives off (slow = stasis, accelerating =
        intensification)."""
        return tuple(c.duration_beats for c in self.changes)


def _chord_key(chord: Chord) -> tuple:
    """A hashable identity for a chord (for distinct-counting). Two chords are
    the same iff they sound the same set of pitch classes from the same root."""
    return (chord.root_pc, tuple(sorted(chord.pitch_classes())))
