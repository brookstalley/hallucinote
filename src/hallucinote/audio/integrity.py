"""Render integrity — is this captured audio DAMAGED?

Every other lens in the mix report asks a musical question: is this loud enough,
bright enough, wide enough, on the grid. This one asks the question that comes
BEFORE all of them — *did the capture survive?* — and it is upstream of the whole
report because a defect does not merely sit beside the musical readings, it
CORRUPTS them:

  * A click is a large sample derivative, and so is a musical attack. ``onsets.py``
    cannot tell them apart, so a click becomes a phantom onset and the timing and
    cross-rhythm lenses faithfully report a groove that was never played.
  * A dropout is a hole in the envelope, so the dynamics and energy lenses read it
    as a written level move.
  * A truncated capture is a decay that stops early, so the transient lens reads a
    shortened ring and the reverb lens a shorter tail.

Believe the rest of the report only after this lens says the audio is intact.

**What this lens will and will not say.** It measures DEFECTS, whose ground truth
is physical: a sample discontinuity, a run of samples pinned to full scale, a
buffer-sized hole, a non-zero mean. It never says how much of one is musically
acceptable — a snare could legitimately be smashed into the ceiling, and this
module has no opinion about that. It reports where the audio departs from what a
D/A converter can reproduce; ``/mix-review`` decides what that is worth.

**Six detectors**

  ``clip_events``        Runs of consecutive samples at or above full scale, per
                         channel, with the worst run, the clipped fraction and
                         where. Distinct from the master's delivered TRUE PEAK
                         (``loudness.py``): true peak asks whether the delivered
                         master overshoots between samples, and only the master
                         has one. This catches a STEM flat-topping on its way into
                         the master — sample-domain damage that is already baked
                         into the stem before the bus ever sees it.
  ``dc_offset``          Per-channel mean. It eats headroom on every subsequent
                         gain stage and it is the classic tell that a plugin is
                         misbehaving.
  ``dropouts``           Mid-signal holes: bit-exact zero runs, and abrupt
                         non-zero RMS collapses. Live's realtime capture drops
                         buffers under CPU load; this is the failure the detector
                         exists for.
  ``discontinuities``    Sample-to-sample derivative outliers — clicks and pops.
                         This project authors envelopes and clip boundaries
                         programmatically, which is exactly how a clip that starts
                         on a non-zero crossing gets made, so this detector is the
                         one most likely to find a real bug in the project's own
                         output rather than in Live.
  ``tail_level_dbfs``    Level over the final samples. Signal still running when
                         the file ends means the capture cut a decay.
  ``silent``             An entirely silent surface, reported as a fact — not as a
                         pile of NaNs that every downstream reader has to guess at.

**Honest limits.** The clip detector keys on a FLAT TOP — samples pinned to one
value near the surface's own ceiling — rather than on amplitude, because captured
stems are pre-fader float32 and a healthy part routinely peaks well above 0 dBFS.
The cost of that choice is at the other end: a limiter with any release at all
curves as it recovers, so an over that is squashed but not perfectly squared can
fall under the flatness test. This lens finds hard flat-topping, and reports
``peak_dbfs`` beside it so a reader can see how hard a surface is running even
when no run qualified.

A musical rest is a hole too. The zero-run detector requires
BIT-EXACT zeros bounded by an abrupt edge, which a decayed-into-a-rest passage
does not produce, but a hard-gated part rendered without reverb can — such a part
will read its rests as dropouts, and that is a false positive this lens cannot
resolve from the audio alone. The RMS-collapse detector reads a fixed frame grid,
so a hole shorter than one frame is diluted below the collapse threshold and only
the zero-run detector will see it. And the discontinuity count separates a splice from a
sound only by its SIZE, not by any test this module applies: a few isolated
regions is the splice signature, while hundreds mean the material steps
everywhere because it is distorted, bitcrushed or granular. Deciding which is a
defect requires the song's intent, which is the reader's, not this module's.

Neither of those is silent: what could not be
checked is named in ``checks_skipped``, which is also where a truncated event list
says so, so an empty list always means "clean", never "gave up".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

import numpy as np

_Event = TypeVar("_Event")

# --- detection constants -------------------------------------------------------
# Every one of these separates a defect from ordinary program material. They are
# set from the physics plus the shape of a Live capture, not from a listening
# campaign — that is what keeps this lens outside the analyzer freeze.

# Clipping is a FLAT TOP, and flatness is the whole test — not loudness.
#
# Captured stems are float32 and PRE-fader, so a perfectly healthy part routinely
# peaks well above 0 dBFS and the mixer brings it down afterwards; float has no
# ceiling to hit. That makes an absolute amplitude threshold useless here: a
# waveform peaking at +6 dBFS spends most of every cycle above 0.999 without ever
# being flat, so a `|x| >= 0.999` rule reports thousands of clip runs on undamaged
# audio. It fails in the worst possible direction, accusing the loudest healthy
# stem in the song.
#
# What a clipped run actually looks like is samples pinned to ONE value: an
# integer stage or a hard limiter returns bit-identical samples for the duration
# of the over. A band-limited waveform passing through its own peak never does —
# it is curving, so consecutive samples differ. So a run qualifies when its
# samples are equal to within `_FLAT_TOP_EPS` of the channel's own peak AND it
# sits near that peak, which makes the test work at any level and for clipping
# that happened inside a plugin before later gain.
#
# RELATIVE, not absolute: the flatness of a real waveform's crest scales with
# amplitude (a sine's crest falls off as A·d²/2 for angular step d), so a fixed
# tolerance turns into a false positive as material gets quieter. An absolute
# 1e-6 flagged a clean 20 Hz sine at -12 dBFS — which is where a sub, an 808
# tail or a low pad lives — the same failure as the amplitude rule it replaced,
# just at the other end of the range.
_FLAT_TOP_EPS = 1e-6

# The flat top has to be AT the ceiling the surface actually reached; a brief
# plateau partway down is a waveform shape, not an over. Measured against the
# CHANNEL's own peak, not the surface's: an asymmetric pan or M/S-processed stem
# routinely leaves one channel below the other, and a surface-wide ceiling hides
# a hard-clipped quiet channel behind its louder sibling entirely.
_FLAT_TOP_REL_TO_PEAK = 0.9

# Three CONSECUTIVE pinned samples: one sample at the peak is what every correctly
# normalized waveform does, two can be a sampling coincidence, three is held.
# Three is the long-standing convention in clip counters, and at 48 kHz it is
# 62 microseconds of held ceiling.
_MIN_CLIP_RUN = 3

# Below this peak amplitude a surface carries nothing at all: -120 dBFS is under
# the 16-bit LSB and under any real capture's noise floor, so anything above it is
# signal rather than the absence of it. Doubles as the edge of the SOUNDING REGION
# — the span between the first and last sample above it — which is what keeps the
# dropout detectors off the natural silence before the first note and after the
# last.
_SILENT_PEAK = 1e-6

# A fully-silent channel is -inf dBFS, which is neither valid JSON nor a useful
# reading. Floor it deep enough to read unambiguously as "nothing" while staying
# finite — the same move `stereo.py` makes for a fully-cancelling mono sum.
_SILENCE_FLOOR_DBFS = -180.0

# Keeps a log10 of an exactly-zero level finite (matches `transients.py`).
_DB_FLOOR = 1e-12

# The shortest hole worth calling a dropout. Live's audio buffer is 64-512 samples
# (1.3-10.7 ms at 48 kHz) and a dropped buffer is at least one of them; 5 ms sits
# inside that range while being far longer than any zero-crossing region a real
# waveform passes through.
_MIN_DROPOUT_S = 0.005

# The frame the non-zero collapse detector reads. One minimum-dropout long, so the
# shortest hole this lens claims to find fills a whole frame.
_DROPOUT_FRAME_S = _MIN_DROPOUT_S

# How far a frame must fall below BOTH its neighbours to be a hole rather than a
# musical decay. The flanking test is the physical part: a decay is monotonic, so
# it never recovers 40 dB in 5 ms, while a dropped buffer does exactly that on its
# far edge. 40 dB is the depth at which the material is gone rather than quiet.
_DROPOUT_COLLAPSE_DB = 40.0

# A dropout cuts the waveform wherever it happened to be, so its LEADING edge is
# a hard step; a musical rest is approached through a decay. Requiring an edge at
# 1% of the surface peak (-40 dB relative) is what separates the two.
#
# The leading edge specifically, not either edge. A gap that merely ENDS in an
# attack is ordinary music — every rest is followed by the next note — so
# accepting either edge turned every rest into a dropout: 15 false dropouts for
# 16 hits on a percussion part. In Live this is not hypothetical, because a track
# outputs bit-exact zeros whenever nothing is sounding, so any part that rests
# for a section hits it. What makes a dropout a dropout is that the audio was
# CUT while it was still running.
_DROPOUT_EDGE_REL = 0.01

# Discontinuity threshold, expressed against the material rather than as an
# absolute: a robust sigma of the sample-to-sample derivative (MAD scaled by the
# Gaussian consistency constant, so the very outliers being hunted cannot inflate
# it). 12 sigma is far above what a band-limited waveform reaches — a pure sine's
# largest derivative is about 1 sigma, broadband noise about 4 over a second — and
# far below the derivative of a splice.
_DISCONTINUITY_SIGMA = 12.0
_MAD_TO_SIGMA = 1.4826

# Floor under that threshold, relative to the LOCAL peak. Sparse material is
# mostly silence, so its median derivative is ~0 and the sigma test would degrade
# into reporting the noise floor's every wiggle. 2% of the local peak (-34 dB) is
# the smallest step worth calling a pop.
_DISCONTINUITY_FLOOR_REL = 0.02

# The threshold is computed per WINDOW, not once per surface, and that is the
# whole design of this detector rather than a refinement of it.
#
# Music is strongly non-stationary: a surface with 60 dB of envelope range has a
# median derivative set by its quiet majority, so every loud moment reads as a
# 100-sigma outlier and a single global sigma reports tens of thousands of
# phantom clicks on any percussive or broadband part. Measured on synthetic
# drum-like material: 32,752 "discontinuities" against 31 real onsets.
#
# Locally the statistic behaves: within 25 ms a part is roughly stationary, so
# steady broadband content produces no outliers at all (its steps are all alike,
# which is exactly what a robust sigma is for), while a splice or a clip
# boundary remains an outlier against its own neighbourhood. 25 ms is long
# enough that one bad sample cannot move the median of ~1200 and short enough to
# track an envelope.
_DISCONTINUITY_WINDOW_S = 0.025

# How far above its local threshold a step must sit to be reported EVEN WHEN it
# falls inside the onset guard.
#
# The guard exists because a percussive attack is a burst of large derivatives
# and would otherwise be reported as a hundred clicks. But the onsets are
# detected from the same audio, so a click loud enough to register as a
# spectral-flux event manufactures the very onset that then hides it — a planted
# splice was located exactly and then suppressed by an onset 224 samples away.
# A defect that conceals itself in proportion to its own severity is the worst
# possible failure for this detector.
#
# A musical attack is band-limited: however sharp, it cannot move by an
# arbitrary fraction of full scale between two adjacent samples. A step this far
# above what the surrounding material produces has no musical explanation, so
# the guard does not apply to it.
_ONSET_GUARD_EXEMPTION = 4.0

# One reported event per window per channel, not one per stepping sample.
#
# Step-rich audio does not arrive as isolated samples: on a finished song the
# vocal produced 42,578 flagged steps inside 660 windows — about 65 per window,
# which is very nearly every sample in those spans. That is one REGION of
# step-rich material, not 65 defects, and counting it per sample turns a
# processed passage into a catastrophe in the report. Collapsing to the largest
# step per window makes the count mean "how many spans of this surface step",
# which is the number a reader can act on.
_DISCONTINUITY_ONE_PER_WINDOW = True

# Above this share of windows carrying a flagged step, the surface is not damaged
# — it is MADE of steps, and the per-event reading stops meaning anything.
#
# A defect is rare and local: a splice, a dropped buffer, a clip boundary. What
# distortion, bitcrushing, hard sync and granular processing produce is
# pervasive — genuine sample-to-sample steps everywhere, because that is the
# sound. No per-event test can separate one authored step from one accidental
# one; the DISTRIBUTION separates them, and it is the only thing that can.
#
# Measured on a finished song: six surfaces sat at 0-18 events, and three
# heavily-processed ones ran to 8,700-42,600 — the vocal at 296 events per
# detected onset. Reporting those as clicks would tell the author their vocal is
# destroyed, which is the same false accusation this lens family has already had
# to fix twice. Naming the material instead is the honest reading.
_DISCONTINUITY_PERVASIVE_FRAC = 0.20

# How close to a known onset a discontinuity is presumed to BE that onset. Two
# things have to fit inside it: the spectral-flux front end that supplies the
# onsets reads a 512-sample hop (10.7 ms at 48 kHz), so the reported position
# carries about that much jitter; and an attack is a BURST, not one sample — a
# percussive transient's broadband body runs on for tens of milliseconds, every
# sample of it a large derivative. 25 ms covers both. The cost is real and is the
# right trade: a genuine click inside 25 ms of an attack is invisible here, which
# is also where it is least audible.
_ONSET_GUARD_S = 0.025

# The window read at the very end of the capture. 10 ms is long enough for a
# stable RMS at any musical pitch and short enough that a decay which ended
# normally has already reached the noise floor across all of it.
_TAIL_WINDOW_S = 0.010


@dataclass(frozen=True)
class ClipEvent:
    """One run of consecutive samples pinned at or above full scale."""

    start_sample: int
    length_samples: int
    channel: int


@dataclass(frozen=True)
class Dropout:
    """One mid-signal hole. ``kind`` is ``"zero_run"`` (bit-exact digital silence)
    or ``"rms_collapse"`` (level gone but samples still non-zero)."""

    start_sample: int
    length_samples: int
    kind: str


@dataclass(frozen=True)
class Discontinuity:
    """One sample-to-sample step too large for the material. ``sample`` is the
    first sample AFTER the jump; ``magnitude`` is the size of the step in
    normalized amplitude."""

    sample: int
    channel: int
    magnitude: float


@dataclass(frozen=True)
class SurfaceIntegrity:
    """Whole-capture defect readings for one surface.

    ``checks_skipped`` carries one ``"token: detail"`` string per check that could
    not run or could not report everything it found, so an empty event list always
    means the detector looked and found nothing. The tokens are
    ``empty_surface``, ``silent_surface``, ``discontinuities_unsuppressed``,
    ``discontinuities_pervasive``, ``dropouts_window_too_short``,
    ``tail_window_too_short``, and
    ``{clip_events,dropouts,discontinuities}_truncated``.
    """

    silent: bool
    peak_dbfs: float
    clip_events: list[ClipEvent]
    clipped_sample_fraction: float
    worst_clip_run_samples: int
    dc_offset: tuple[float, float]
    dc_offset_dbfs: float
    dropouts: list[Dropout]
    discontinuities: list[Discontinuity]
    tail_level_dbfs: float | None
    checks_skipped: list[str]
    # Which surface this row describes. The measurement itself needs only audio,
    # so the caller supplies the identity — but a row that cannot say what it
    # measured is unusable in a report that carries one per surface, and the
    # empty default keeps hand-built fixtures valid.
    track_id: str = ""


def measure_integrity(
    audio: np.ndarray,
    *,
    sample_rate: int,
    onset_samples: Sequence[int] | np.ndarray | None = None,
    max_events: int = 32,
    track_id: str = "",
) -> SurfaceIntegrity:
    """Measure render defects over one whole captured surface.

    Args:
        audio: ``(n_samples, 2)`` float — every captured surface is float32 stereo
            (``audio/io.py`` ``load_capture``).
        sample_rate: samples per second; the time-based detectors are all defined
            in seconds and converted here.
        onset_samples: known musical attacks, in samples. A real attack is a large
            derivative too, so a discontinuity within ``_ONSET_GUARD_S`` of one is
            not reported. Pass ``None`` and every attack is reported as a
            discontinuity — which the result says, in ``checks_skipped``, rather
            than leaving the caller to discover it.
        max_events: per-list cap. A badly clipped stem must not return a million
            rows; the counts and the worst-case readings are still computed over
            everything found, and the truncation is named in ``checks_skipped``.

    Raises:
        ValueError: the array is not stereo, or the sample rate is not positive.
            Guessing either would produce a confident reading of the wrong thing.
    """
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError(
            f"measure_integrity expects a stereo (n_samples, 2) array, got "
            f"shape={audio.shape!r} — every captured surface is float32 stereo "
            f"(see audio/io.py load_capture)."
        )
    if sample_rate <= 0:
        raise ValueError(
            f"measure_integrity needs a positive sample rate, got {sample_rate} — "
            f"every detector's window is defined in seconds."
        )

    data = audio.astype(np.float64, copy=False)
    n_samples = int(data.shape[0])
    cap = max(0, int(max_events))

    if n_samples == 0:
        return _nothing_to_measure(
            "empty_surface: the surface has no samples", track_id=track_id
        )

    abs_data = np.abs(data)
    peak = float(np.max(abs_data))
    peak_dbfs = _amplitude_dbfs(peak)
    if peak <= _SILENT_PEAK:
        return _nothing_to_measure(
            f"silent_surface: peak {peak_dbfs:.1f} dBFS is below the "
            f"{_amplitude_dbfs(_SILENT_PEAK):.0f} dBFS signal floor, so there is "
            f"no audio to find defects in",
            track_id=track_id,
            peak_dbfs=peak_dbfs,
            dc_offset=(float(np.mean(data[:, 0])), float(np.mean(data[:, 1]))),
        )

    skipped: list[str] = []

    # --- clipping ---------------------------------------------------------------
    clip_events: list[ClipEvent] = []
    clipped_samples = 0
    worst_clip_run = 0
    for channel in range(2):
        column = abs_data[:, channel]
        channel_peak = float(np.max(column))
        if channel_peak <= _SILENT_PEAK:
            continue
        # Pinned = this sample is level with the next one, near THIS channel's
        # own ceiling. A run of pinned samples is a flat top; a waveform curving
        # through its peak breaks the equality on the first sample.
        near_ceiling = column >= channel_peak * _FLAT_TOP_REL_TO_PEAK
        level_with_next = np.abs(np.diff(column)) <= _FLAT_TOP_EPS * channel_peak
        pinned = np.zeros(column.shape[0], dtype=bool)
        pinned[:-1] = near_ceiling[:-1] & level_with_next
        starts, lengths = _true_runs(pinned)
        # A run of N pinned transitions spans N+1 samples.
        lengths = lengths + 1
        keep = lengths >= _MIN_CLIP_RUN
        starts, lengths = starts[keep], lengths[keep]
        if starts.size == 0:
            continue
        clipped_samples += int(lengths.sum())
        worst_clip_run = max(worst_clip_run, int(lengths.max()))
        clip_events.extend(
            ClipEvent(
                start_sample=int(start),
                length_samples=int(length),
                channel=channel,
            )
            for start, length in zip(starts, lengths)
        )
    # Both channels contribute, so the denominator is every sample in the surface.
    clipped_sample_fraction = clipped_samples / float(n_samples * 2)
    clip_events.sort(key=lambda e: (e.start_sample, e.channel))
    clip_events = _truncate(clip_events, cap, "clip_events", skipped)

    # --- DC offset --------------------------------------------------------------
    dc_left = float(np.mean(data[:, 0]))
    dc_right = float(np.mean(data[:, 1]))
    dc_offset = (dc_left, dc_right)
    dc_offset_dbfs = _amplitude_dbfs(max(abs(dc_left), abs(dc_right)))

    # The span the audio actually sounds over. Everything outside it is the lead-in
    # and the release of the capture region, which are silence by design.
    sounding = np.flatnonzero(np.max(abs_data, axis=1) > _SILENT_PEAK)
    first_sound, last_sound = int(sounding[0]), int(sounding[-1])

    # --- dropouts ---------------------------------------------------------------
    dropouts = _find_zero_runs(
        data, abs_data, sample_rate, peak, first_sound, last_sound
    )
    collapses, collapse_skip = _find_rms_collapses(
        data, sample_rate, first_sound, last_sound, dropouts
    )
    if collapse_skip is not None:
        skipped.append(collapse_skip)
    dropouts.extend(collapses)
    dropouts.sort(key=lambda d: d.start_sample)
    dropouts = _truncate(dropouts, cap, "dropouts", skipped)

    # --- discontinuities --------------------------------------------------------
    # An EMPTY onset list suppresses nothing, exactly like no list at all, and it
    # is what the real caller produces when the onset front end finds nothing —
    # so the token has to cover both or it is unreachable in production and the
    # degraded reading arrives looking authoritative. The partial case is the
    # nastier one and cannot be detected from here: a surface where the front end
    # finds 5 onsets out of 200 notes gets 195 unsuppressed attacks and no token,
    # which is why the caller states the onset count it supplied.
    if onset_samples is None or len(onset_samples) == 0:
        skipped.append(
            "discontinuities_unsuppressed: no onsets supplied, so every musical "
            "attack is reported as a discontinuity"
        )
    discontinuities = _find_discontinuities(data, peak, sample_rate, onset_samples)
    discontinuities = _collapse_per_window(discontinuities, sample_rate)
    discontinuities, pervasive = _drop_if_pervasive(
        discontinuities, data.shape[0], sample_rate
    )
    if pervasive is not None:
        skipped.append(pervasive)
    discontinuities = _truncate(discontinuities, cap, "discontinuities", skipped)

    # --- truncated decay --------------------------------------------------------
    tail_n = int(round(_TAIL_WINDOW_S * sample_rate))
    if tail_n < 1 or n_samples < tail_n:
        tail_level_dbfs = None
        skipped.append(
            f"tail_window_too_short: the surface is {n_samples} samples, shorter "
            f"than the {tail_n}-sample tail window"
        )
    else:
        tail_level_dbfs = _rms_dbfs(data[-tail_n:, :])

    return SurfaceIntegrity(
        track_id=track_id,
        silent=False,
        peak_dbfs=peak_dbfs,
        clip_events=clip_events,
        clipped_sample_fraction=clipped_sample_fraction,
        worst_clip_run_samples=worst_clip_run,
        dc_offset=dc_offset,
        dc_offset_dbfs=dc_offset_dbfs,
        dropouts=dropouts,
        discontinuities=discontinuities,
        tail_level_dbfs=tail_level_dbfs,
        checks_skipped=skipped,
    )


def _nothing_to_measure(
    reason: str,
    *,
    track_id: str = "",
    peak_dbfs: float = _SILENCE_FLOOR_DBFS,
    dc_offset: tuple[float, float] = (0.0, 0.0),
) -> SurfaceIntegrity:
    """The result for a surface with no audio in it.

    Silence is a FACT about the render, not an unmeasurable window, so the fields
    that ARE defined carry their real values — the peak and the mean of a
    below-the-floor surface are still numbers — and the detectors that need signal
    are named as skipped rather than returned as a zero that reads like a clean
    bill of health.
    """
    return SurfaceIntegrity(
        track_id=track_id,
        silent=True,
        peak_dbfs=peak_dbfs,
        clip_events=[],
        clipped_sample_fraction=0.0,
        worst_clip_run_samples=0,
        dc_offset=dc_offset,
        dc_offset_dbfs=_amplitude_dbfs(max(abs(dc_offset[0]), abs(dc_offset[1]))),
        dropouts=[],
        discontinuities=[],
        tail_level_dbfs=None,
        checks_skipped=[reason],
    )


def _amplitude_dbfs(amplitude: float) -> float:
    """Normalized amplitude to dBFS, floored so silence stays finite."""
    if amplitude <= 0.0:
        return _SILENCE_FLOOR_DBFS
    return max(_SILENCE_FLOOR_DBFS, 20.0 * float(np.log10(amplitude)))


def _rms_dbfs(block: np.ndarray) -> float:
    """RMS of a block (any shape) in dBFS, floored the same way."""
    if block.size == 0:
        return _SILENCE_FLOOR_DBFS
    rms = float(np.sqrt(np.mean(block * block)))
    return max(_SILENCE_FLOOR_DBFS, 20.0 * float(np.log10(rms + _DB_FLOOR)))


def _true_runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Start index and length of every run of ``True`` in a 1-D boolean mask.

    Vectorized rather than looped because the caller may be holding a stem that is
    clipped for its whole length: the counts have to come off the arrays before any
    per-event object is built.
    """
    if mask.size == 0:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1]).astype(np.int64)
    starts = edges[0::2]
    ends = edges[1::2]
    return starts, ends - starts


