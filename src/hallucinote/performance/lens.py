"""hallucinote.performance.lens — the build-time symbolic performance lens.

The rhythmic/dynamic analog of ``theory.lint`` (the harmonic-conformance lens):
a pure SYMBOLIC ruler over (authored notes, the metric grid). It runs on
NoteDicts at BUILD time — no audio render, no Live (unlike ``audio.timing``,
which detects onsets from rendered WAVs and pays the onset-detection error
budget). The symbolic feed is exact and render-free, so it sidesteps that whole
class of detection bugs. It REPORTS; it never edits a note.

Load-bearing framing (memory ``feedback_microtiming_is_authorship``): **authored
feel is NOT error.** The lens reads BACK what was authored and asks whether a
part reads *mechanical*, *human/grooving*, or *sloppy*; it never treats a
deviation as a mistake. Findings are coaching QUESTIONS framed against intent
(the masking-analyzer shape), never verdicts — so every P1 finding is
``severity="info"``.

What it measures, per part (track) per section that has onsets:

  * **timing deviation from the metric grid** — the signed MEAN (``< 0`` = push/
    ahead of the beat, ``> 0`` = drag/behind) and the STDEV (looseness; lower =
    more machine-tight), measured against a subdivision grid (default 16th =
    ``0.25`` beat). Same vocabulary + grid default as ``audio.timing`` so the
    symbolic and audio feeds speak one language.
  * **deviation correlation structure** (``performance.correlation``) — lag-1
    autocorrelation (the robust structured-vs-white discriminator) + the DFA 1/f
    exponent α when the series is long enough to trust. This is what separates a
    HUMAN groove from SLOPPY jitter.
  * **dynamics + articulation** (``performance.dynamics``) — per-note velocity
    mean/stdev and a ``flat_dynamics`` flag (the organ-at-one-velocity case), plus
    an articulation character (median duration/IOI: ≈1 legato, <≈0.5 staccato).

The **mechanical / human / sloppy** classification (performance-model §7): a part
whose onsets sit on the grid with ~zero spread reads ``mechanical`` (this
includes a *constant-offset shifted grid* — nonzero mean, ~zero stdev — a
precisely-shifted grid is still a machine: tightness, not lateness, is the
mechanical signal). A part with real spread is then split by the correlation
STRUCTURE of its deviation: correlated (≈1/f) reads ``human``; uncorrelated white
jitter reads ``sloppy``. **Magnitude is NOT the splitter** — small *structured*
deviation is human, while even small *uncorrelated* jitter is not (Keil's
participatory discrepancies). Too few onsets reads ``insufficient-data``.

Output mirrors ``theory.lint`` (frozen dataclasses, a ``Severity`` Literal, an
explicit ``to_dict()`` boundary), defined locally so the performance layer never
depends on the higher ``audio`` layer. Pure stdlib (``statistics``) — no numpy —
matching the stdlib-only core-library posture and ``theory.lint``.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from hallucinote.performance.correlation import (
    RELIABLE_ACF_ONSETS,
    STRUCTURED_ACF_MIN,
    dfa_alpha,
    lag1_autocorr,
)
from hallucinote.performance.dynamics import (
    articulation_stats,
    is_flat_dynamics,
    velocity_stats,
)

NoteDict = dict[str, Any]

Severity = Literal["info", "warning", "blocking"]
_VALID_SEVERITIES = ("info", "warning", "blocking")

Classification = Literal["mechanical", "human", "sloppy", "insufficient-data"]

# Grid resolution for timing-deviation snapping (beats). 0.25 = a 16th note in
# 4/4 — the finest subdivision most rhythmic material lands on. Shared default
# with ``audio.timing`` so the symbolic + audio feeds report against one grid.
GRID_SUBDIVISION_BEATS = 0.25

# Below this many distinct rhythmic onsets a part's timing stats are too sparse
# to trust — mean/stdev are reported ``None`` and the part reads
# ``insufficient-data`` (a sustained pad has no feel to recover).
_MIN_ONSETS = 4

# Onsets closer than this (beats) are treated as ONE rhythmic event — a block
# chord authored as N simultaneous notes is one timing event, not N. A
# deliberately spread strum (distinct start_beats) is NOT collapsed; that spread
# is authored feel. Tight tolerance: collapse only effectively-simultaneous onsets.
_ONSET_DEDUP_BEATS = 1e-6

# Timing stdev (beats) at or below which a part reads mechanically tight. ~0.01
# beat ≈ 5 ms @ 120 bpm — tighter than any human ensemble; only quantized /
# constant-offset material lands here. A calibration parameter (P2 revisits it
# alongside the 1/f metric and the human/sloppy thresholds).
_MECHANICAL_STDEV_MAX = 0.01

# Onset count at which timing confidence saturates to 1.0; fewer onsets scale
# confidence down linearly so sparse parts read low-trust, not confidently wrong.
_CONFIDENCE_FULL_ONSETS = 8

# A part must be this rhythmically active (distinct onsets) before a flat-dynamics
# finding fires — flags the organ-at-one-velocity case while sparing a sustained
# pad, whose single velocity is expected, not a missed dynamic opportunity.
_FLAT_DYNAMICS_FINDING_MIN_ONSETS = 8


@dataclass(frozen=True)
class PerfFinding:
    """One performance observation, intent-keyed by ``kind`` + ``severity``.

    Mirrors ``theory.lint.HarmonyFinding``. In P1 every finding is ``info`` — a
    coaching question, never a verdict (authored feel is not error)."""

    kind: str            # "mechanical-timing" (P1); P2+ adds human/sloppy/flat-dynamics
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
class PartPerformance:
    """One part's (track's) timing measurements over a section.

    ``timing_mean`` is the signed mean grid deviation in beats (``< 0`` push /
    ahead, ``> 0`` drag / behind); ``timing_stdev`` is the looseness. Both are
    ``None`` when the part has fewer than ``_MIN_ONSETS`` distinct onsets.
    ``timing_acf`` is the lag-1 autocorrelation of the deviation series (the
    structured-vs-white discriminator: ≥ ``STRUCTURED_ACF_MIN`` ⇒ human, near 0 ⇒
    sloppy); ``timing_dfa_alpha`` is the DFA 1/f exponent, populated only when the
    series is long enough to trust (``correlation.DFA_MIN_POINTS``), else ``None``.
    ``onset_count`` counts distinct rhythmic events (block-chord notes collapse to
    one); ``note_count`` is the raw note total. ``confidence`` (0..1) scales with
    onset count.

    Dynamics (per-note) + articulation (per-onset): ``velocity_mean`` /
    ``velocity_stdev`` over the part's note velocities; ``flat_dynamics`` is True
    when many notes sit at essentially one level (the organ-at-one-velocity case).
    ``articulation`` is the median duration/IOI (≈1 legato/sustained, <≈0.5
    staccato) and ``articulation_stdev`` its consistency — reported, not yet a
    finding source."""

    track_name: str
    onset_count: int
    note_count: int
    timing_mean: float | None
    timing_stdev: float | None
    timing_acf: float | None
    timing_dfa_alpha: float | None
    velocity_mean: float | None
    velocity_stdev: float | None
    flat_dynamics: bool
    articulation: float | None
    articulation_stdev: float | None
    classification: Classification
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_name": self.track_name,
            "onset_count": self.onset_count,
            "note_count": self.note_count,
            "timing_mean": self.timing_mean,
            "timing_stdev": self.timing_stdev,
            "timing_acf": self.timing_acf,
            "timing_dfa_alpha": self.timing_dfa_alpha,
            "velocity_mean": self.velocity_mean,
            "velocity_stdev": self.velocity_stdev,
            "flat_dynamics": self.flat_dynamics,
            "articulation": self.articulation,
            "articulation_stdev": self.articulation_stdev,
            "classification": self.classification,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SectionPerformance:
    """A section's per-part performance result + its findings."""

    section: str
    parts: tuple[PartPerformance, ...]
    findings: tuple[PerfFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "parts": [p.to_dict() for p in self.parts],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class PerformanceReport:
    """The whole-song symbolic-performance report."""

    song_slug: str
    sections: tuple[SectionPerformance, ...]
    findings: tuple[PerfFinding, ...]  # song-level rollup (all findings, flattened)

    @property
    def blocking(self) -> tuple[PerfFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "blocking")

    @property
    def ok(self) -> bool:
        """No BLOCKING findings. P1 emits only ``info`` findings (authored feel
        is not error), so ``ok`` is always True until a future phase introduces a
        genuinely-blocking performance condition — kept for contract parity with
        ``theory.lint`` and forward use."""
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "song_slug": self.song_slug,
            "sections": [s.to_dict() for s in self.sections],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True)
