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
from typing import Any, Literal, Mapping, Sequence

from hallucinote.melody.contour import (
    ContourShape,
    apex,
    contour_shape,
    direction_changes,
    gradient_stdev,
)
from hallucinote.melody.harmony_fit import HarmonyFit, analyze_harmony_fit
from hallucinote.melody.intervals import (
    ambitus,
    melodic_intervals,
    pitch_alphabet_size,
    post_skip_reversal_rate,
    step_leap_unison_counts,
)
from hallucinote.theory.model import Progression

NoteDict = dict[str, Any]

Severity = Literal["info", "warning", "blocking"]
_VALID_SEVERITIES = ("info", "warning", "blocking")

Classification = Literal["active", "static", "insufficient-data"]

# Onsets closer than this (beats) are treated as ONE melodic event — a melody is
# monophonic, so a block-chord onset collapses to its TOP voice (the melody note).
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

_DEFAULT_BEATS_PER_BAR = 4.0


@dataclass(frozen=True)
class MelodyFinding:
    """One melodic observation, intent-keyed by ``kind`` + ``severity``. Every
    finding is ``info`` — a coaching question, never a verdict (model §7)."""

    kind: str            # "static-line" | "wandering-line" | "unresolved-nct"
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
    ``apex_position`` locate the climax. ``harmony`` is ``None`` when the section
    declared no progression. ``classification`` is the genre-safe active/static
    read (shaped-vs-aimless is profile-relative, deferred); ``confidence`` (0..1)
    scales with note count."""

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
    harmony: HarmonyFit | None
    classification: Classification
    confidence: float

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
            "harmony": self.harmony.to_dict() if self.harmony is not None else None,
            "classification": self.classification,
            "confidence": self.confidence,
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
            "lines": [l.to_dict() for l in self.lines],
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
    interval substrate. ``beats_per_bar`` feeds the strong-beat read."""

    name: str
    length_beats: float
    layers: Mapping[str, Sequence[NoteDict]]
    progression: Progression | None = None
    melody_layers: tuple[str, ...] | None = None
    beats_per_bar: float = _DEFAULT_BEATS_PER_BAR


def _melodic_sequence(notes: Sequence[NoteDict]) -> list[tuple[float, int]]:
    """Reduce a track's notes to an onset-ordered monophonic ``(start, pitch)``
    line: sort by onset, and for effectively-simultaneous notes keep the TOP voice
    (highest pitch) — the melody note. A melody is one note at a time; this makes
    the contour/interval read robust to an incidental block-chord onset."""
    pairs = sorted(
        ((float(n["start_beats"]), int(n["pitch"])) for n in notes),
        key=lambda sp: (sp[0], -sp[1]),
    )
    seq: list[tuple[float, int]] = []
    for start, pitch in pairs:
        if seq and abs(start - seq[-1][0]) <= _ONSET_EPS:
            continue  # same onset — keep the first (highest) = top voice
        seq.append((start, pitch))
    return seq


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


def _line(track: str, notes: Sequence[NoteDict], sec: SectionMelody) -> MelodicLine:
    seq = _melodic_sequence(notes)
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
        contour_shape=contour_shape(pitches),
        apex_pitch=apex_pitch,
        apex_position=apex_pos,
        direction_changes=direction_changes(intervals),
        gradient_stdev=gradient_stdev(intervals),
        harmony=harmony,
        classification=_classify(amb, onset_count),
        confidence=_confidence(onset_count),
    )


def _layer_names(sec: SectionMelody) -> list[str]:
    if sec.melody_layers is not None:
        return [t for t in sec.melody_layers if t in sec.layers]
    return list(sec.layers)


def _findings_for(line: MelodicLine, section: str) -> list[MelodyFinding]:
    out: list[MelodyFinding] = []
    # Each finding is a coaching QUESTION — a static line may be an intended drone;
    # the lens asks, the composer decides (the harmony lint honors an intentional
    # drone the same way). Gated on enough notes to trust the call. NOTE: there is
    # deliberately NO "aimless/random-walk" finding — that verdict is genre-relative
    # and needs the declared profile (phase 2b); v1 reports the facts, never nags a
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
    # unresolved (stranded dissonance) — high NCT alone is normal melodic color, and
    # is graded against the (future) declared harmonic-freedom, never a verdict.
    hf = line.harmony
    if (
        hf is not None
        and hf.nct_resolves_by_step is not None
        and hf.non_chord_tone_fraction > _NCT_COACH_MIN
        and hf.nct_resolves_by_step < _NCT_RESOLVE_MIN
        and line.onset_count >= _MIN_MELODIC_NOTES
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
    return out


def _analyze_section(sec: SectionMelody) -> SectionMelodyResult:
    names = _layer_names(sec)
    lines = tuple(_line(t, sec.layers[t], sec) for t in names)
    findings: list[MelodyFinding] = []
    for line in lines:
        findings.extend(_findings_for(line, sec.name))
    return SectionMelodyResult(section=sec.name, lines=lines, findings=tuple(findings))


def analyze_melody(
    sections: Sequence[SectionMelody],
    *,
    song_slug: str,
) -> MelodyReport:
    """Analyze a song's authored melodic lines, section by section, line by line.

    Pure symbolic measurement over the per-section note content — the build-time
    counterpart to the harmony conformance lint + performance feel lens. The
    headline is per-line ``classification`` (``shaped`` / ``wandering`` / ``static``
    / ``insufficient-data``) + the contour / interval / harmony-fit facts. Render-
    free and DB-decoupled: feed it ``arrangement.Arrangement.section_melody_inputs()``
    at build time, or synthetic ``SectionMelody`` inputs in a test.
    """
    secs = tuple(_analyze_section(s) for s in sections)
    rollup = tuple(f for s in secs for f in s.findings)
    return MelodyReport(song_slug=song_slug, sections=secs, findings=rollup)