def _truncate(
    events: list[_Event], cap: int, name: str, skipped: list[str]
) -> list[_Event]:
    """Apply the per-list cap, recording what was dropped."""
    if len(events) <= cap:
        return events
    skipped.append(
        f"{name}_truncated: {len(events)} found, {cap} reported"
    )
    return events[:cap]


def _find_zero_runs(
    data: np.ndarray,
    abs_data: np.ndarray,
    sample_rate: int,
    peak: float,
    first_sound: int,
    last_sound: int,
) -> list[Dropout]:
    """Bit-exact digital silence in the middle of sounding material.

    Three conditions together are what make this a dropout rather than a rest: the
    samples are exactly zero in BOTH channels (a decayed tail is small, not zero),
    the run is at least one audio buffer long, and at least one of its edges is a
    hard step — the waveform was cut wherever it happened to be, which is not how a
    part arrives at a rest.
    """
    min_len = max(1, int(round(_MIN_DROPOUT_S * sample_rate)))
    silent_mask = np.max(abs_data, axis=1) == 0.0
    # Only the sounding region: the lead-in before the first note and the release
    # after the last are silence by design, not damage.
    silent_mask[: first_sound + 1] = False
    silent_mask[last_sound:] = False

    starts, lengths = _true_runs(silent_mask)
    keep = lengths >= min_len
    starts, lengths = starts[keep], lengths[keep]

    edge_floor = _DROPOUT_EDGE_REL * peak
    dropouts: list[Dropout] = []
    for start, length in zip(starts, lengths):
        start, length = int(start), int(length)
        before = float(np.max(np.abs(data[start - 1, :]))) if start > 0 else 0.0
        if before < edge_floor:
            continue
        dropouts.append(
            Dropout(start_sample=start, length_samples=length, kind="zero_run")
        )
    return dropouts