class SectionPerf:
    """Performance-lens input for one section — decoupled from ``PlacedSection``
    so the lens is unit-testable without the arrangement layer (mirrors
    ``theory.lint.SectionLint``; the ``arrangement.Arrangement.section_perf_inputs``
    adapter bridges the two). Note onsets are 0-based within the section.

    Unlike the harmony lint, NO track is excluded by default: drums are the
    primary carriers of timing feel, so every layer is measured. ``length_beats``
    is carried for parity + future per-section-length-aware findings."""

    name: str
    length_beats: float
    layers: Mapping[str, Sequence[NoteDict]]


def _grid_deviation(start_beats: float, grid: float) -> float:
    """Signed distance from an onset to the NEAREST grid subdivision (beats).

    Negative = ahead of the grid (push); positive = behind (drag). An onset
    exactly on the midpoint between two subdivisions is maximally ambiguous —
    ``round``'s banker's rounding may pick either neighbour, but ``|deviation|``
    is identical either way, so the magnitude (the looseness signal) is stable."""
    nearest = round(start_beats / grid) * grid
    return start_beats - nearest


def _onset_events(notes: Sequence[NoteDict]) -> list[tuple[float, float]]:
    """Sorted distinct rhythmic onsets, each paired with its sustaining (max)
    duration. Effectively-simultaneous notes (a block chord) collapse to one
    event keeping the longest voice; a spread strum stays distinct. The single
    source of de-duplicated onsets for both the timing core (uses the onsets) and
    articulation (uses onset + duration)."""
    pairs = sorted(
        (float(n["start_beats"]), float(n["duration_beats"])) for n in notes
    )
    events: list[tuple[float, float]] = []
    for onset, dur in pairs:
        if events and (onset - events[-1][0]) <= _ONSET_DEDUP_BEATS:
            prev_onset, prev_dur = events[-1]
            events[-1] = (prev_onset, max(prev_dur, dur))
        else:
            events.append((onset, dur))
    return events


