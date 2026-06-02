"""MixReport — the audio analysis pipeline's wire format.

Produced by ``analyze_mix(captures_dir)`` and serialized to
``songs/<slug>/analysis/<iso-ts>.json``. The MCP handler
(``ableton_analysis(action='analyze')``) is a thin wrapper that calls
``analyze_mix`` and writes this report.

Schema version is pinned in the report itself; downstream consumers
(future ``compare_to`` differs, dashboards) discriminate by
``schema_version`` rather than file path or git tag.

The MVP carries skeleton fields that aren't yet populated:

  ``compare_to``         — baseline-diff field. Reserved per spike §9
                            (P2 backlog). Always ``None`` in MVP output.
  ``skipped_analyses``   — explicit record when a declared analysis
                            couldn't run (e.g. no declared decay times
                            in the song DB for the reverb check). Keeps
                            us honest per CLAUDE.md "Never silently drop
                            a requirement."

Per project preferences: ``@dataclass`` for in-process value objects;
serialization is one explicit ``to_json_dict()`` boundary (not
``dataclasses.asdict()`` — we want to control field ordering and reject
non-JSON-safe nesting at the seam).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1"

SurfaceKind = Literal["track", "return", "master"]
Severity = Literal["info", "warning", "blocking"]

_VALID_SURFACE_KINDS = ("track", "return", "master")
_VALID_SEVERITIES = ("info", "warning", "blocking")


@dataclass(frozen=True)
class LoudnessMetrics:
    """Per-surface loudness measurements.

    All values in dB. LUFS-I follows BS.1770-4 gating; LUFS-S median is the
    50th percentile of 3-second short-term blocks; LUFS-M peak is the max
    400 ms momentary block. True peak is 4×-oversampled sample-peak in dBTP.
    """
    lufs_i: float
    lufs_s_median: float
    lufs_m_peak: float
    true_peak_dbtp: float


@dataclass(frozen=True)
class StemMetrics:
    """One row per captured surface (audio track / return / master)."""
    track_id: str
    surface_kind: SurfaceKind
    surface_name: str
    loudness: LoudnessMetrics

    def __post_init__(self) -> None:
        if self.surface_kind not in _VALID_SURFACE_KINDS:
            raise ValueError(
                f"surface_kind={self.surface_kind!r} must be one of "
                f"{_VALID_SURFACE_KINDS}"
            )


@dataclass(frozen=True)
class MasterOvershoot:
    """A master-bus true-peak overshoot window with per-stem attribution.

    ``attribution`` is ranked top-to-bottom; each entry is
    ``(track_id, fraction)`` where ``fraction`` is the stem's share of RMS
    energy in ``dominant_band`` during the overshoot window. Sums may not
    reach 1.0 — only top contributors are surfaced; long-tail stems are
    aggregated into the residual.
    """
    start_beat: float
    end_beat: float
    peak_dbtp: float
    dominant_band: str
    attribution: list[tuple[str, float]]


@dataclass(frozen=True)
class ReverbVerification:
    """One per-RETURN RT60 verification result.

    RT60 is a property of the return's reverb *device*, not of any single
    send into it — so it is measured ONCE per return, from the return's
    own captured decay tail (ring-out) via Schroeder backward energy
    integration (``pyroomacoustics.experimental.rt60.measure_rt60``),
    dry-source-free. A return fed by N sends declares RT60 N times
    (redundantly): ``contributing_track_ids`` records those dry sources and
    ``conflicting_declarations`` is non-empty when the per-send
    declarations disagree (one device cannot have two decay times).

    Honesty fields surface measurement confidence rather than a bare
    number. ``measurement_method`` names the technique; ``decay_db_used``
    is the decay window actually fit (RT20/RT30 extrapolated to RT60 when
    the tail is short); ``tail_span_db`` is the clean decay the tail
    afforded; ``sufficient_tail`` is False when the capture has no usable
    ring-out — then ``measured_rt60_s`` is NaN and ``within_tolerance`` is
    False (we refuse to extrapolate RT60 from noise; the fix is a re-render
    with a captured ring-out, see ``render`` ``ring_out_beats``).
    ``within_tolerance`` is ``sufficient_tail and
    abs(measured - declared) <= tolerance_s``.
    """
    return_track_id: str
    declared_rt60_s: float
    measured_rt60_s: float
    within_tolerance: bool
    tolerance_s: float
    measurement_method: str = "decay_tail"
    decay_db_used: float = 60.0
    tail_span_db: float = 0.0
    sufficient_tail: bool = True
    contributing_track_ids: tuple[str, ...] = ()
    conflicting_declarations: tuple[float, ...] = ()


@dataclass(frozen=True)
class BandContribution:
    """Per-band ranking of stem RMS contribution within a section window.

    ``contributors`` is ranked top-to-bottom; each entry is
    ``(track_id, fraction)`` where ``fraction`` is the stem's share of total
    stem RMS energy in ``band`` over the section window. Top-N only; the
    long tail is omitted (sums may not reach 1.0). Empty when no stem carried
    energy in the band. This is the steady-state companion to
    ``MasterOvershoot.attribution`` (which is tied to a peak event) — it
    answers "which stems own the low end in the chorus?".
    """
    band: str
    contributors: list[tuple[str, float]]


@dataclass(frozen=True)
class MaskingPair:
    """One ordered inter-stem masking relationship within a section window.

    ``masked_fraction`` (0..1) is the share of the maskee's *energized* tiles
    (frame × Bark-band cells where it carries non-trivial energy) in which the
    masker's spread excitation exceeds the maskee's own band power — i.e. where
    the masker likely renders the maskee inaudible. ``dominant_band`` is the
    musical-region label (``sub`` / ``lows`` / ``mud`` / ``body`` / ``presence``
    / ``brilliance`` / ``air``) carrying the most masked energy;
    ``dominant_region_hz`` is the precise Bark-band Hz edges under it.

    This is NEUTRAL EVIDENCE, not a judgement — masking is the mechanism of
    foregrounding, not a defect. Whether a given pair is a problem depends on
    per-section composer intent (which element is meant to win), which the
    holistic interpreter grades against recalled markdown intent. See
    ``.prawduct/artifacts/intent-architecture.md`` and ``masking-analyzer-goals.md``.

    Pre-fader capture caveat: only valid on mix-level-reconstructed stems (the
    M4L analyzer taps pre-fader). See ``masking-analyzer-spec.md`` §3.
    """
    masker_track_id: str
    maskee_track_id: str
    masked_fraction: float
    dominant_band: str
    dominant_region_hz: tuple[float, float]


@dataclass(frozen=True)
class BedMasking:
    """A maskee's masked fraction against the SUM of all other energized stems.

    Pairwise :class:`MaskingPair` cannot see *distributed* buildup — a part
    clear against every single other stem yet buried under the combined bed
    (the most common real-world low-mid clarity killer). This measures exactly
    that: the maskee vs the summed spread excitation of every other energized
    stem in the window. Same evidence-not-judgement framing as ``MaskingPair``.
    """
    maskee_track_id: str
    masked_fraction: float
    dominant_band: str
    dominant_region_hz: tuple[float, float]


@dataclass(frozen=True)
class PartTiming:
    """One part's onset-vs-grid timing measurement within a section window.

    The read-side counterpart to the ``feel`` pattern generator (which BAKES
    push/pull/swing into note timing at compose time): this RECOVERS the feel
    actually present in the captured audio, so the interpreter can ask "is this
    part's groove what the composer intended for this section?".

    All deviations are in **beats** (quarter = 1.0 in 4/4). Sign convention:
    ``mean_drift_beats`` < 0 means the part sits *ahead* of the grid
    (pushed / rushed); > 0 means *behind* (laid-back / dragged).
    ``drift_stdev_beats`` is the spread of those deviations — timing tightness
    (lower = more machine-tight; higher = looser/human). ``swing_ratio`` is the
    long:short ratio of off-beat 8th placement (1.0 = straight; ~1.5 light
    swing; ~2.0 triplet/hard swing); it is ``None`` when there are too few
    off-beat 8th onsets to measure. ``confidence`` (0..1) is low for parts with
    few onsets or loose, scattered timing (sustained pads with no clear
    transients, or a part on a cross-rhythm rather than the grid) — read it as
    "how much to trust these numbers".

    NEUTRAL MEASUREMENT, not a judgement — there is no "right" feel. A dragged
    snare may be a deliberate laid-back chorus or a sloppy take; only per-section
    composer intent distinguishes them, which the holistic interpreter grades
    against recalled markdown intent (see ``intent-architecture.md``). Parallel
    to masking's DSP↔intent split.

    Caveats carried into the interpreter (not corrected in the DSP): drift is
    measured against a constant-tempo grid within the window, and a heavily
    swung part reads as drift on a fine grid (swing and micro-timing interact);
    onset detection is reliable only on transient-rich parts (low ``confidence``
    flags the rest).
    """
    track_id: str
    onset_count: int
    mean_drift_beats: float
    drift_stdev_beats: float
    swing_ratio: float | None
    confidence: float


@dataclass(frozen=True)
class PartCrossRhythm:
    """One part's cross-rhythm / subdivision read within a section window.

    The read-side counterpart to the question C7's :class:`PartTiming` leaves
    open. ``PartTiming`` measures a part's onset deviation from a single
    straight grid; when a part plays *against* that grid (a 3-over-2 hemiola, a
    quintuplet run) C7 honestly reports low confidence ("not on the straight
    grid") but cannot say *what it is on*. ``PartCrossRhythm`` names the
    relationship: it recovers the part's own base pulse and expresses it as a
    rational subdivision of the known beat.

    ``pulse_ratio`` is the musician's-terms label — ``"3:2"`` / ``"4:3"`` /
    ``"5:4"`` (an N-against-M cross-rhythm: N onsets span M beats) or
    ``"3/beat"`` / ``"5/beat"`` (a plain N-per-beat subdivision / tuplet). It is
    ``None`` when no clean pulse was found (roll, rubato, swing-deferred, or
    low-confidence). ``against_meter`` is True when the pulse fights the song's
    binary grid (M>1, or a non-binary N ∈ {3,5,6,7}) — the signal the
    interpreter reads to ask "intended hemiola, or do you want them locked?".
    ``base_period_beats`` is the recovered pulse period P (beats);
    ``occupancy`` (0..1) is the fraction of expected pulse slots actually filled
    (a 3:2 that rests once a cycle reads ~0.82 — the holes are flagged without
    losing the ratio). ``confidence`` (0..1) scales with onset count and how
    tightly onsets sit on the recovered P-grid.

    ``verdict`` is the categorical read:
      * ``"cross-rhythm"``   — a named pulse that fights the meter (3:2, 5/beat)
      * ``"subdivision"``    — a plain binary subdivision on the grid (2/beat, 16ths)
      * ``"additive"``       — a repeating additive grouping (3+3+2, 2+2+3 = 7/8,
                               Balkan aksak): no single clean pulse, but the
                               irregular IOIs tile a fixed cell. ``grouping`` and
                               ``cycle_length_beats`` carry the decode (C8c).
      * ``"rubato"``         — the tempo itself is moving (monotonic IOI trend);
                               not a polyrhythm, flagged so it's never mislabeled
      * ``"roll"``           — density above the floor (buzz roll / tremolo); no ratio
      * ``"swing(see-timing)"`` — a triplet feel that C7's ``swing_ratio`` already
                               explains; deferred rather than double-reported
      * ``"low-confidence"`` — too few onsets, or no single clean pulse and no
                               clean grouping — honest, not a fabricated ratio

    ``grouping`` is the decoded additive cell as a tuple of sub-unit counts —
    ``(3, 3, 2)`` for a 3+3+2 / 8-unit bar, ``(2, 2, 3)`` for 7/8 — or ``None``
    when the verdict isn't ``"additive"``. When the part carries accents (a
    louder bar-downbeat), the tuple is rotated to start at the downbeat (so
    2+2+3 and 3+2+2 read distinctly); with equal-velocity onsets the bar
    downbeat is unknowable, so the tuple is the canonical (lexicographically-
    largest) rotation of the cyclic grouping. ``cycle_length_beats`` is the
    grouping cell's length in beats (sum of the grouping × the sub-unit), or
    ``None``. Both ``None`` for every non-additive verdict.

    NEUTRAL MEASUREMENT, not a judgement — a cross-rhythm is an authorial
    choice, not a defect. Only per-section composer intent says whether a given
    relationship is a wanted hemiola or an accidental clash; the holistic
    interpreter grades that against recalled markdown intent (see
    ``intent-architecture.md``). Parallel to masking's and timing's DSP↔intent
    split. Remaining limitations (rubato-within-window, mixed stems, sparse
    parts, accent-extraction timbre dependence) all resolve to an explicit
    low-confidence / rubato / roll verdict — never a confident wrong answer. See
    ``docs/polyrhythms.md`` §5.
    """
    track_id: str
    pulse_ratio: str | None
    against_meter: bool
    base_period_beats: float
    occupancy: float
    confidence: float
    verdict: str
    grouping: tuple[int, ...] | None = None
    cycle_length_beats: float | None = None


@dataclass(frozen=True)
class Phasing:
    """A two-part phasing relationship within a section window (Reich-style).

    The two-part counterpart to :class:`PartCrossRhythm`. Phasing is two parts
    playing the *same* figure at fractionally different tempi, so one slowly
    slides against the other (Steve Reich, "Piano Phase"). It is detected as a
    **monotonic drift** in the mean nearest-onset offset of B relative to A,
    sampled across the window — each part stays individually steady, but their
    relative alignment marches.

    ``track_a`` / ``track_b`` are the two surface IDs (B measured relative to A,
    so the sign of the drift is B-leads-negative / B-lags-positive).
    ``drift_beats_per_cycle`` is the rate that relative offset accumulates per
    analysis cycle (default a 4-beat window — see ``cross_rhythm.py``); its
    magnitude is how fast they're sliding apart, its sign which way.
    ``confidence`` (0..1) is high when the drift is cleanly monotonic (the
    offset-vs-time correlation is strong) — two locked parts drift ≈ 0 and never
    surface here.

    NEUTRAL MEASUREMENT — phasing is a compositional technique, not a defect;
    the interpreter grades it against intent. Caveat (``docs/polyrhythms.md``
    §3): nearest-onset matching wraps once the accumulated drift exceeds half a
    pulse period, so this reads the onset of a phase relationship, not its
    full multi-cycle trajectory.
    """
    track_a: str
    track_b: str
    drift_beats_per_cycle: float
    confidence: float


@dataclass(frozen=True)
class Polymeter:
    """A two-part polymeter relationship within a section window.

    Polymeter is two parts looping cells of DIFFERENT length at the *same*
    tempo (Meshuggah/Tool: a 4-beat riff under a 3-beat ostinato), so their
    downbeats realign only every lcm(cells) beats. Distinct from phasing (same
    cell, drifting tempo) and from a single part's additive grouping (one part,
    irregular cell). With equal-velocity hits two cells of different length
    produce identical onset *trains* — the cell length lives entirely in the
    **accent pattern** (``docs/polyrhythms.md`` §5 #2), recovered per part via
    accent autocorrelation (harmonic-safe: an accent series, unlike an onset
    train, is not self-similar at sub-multiples of its period).

    ``track_a`` / ``track_b`` are the two surface IDs; ``cycle_a_beats`` /
    ``cycle_b_beats`` are their recovered cell lengths (beats). ``realign_beats``
    is when the two downbeats next coincide (the rational lcm of the cells) — the
    period of the combined groove. ``confidence`` (0..1) reflects how cleanly
    each part's accent cycle resolved (the weaker of the two).

    NEUTRAL MEASUREMENT — polymeter is a compositional technique, not a defect;
    the interpreter grades it against intent. Caveat: cell detection needs an
    audible accent (equal-velocity parts surface nothing — correctly, the
    relationship is then unknowable from audio) and inherits the accent-
    extraction timbre dependence (``docs/polyrhythms.md`` §5 #6).
    """
    track_a: str
    track_b: str
    cycle_a_beats: float
    cycle_b_beats: float
    realign_beats: float
    confidence: float


@dataclass(frozen=True)
class SectionMetrics:
    """Per-surface loudness scoped to one named section window.

    Mirrors the top-level report's ``master`` / ``stems`` / ``returns``
    shape, but every loudness number is measured over only the audio that
    falls inside ``[start_beat, end_beat)`` — the half-open beat-domain
    window the handler derived from the song's ``sections`` table (named
    half-open ``[start_bar, end_bar)`` spans, not ``cue_points`` which are
    point markers). This is the read-side answer to "is the chorus
    actually louder than the verse?" — the LLM compares ``master.loudness``
    across sections without re-parsing bars.

    ``start_beat`` / ``end_beat`` are song-absolute beats (bar 1's downbeat
    == beat 0.0), the same domain as ``MasterOvershoot.start_beat`` and the
    capture's transport window. Windows are clamped to the captured extent;
    a section that falls entirely outside the capture is recorded in
    ``MixReport.skipped_analyses`` rather than emitted with empty metrics.
    """
    section_name: str
    start_beat: float
    end_beat: float
    master: StemMetrics
    stems: list[StemMetrics] = field(default_factory=list)
    returns: list[StemMetrics] = field(default_factory=list)
    # Per-band stem-dominance over the section window (one entry per BANDS
    # band). Answers "kick + bass dominate the chorus low end" per-section.
    attribution: list[BandContribution] = field(default_factory=list)
    # Inter-stem masking evidence (ranked top-N), populated only when masking
    # analysis is enabled and the section has >= 2 energized stems. ``masking``
    # is ordered pairs (A masks B); ``bed_masking`` is each maskee vs the summed
    # bed. Neutral evidence — the interpreter grades it against intent.
    masking: list[MaskingPair] = field(default_factory=list)
    bed_masking: list[BedMasking] = field(default_factory=list)
    # Per-part onset-vs-grid timing feel (one entry per transient-rich stem
    # above the confidence floor), populated only when timing analysis is
    # enabled. The read-side counterpart to the `feel` generator. Neutral
    # measurement — the interpreter grades it against intent.
    timing: list[PartTiming] = field(default_factory=list)
    # Per-part cross-rhythm / subdivision read (one entry per transient-rich
    # stem above the confidence floor), populated only when cross-rhythm
    # analysis is enabled. Names what grid a part is on when it fights the
    # straight grid C7 measures against (3:2, quintuplets, ...). Neutral
    # measurement — the interpreter grades it against intent.
    cross_rhythm: list[PartCrossRhythm] = field(default_factory=list)
    # Two-part phasing relationships (Reich-style drift), populated only when
    # cross-rhythm analysis is enabled and the section has >= 2 onset-bearing
    # parts that drift monotonically. Empty when parts are locked. Neutral
    # measurement — the interpreter grades it against intent.
    phasing: list[Phasing] = field(default_factory=list)
    # Two-part polymeter relationships (different cell lengths at one tempo),
    # populated only when cross-rhythm analysis is enabled and the section has
    # >= 2 accented parts whose recovered cells differ. Empty when parts share a
    # cell or carry no audible accent. Neutral — the interpreter grades intent.
    polymeter: list[Polymeter] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    """Structured intent-keyed observation from the analysis pass.

    The MVP populates findings keyed to DB-declared intent (track role,
    send target, declared decay). The LLM ranks/filters by ``kind`` +
    ``severity`` without parsing prose — per spike §6.

    ``db_reference`` is a free-form pointer back into the song DB
    (cue point, send id, track role) — purely for the LLM to cite when
    explaining the finding.
    """
    kind: str
    severity: Severity
    subject: str
    metric: str
    observed: float
    expected: float
    db_reference: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity={self.severity!r} must be one of "
                f"{_VALID_SEVERITIES}"
            )


@dataclass
class MixReport:
    """Top-level wire format. Mutable so ``analyze_mix`` can populate
    progressively without re-allocating; the ``to_json_dict()`` boundary
    is where it becomes pure data."""

    song_slug: str
    captures_dir: str
    captured_at: str
    analyzer_signature: str
    stems: list[StemMetrics]
    master: StemMetrics
    returns: list[StemMetrics] = field(default_factory=list)
    overshoots: list[MasterOvershoot] = field(default_factory=list)
    reverb_verifications: list[ReverbVerification] = field(default_factory=list)
    per_section: list[SectionMetrics] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    skipped_analyses: list[dict[str, Any]] = field(default_factory=list)
    # Capture-alignment audit (AUD-1C7K): per-surface trim applied before
    # analysis so the correction is visible, not silent. None when analysis ran
    # without an alignment pass (e.g. a directly-constructed report in a test).
    alignment: dict[str, Any] | None = None
    compare_to: dict[str, Any] | None = None
    schema_version: str = SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict.

        Explicit rather than ``dataclasses.asdict`` because (a) we want a
        stable field ORDER in the file (schema_version first, payload
        next, optional/empty fields last), and (b) tuples serialize as
        lists in JSON anyway — we make that explicit at the boundary so
        round-trip equality of typed objects works.
        """
        return {
            "schema_version": self.schema_version,
            "song_slug": self.song_slug,
            "captures_dir": self.captures_dir,
            "captured_at": self.captured_at,
            "analyzer_signature": self.analyzer_signature,
            "master": _stem_to_dict(self.master),
            "stems": [_stem_to_dict(s) for s in self.stems],
            "returns": [_stem_to_dict(r) for r in self.returns],
            "overshoots": [_overshoot_to_dict(o) for o in self.overshoots],
            "reverb_verifications": [
                _reverb_to_dict(r) for r in self.reverb_verifications
            ],
            "per_section": [_section_to_dict(s) for s in self.per_section],
            "findings": [_finding_to_dict(f) for f in self.findings],
            "skipped_analyses": list(self.skipped_analyses),
            "alignment": self.alignment,
            "compare_to": self.compare_to,
        }


def _stem_to_dict(s: StemMetrics) -> dict[str, Any]:
    return {
        "track_id": s.track_id,
        "surface_kind": s.surface_kind,
        "surface_name": s.surface_name,
        "loudness": {
            "lufs_i": s.loudness.lufs_i,
            "lufs_s_median": s.loudness.lufs_s_median,
            "lufs_m_peak": s.loudness.lufs_m_peak,
            "true_peak_dbtp": s.loudness.true_peak_dbtp,
        },
    }


def _section_to_dict(s: SectionMetrics) -> dict[str, Any]:
    return {
        "section_name": s.section_name,
        "start_beat": s.start_beat,
        "end_beat": s.end_beat,
        "master": _stem_to_dict(s.master),
        "stems": [_stem_to_dict(stem) for stem in s.stems],
        "returns": [_stem_to_dict(r) for r in s.returns],
        "attribution": [
            {
                "band": bc.band,
                "contributors": [list(pair) for pair in bc.contributors],
            }
            for bc in s.attribution
        ],
        "masking": [_masking_pair_to_dict(m) for m in s.masking],
        "bed_masking": [_bed_masking_to_dict(b) for b in s.bed_masking],
        "timing": [_part_timing_to_dict(t) for t in s.timing],
        "cross_rhythm": [_part_cross_rhythm_to_dict(c) for c in s.cross_rhythm],
        "phasing": [_phasing_to_dict(p) for p in s.phasing],
        "polymeter": [_polymeter_to_dict(p) for p in s.polymeter],
    }


def _phasing_to_dict(p: Phasing) -> dict[str, Any]:
    return {
        "track_a": p.track_a,
        "track_b": p.track_b,
        "drift_beats_per_cycle": p.drift_beats_per_cycle,
        "confidence": p.confidence,
    }


def _polymeter_to_dict(p: Polymeter) -> dict[str, Any]:
    return {
        "track_a": p.track_a,
        "track_b": p.track_b,
        "cycle_a_beats": p.cycle_a_beats,
        "cycle_b_beats": p.cycle_b_beats,
        "realign_beats": p.realign_beats,
        "confidence": p.confidence,
    }


def _part_cross_rhythm_to_dict(c: PartCrossRhythm) -> dict[str, Any]:
    return {
        "track_id": c.track_id,
        "pulse_ratio": c.pulse_ratio,
        "against_meter": c.against_meter,
        "base_period_beats": c.base_period_beats,
        "occupancy": c.occupancy,
        "confidence": c.confidence,
        "verdict": c.verdict,
        "grouping": list(c.grouping) if c.grouping is not None else None,
        "cycle_length_beats": c.cycle_length_beats,
    }


def _part_timing_to_dict(t: PartTiming) -> dict[str, Any]:
    return {
        "track_id": t.track_id,
        "onset_count": t.onset_count,
        "mean_drift_beats": t.mean_drift_beats,
        "drift_stdev_beats": t.drift_stdev_beats,
        "swing_ratio": t.swing_ratio,
        "confidence": t.confidence,
    }


def _masking_pair_to_dict(m: MaskingPair) -> dict[str, Any]:
    return {
        "masker_track_id": m.masker_track_id,
        "maskee_track_id": m.maskee_track_id,
        "masked_fraction": m.masked_fraction,
        "dominant_band": m.dominant_band,
        "dominant_region_hz": list(m.dominant_region_hz),
    }


def _bed_masking_to_dict(b: BedMasking) -> dict[str, Any]:
    return {
        "maskee_track_id": b.maskee_track_id,
        "masked_fraction": b.masked_fraction,
        "dominant_band": b.dominant_band,
        "dominant_region_hz": list(b.dominant_region_hz),
    }


def _overshoot_to_dict(o: MasterOvershoot) -> dict[str, Any]:
    return {
        "start_beat": o.start_beat,
        "end_beat": o.end_beat,
        "peak_dbtp": o.peak_dbtp,
        "dominant_band": o.dominant_band,
        "attribution": [list(pair) for pair in o.attribution],
    }


def _reverb_to_dict(r: ReverbVerification) -> dict[str, Any]:
    return {
        "return_track_id": r.return_track_id,
        "declared_rt60_s": r.declared_rt60_s,
        "measured_rt60_s": r.measured_rt60_s,
        "within_tolerance": r.within_tolerance,
        "tolerance_s": r.tolerance_s,
        "measurement_method": r.measurement_method,
        "decay_db_used": r.decay_db_used,
        "tail_span_db": r.tail_span_db,
        "sufficient_tail": r.sufficient_tail,
        "contributing_track_ids": list(r.contributing_track_ids),
        "conflicting_declarations": list(r.conflicting_declarations),
    }


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "kind": f.kind,
        "severity": f.severity,
        "subject": f.subject,
        "metric": f.metric,
        "observed": f.observed,
        "expected": f.expected,
        "db_reference": f.db_reference,
    }