def _find_rms_collapses(
    data: np.ndarray,
    sample_rate: int,
    first_sound: int,
    last_sound: int,
    zero_runs: list[Dropout],
) -> tuple[list[Dropout], str | None]:
    """Holes whose samples are non-zero but whose level is gone.

    A frame is a collapse when it sits ``_DROPOUT_COLLAPSE_DB`` below the frame
    immediately BEFORE the run, and the signal then climbs back above that same
    level. The sliding left flank is what makes it work on real material: a decay
    also falls that far eventually, but it falls gradually — each frame is only
    slightly below the one before it — so a decay never trips a threshold measured
    against its own immediate predecessor, while a cut does at once. Requiring the
    recovery is the other half: only something that removed the signal and then
    restored it qualifies. Frames
    already claimed by a zero run are left alone — the same hole reported twice
    under two names is not two defects.
    """
    frame = int(round(_DROPOUT_FRAME_S * sample_rate))
    if frame < 1:
        return [], (
            f"dropouts_window_too_short: {sample_rate} Hz gives a "
            f"{_DROPOUT_FRAME_S * 1000:.0f} ms frame of under one sample"
        )
    region = data[first_sound : last_sound + 1, :]
    n_frames = region.shape[0] // frame
    if n_frames < 3:
        # Two flanks plus a hole is the minimum shape the test can even express.
        return [], (
            f"dropouts_window_too_short: the sounding region holds {n_frames} "
            f"frames of {frame} samples, fewer than the 3 a flanked hole needs"
        )

    frames = region[: n_frames * frame, :].reshape(n_frames, frame * 2)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    db = 20.0 * np.log10(rms + _DB_FLOOR)

    claimed = np.zeros(n_frames, dtype=bool)
    for run in zero_runs:
        lo = (run.start_sample - first_sound) // frame
        hi = (run.start_sample + run.length_samples - 1 - first_sound) // frame
        claimed[max(0, lo) : min(n_frames, hi + 1)] = True

    collapses: list[Dropout] = []
    index = 1
    while index < n_frames - 1:
        floor_db = db[index - 1] - _DROPOUT_COLLAPSE_DB
        if db[index] >= floor_db:
            index += 1
            continue
        end = index
        while end < n_frames and db[end] < floor_db:
            end += 1
        # `end` is the first frame back above the floor. Running off the array
        # instead means the level never recovered, which is a decay or the end of
        # the take, not a hole.
        if end < n_frames and not claimed[index:end].any():
            collapses.append(
                Dropout(
                    start_sample=first_sound + index * frame,
                    length_samples=(end - index) * frame,
                    kind="rms_collapse",
                )
            )
        # Resume AT the recovery frame, not past it: it is the flank of whatever
        # comes next, and skipping it would hide a second hole right behind the
        # first — which is what a stuttering buffer looks like.
        index = end
    return collapses, None