def _confidence(onset_count: int) -> float:
    return min(1.0, onset_count / _CONFIDENCE_FULL_ONSETS)


def _classify_timing(stdev: float | None, acf: float | None) -> Classification:
    if stdev is None:
        return "insufficient-data"
    # A constant-offset shifted grid (nonzero mean, ~zero stdev) is mechanical
    # too — tightness, not lateness, is the mechanical signal (§7).
    if stdev <= _MECHANICAL_STDEV_MAX:
        return "mechanical"
    # Real deviation present. Its STRUCTURE — not its magnitude — splits human
    # from sloppy: correlated (≈1/f) deviation is a groove; uncorrelated white
    # jitter is sloppy (§4.4, §7). ``acf`` is None only on a zero-variance series,
    # which the mechanical branch already caught — so default to sloppy.
    if acf is not None and acf >= STRUCTURED_ACF_MIN:
        return "human"
    return "sloppy"


def _part_performance(track: str, notes: Sequence[NoteDict], *, grid: float) -> PartPerformance:
    events = _onset_events(notes)
    onset_count = len(events)
    # Dynamics + articulation are assessed for EVERY part, independent of the
    # timing-onset floor — a sustained pad has no recoverable feel but still has a
    # velocity profile and an articulation character.
    vmean, vstdev, note_count = velocity_stats(notes)
    artic, artic_stdev = articulation_stats(events)
    common = dict(
        track_name=track, onset_count=onset_count, note_count=note_count,
        velocity_mean=vmean, velocity_stdev=vstdev,
        flat_dynamics=is_flat_dynamics(vstdev, note_count),
        articulation=artic, articulation_stdev=artic_stdev,
    )
    if onset_count < _MIN_ONSETS:
        return PartPerformance(
            timing_mean=None, timing_stdev=None, timing_acf=None,
            timing_dfa_alpha=None, classification="insufficient-data",
            confidence=_confidence(onset_count), **common,
        )
    devs = [_grid_deviation(onset, grid) for onset, _dur in events]
    mean = statistics.fmean(devs)
    # Population stdev: we are describing THIS part's spread, not estimating a
    # wider population — matches audio.timing's intent.
    stdev = statistics.pstdev(devs)
    # Correlation structure is only meaningful when there's real deviation to
    # have structure. For a mechanically-tight part (stdev <= floor) the series
    # is constant-up-to-float-noise, so acf/dfa would be computed on rounding
    # noise — report None instead (honest: a machine has no deviation structure).
    if stdev <= _MECHANICAL_STDEV_MAX:
        acf = dfa = None
    else:
        acf = lag1_autocorr(devs)
        dfa = dfa_alpha(devs)
    return PartPerformance(
        timing_mean=mean, timing_stdev=stdev, timing_acf=acf, timing_dfa_alpha=dfa,
        classification=_classify_timing(stdev, acf),
        confidence=_confidence(onset_count), **common,
    )


