"""hallucinote.melody.lens — the build-time symbolic melody lens.

The melodic-line analog of ``theory.lint`` (harmonic conformance) and
``performance.lens`` (timing/dynamics feel): a pure SYMBOLIC ruler over an
authored monophonic line. It runs on ``NoteDict``s at BUILD time — no audio
render, no Live — and it REPORTS; it never edits a note. See
``.prawduct/artifacts/melody-model.md``.

Load-bearing framing (memory ``project_melody_model_meta_answer`` + §1 of the
model): **there is no universal "good melody" function.** The lens measures the
genre-GENERAL substrate facts the research finds cross-culturally robust (pitch
proximity, contour shape, a small alphabet, harmonic anchoring) and classifies a
line's intrinsic structure; it does NOT grade against a declared melodic profile
yet (that — and learning the revealed intent back per-song — is the authoring
phase, exactly as ``performance.lens`` read "what's authored, not what was
declared" before the profile object existed). Findings are coaching QUESTIONS
framed against intent, never verdicts (authored melodic choice is not error) — so
every finding is ``severity="info"``.

What it measures, per melodic line (track) per section:

  * **contour** (``melody.contour``) — the coarse shape (a continuous summary, not
    a discrete type — §3.7), the apex (climax pitch + normalized position), the
    direction-change count, and the signed-gradient stdev (the steep-vs-flat
    variability that tracks recognition — §3.B2).
  * **intervallic profile** (``melody.intervals``) — step↔leap fractions (pitch
    proximity — §3.6), post-skip-reversal rate (gap-fill — §3.4), pitch-alphabet
    size (the ≤7-degree tendency), and ambitus (range).
  * **harmony fit** (``melody.harmony_fit``, when the section declares a
    ``Progression``) — chord-tone / scale-tone / chromatic shares, whether
    non-chord-tones resolve by step (anchoring — §3.A3), and whether chord tones
    favor strong beats (§3.A1). The horizontal counterpart to ``theory.lint``.

The **active / static / insufficient-data** classification (model §7) is
deliberately genre-SAFE: a near-monotone (tiny ambitus) reads ``static``, a line
with real melodic range reads ``active``, too few notes reads ``insufficient-data``.
It does NOT verdict *shaped vs aimless/random-walk* — that split is genre-relative
(a line built on 3rds, a chromatic bebop head, and a folk hook each read against
their own idiom) and needs the DECLARED melodic profile to grade against, so it is
a phase-2b capability. v1 instead REPORTS the facts that feed that judgment
(step↔leap, reversal, contour shape, alphabet, harmony fit); a deliberately angular
line is never nagged as "wrong". Findings are questions, never verdicts.

Output mirrors ``theory.lint`` / ``performance.lens`` (frozen dataclasses, a
``Severity`` Literal, an explicit ``to_dict()`` boundary), defined locally so the
melody layer never depends on the higher ``audio`` layer. Pure stdlib — no numpy.

Scope (model §6, §8): this phase ships **contour + intervals + harmony-fit** over
pitched discrete-onset monophonic lines. Motivic-economy / n-gram repetition
readings, declared-profile grading, and learn-back are friction-driven follow-ons.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

if TYPE_CHECKING:  # avoid a runtime cycle — arrangement imports SectionMelody from here
    from hallucinote.arrangement import Arrangement

from hallucinote.melody.contour import (
    ContourShape,
    apex,
    contour_shape,
    direction_changes,
    gradient_stdev,
)
from hallucinote.melody.economy import repetition_coverage as _repetition_coverage
from hallucinote.melody.harmony_fit import HarmonyFit, analyze_harmony_fit
from hallucinote.melody.intervals import (
    ambitus,
    melodic_intervals,
    pitch_alphabet_size,
    post_skip_reversal_rate,
    step_leap_unison_counts,
)
from hallucinote.melody.profile import Appetite, MelodicProfile
from hallucinote.melody.segmentation import per_phrase_contours as _per_phrase_contours
from hallucinote.theory.model import Progression

NoteDict = dict[str, Any]

Severity = Literal["info", "warning", "blocking"]
_VALID_SEVERITIES = ("info", "warning", "blocking")

Classification = Literal["active", "static", "insufficient-data"]

# The profile-RELATIVE shaped-vs-aimless reading (design §4, the recorded
# universal-verdict correction). ``ungraded`` (no definite declared intent — the
# genre-safe default), ``shaped`` (the measured contour/repetition are consistent
# with the declared intents), ``aimless`` (a DEFINITE declared intent is
# contradicted). ``aimless`` can NEVER fire on a silent or ``free`` profile — that
# is exactly why the reggae-hook universal-verdict bug cannot recur (model §7).
ShapedReading = Literal["shaped", "aimless", "ungraded"]

# Float tolerance (beats) for "same onset" / "already ended" in the skyline reduction
# (_extract_melodic_line): notes within this window count as one melodic event (a
# block-chord onset collapses to its TOP voice), and a note ending within it of the
# next onset is treated as no longer sounding (back-to-back notes don't mask).
_ONSET_EPS = 1e-6

# Below this many distinct melodic onsets a line is too sparse for contour /
# interval structure to mean anything — it reads ``insufficient-data``.
_MIN_MELODIC_NOTES = 4

# Ambitus (semitones) at/below which a line reads ``static`` — a near-monotone
# recitation. 2 = a whole tone of TOTAL range. A calibration parameter.
_STATIC_AMBITUS_MAX = 2

# Onset count at which confidence saturates to 1.0; fewer scales down linearly.
_CONFIDENCE_FULL_NOTES = 8

# A finding fires only with enough notes to TRUST the call (mirrors performance's
# onset-count gates), so a short line never false-nags.
_STATIC_FINDING_MIN_NOTES = 8

# Harmony coaching fires only when non-chord-tones are BOTH abundant AND mostly
# unresolved (stranded dissonance) — high NCT alone is normal melodic color.
_NCT_COACH_MIN = 0.4
_NCT_RESOLVE_MIN = 0.5

# A declared ``harmonic_freedom="low"`` (chord-tone-locked) is contradicted when the
# line's non-chord-tone share rises above this — the profile-relative grading edge
# for the harmonic-freedom field (design §4). Chosen to align with the 2a
# ``_NCT_COACH_MIN`` "abundant NCT" threshold so the two readings speak one notion
# of "a lot of non-chord-tones".
_HARMONIC_FREEDOM_LOW_NCT_MAX = 0.4

# ---------------------------------------------------------------------------
# Appetite -> fraction grading edges (design §4 / §8).
#
# PENDING by-ear calibration — see build-plan Chunk 4 / design §8. These map a
# coarse declared appetite band (low/moderate/high) to a measured-fraction range.
# The VALUES below are PLACEHOLDERS: Chunk 4 renders + measures sun-zone-done's two
# hooks objectively and SURFACES the numbers, but the threshold VALUES (and which
# profile each hook declares) are a creative lock-in left to the user's ear — they
# are NOT finalized here. Isolated as named constants so the ear-set values land in
# ONE place (no magic numbers scattered through the grading).
#
# Semantics: a declared "low" step appetite expects step_fraction at/below
# ``_STEP_FRACTION_LOW_MAX`` (leap-driven); "high" expects at/above
# ``_STEP_FRACTION_HIGH_MIN`` (proximity-driven); "moderate" is the band between.
# A finding fires only when the MEASURED band disagrees with the DECLARED band.
_STEP_FRACTION_LOW_MAX = 0.4   # PENDING by-ear calibration
_STEP_FRACTION_HIGH_MIN = 0.7  # PENDING by-ear calibration

# The apex-position tolerance: a measured apex within this (normalized 0..1)
# distance of the declared apex_position reads as "where you intended"; beyond it
# the climax-moved question fires. PENDING by-ear calibration.
_APEX_POSITION_TOLERANCE = 0.2  # PENDING by-ear calibration

# The within-line repetition edges (the Chunk 4 economy reading grades against
# repetition_appetite, and shaped_reading uses _REPETITION_HIGH_MIN as the "is this
# a repeating hook?" floor). repetition-coverage at/above _REPETITION_HIGH_MIN reads
# "high" (a cell-driven hook); at/below _REPETITION_LOW_MAX reads "low" (through-
# composed); between is "moderate". PENDING by-ear calibration — Chunk 4 surfaces
# the measured numbers; the user's ear sets the values.
_REPETITION_LOW_MAX = 0.25  # PENDING by-ear calibration
_REPETITION_HIGH_MIN = 0.5  # PENDING by-ear calibration

_DEFAULT_BEATS_PER_BAR = 4.0


@dataclass(frozen=True)
class MelodyFinding:
    """One melodic observation, intent-keyed by ``kind`` + ``severity``. Every
    finding is ``info`` — a coaching question, never a verdict (model §7)."""

    kind: str            # "static-line" | "unresolved-nct"
    severity: Severity
    section: str
    detail: str
    metric: float | None = None
    track: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity={self.severity!r} must be one of {_VALID_SEVERITIES}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "section": self.section,
            "detail": self.detail,
            "metric": self.metric,
            "track": self.track,
        }


@dataclass(frozen=True)
class MelodicLine:
    """One line's (track's) melodic measurements over a section.

    ``ambitus`` is the range in semitones; ``register`` the mean pitch.
    ``step_fraction`` / ``leap_fraction`` are over MOVING intervals (unisons
    excluded) and are ``None`` for a line that never moves; ``post_skip_reversal``
    is ``None`` when there is no leap with a successor. ``contour_shape`` is a
    COARSE continuous-summary label (not a discrete type — §3.7); ``apex_pitch`` /
    ``apex_position`` locate the climax. ``repetition_coverage`` is the within-line
    motivic-economy number (``economy.repetition_coverage`` — ``None`` for a line too
    short for a cell to repeat). ``harmony`` is ``None`` when the section
    declared no progression. ``classification`` is the genre-safe active/static
    read (shaped-vs-aimless is profile-relative, deferred); ``confidence`` (0..1)
    scales with note count. ``profile_name`` is the declared ``MelodicProfile``'s
    name when this line was graded against one (``None`` = the unchanged 2a
    no-profile path)."""

    track_name: str
    note_count: int
    onset_count: int
    ambitus: int
    register: float
    pitch_alphabet_size: int
    step_fraction: float | None
    leap_fraction: float | None
    unison_count: int
    post_skip_reversal: float | None
    contour_shape: ContourShape
    apex_pitch: int | None
    apex_position: float | None
    direction_changes: int
    gradient_stdev: float
    repetition_coverage: float | None
    harmony: HarmonyFit | None
    classification: Classification
    confidence: float
    profile_name: str | None = None
    shaped_reading: ShapedReading = "ungraded"
    # Per-LBDM-phrase ``(contour_shape, apex_pitch, apex_position)`` — the contour
    # facts recomputed at the PHRASE unit (research C8b), where the arch actually
    # lives. A looping hook reads ``level`` whole-section but keeps its per-phrase
    # shape here. Empty tuple for a line too short to segment (one phrase = the
    # whole-line ``contour_shape``).
    phrase_contours: tuple[tuple[ContourShape, int | None, float | None], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_name": self.track_name,
            "note_count": self.note_count,
            "onset_count": self.onset_count,
            "ambitus": self.ambitus,
            "register": self.register,
            "pitch_alphabet_size": self.pitch_alphabet_size,
            "step_fraction": self.step_fraction,
            "leap_fraction": self.leap_fraction,
            "unison_count": self.unison_count,
            "post_skip_reversal": self.post_skip_reversal,
            "contour_shape": self.contour_shape,
            "apex_pitch": self.apex_pitch,
            "apex_position": self.apex_position,
            "direction_changes": self.direction_changes,
            "gradient_stdev": self.gradient_stdev,
            "repetition_coverage": self.repetition_coverage,
            "harmony": self.harmony.to_dict() if self.harmony is not None else None,
            "classification": self.classification,
            "confidence": self.confidence,
            "profile_name": self.profile_name,
            "shaped_reading": self.shaped_reading,
            "phrase_contours": [
                {"contour_shape": shape, "apex_pitch": ap, "apex_position": pos}
                for shape, ap, pos in self.phrase_contours
            ],
        }


@dataclass(frozen=True)
class SectionMelodyResult:
    """A section's per-line melodic results + its findings."""

    section: str
    lines: tuple[MelodicLine, ...]
    findings: tuple[MelodyFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "lines": [line.to_dict() for line in self.lines],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class MelodyReport:
    """The whole-song symbolic-melody report."""

    song_slug: str
    sections: tuple[SectionMelodyResult, ...]
    findings: tuple[MelodyFinding, ...]  # song-level rollup (all findings, flattened)

    @property
    def blocking(self) -> tuple[MelodyFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "blocking")

    @property
    def ok(self) -> bool:
        """No BLOCKING findings. This phase emits only ``info`` findings (authored
        melodic choice is not error), so ``ok`` is always True — kept for contract
        parity with ``theory.lint`` / ``performance.lens`` and forward use."""
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "song_slug": self.song_slug,
            "sections": [s.to_dict() for s in self.sections],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class SectionMelody:
    """Melody-lens input for one section — decoupled from ``PlacedSection`` so the
    lens is unit-testable without the arrangement layer (mirrors
    ``theory.lint.SectionLint`` / ``performance.lens.SectionPerf``; the
    ``arrangement.Arrangement.section_melody_inputs`` adapter bridges the two).
    Notes are 0-based within the section; the ``progression`` (if any) is likewise
    0-based and cyclic.

    ``melody_layers`` names the monophonic melodic lines (lead / vocal / riff) to
    analyze — drums and chordal pads are NOT melodic lines; ``None`` analyzes every
    layer. ``progression=None`` means no declared harmony — the harmony-fit read is
    skipped (``harmony`` reports ``None``), a graceful degradation to the contour /
    interval substrate. ``beats_per_bar`` feeds the strong-beat read.

    ``profiles`` (phase 2b) maps a layer NAME to its declared ``MelodicProfile`` —
    the authoring side the lens grades each line AGAINST (design §4, Decision-Record
    1). ``None`` (the default) is the byte-for-byte-unchanged 2a no-profile path: no
    profile-relative findings, every line reads as unconstrained substrate facts. A
    profile keyed to a layer name absent from this section surfaces a
    ``declared-but-unmatched`` typo finding (enumerate-every-state)."""

    name: str
    length_beats: float
    layers: Mapping[str, Sequence[NoteDict]]
    progression: Progression | None = None
    melody_layers: tuple[str, ...] | None = None
    beats_per_bar: float = _DEFAULT_BEATS_PER_BAR
    profiles: Mapping[str, MelodicProfile] | None = None


def _extract_melodic_line(notes: Sequence[NoteDict]) -> list[NoteDict]:
    """Reduce a track's notes to an onset-ordered, monophonic TOP-VOICE line.

    A note is dropped from the line iff a strictly-higher note temporally CONTAINS it
    — starts no later and ends no earlier (within :data:`_ONSET_EPS`). Containment is
    the faithful test for "this note sits entirely beneath a sustained higher voice":
    an octave double, a held-over chord tone, a backing voice under a long melody note.
    It deliberately does NOT mask on mere tail overlap: in a legato *monophonic* line a
    note's tail laps the next (lower) note's onset, and that next note IS the melody —
    masking it would gut a descending legato line (sun-zone-done's reggae hook is
    exactly this). Containment generalizes the prior exact-onset top-voice collapse to
    octave-doubles / sustained voices struck at STAGGERED onsets (the bug: an
    integration section's staggered octave-double the exact-onset rule missed), while
    leaving monophonic articulation — and genuinely wide single-voice lines — untouched.

    This is the SINGLE source of the monophonic line: the contour / interval read,
    harmony-fit, AND LBDM phrase segmentation all consume it, so none re-derives the
    line from the raw (possibly polyphonic) notes. The melody layer models monophonic
    lines (model §6); brief/incidental polyphony folds into the top voice rather than
    interleaving into a zig-zag.

    Reads ``duration_beats`` (default 0.0). Returns the kept note dicts unchanged, in
    onset order."""
    ordered = sorted(
        notes, key=lambda n: (float(n["start_beats"]), -int(n["pitch"]))
    )
    spans = [
        (float(n["start_beats"]),
         float(n["start_beats"]) + float(n.get("duration_beats", 0.0)),
         int(n["pitch"]))
        for n in ordered
    ]
    line: list[NoteDict] = []
    last_onset: float | None = None
    for n, (start, end, pitch) in zip(ordered, spans):
        contained = any(
            hp > pitch and hs <= start + _ONSET_EPS and he >= end - _ONSET_EPS
            for (hs, he, hp) in spans
        )
        # Drop a unison double sharing an onset with the note just kept (containment
        # leaves equal-pitch simultaneous notes both standing; one is the melody).
        same_onset = last_onset is not None and abs(start - last_onset) <= _ONSET_EPS
        if not contained and not same_onset:
            line.append(n)
            last_onset = start
    return line


def _melodic_sequence(notes: Sequence[NoteDict]) -> list[tuple[float, int]]:
    """The reduced monophonic line as onset-ordered ``(start, pitch)`` pairs — the
    contour / interval read's input. A thin ``(start, pitch)`` view over
    :func:`_extract_melodic_line` (the single source of the monophonic line)."""
    return [
        (float(n["start_beats"]), int(n["pitch"]))
        for n in _extract_melodic_line(notes)
    ]


def _confidence(onset_count: int) -> float:
    return min(1.0, onset_count / _CONFIDENCE_FULL_NOTES)


def _classify(ambitus_semitones: int, onset_count: int) -> Classification:
    """The genre-SAFE structural read: ``insufficient-data`` (too few notes),
    ``static`` (a near-monotone — tiny ambitus), else ``active`` (a melodic line
    with real range). It deliberately does NOT verdict *shaped vs aimless/random
    walk* — that split is genre-relative (a line built on 3rds, a chromatic bebop
    head, and a folk hook all read differently against their own idiom), so it
    needs the DECLARED melodic profile to grade against and is a phase-2b
    capability (model §1, §7). v1 reports the facts that feed that judgment
    (step↔leap, reversal, contour, alphabet) without imposing a universal verdict —
    the same honesty as ``performance.lens`` deferring declared-profile grading."""
    if onset_count < _MIN_MELODIC_NOTES:
        return "insufficient-data"
    if ambitus_semitones <= _STATIC_AMBITUS_MAX:
        return "static"
    return "active"


def _shaped_reading(
    profile: MelodicProfile | None,
    *,
    contour_shape: ContourShape,
    onset_count: int,
    repetition_number: float | None = None,
) -> ShapedReading:
    """The profile-RELATIVE shaped-vs-aimless reading (design §4) — the recorded
    universal-verdict correction made permanent.

    The metaperformer pattern (model §1): the universal is a prior, the PROFILE is
    the truth. A line is graded against its OWN declared aim, never a universal
    ideal — so a third-based reggae hook, a chromatic bebop head, and a folk tune
    each read against their declared idiom, and ``aimless`` can fire ONLY against a
    profile that declared a DEFINITE intent the line contradicts.

      * ``ungraded`` — no profile, too few notes, or the profile declares neither a
        definite ``contour_intent`` (``free`` is not definite) nor a
        ``repetition_appetite``. The genre-safe default: the universal verdict stays
        forbidden (the 2a behavior preserved). **``aimless`` can NEVER fire here** —
        exactly why the reggae-hook bug cannot recur.
      * ``shaped`` — a definite intent was declared and the line SATISFIES at least
        one of its declared aims: it has a net shape (any non-``level`` measured
        contour) when a definite contour was intended, OR it repeats a cell when high
        repetition was intended. "Shaped" means "doing what it set out to do," NOT
        "good." A line that satisfies ANY declared aim is shaped — it is not wandering.
      * ``aimless`` — EVERY declared aim is contradicted: the line has NO net shape
        (measures ``level``) where a definite contour was intended, AND it does not
        repeat its cell where high repetition was intended. The line wanders relative
        to *its own* stated aim. NOTE a DIFFERENT definite shape than declared is the
        contour-mismatch re-shape QUESTION, NOT aimlessness — only a no-net-shape
        ``level`` line counts as a contradicted contour. Satisfying ONE aim is enough
        to be ``shaped``: this is why a third-based reggae hook with a real
        descending shape but loop-level (not cell-level) repetition reads ``shaped``,
        never ``aimless`` (the recorded universal-verdict bug, made impossible).

    Chunk 3 graded on ``contour_intent`` alone (``repetition_number`` was
    ``None``-tolerant); Chunk 4 supplies the real repetition number and folds in the
    ``repetition_appetite`` direction.
    """
    if profile is None or onset_count < _STATIC_FINDING_MIN_NOTES:
        return "ungraded"

    definite_contour = (
        profile.contour_intent is not None and profile.contour_intent != "free"
    )
    declares_repetition = profile.repetition_appetite is not None
    if not definite_contour and not declares_repetition:
        return "ungraded"
    if contour_shape == "insufficient-data":
        return "ungraded"

    # Per-aim satisfaction. A definite contour aim is SATISFIED by any net shape (a
    # non-"level" measured contour) — a different shape than declared is a re-shape
    # question, not a failure of the "have a shape" aim. The high-repetition aim is
    # satisfied by a cell-covered line (the PENDING by-ear edge; an unmeasurable
    # repetition number does not contradict the aim, so it counts as satisfied —
    # never invent a verdict from missing data).
    contour_satisfied = definite_contour and contour_shape != "level"
    contour_contradicted = definite_contour and contour_shape == "level"
    repetition_satisfied = (
        profile.repetition_appetite == "high"
        and (repetition_number is None or repetition_number >= _REPETITION_HIGH_MIN)
    )
    repetition_contradicted = (
        profile.repetition_appetite == "high"
        and repetition_number is not None
        and repetition_number < _REPETITION_HIGH_MIN
    )

    # Satisfying ANY declared aim => shaped (the line is doing something it set out
    # to do — it is not wandering). aimless only when EVERY declared aim is
    # contradicted and none is satisfied.
    if contour_satisfied or repetition_satisfied:
        return "shaped"
    if contour_contradicted or repetition_contradicted:
        return "aimless"
    return "shaped"


def _line(
    track: str,
    notes: Sequence[NoteDict],
    sec: SectionMelody,
    profile: MelodicProfile | None = None,
) -> MelodicLine:
    # Extract the monophonic top-voice line ONCE; the interval/contour read,
    # harmony-fit, and LBDM segmentation all consume the same reduced line.
    line_notes = _extract_melodic_line(notes)
    seq = [(float(n["start_beats"]), int(n["pitch"])) for n in line_notes]
    pitches = [p for _start, p in seq]
    onset_count = len(seq)
    note_count = len(notes)

    intervals = melodic_intervals(pitches)
    steps, leaps, unisons = step_leap_unison_counts(intervals)
    moving = steps + leaps
    step_frac = (steps / moving) if moving else None
    leap_frac = (leaps / moving) if moving else None
    reversal = post_skip_reversal_rate(intervals)

    amb = ambitus(pitches)
    register = statistics.fmean(float(p) for p in pitches) if pitches else 0.0
    if pitches:
        apex_pitch, apex_pos = apex(pitches)
    else:
        apex_pitch, apex_pos = None, None

    harmony = None
    if sec.progression is not None and seq:
        harmony = analyze_harmony_fit(
            seq, sec.progression, beats_per_bar=sec.beats_per_bar
        )

    shape = contour_shape(pitches)
    rep_coverage = _repetition_coverage(pitches)
    # Per-phrase contour (LBDM, research C8b): surfaced only when the line actually
    # segments into more than one phrase — a single-phrase line's shape IS the
    # whole-line ``contour_shape``, so an empty tuple avoids redundant noise.
    phrases = tuple(_per_phrase_contours(line_notes))
    phrase_contours = phrases if len(phrases) > 1 else ()
    shaped = _shaped_reading(
        profile,
        contour_shape=shape,
        onset_count=onset_count,
        repetition_number=rep_coverage,
    )

    return MelodicLine(
        track_name=track,
        note_count=note_count,
        onset_count=onset_count,
        ambitus=amb,
        register=register,
        pitch_alphabet_size=pitch_alphabet_size(pitches),
        step_fraction=step_frac,
        leap_fraction=leap_frac,
        unison_count=unisons,
        post_skip_reversal=reversal,
        contour_shape=shape,
        apex_pitch=apex_pitch,
        apex_position=apex_pos,
        direction_changes=direction_changes(intervals),
        gradient_stdev=gradient_stdev(intervals),
        repetition_coverage=rep_coverage,
        harmony=harmony,
        classification=_classify(amb, onset_count),
        confidence=_confidence(onset_count),
        profile_name=profile.name if profile is not None else None,
        shaped_reading=shaped,
        phrase_contours=phrase_contours,
    )


def _layer_names(sec: SectionMelody) -> list[str]:
    if sec.melody_layers is not None:
        return [t for t in sec.melody_layers if t in sec.layers]
    return list(sec.layers)


def _findings_for(
    line: MelodicLine, section: str, profile: MelodicProfile | None = None
) -> list[MelodyFinding]:
    out: list[MelodyFinding] = []
    # Each finding is a coaching QUESTION — a static line may be an intended drone;
    # the lens asks, the composer decides (the harmony lint honors an intentional
    # drone the same way). Gated on enough notes to trust the call. NOTE: there is
    # deliberately NO "aimless/random-walk" finding here — that verdict is
    # genre-relative and needs the declared profile (the profile-relative
    # ``shaped_reading``, Chunk 3); v1's findings report the facts, never nag a
    # leap-driven idiom (a line built on 3rds is not "wrong").
    if line.classification == "static" and line.onset_count >= _STATIC_FINDING_MIN_NOTES:
        out.append(MelodyFinding(
            kind="static-line", severity="info", section=section, track=line.track_name,
            detail=(
                f"{line.track_name} is a near-static line ({line.ambitus}-semitone "
                f"range across {line.onset_count} notes) — intended drone/recitation, "
                f"or an unrealized melodic line?"
            ),
            metric=float(line.ambitus),
        ))
    # Harmony coaching: only when non-chord-tones are BOTH abundant AND mostly
    # unresolved (stranded dissonance) — high NCT alone is normal melodic color. A
    # declared ``harmonic_freedom="high"`` SUPPRESSES this (design §4): high freedom
    # means floating, freely-chromatic color is the intended idiom, so stranded-
    # dissonance coaching would nag exactly what the profile declared on purpose.
    hf = line.harmony
    declared_freedom = profile.harmonic_freedom if profile is not None else None
    if (
        hf is not None
        and hf.nct_resolves_by_step is not None
        and hf.non_chord_tone_fraction > _NCT_COACH_MIN
        and hf.nct_resolves_by_step < _NCT_RESOLVE_MIN
        and line.onset_count >= _MIN_MELODIC_NOTES
        and declared_freedom != "high"
    ):
        out.append(MelodyFinding(
            kind="unresolved-nct", severity="info", section=section, track=line.track_name,
            detail=(
                f"{line.track_name}: {hf.non_chord_tone_fraction:.0%} of notes are "
                f"non-chord-tones and only {hf.nct_resolves_by_step:.0%} resolve by "
                f"step to a chord tone — intended floating color, or stranded "
                f"dissonance against the harmony?"
            ),
            metric=hf.nct_resolves_by_step,
        ))
    out.extend(_profile_findings(line, section, profile))
    return out


def _profile_findings(
    line: MelodicLine, section: str, profile: MelodicProfile | None
) -> list[MelodyFinding]:
    """Profile-RELATIVE findings — the line's measured values graded AGAINST its
    declared intent (design §4). Each is still ``severity="info"`` and phrased as a
    coaching QUESTION ("you declared X; the line measures Y — intended?"), never a
    verdict. Fired only when the declared field has a measured counterpart, the
    measure DIVERGES, and there are enough notes to trust it (the
    ``_STATIC_FINDING_MIN_NOTES`` gate). Grades ``harmonic_freedom`` / contour /
    apex / ambitus / ``step_appetite`` divergences + the profile-relative
    shaped-vs-aimless QUESTION (the recorded universal-verdict correction)."""
    if profile is None:
        return []
    out: list[MelodyFinding] = []

    # All profile-relative findings gate on enough notes to trust the call (the 2a
    # _STATIC_FINDING_MIN_NOTES discipline) — a short line never false-nags.
    enough = line.onset_count >= _STATIC_FINDING_MIN_NOTES

    # harmonic_freedom="low" (chord-tone-locked) contradicted by abundant NCT share.
    # (declared "high" instead SUPPRESSES the 2a unresolved-nct finding above — that
    # is the high-freedom direction; the low direction asks the opposite question.)
    hf = line.harmony
    if (
        profile.harmonic_freedom == "low"
        and hf is not None
        and hf.non_chord_tone_fraction > _HARMONIC_FREEDOM_LOW_NCT_MAX
        and enough
    ):
        out.append(MelodyFinding(
            kind="harmonic-freedom-mismatch", severity="info", section=section,
            track=line.track_name,
            detail=(
                f"{line.track_name}: you declared chord-tone-locked harmony "
                f"(harmonic_freedom=low), but {hf.non_chord_tone_fraction:.0%} of "
                f"notes are non-chord-tones — intended looser color, or has the line "
                f"drifted off its declared harmonic anchor?"
            ),
            metric=hf.non_chord_tone_fraction,
        ))

    # contour_intent vs the measured contour_shape (string-equal by construction —
    # ContourIntent's members ARE ContourShape's, minus insufficient-data, plus free,
    # W2). "free" intent and an "insufficient-data" measured shape both suppress it:
    # no shape was declared to diverge from / too few notes to read a shape. The
    # ``level`` case is handled by the aimless finding below (a no-net-shape line
    # against a declared shape is the "you wanted shape, there is none" question, not
    # a "different definite shape" re-shape question), so it is excluded here to
    # avoid double-reporting the same fact.
    if (
        profile.contour_intent is not None
        and profile.contour_intent != "free"
        and line.contour_shape not in ("insufficient-data", "level")
        and line.contour_shape != profile.contour_intent
        and enough
    ):
        out.append(MelodyFinding(
            kind="contour-intent-mismatch", severity="info", section=section,
            track=line.track_name,
            detail=(
                f"{line.track_name}: you declared a {profile.contour_intent} contour, "
                f"but the line reads {line.contour_shape} — intended re-shape, or did "
                f"the climax move?"
            ),
        ))

    # The profile-relative shaped-vs-aimless QUESTION (design §4 done-when #3): when
    # the line reads ``aimless`` (a DEFINITE declared intent the line contradicts —
    # never a universal verdict), ask the coaching question. Still severity=info, a
    # question, NEVER "this melody is bad / wandering". ``shaped`` / ``ungraded`` emit
    # nothing (the line is doing what it set out to, or there is no aim to grade).
    if line.shaped_reading == "aimless" and enough:
        # mode-aware evidence: name the contradicted aim(s) so the question is
        # precise (a no-net-shape line vs an un-repeating high-repetition line).
        evidence: list[str] = []
        if profile.contour_intent not in (None, "free") and line.contour_shape == "level":
            evidence.append(f"reads {line.contour_shape} with no net shape")
        if (
            profile.repetition_appetite == "high"
            and line.repetition_coverage is not None
            and line.repetition_coverage < _REPETITION_HIGH_MIN
        ):
            evidence.append(
                f"repeats a cell across only {line.repetition_coverage:.0%} of itself"
            )
        out.append(MelodyFinding(
            kind="aimless-line", severity="info", section=section,
            track=line.track_name,
            detail=(
                f"{line.track_name}: you declared a shaped line "
                f"(contour_intent={profile.contour_intent!r}, "
                f"repetition_appetite={profile.repetition_appetite!r}), but it "
                f"{' and '.join(evidence)} — intended, or has the line wandered off "
                f"the shape it set out to make?"
            ),
        ))

    # apex_position vs the measured apex position (tolerance band).
    if (
        profile.apex_position is not None
        and line.apex_position is not None
        and abs(line.apex_position - profile.apex_position) > _APEX_POSITION_TOLERANCE
        and enough
    ):
        out.append(MelodyFinding(
            kind="apex-position-mismatch", severity="info", section=section,
            track=line.track_name,
            detail=(
                f"{line.track_name}: you intended the climax at {profile.apex_position:.0%} "
                f"of the line, but it crests at {line.apex_position:.0%} — intended "
                f"lift placement, or has the peak drifted?"
            ),
            metric=line.apex_position,
        ))

    # ambitus band: measured range outside the declared [min, max] window.
    if (
        (profile.ambitus_min is not None or profile.ambitus_max is not None)
        and enough
    ):
        below = profile.ambitus_min is not None and line.ambitus < profile.ambitus_min
        above = profile.ambitus_max is not None and line.ambitus > profile.ambitus_max
        if below or above:
            band = (
                f"{profile.ambitus_min if profile.ambitus_min is not None else '—'}"
                f"..{profile.ambitus_max if profile.ambitus_max is not None else '—'}"
            )
            out.append(MelodyFinding(
                kind="ambitus-mismatch", severity="info", section=section,
                track=line.track_name,
                detail=(
                    f"{line.track_name}: you declared a {band}-semitone range, but the "
                    f"line spans {line.ambitus} — intended register, or has the line "
                    f"outgrown / shrunk from its declared ambitus?"
                ),
                metric=float(line.ambitus),
            ))

    # step_appetite vs the measured step_fraction band (the PENDING by-ear edges).
    if (
        profile.step_appetite is not None
        and line.step_fraction is not None
        and enough
    ):
        measured_band = _step_fraction_band(line.step_fraction)
        if measured_band != profile.step_appetite:
            out.append(MelodyFinding(
                kind="step-appetite-mismatch", severity="info", section=section,
                track=line.track_name,
                detail=(
                    f"{line.track_name}: you declared a {profile.step_appetite} step "
                    f"appetite, but {line.step_fraction:.0%} of moving intervals are "
                    f"steps ({measured_band}) — intended proximity/leap balance, or has "
                    f"the line's motion drifted?"
                ),
                metric=line.step_fraction,
            ))

    # repetition_appetite vs the within-line repetition number (economy.py — the
    # motivic-economy BOTH-SIDES pairing). Graded against the PENDING by-ear edges.
    if (
        profile.repetition_appetite is not None
        and line.repetition_coverage is not None
        and enough
    ):
        measured_band = _repetition_band(line.repetition_coverage)
        if measured_band != profile.repetition_appetite:
            out.append(MelodyFinding(
                kind="repetition-appetite-mismatch", severity="info", section=section,
                track=line.track_name,
                detail=(
                    f"{line.track_name}: you declared a {profile.repetition_appetite} "
                    f"repetition appetite, but {line.repetition_coverage:.0%} of the line "
                    f"is covered by its most-repeated cell ({measured_band}) — intended "
                    f"economy, or has the cell-vs-through-composed balance drifted?"
                ),
                metric=line.repetition_coverage,
            ))
    return out


def _repetition_band(coverage: float) -> Appetite:
    """Map a measured within-line repetition coverage to a coarse appetite band
    using the PENDING by-ear edges. Higher coverage = more cell-driven = HIGHER
    repetition appetite. (The edge VALUES are calibration placeholders — design §8.)"""
    if coverage <= _REPETITION_LOW_MAX:
        return "low"
    if coverage >= _REPETITION_HIGH_MIN:
        return "high"
    return "moderate"


def _step_fraction_band(step_fraction: float) -> Appetite:
    """Map a measured step-fraction to a coarse appetite band using the PENDING
    by-ear edges. Higher step-fraction = more proximity-driven = HIGHER step
    appetite. (The edge VALUES are calibration placeholders — design §8.)"""
    if step_fraction <= _STEP_FRACTION_LOW_MAX:
        return "low"
    if step_fraction >= _STEP_FRACTION_HIGH_MIN:
        return "high"
    return "moderate"


def _declared_but_unmatched(sec: SectionMelody) -> list[MelodyFinding]:
    """A declared profile keyed to a layer NAME absent from this section is almost
    always a typo (the binding is by string — Decision-Record 1) — surface it as a
    coaching question rather than silently grading nothing (enumerate-every-state,
    learnings "Detection that replaces a user question must enumerate every state").
    Compared against the FULL layer set, not the melody-filtered names, so declaring
    a profile for a real-but-non-melodic layer is not falsely flagged a typo."""
    if not sec.profiles:
        return []
    present = set(sec.layers)
    out: list[MelodyFinding] = []
    for layer_name in sec.profiles:
        if layer_name not in present:
            out.append(MelodyFinding(
                kind="declared-but-unmatched", severity="info", section=sec.name,
                track=layer_name,
                detail=(
                    f"you declared a MelodicProfile for {layer_name!r} but this "
                    f"section has no such line — a typo in the layer name, or a "
                    f"profile left over from a different section?"
                ),
            ))
    return out


def _analyze_section(sec: SectionMelody) -> SectionMelodyResult:
    names = _layer_names(sec)
    profiles = sec.profiles or {}
    lines = tuple(_line(t, sec.layers[t], sec, profiles.get(t)) for t in names)
    findings: list[MelodyFinding] = []
    for line in lines:
        findings.extend(_findings_for(line, sec.name, profiles.get(line.track_name)))
    findings.extend(_declared_but_unmatched(sec))
    return SectionMelodyResult(section=sec.name, lines=lines, findings=tuple(findings))


def analyze_melody(
    sections: Sequence[SectionMelody],
    *,
    song_slug: str,
    profiles: Mapping[str, MelodicProfile] | None = None,
) -> MelodyReport:
    """Analyze a song's authored melodic lines, section by section, line by line.

    Pure symbolic measurement over the per-section note content — the build-time
    counterpart to the harmony conformance lint + performance feel lens. The
    headline is per-line ``classification`` (``active`` / ``static`` /
    ``insufficient-data`` — the genre-safe read) + the contour / interval /
    harmony-fit facts. Render-free and DB-decoupled: feed it
    ``arrangement.Arrangement.section_melody_inputs()`` at build time, or synthetic
    ``SectionMelody`` inputs in a test.

    ``profiles`` (phase 2b) is a song-wide ``{layer_name: MelodicProfile}`` default
    applied to every section that does not carry its own ``SectionMelody.profiles``
    (the per-section map wins). ``None`` (the default) is the byte-for-byte-unchanged
    2a no-profile path. The lens then emits profile-relative coaching questions
    (still ``info``, still questions) on top of the unconditional neutral facts.
    """
    if profiles:
        sections = [
            s if s.profiles is not None else _with_profiles(s, profiles)
            for s in sections
        ]
    secs = tuple(_analyze_section(s) for s in sections)
    rollup = tuple(f for s in secs for f in s.findings)
    return MelodyReport(song_slug=song_slug, sections=secs, findings=rollup)


def _with_profiles(
    sec: SectionMelody, profiles: Mapping[str, MelodicProfile]
) -> SectionMelody:
    """A copy of ``sec`` carrying the song-wide ``profiles`` default. Kept explicit
    (not ``dataclasses.replace``) so a future ``SectionMelody`` field can't silently
    drop here."""
    return SectionMelody(
        name=sec.name,
        length_beats=sec.length_beats,
        layers=sec.layers,
        progression=sec.progression,
        melody_layers=sec.melody_layers,
        beats_per_bar=sec.beats_per_bar,
        profiles=profiles,
    )


def analyze_arrangement(
    arr: "Arrangement",
    *,
    song_slug: str,
    melody_layers: Sequence[str] | None = None,
    start_bar: int = 1,
    profiles: Mapping[str, MelodicProfile] | None = None,
) -> MelodyReport:
    """Run the melody lens over an in-memory ``Arrangement`` — the build-time entry
    point a song's ``melody_report()`` calls (and ``tools/melody_lens.py`` surfaces
    to ``/compose-review``).

    Full harmony-fit (§5 of the model) needs the in-memory ``Progression`` carried
    by each section, which is NOT persisted to the DB — so the lens runs build-time
    over the arrangement, not over a DB read. Thin wrapper over
    ``arr.section_melody_inputs()`` -> ``analyze_melody()``; kept HERE (not on
    ``arrangement.py``) so the melody layer never depends on the arrangement layer
    at runtime — the adapter lives on the arrangement, the lens stays a leaf.

    ``melody_layers`` names the monophonic lines to read (lead / vocal / riff);
    exclude drums and chordal pads. ``None`` reads every layer.

    ``profiles`` (phase 2b) is the song's declared ``{layer_name: MelodicProfile}``
    map (Decision-Record 1: profiles live in build.py, not on the arrangement). It
    is threaded onto every section's ``SectionMelody.profiles`` so the lens grades
    each line against its declared intent. ``None`` = the unchanged 2a path.
    """
    return analyze_melody(
        arr.section_melody_inputs(
            melody_layers=melody_layers, start_bar=start_bar, profiles=profiles
        ),
        song_slug=song_slug,
    )