def _local_step_threshold(
    deriv: np.ndarray, amplitude: np.ndarray, sample_rate: int
) -> np.ndarray:
    """A per-sample step threshold from each sample's own neighbourhood.

    Returns an array the length of ``deriv``. Within a window the threshold is
    the larger of a robust sigma of the local derivative and a fraction of the
    local amplitude — the first is what makes steady broadband material produce
    no outliers, the second is what stops near-silence reporting its own noise
    floor.

    The window's statistics are taken over a span CENTRED on it (the window plus
    its two neighbours) so a transient landing on a window boundary is judged
    against the material around it rather than against whichever half it fell in.
    """
    n = deriv.size
    win = max(1, int(round(_DISCONTINUITY_WINDOW_S * sample_rate)))
    n_win = int(np.ceil(n / win))
    pad = n_win * win - n
    d_pad = np.pad(deriv, (0, pad), mode="edge").reshape(n_win, win)
    a_pad = np.pad(amplitude[: n], (0, pad + (n - amplitude[:n].size)), mode="edge")
    a_pad = a_pad[: n_win * win].reshape(n_win, win)

    med = np.median(d_pad, axis=1)
    loc_peak = np.max(a_pad, axis=1)
    # Widen to the neighbouring windows: a step exactly on a boundary otherwise
    # sees only the quieter side and is judged too harshly.
    def _widen(v: np.ndarray) -> np.ndarray:
        if v.size == 1:
            return v
        stacked = np.stack(
            [np.roll(v, 1), v, np.roll(v, -1)]
        )
        stacked[0, 0] = v[0]
        stacked[2, -1] = v[-1]
        return np.max(stacked, axis=0)

    sigma = _MAD_TO_SIGMA * _widen(med)
    floor = _DISCONTINUITY_FLOOR_REL * _widen(loc_peak)
    per_window = np.maximum(_DISCONTINUITY_SIGMA * sigma, floor)
    return np.repeat(per_window, win)[:n]


