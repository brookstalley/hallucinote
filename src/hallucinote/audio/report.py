"""MixReport — the audio analysis pipeline's wire format.

Produced by ``analyze_mix(captures_dir)`` and serialized to
``songs/<slug>/analysis/<iso-ts>.json``. The MCP handler
(``ableton_analysis(action='analyze')``) is a thin wrapper that calls
``analyze_mix`` and writes this report.

Schema version is pinned in the report itself; downstream consumers
(the ``compare_to`` differ, dashboards) discriminate by
``schema_version`` rather than file path or git tag.

Two fields carry honesty/optional payloads:

  ``compare_to``         — baseline-diff payload (AUD-4W7K): per-surface
                            loudness deltas + significance flags against a
                            previous analysis JSON, populated when the
                            caller passes ``analyze_mix(compare_to=...)``
                            (see ``compare.diff_reports``). ``None`` when
                            no baseline was requested.
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

import math
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1"


def _finite_or_none(x: float | None) -> float | None:
    """Map a non-finite float (NaN / ±Inf) — or ``None`` — to ``None`` (→ JSON
    ``null``) so the whole report is valid JSON under
    ``json.dumps(allow_nan=False)`` (ARR-7M3D B1 backstop). Several fields carry a
    deliberate NaN SENTINEL — an insufficient-tail RT60 measurement
    (``ReverbVerification.measured_rt60_s``), an unmeasurable automation change
    (``EnvelopeVerification.before/after``) — that means "honestly unmeasured",
    which is exactly what JSON ``null`` conveys. Optional dB fields (a muted
    master's ``delivered_true_peak_dbtp`` = bus + ``-inf``) collapse the same way.
    Strict consumers (``JSON.parse``, the eval judge) reject the bare ``NaN``
    token, so this serializes the sentinel as ``null`` at the boundary rather than
    writing invalid JSON. ``None`` passes straight through (not yet supplied)."""
    if x is None:
        return None
    return None if not math.isfinite(x) else x

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
class TimbreMetrics:
    """Per-surface standing timbre descriptors (AUD-8T3K).

    A read-side lens — neutral measurement, never a grade (consistent with the
    energy lens). Each value is the MEDIAN over silence-gated STFT frames, so it
    describes the surface's timbre *while it is sounding*, not diluted by
    inter-onset silence. ``NaN`` (→ JSON ``null`` via ``_finite_or_none``) when
    no frame carries measurable energy (a silent/empty surface).

      ``spectral_centroid_hz``  — magnitude-weighted mean frequency. Brightness:
                                  distortion / an open filter pushes it up.
      ``spectral_flatness``     — geometric ÷ arithmetic mean over the 24 Bark
                                  band powers, 0..1. Tonal → ~0, white noise →
                                  ~1. The "noisiness" axis. Computed over Bark
                                  bands, NOT raw FFT bins (raw bins crush to ~0
                                  for any pitched material).
      ``spectral_rolloff_hz``   — frequency below which 85 % of the energy lies.
                                  A second brightness/edge cue, robust to a
                                  bright but low-energy top end.
      ``sharpness_acum``        — psychoacoustic sharpness (von Bismarck /
                                  Zwicker weighting over Bark specific
                                  loudness). The SHRILLNESS axis: a piercing
                                  lead reads higher than a warm pad at the same
                                  centroid. Scale-invariant; ordering and A/B
                                  deltas are the contract, the acum calibration
                                  is provisional. NaN default so hand-built
                                  fixtures and pre-sharpness baselines stay
                                  valid (the AUD-2N6K optional-field pattern).
    """
    spectral_centroid_hz: float
    spectral_flatness: float
    spectral_rolloff_hz: float
    sharpness_acum: float = float("nan")


@dataclass(frozen=True)
class StereoMetrics:
    """Per-surface stereo image descriptors (STR-4C8N).

    A read-side lens — neutral measurement, never a grade. ``NaN`` (→ JSON
    ``null`` via ``_finite_or_none``) when the window is silent or empty, so a
    silent surface never reads as a healthy image.

      ``correlation``       Pearson L/R, -1..+1. ``+1`` is bit-exact mono or a
                            perfectly correlated pair; ``0`` fully decorrelated;
                            negative means the channels partly cancel.
      ``mono_sum_loss_db``  Level LOST when summed to mono,
                            ``20·log10(rms(mono)/rms(stereo))``. ``0 dB`` = nothing
                            lost; ``≈-3 dB`` = two equal uncorrelated channels;
                            large negatives mean the part cancels itself on mono
                            playback. This is the actionable number — it says what
                            a listener loses, in units a composer thinks in.

    Both are BROADBAND: a part wide in the highs and mono in the lows averages to
    something unremarkable, and neither localises where the image lives.
    """
    correlation: float
    mono_sum_loss_db: float


@dataclass(frozen=True)
class WidthRealization:
    """A declared width control beside what the audio actually did (STR-4C8N).

    Neutral evidence, deliberately with NO severity and NO verdict — the same
    stance as ``masking``. A width control doing nothing may be an oversight or
    may be a part that simply has no side content to widen; a large mono loss may
    be exactly the image the composer wanted. Only the reader knows, so
    ``/mix-review`` grades this against declared intent and this row does not.

    The pairing is the point: a declared value with no measured effect is the
    silent failure nothing else in the toolchain can see, because catching it
    needs BOTH the declaration and the rendered audio.

      ``declared_display``    the control's value as authored ("165 %").
      ``mono_sum_loss_db``    what the surface loses summed to mono. Near ``0``
                              against an above-unity declared width is the
                              no-op signature.
      ``correlation``         the L/R correlation behind that loss.
    """
    surface_id: str
    surface_name: str
    device_name: str
    parameter_name: str
    declared_display: str
    correlation: float
    mono_sum_loss_db: float


@dataclass(frozen=True)
class StemMetrics:
    """One row per captured surface (audio track / return / master)."""
    track_id: str
    surface_kind: SurfaceKind
    surface_name: str
    loudness: LoudnessMetrics
    # Standing timbre descriptors (AUD-8T3K). Optional + default ``None`` so
    # hand-built fixtures and pre-timbre baselines stay valid (AUD-2N6K
    # optional-field pattern); ``analyze_mix`` always populates it.
    timbre: "TimbreMetrics | None" = None
    # Standing stereo descriptors (STR-4C8N). Same optional-field pattern, same
    # reason: pre-stereo baselines and hand-built fixtures stay valid.
    stereo: "StereoMetrics | None" = None

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
class EnvelopeVerification:
    """Realized-vs-declared verdict for one authored automation change (AUD-8H2M).

    One record per value-changing breakpoint of a declared envelope. ``metric``
    + ``before`` / ``after`` are the measured quantity across the change
    (``spectral_centroid_hz`` for a device-parameter flip, ``rms_db``
    for a send-level step — the return's STEREO RMS, the same quantity the
    silence gate reads, so a wide return is not judged on a half-cancelling mono
    sum — and ``master_rms_db`` / ``master_balance_db`` for the post-fader
    mixer_volume / mixer_pan kinds, measured on the master, the post-fader sum,
    per AUD-3F8M). ``realized`` says whether the authored
    change actually happened in the audio. ``measurable`` is False when the
    change can't be verified from this capture — a window too quiet to
    characterise, a mixer move whose predicted master effect is below the
    detectability floor (stem too diluted in the mix), or a master-chain-
    compressed window where the prediction model breaks down; in that case
    ``realized`` is meaningless and ``before``/``after`` are NaN. ``note`` is
    the human-readable explanation the interpreter (``/mix-review``) surfaces.

    **``device_parameter`` is verified on TWO probes — timbre OR image
    (STR-4C8N) — and ``probe`` names which one carried the verdict**
    (``"timbre"`` / ``"image"``, ``None`` for every other kind and for an
    unmeasurable window). Spectral centroid alone cannot see a comb/width
    effect, so a working flanger read as unrealized; accepting either probe
    fixes that, at the cost that ``metric``/``before``/``after`` are ALWAYS the
    centroid pair whichever probe fired. **On an image-carried verdict they are
    therefore a near-unchanged centroid sitting beside a ``realized: true``, and
    reading them as the evidence asserts a brightness change the audio does not
    support.** ``probe`` exists so that basis is machine-readable rather than
    recoverable only by string-matching ``note``.
    """
    target_surface_id: str
    target_kind: str
    parameter_path: str | None
    at_beat: float
    metric: str
    before: float
    after: float
    measurable: bool
    realized: bool
    note: str
    probe: str | None = None


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
class PartTransient:
    """One part's LOW-BAND (kick-class) hit SHAPE within a section window.

    The read-side answer to "is the kick a thud or a punch?" — measured from
    the hits the transient lens picks on the 40-150 Hz band of the stem (a
    kit stem's hats and snares don't register there). All values are MEDIANS
    across the window's hits.

      ``rise_ms``            — 10 -> 90 % of the low-band envelope on the
                               hit's FINAL approach to its peak (both
                               thresholds found scanning back from the peak, so
                               an earlier lobe cannot capture the 90 % point).
                               RELATIVE, never an absolute attack time: it sees
                               only 40-150 Hz, so a kick whose beater click
                               leads its low-band peak by tens of ms has an
                               attack this number never looks at, and it moves
                               with the hit band's edges (one real kit read
                               44 ms at 40-150 Hz and 15 ms at 50-150 Hz for
                               the same hits). Compare it across renders and
                               sections of ONE kit; not across kits, and not
                               against an absolute "punchy" threshold.
                               ``None`` when every hit's rise was censored
                               (see below).
      ``t20_ms``             — time after the peak for the low envelope to
                               fall 20 dB. The ring. ``None`` when every hit's
                               T20 was censored.
      ``censored_*_hits``    — hits whose estimator hit its own boundary (the
                               10 % point earlier than the 60 ms search window;
                               no 20 dB fall inside the 600 ms cap or before the
                               slice ended; an attack window with no 10 % point
                               to anchor it — a rise-censored hit is always
                               attack-censored — or cut by the slice end).
                               Excluded from the medians, counted here — a
                               boundary value is never reported as a
                               measurement, and no band level is read over a
                               window that could not be placed.
      ``attack_<band>_db``   — band RMS (dBFS, PRE-FADER stem as captured)
                               over the first 30 ms of the hit; the names carry
                               their edges: sub 40-100, low 100-250 (the thud
                               register), lowmid 250-600 (boxiness), click
                               2-6 kHz (the beater). These are NOT the
                               attribution bands (``sub_20_60`` …).
      ``click_minus_sub_db`` — the punch read (level-blind): how far the click
                               sits under the sub weight. Near 0 = a defined
                               attack; -15 or below = no click to speak of.
      ``low_minus_sub_db``   — the thud read (level-blind): > 0 means the
                               attack lives in the low-mids rather than the
                               sub — the "muffled / muddy with the bass" shape.

    Neutral measurement — the interpreter grades it against intent.
    """
    track_id: str
    hit_count: int
    rise_ms: float | None
    t20_ms: float | None
    censored_rise_hits: int
    censored_t20_hits: int
    censored_attack_hits: int
    attack_sub_40_100_db: float
    attack_low_100_250_db: float
    attack_lowmid_250_600_db: float
    attack_click_2k_6k_db: float
    click_minus_sub_db: float
    low_minus_sub_db: float


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
    # The DB ``sections`` row id this window came from (handler-supplied via
    # ``SectionWindow``). ``None`` when ``analyze_mix`` is driven by hand-built
    # fixtures that carry no DB identity. Lets a consumer correlate a finding
    # back to its ``sections`` row without a name/beat match (AUD-2N6K).
    section_id: str | None = None
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
    # Per-part low-band hit SHAPE (one entry per stem with enough kick-class
    # hits), populated only when transient analysis is enabled. The read-side
    # answer to "thud or punch?". Neutral — the interpreter grades it.
    transients: list[PartTransient] = field(default_factory=list)
    # The transient lens's failure channel: one structured skip per part that
    # produced no reading — the complete set is invalid_sample_rate /
    # window_too_short / no_low_band_energy / too_few_hits / all_hits_censored
    # (``transients.TransientWindowResult`` is the home) — so an empty
    # ``transients`` never hides WHY. Empty when the lens is off or every part
    # measured.
    transient_skips: list[dict] = field(default_factory=list)
    # Onset/event density (onsets-per-beat summed across stems) over the section
    # window — the second energy-realization correlate (ARR-7M3D), alongside
    # master.loudness.lufs_s_median. Level-blind. None when timing/cross-rhythm
    # analysis was disabled (the density pass shares their grid geometry), 0.0
    # when the window had no detected onsets. A RELATIVE read across sections:
    # only the ranking feeds the energy-realization Spearman ρ.
    onset_density: float | None = None


@dataclass(frozen=True)
class SectionEnergy:
    """A declared section in the ranked energy curve, keyed by its song-unique
    ``start_beat`` (ARR-7M3D).

    ``start_beat`` (NOT name) is the join key the energy-realization lens uses
    to pair declared intent with measured intensity: ``vary()`` /
    recapitulation produces repeated section names (two "Chorus" rows), so name
    alone mis-pairs. ``energy`` is the authored 0..1 ordinal intensity intent;
    NULL-energy sections are excluded upstream and never reach here.
    """
    start_beat: float
    name: str
    energy: float


@dataclass(frozen=True)
class EnergyInversion:
    """One ordered section pair where rendered intensity inverts declared intent
    (ARR-7M3D).

    Sections are identified by ``start_beat`` (the robust, song-unique key),
    NOT by name (repeated names mis-pair). The higher-declared-energy section
    measures LOWER intensity than the lower-declared-energy section
    (``measured_delta`` < 0). NEUTRAL EVIDENCE, not a verdict — a deliberate
    energy-drop (a stripped final chorus, the Nobile case) is authorship;
    ``/mix-review`` grades the inversion against recalled intent.
    """
    higher_energy_start_beat: float
    higher_energy_section: str   # display only; not the join key
    lower_energy_start_beat: float
    lower_energy_section: str    # display only; not the join key
    declared_energy_delta: float  # higher.energy - lower.energy (> 0 by construction)
    correlate: str                # "loudness" | "onset_density"
    measured_higher: float        # measured value of the higher-energy section
    measured_lower: float         # measured value of the lower-energy section
    measured_delta: float         # measured_higher - measured_lower (< 0 = inverted)


@dataclass(frozen=True)
class EnergyRealization:
    """Declared-energy-curve vs rendered-intensity read (ARR-7M3D).

    RULER, not stamp: reports ranked intensity vs intent + names inversions; it
    NEVER re-authors the curve, sets a target loudness, or grades pass/fail.
    Neutral evidence — ``/mix-review`` grades it against intent.

    ``correlate_rho`` is per-correlate Spearman ρ of (declared energy rank,
    measured intensity rank) over the energy-declared sections — or ``None``
    when ρ is undefined (a constant/tied measured correlate makes
    ``scipy.stats.spearmanr`` return ``nan``; the lens records ``None``, NEVER
    serializes ``nan``). The reason for each ``None`` is in ``skipped``.
    ``inversions`` is per-pair (well-defined even when ρ is ``None``).
    ``sections_ranked`` is the declared curve (excl. NULL energy), each carrying
    its ``start_beat`` so repeated-name sections stay distinct. ``skipped`` names
    every exclusion (NULL declared energy, missing/nan measured correlate,
    undefined ρ).
    """
    correlate_rho: dict[str, float | None]
    inversions: list[EnergyInversion]
    sections_ranked: list[SectionEnergy]
    skipped: list[str]


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
    is where it becomes pure data.

    Every path this report records — ``captures_dir`` and
    ``compare_to.baseline.ref`` — is a PORTABLE reference, not a machine
    path: song-relative (``captures/20260807T161909Z``) when it lives under
    the song dir, ``~``-collapsed otherwise. Resolve one with
    ``hallucinote.paths.resolve_portable_path(song_dir, ref)``, where
    ``song_dir`` is the parent of the directory the report was read from.
    That helper also passes an absolute path straight through, so reports
    written before AUD-PORTPATH (which recorded ``/Users/<account>/…``)
    still load and still resolve — the change is representational, not a
    schema break, which is why ``SCHEMA_VERSION`` did not move: bumping it
    would make every existing report un-diffable (``compare.ensure_comparable``
    refuses across versions) to no consumer's benefit."""

    song_slug: str
    # Portable reference (see the class docstring), NOT a machine path — this
    # file is git-tracked, and an absolute path here commits the author's home
    # directory into the repo.
    captures_dir: str
    captured_at: str
    analyzer_signature: str
    stems: list[StemMetrics]
    master: StemMetrics
    returns: list[StemMetrics] = field(default_factory=list)
    overshoots: list[MasterOvershoot] = field(default_factory=list)
    reverb_verifications: list[ReverbVerification] = field(default_factory=list)
    automation_verifications: list[EnvelopeVerification] = field(default_factory=list)
    # Declared width controls beside their measured effect (STR-4C8N). Empty
    # with a skipped_analyses entry when the song declares none — never
    # silently absent.
    width_realizations: list[WidthRealization] = field(default_factory=list)
    per_section: list[SectionMetrics] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    skipped_analyses: list[dict[str, Any]] = field(default_factory=list)
    # Declared-energy-curve vs rendered-intensity read (ARR-7M3D). None when
    # fewer than 2 energy-declared sections remain after exclusions (Spearman
    # needs >= 2 ranks) — recorded with a skipped_analyses entry, never a
    # fabricated ρ. A ruler: ranked intensity vs intent + inversions, no verdict.
    energy_realization: "EnergyRealization | None" = None
    # Capture-alignment audit (AUD-1C7K): per-surface trim applied before
    # analysis so the correction is visible, not silent. None when analysis ran
    # without an alignment pass (e.g. a directly-constructed report in a test).
    alignment: dict[str, Any] | None = None
    compare_to: dict[str, Any] | None = None
    # Song audit-log seq the analyzed capture reflects (copied from
    # manifest.db_seq — AUD-4W7K). The key ``compare.resolve_baseline``
    # matches when ``analyze_mix(compare_to=<seq>)`` resolves a baseline.
    # None for pre-tagging captures — such reports can still be baselines
    # via an explicit path, just not by seq.
    db_seq: int | None = None
    # The `master` block above is measured PRE master-fader: the HallucinoteAnalyzer
    # sits in the master DEVICE CHAIN, which Live processes before the master mixer
    # volume — so `master.loudness.true_peak_dbtp` is the mix BUS, not the delivered
    # output. When the master fader is known, these surface the post-fader DELIVERED
    # level so an agent never trims the fader expecting `master.true_peak` to move.
    # All None when the master fader volume wasn't supplied (then `master` = bus only).
    master_fader_volume: float | None = None       # normalized 0..1 (DB master volume)
    master_fader_db: float | None = None           # live_fader_db(master_fader_volume)
    # Post-fader true-peak = bus true-peak + master_fader_db (the master fader is a
    # linear gain after the captured chain). THIS is the delivery/clipping number.
    delivered_true_peak_dbtp: float | None = None
    schema_version: str = SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict.

        Explicit rather than ``dataclasses.asdict`` because (a) we want a
        stable field ORDER in the file (schema_version first, payload
        next, optional/empty fields last), and (b) tuples serialize as
        lists in JSON anyway — we make that explicit at the boundary so
        round-trip equality of typed objects works.
        """
        # Resolve masking track ids → display names at the JSON boundary from
        # the report's own surfaces (the single id→name source of truth).
        # Masking entries are produced by the pure-DSP ``masking`` module, which
        # has no surface-name map; rather than denormalize the name onto every
        # frozen ``MaskingPair`` / ``BedMasking``, the consumer-facing names are
        # joined here from ``master`` / ``stems`` / ``returns`` (AUD-2N6K).
        surface_names = {
            s.track_id: s.surface_name
            for s in (self.master, *self.stems, *self.returns)
        }
        return {
            "schema_version": self.schema_version,
            "song_slug": self.song_slug,
            "captures_dir": self.captures_dir,
            "captured_at": self.captured_at,
            "analyzer_signature": self.analyzer_signature,
            "db_seq": self.db_seq,
            "master": _stem_to_dict(self.master),
            # Master is PRE-fader bus (see field comments). Delivered = post-fader.
            # The two dB-domain fields go through _finite_or_none: a muted master
            # (volume 0) gives master_fader_db = -inf → delivered = -inf, which
            # must serialize as null, not crash json.dumps(allow_nan=False).
            "master_fader_volume": self.master_fader_volume,
            "master_fader_db": _finite_or_none(self.master_fader_db),
            "delivered_true_peak_dbtp": _finite_or_none(self.delivered_true_peak_dbtp),
            "stems": [_stem_to_dict(s) for s in self.stems],
            "returns": [_stem_to_dict(r) for r in self.returns],
            "overshoots": [_overshoot_to_dict(o) for o in self.overshoots],
            "reverb_verifications": [
                _reverb_to_dict(r) for r in self.reverb_verifications
            ],
            "automation_verifications": [
                _envelope_to_dict(e) for e in self.automation_verifications
            ],
            "width_realizations": [
                {
                    "surface_id": w.surface_id,
                    "surface_name": w.surface_name,
                    "device_name": w.device_name,
                    "parameter_name": w.parameter_name,
                    "declared_display": w.declared_display,
                    "correlation": _finite_or_none(w.correlation),
                    "mono_sum_loss_db": _finite_or_none(w.mono_sum_loss_db),
                }
                for w in self.width_realizations
            ],
            "per_section": [
                _section_to_dict(s, surface_names) for s in self.per_section
            ],
            "findings": [_finding_to_dict(f) for f in self.findings],
            "skipped_analyses": list(self.skipped_analyses),
            "energy_realization": (
                _energy_realization_to_dict(self.energy_realization)
                if self.energy_realization is not None
                else None
            ),
            "alignment": self.alignment,
            "compare_to": self.compare_to,
        }


def _stem_to_dict(s: StemMetrics) -> dict[str, Any]:
    return {
        "track_id": s.track_id,
        "surface_kind": s.surface_kind,
        "surface_name": s.surface_name,
        "loudness": {
            # BS.1770 returns -inf LUFS on pure silence; serialize the non-finite
            # "silent / no measurable loudness" sentinel as JSON null (B1) so the
            # report is valid JSON for strict consumers under allow_nan=False.
            "lufs_i": _finite_or_none(s.loudness.lufs_i),
            "lufs_s_median": _finite_or_none(s.loudness.lufs_s_median),
            "lufs_m_peak": _finite_or_none(s.loudness.lufs_m_peak),
            "true_peak_dbtp": _finite_or_none(s.loudness.true_peak_dbtp),
        },
        # Standing timbre (AUD-8T3K). None when no timbre was measured (hand-built
        # fixture); each value's NaN "silent" sentinel collapses to null like
        # loudness, so the object is valid JSON under allow_nan=False.
        "timbre": (
            {
                "spectral_centroid_hz": _finite_or_none(s.timbre.spectral_centroid_hz),
                "spectral_flatness": _finite_or_none(s.timbre.spectral_flatness),
                "spectral_rolloff_hz": _finite_or_none(s.timbre.spectral_rolloff_hz),
                "sharpness_acum": _finite_or_none(s.timbre.sharpness_acum),
            }
            if s.timbre is not None
            else None
        ),
        # Standing stereo image (STR-4C8N). None when not measured (hand-built
        # fixture); NaN "unmeasurable" collapses to null like the others.
        "stereo": (
            {
                "correlation": _finite_or_none(s.stereo.correlation),
                "mono_sum_loss_db": _finite_or_none(s.stereo.mono_sum_loss_db),
            }
            if s.stereo is not None
            else None
        ),
    }


def _section_to_dict(
    s: SectionMetrics, surface_names: dict[str, str]
) -> dict[str, Any]:
    return {
        "section_name": s.section_name,
        "section_id": s.section_id,
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
        "masking": [_masking_pair_to_dict(m, surface_names) for m in s.masking],
        "bed_masking": [
            _bed_masking_to_dict(b, surface_names) for b in s.bed_masking
        ],
        "timing": [_part_timing_to_dict(t) for t in s.timing],
        "cross_rhythm": [_part_cross_rhythm_to_dict(c) for c in s.cross_rhythm],
        "phasing": [_phasing_to_dict(p) for p in s.phasing],
        "polymeter": [_polymeter_to_dict(p) for p in s.polymeter],
        "transients": [_part_transient_to_dict(t) for t in s.transients],
        "transient_skips": [dict(sk) for sk in s.transient_skips],
        "onset_density": s.onset_density,
    }


def _part_transient_to_dict(t: PartTransient) -> dict[str, Any]:
    return {
        "track_id": t.track_id,
        "hit_count": t.hit_count,
        "rise_ms": _finite_or_none(t.rise_ms),
        "t20_ms": _finite_or_none(t.t20_ms),
        "censored_rise_hits": t.censored_rise_hits,
        "censored_t20_hits": t.censored_t20_hits,
        "censored_attack_hits": t.censored_attack_hits,
        "attack_sub_40_100_db": _finite_or_none(t.attack_sub_40_100_db),
        "attack_low_100_250_db": _finite_or_none(t.attack_low_100_250_db),
        "attack_lowmid_250_600_db": _finite_or_none(t.attack_lowmid_250_600_db),
        "attack_click_2k_6k_db": _finite_or_none(t.attack_click_2k_6k_db),
        "click_minus_sub_db": _finite_or_none(t.click_minus_sub_db),
        "low_minus_sub_db": _finite_or_none(t.low_minus_sub_db),
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


def _masking_pair_to_dict(
    m: MaskingPair, surface_names: dict[str, str]
) -> dict[str, Any]:
    # Resolved display names beside the raw ids (AUD-2N6K): the narrative form
    # ("Drums masks Bass") needs names inline so a consumer doesn't silently get
    # None joining against the stems list. ``None`` only if a masker/maskee id
    # isn't a captured surface (shouldn't happen — masking runs over the stems).
    return {
        "masker_track_id": m.masker_track_id,
        "maskee_track_id": m.maskee_track_id,
        "masker_surface_name": surface_names.get(m.masker_track_id),
        "maskee_surface_name": surface_names.get(m.maskee_track_id),
        "masked_fraction": m.masked_fraction,
        "dominant_band": m.dominant_band,
        "dominant_region_hz": list(m.dominant_region_hz),
    }


def _bed_masking_to_dict(
    b: BedMasking, surface_names: dict[str, str]
) -> dict[str, Any]:
    return {
        "maskee_track_id": b.maskee_track_id,
        "maskee_surface_name": surface_names.get(b.maskee_track_id),
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
        # NaN when sufficient_tail=False (no usable ring-out) — a deliberate
        # "honestly unmeasured" sentinel, serialized as JSON null (B1).
        "measured_rt60_s": _finite_or_none(r.measured_rt60_s),
        "within_tolerance": r.within_tolerance,
        "tolerance_s": r.tolerance_s,
        "measurement_method": r.measurement_method,
        "decay_db_used": r.decay_db_used,
        "tail_span_db": r.tail_span_db,
        "sufficient_tail": r.sufficient_tail,
        "contributing_track_ids": list(r.contributing_track_ids),
        "conflicting_declarations": list(r.conflicting_declarations),
    }


def _envelope_to_dict(e: EnvelopeVerification) -> dict[str, Any]:
    return {
        "target_surface_id": e.target_surface_id,
        "target_kind": e.target_kind,
        "parameter_path": e.parameter_path,
        "at_beat": e.at_beat,
        "metric": e.metric,
        # NaN when measurable=False (too-quiet / too-diluted / model
        # breakdown) — serialized as JSON null (B1), the "honestly
        # unmeasured" sentinel.
        "before": _finite_or_none(e.before),
        "after": _finite_or_none(e.after),
        "measurable": e.measurable,
        "realized": e.realized,
        "note": e.note,
        # Which probe carried the verdict (STR-4C8N). The whole point of the
        # field is that a consumer never has to string-match `note` to learn
        # it, and /mix-review reads this JSON rather than the dataclass — so
        # omitting it here would leave the capability existing in-process only.
        "probe": e.probe,
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


def _section_energy_to_dict(s: "SectionEnergy") -> dict[str, Any]:
    return {"start_beat": s.start_beat, "name": s.name, "energy": s.energy}


def _energy_inversion_to_dict(i: "EnergyInversion") -> dict[str, Any]:
    return {
        "higher_energy_start_beat": i.higher_energy_start_beat,
        "higher_energy_section": i.higher_energy_section,
        "lower_energy_start_beat": i.lower_energy_start_beat,
        "lower_energy_section": i.lower_energy_section,
        "declared_energy_delta": i.declared_energy_delta,
        "correlate": i.correlate,
        "measured_higher": i.measured_higher,
        "measured_lower": i.measured_lower,
        "measured_delta": i.measured_delta,
    }


def _energy_realization_to_dict(e: "EnergyRealization") -> dict[str, Any]:
    """Serialize the energy-realization read. ``correlate_rho`` values are
    ``None``-or-finite by construction (the lens records ``None`` for an
    undefined ρ, never ``nan``) — emitted as JSON ``null``, never ``NaN``."""
    return {
        "correlate_rho": dict(e.correlate_rho),
        "inversions": [_energy_inversion_to_dict(i) for i in e.inversions],
        "sections_ranked": [_section_energy_to_dict(s) for s in e.sections_ranked],
        "skipped": list(e.skipped),
    }