def _analyze_section(sec: SectionPerf, *, grid: float) -> SectionPerformance:
    parts = tuple(
        _part_performance(track, notes, grid=grid)
        for track, notes in sec.layers.items()
    )
    findings: list[PerfFinding] = []
    for p in parts:
        # Findings are coaching QUESTIONS, never verdicts — authored feel is not
        # error. A mechanical part may be an intended machine-tight choice (a
        # quantized EDM hat), exactly as the harmony lint honors an intentional
        # drone; a sloppy part may be deliberate looseness. The lens asks; the
        # composer decides. Each finding fires only with enough onsets to TRUST
        # the call: the mechanical call is stdev-based (reliable from a handful of
        # onsets), the sloppy call is lag-1-acf-based and needs RELIABLE_ACF_ONSETS
        # (the correlation calibration) so a short noisy estimate never false-nags
        # a good groove.
        if p.classification == "mechanical" and p.onset_count >= _CONFIDENCE_FULL_ONSETS:
            findings.append(PerfFinding(
                kind="mechanical-timing", severity="info", section=sec.name,
                track=p.track_name,
                detail=(
                    f"{p.track_name} plays {p.onset_count} onsets mechanically "
                    f"tight to the grid (timing stdev {p.timing_stdev:.4f} beat) "
                    f"— intended machine-tight feel, or missing human push/drag?"
                ),
                metric=p.timing_stdev,
            ))
        elif p.classification == "sloppy" and p.onset_count >= RELIABLE_ACF_ONSETS:
            findings.append(PerfFinding(
                kind="sloppy-timing", severity="info", section=sec.name,
                track=p.track_name,
                detail=(
                    f"{p.track_name}'s timing varies (stdev {p.timing_stdev:.4f} "
                    f"beat) but WITHOUT the correlated structure of a human groove "
                    f"(lag-1 acf {p.timing_acf:.2f}) — intended looseness, or "
                    f"quantize-then-randomize white jitter?"
                ),
                metric=p.timing_acf,
            ))
        # Flat dynamics is INDEPENDENT of the timing classification (a part can
        # groove in time yet play every note at one velocity). Gated on rhythmic
        # activity so a sustained pad's natural single velocity isn't nagged.
        if p.flat_dynamics and p.onset_count >= _FLAT_DYNAMICS_FINDING_MIN_ONSETS:
            findings.append(PerfFinding(
                kind="flat-dynamics", severity="info", section=sec.name,
                track=p.track_name,
                detail=(
                    f"{p.track_name} plays {p.note_count} notes at essentially one "
                    f"velocity (mean {p.velocity_mean:.0f}, stdev "
                    f"{p.velocity_stdev:.1f}) — intended drone/organ, or missing "
                    f"dynamic shaping?"
                ),
                metric=p.velocity_stdev,
            ))
    return SectionPerformance(section=sec.name, parts=parts, findings=tuple(findings))


def analyze_performance(
    sections: Sequence[SectionPerf],
    *,
    song_slug: str,
    grid_subdivision_beats: float = GRID_SUBDIVISION_BEATS,
) -> PerformanceReport:
    """Analyze a song's authored performance feel, section by section, part by part.

    Pure symbolic measurement over the per-section note content — the build-time
    counterpart to the audio feel-recovery in ``audio.timing``. The headline is
    per-part ``classification`` (``mechanical`` / ``human`` / ``sloppy`` /
    ``insufficient-data``) + the timing-deviation and correlation stats. Render-
    free and DB-decoupled: feed it ``arrangement.Arrangement.section_perf_inputs()``
    at build time, or synthetic ``SectionPerf`` inputs in a test.
    """
    secs = tuple(
        _analyze_section(s, grid=grid_subdivision_beats) for s in sections
    )
    rollup = tuple(f for s in secs for f in s.findings)
    return PerformanceReport(song_slug=song_slug, sections=secs, findings=rollup)