def _collapse_per_window(
    found: list[Discontinuity], sample_rate: int
) -> list[Discontinuity]:
    """Keep the largest step per window per channel.

    A burst of step-rich material flags nearly every sample in its span; those
    are one region, not one defect each. See ``_DISCONTINUITY_ONE_PER_WINDOW``.
    """
    if not found or not _DISCONTINUITY_ONE_PER_WINDOW:
        return found
    win = max(1, int(round(_DISCONTINUITY_WINDOW_S * sample_rate)))
    best: dict[tuple[int, int], Discontinuity] = {}
    for d in found:
        key = (d.channel, d.sample // win)
        if key not in best or d.magnitude > best[key].magnitude:
            best[key] = d
    return sorted(best.values(), key=lambda d: (d.sample, d.channel))


def _drop_if_pervasive(
    found: list[Discontinuity], n_samples: int, sample_rate: int
) -> tuple[list[Discontinuity], str | None]:
    """Characterise a step-rich surface instead of listing its every step.

    Returns the events unchanged, or an empty list plus a skip token when the
    steps are spread over enough of the surface that they describe its material
    rather than a defect in it. See ``_DISCONTINUITY_PERVASIVE_FRAC`` for why the
    distribution is the only thing that can make this call.
    """
    if not found:
        return found, None
    win = max(1, int(round(_DISCONTINUITY_WINDOW_S * sample_rate)))
    total = max(1, int(np.ceil(n_samples / win)))
    touched = len({d.sample // win for d in found})
    share = touched / total
    if share < _DISCONTINUITY_PERVASIVE_FRAC:
        return found, None
    return [], (
        f"discontinuities_pervasive: steps appear in {share:.0%} of this "
        f"surface's {_DISCONTINUITY_WINDOW_S * 1000:.0f} ms windows, so they "
        f"characterise the material (distortion, bitcrushing, granular "
        f"processing) rather than marking a defect in it"
    )


def _find_discontinuities(
    data: np.ndarray,
    peak: float,
    sample_rate: int,
    onset_samples: Sequence[int] | np.ndarray | None,
) -> list[Discontinuity]:
    """Sample-to-sample steps too large for the material to have produced.

    The threshold is derived from the surface itself — a robust sigma of its own
    derivative — because "too large" is a statement about this waveform's bandwidth
    and level, not a constant that would flag a loud part and miss a quiet one.
    It is derived PER WINDOW rather than once: see ``_DISCONTINUITY_WINDOW_S`` for
    why a single global sigma cannot work on music.
    """
    guard = int(round(_ONSET_GUARD_S * sample_rate))
    onsets = (
        np.sort(np.asarray(onset_samples, dtype=np.int64))
        if onset_samples is not None
        else None
    )

    found: list[Discontinuity] = []
    for channel in range(2):
        deriv = np.abs(np.diff(data[:, channel]))
        if deriv.size == 0:
            continue
        threshold = _local_step_threshold(
            deriv, np.abs(data[:, channel]), sample_rate
        )
        starts, _ = _true_runs(deriv > threshold)
        if starts.size == 0:
            continue
        # Consecutive over-threshold samples are one step, not several: the max
        # within each run is that step's size. Every value between two runs is
        # below threshold and therefore below both runs' maxima, so segmenting on
        # the run starts alone gives each run its own maximum.
        magnitudes = np.maximum.reduceat(deriv, starts)
        # `deriv[i]` spans samples i and i+1, so the step lands on i+1.
        samples = starts + 1
        if onsets is not None and onsets.size > 0:
            near = np.searchsorted(onsets, samples)
            left = np.abs(samples - onsets[np.clip(near - 1, 0, onsets.size - 1)])
            right = np.abs(samples - onsets[np.clip(near, 0, onsets.size - 1)])
            explained = np.minimum(left, right) <= guard
            # ...unless the step is far too large for any attack to have made it.
            local = threshold[np.clip(samples - 1, 0, threshold.size - 1)]
            inexplicable = magnitudes > _ONSET_GUARD_EXEMPTION * local
            keep = ~explained | inexplicable
            samples, magnitudes = samples[keep], magnitudes[keep]
        found.extend(
            Discontinuity(
                sample=int(sample), channel=channel, magnitude=float(magnitude)
            )
            for sample, magnitude in zip(samples, magnitudes)
        )
    found.sort(key=lambda d: (d.sample, d.channel))
    return found


__all__ = [
    "ClipEvent",
    "Discontinuity",
    "Dropout",
    "SurfaceIntegrity",
    "measure_integrity",
]
