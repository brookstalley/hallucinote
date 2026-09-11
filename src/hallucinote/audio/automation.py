"""Envelope-aware automation verification (AUD-8H2M).

The framework authors time-varying automation — a device-parameter flip (the
Amp Type Clean↔Heavy genre switch), a volume swell, a dynamic send. This module
verifies those gestures were REALIZED in the rendered audio: it windows a
surface around each declared breakpoint and asks whether the expected change
actually happened in the sound, reporting realized-vs-declared.

What's verifiable depends on where the analyzer taps — **pre-fader**, per
``levels.py``:

  - ``device_parameter`` (incl. enum flips like Amp Type) — the device sits
    BEFORE the analyzer tap, so its timbre change IS in the stem. The verdict is
    **directional**: "a timbre shift occurred at the declared beat", measured as
    a spectral-centroid move — NOT a scalar tolerance match, because timbre
    isn't a single number with a known target (Honest Confidence).
  - ``send_level`` — visible on the RETURN surface (more send → louder return).
    Numeric, so the expected direction (up/down) is known and checked.
  - ``mixer_volume`` — POST-fader, invisible to the pre-fader stem, but visible
    on the MASTER (the post-fader sum). AUD-3F8M: window the master around the
    breakpoint and check the level step. The declared fader values + the
    measured pre-fader stem power *predict* the expected master dB step
    (uncorrelated power model, ``levels.live_fader_gain`` calibration); when
    the prediction is below the detectability floor (stem too diluted in the
    mix, or the stem silent there), the breakpoint is honestly
    ``measurable=False`` rather than a false verdict. The realized check is
    directional + a lenient fraction of the predicted magnitude, because
    master-chain processing (the house limiter) compresses level deltas.
  - ``mixer_pan`` — post-fader; verified on the master's L−R balance
    (AUD-3F8M). Constant-power pan gains + the stem's static fader gain
    (``stem_gain``, from the snapshot's mixer state) predict the expected
    balance shift; the same detectability floor / model-breakdown honesty
    rules as ``mixer_volume`` apply.

DB-agnostic and beat-domain, like ``DeclaredReverbSend`` / ``SectionWindow``:
the MCP handler resolves DB envelopes into ``DeclaredEnvelope`` records (capture
surface IDs + song-absolute beat breakpoints) and passes them in. This module
never touches the DB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .levels import live_fader_gain
from .report import EnvelopeVerification
from .section import BeatSampleMap
from .stereo import QUIET_RMS, measure_stereo
from .timbre import spectral_centroid_hz, spectral_centroid_stereo_hz

# Beats measured on each side of a GESTURE, clamped to the neighbouring
# gestures (so adjacent moves don't bleed into each other).
_WINDOW_BEATS = 2.0

# A declared segment shorter than this is a step whatever curve it carries: an
# authored "ramp" a millionth of a beat long is a jump, and treating it as a
# traversal would leave the windows nowhere to sit.
_STEP_EPS_BEATS = 1e-6

# A window is only a fair reading of "the value before/after this move" while
# the declared value is (near enough) STILL there. A window across which the
# declaration itself swings more than this fraction of the gesture's own
# magnitude is measuring part of the neighbouring move, so it is shrunk back
# toward the gesture until it satisfies the bound.
_WINDOW_PURITY_FRACTION = 0.25

# The shortest window that can carry a verdict. Below this the centroid's
# STFT grid (2048/512) has too few frames at a musical tempo to characterise
# a window, so a gesture whose settled span shrinks under it is reported
# unmeasurable rather than graded on noise.
_MIN_WINDOW_BEATS = 0.5

# A device-parameter timbre shift counts as realized when the spectral centroid
# moves at least this fraction (relative) across the breakpoint. ~12% is well
# above measurement jitter but below a real Clean→distorted move.
_CENTROID_REL_THRESHOLD = 0.12

# The second probe: a device-parameter change also counts as realized when the
# L/R correlation moves at least this much (absolute, on a -1..+1 scale) across
# the breakpoint. Sized against the case that motivated it — a chorus flanger
# opening from bit-exact mono (+1.000) to a working image (~+0.907) moves ~0.09,
# comfortably clear of this floor, while a dry-signal correlation sits stable
# well inside it.
#
# Public because ``compare.py``'s A/B correlation significance imports it rather
# than restating the number: the two answer the same question ("is this
# correlation move real, or jitter?"), so a recalibration of one that left the
# other behind would make an A/B disagree with the verifier about the same audio.
CORRELATION_ABS_THRESHOLD = 0.05

# A send-level step counts as realized when the return RMS moves at least this
# many dB in the DECLARED direction.
_SEND_DB_THRESHOLD = 1.5

# The silence floor is stereo.QUIET_RMS, imported rather than restated: a
# window too quiet for the image lens to characterise is too quiet for this one
# to hand back a verdict on. See that constant for why the tie must not drift.

# A declared mixer_volume move must predict at least this much master-level
# change to be measurable there. Below it the stem is too diluted in the mix
# (or silent around the breakpoint) for the master to speak — calibrated on
# the sun-zone-done v4-full-aligned capture (2026-06-10 spike: pre-fader
# stem/master power ratios span 0.0–3.3 across stems and windows, so a fixed
# share threshold is meaningless; predict per-breakpoint instead). The
# same floor gates pan's predicted L−R balance shift — a balance shift is
# ~2× a single channel's change, so the floor is effectively more lenient
# there; whether pan deserves its own floor is a QLT-3D8R listening-day
# question.
_MIN_DETECTABLE_MASTER_DB = 0.75

# Realized when the measured master step (level for mixer_volume, L−R
# balance for mixer_pan) is at least this fraction of the predicted step
# (and in the predicted direction). Lenient on purpose: master-chain
# processing (the house limiter) compresses level deltas, and program
# content differs across the breakpoint.
_MIXER_REALIZED_FRACTION = 0.3

# Envelope kinds verified on the captured surface itself; the post-fader
# mixer kinds (mixer_volume / mixer_pan) are verified on the MASTER
# (post-fader sum) and dispatched by name in verify_envelope_realization.
_TIMBRE_KINDS = frozenset({"device_parameter"})
_LEVEL_KINDS = frozenset({"send_level"})


@dataclass(frozen=True)
class DeclaredEnvelope:
    """One declared automation envelope to verify, beat-domain.

    ``target_surface_id`` is the capture surface the verification reads — for
    ``device_parameter`` the track (or return) hosting the device; for
    ``send_level`` the return the send feeds; for ``mixer_volume``/``mixer_pan``
    the track whose pre-fader stem FEEDS THE PREDICTION (the measurement
    itself happens on the master, AUD-3F8M). ``target_kind`` is the DB
    envelope kind. ``breakpoints`` are
    ``(song_absolute_beat, value, curve_kind)`` triples in time order, where
    ``curve_kind`` describes the segment FROM this breakpoint TO the next one
    (``automation_breakpoints.curve_kind``: ``'linear'`` — the DB default —
    ramps straight to the next breakpoint, ``'hold'`` freezes the value until
    it, ``'fast'``/``'slow'`` are exponential ramps). The curve is what tells a
    step apart from a traversal; without it the verifier can only assume step,
    which mis-windows every ramp longer than ``_WINDOW_BEATS``. The MCP handler
    builds these from the DB; fixtures construct them directly, or via
    :meth:`from_pairs` for the step-only case.
    """
    target_surface_id: str
    target_kind: str
    parameter_path: str | None
    breakpoints: tuple[tuple[float, float, str], ...]

    @classmethod
    def from_pairs(
        cls,
        *,
        target_surface_id: str,
        target_kind: str,
        parameter_path: str | None,
        breakpoints: Sequence[tuple[float, float]],
    ) -> "DeclaredEnvelope":
        """Build from bare ``(beat, value)`` pairs, each an INSTANTANEOUS step.

        A bare pair carries no curve, and the only curve that means what a bare
        pair has always meant here — "the value is X until this beat, then Y" —
        is ``'hold'``. Filling ``'linear'`` instead would silently re-read every
        pair-form envelope as a ramp spanning its whole segment, moving verdicts
        that were never about ramps.

        This is the step/fixture constructor. Envelopes lifted from the DB carry
        their recorded curve and must NOT come through here.
        """
        return cls(
            target_surface_id=target_surface_id,
            target_kind=target_kind,
            parameter_path=parameter_path,
            breakpoints=tuple(
                (float(t), float(v), "hold") for t, v in breakpoints
            ),
        )


def _mono_window(
    audio: np.ndarray, beat_map: BeatSampleMap, lo_beat: float, hi_beat: float
) -> np.ndarray:
    a = beat_map.beat_to_sample(lo_beat)
    b = beat_map.beat_to_sample(hi_beat)
    if b <= a:
        return np.zeros(0, dtype=np.float64)
    seg = audio[a:b]
    return (0.5 * (seg[:, 0] + seg[:, 1])).astype(np.float64)


def _stereo_window(
    audio: np.ndarray, beat_map: BeatSampleMap, lo_beat: float, hi_beat: float
) -> np.ndarray:
    a = beat_map.beat_to_sample(lo_beat)
    b = beat_map.beat_to_sample(hi_beat)
    if b <= a:
        return np.zeros((0, 2), dtype=np.float64)
    return audio[a:b].astype(np.float64)


def _pan_gains(pan: float) -> tuple[float, float]:
    """Live pan (−1 hard left … +1 hard right) → constant-power (gL, gR)."""
    theta = (float(pan) + 1.0) * math.pi / 4.0
    return math.cos(theta), math.sin(theta)


def _rms(mono: np.ndarray) -> float:
    if mono.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(mono ** 2)))


def _window_energy(stereo: np.ndarray, mono: np.ndarray) -> float:
    """How much signal a window actually carries, for the silence gate.

    The stereo RMS, falling back to the mono sum when no stereo window is
    available. Using the mono sum alone would report a near anti-phase window as
    silent at full level — the channels cancel in the sum but the surface is
    plainly audible, and it is precisely the shape the image probe exists to
    measure.
    """
    if stereo.size:
        return float(np.sqrt(np.mean(stereo ** 2)))
    return _rms(mono)


_Breakpoints = Sequence[tuple[float, float, str]]


@dataclass(frozen=True)
class _Gesture:
    """One authored MOVE — a run of value changes graded as a single unit.

    ``i_start`` / ``i_end`` are breakpoint indices: the run's first and last
    value-changing breakpoint. The move is graded from ``bps[i_start - 1]``
    (the value before the run) to ``bps[i_end]`` (the value after it).
    ``steps`` is how many value changes the run collapsed — 1 for a lone
    breakpoint, 64 for a 64-step staircase.
    """
    i_start: int
    i_end: int
    steps: int


def _gestures(bps: _Breakpoints) -> list[_Gesture]:
    """Segment an envelope's value changes into gestures.

    A run of consecutive value changes joins into one gesture while they stay
    (a) in the same direction and (b) closer together than ``_WINDOW_BEATS``.
    Either condition failing closes the run.

    **The join criterion IS ``_WINDOW_BEATS``, deliberately.** A per-step
    verdict is only valid when the step has a full analysis window on each
    side; the window is therefore exactly the right ruler for "are these steps
    separable?". A future retune of ``_WINDOW_BEATS`` re-segments every
    envelope, and that coupling is the point — grading a 64-step staircase per
    step compares two points on the same gesture and calls the result a
    failure, so better authorship read as worse realization.

    A direction reversal splits the run (a rise and the fall after it are two
    moves, not a net no-op). A plateau longer than the window splits it too:
    the spacing test measures change-to-change, so any gap that could hold a
    full window closes the run.
    """
    changes = [
        i for i in range(1, len(bps))
        if bps[i][1] != bps[i - 1][1]
    ]
    out: list[_Gesture] = []
    run: list[int] = []
    for i in changes:
        if run:
            prev = run[-1]
            rising_now = bps[i][1] > bps[i - 1][1]
            rising_prev = bps[prev][1] > bps[prev - 1][1]
            close = (bps[i][0] - bps[prev][0]) < _WINDOW_BEATS
            if rising_now == rising_prev and close:
                run.append(i)
                continue
            out.append(_Gesture(run[0], run[-1], len(run)))
        run = [i]
    if run:
        out.append(_Gesture(run[0], run[-1], len(run)))
    return out


def _segment_ramps(bps: _Breakpoints, k: int) -> bool:
    """Does segment ``k`` (``bps[k]`` → ``bps[k+1]``) TRAVERSE its value change
    rather than step it?

    ``'hold'`` freezes the value until the next breakpoint, so it steps. So
    does a segment with no value change at all, and so does one shorter than
    ``_STEP_EPS_BEATS`` whatever curve it declares. Everything else — the DB
    default ``'linear'``, and the ``'fast'``/``'slow'`` exponentials — moves
    the value ACROSS the segment, and that is the interval the before/after
    windows must not sit inside.
    """
    if bps[k][1] == bps[k + 1][1]:
        return False
    if bps[k][2] == "hold":
        return False
    return (bps[k + 1][0] - bps[k][0]) > _STEP_EPS_BEATS


def _transition(bps: _Breakpoints, g: _Gesture) -> tuple[float, int, float]:
    """The gesture's transition interval: ``(start_beat, start_index, end_beat)``.

    The value moves across ``[start_beat, end_beat]`` and is settled on neither
    side of it, so neither window may overlap it. When the segment INTO the run
    ramps, the move starts at the breakpoint before the first change; when it
    steps, it starts at the change itself. It always ends at the run's last
    change, which is where the new value first holds.
    """
    s = g.i_start
    if _segment_ramps(bps, s - 1):
        return bps[s - 1][0], s - 1, bps[g.i_end][0]
    return bps[s][0], s, bps[g.i_end][0]


def _settled_back_to(
    bps: _Breakpoints, anchor_idx: int, anchor_value: float,
    floor_beat: float, tol: float,
) -> float:
    """Earliest beat ≥ ``floor_beat`` from which the DECLARED value stays
    within ``tol`` of ``anchor_value`` all the way up to ``bps[anchor_idx]``.

    The plateau-purity walk (backwards). ``'fast'``/``'slow'`` segments are
    walked as linear — the exponential shape moves the crossing point but not
    which side of the bound a window sits on, and the module has no exponent
    to reconstruct the curve from.
    """
    limit = floor_beat
    j = anchor_idx
    while j >= 1:
        a, va = bps[j - 1][0], bps[j - 1][1]
        b, vb = bps[j][0], bps[j][1]
        if b <= limit:
            break
        if not _segment_ramps(bps, j - 1):
            if abs(va - anchor_value) > tol:
                return b
            j -= 1
            continue
        slope = (vb - va) / (b - a)
        x_hi = a + (anchor_value + tol - va) / slope
        x_lo = a + (anchor_value - tol - va) / slope
        left = min(x_hi, x_lo)
        if left > a:
            return max(left, limit)
        j -= 1
    return limit


def _settled_forward_to(
    bps: _Breakpoints, anchor_idx: int, anchor_value: float,
    ceiling_beat: float, tol: float,
) -> float:
    """Latest beat ≤ ``ceiling_beat`` up to which the DECLARED value stays
    within ``tol`` of ``anchor_value``, starting from ``bps[anchor_idx]``.

    The mirror of :func:`_settled_back_to`; it is what keeps the after-window
    off a neighbouring ramp that starts before its own first change.
    """
    limit = ceiling_beat
    j = anchor_idx
    while j <= len(bps) - 2:
        a, va = bps[j][0], bps[j][1]
        b, vb = bps[j + 1][0], bps[j + 1][1]
        if a >= limit:
            break
        if not _segment_ramps(bps, j):
            if abs(va - anchor_value) > tol:
                return a
            j += 1
            continue
        slope = (vb - va) / (b - a)
        x_hi = a + (anchor_value + tol - va) / slope
        x_lo = a + (anchor_value - tol - va) / slope
        right = max(x_hi, x_lo)
        if right < b:
            return min(right, limit)
        j += 1
    return limit


@dataclass(frozen=True)
class _Windows:
    """The two spans a gesture is graded across, and the transition between."""
    before_start: float
    before_end: float
    after_start: float
    after_end: float

    @property
    def before_beats(self) -> float:
        return self.before_end - self.before_start

    @property
    def after_beats(self) -> float:
        return self.after_end - self.after_start


def _windows_for_gesture(
    bps: _Breakpoints, gestures: Sequence[_Gesture], k: int,
) -> _Windows:
    """Where to read "before" and "after" for gesture ``k``.

    Three rules, in order:

    1. **Off the transition.** The before-window ENDS where the move starts and
       the after-window BEGINS where it ends, so neither contains the traversal
       being graded. For a step those two beats coincide and the windows are
       exactly the historical ``[B-W, B)`` / ``[B, B+W)``.
    2. **Clamped to the neighbouring GESTURE**, not the neighbouring
       breakpoint: back to the previous gesture's last change, forward to the
       next gesture's first change. Clamping to the neighbouring breakpoint
       inside a staircase would floor the window on the ramp's own second step
       — measuring a gesture against itself.
    3. **Purity.** A window across which the declaration itself swings more
       than ``_WINDOW_PURITY_FRACTION`` of this gesture's magnitude is reading
       part of a neighbouring move, so it is shrunk back toward the transition
       until it doesn't. This is what keeps the after-window off a gently
       ramping neighbour that the gesture clamp lets it reach.
    """
    g = gestures[k]
    t_start, start_idx, t_end = _transition(bps, g)
    v_from = bps[g.i_start - 1][1]
    v_to = bps[g.i_end][1]
    tol = _WINDOW_PURITY_FRACTION * abs(v_to - v_from)

    lo = t_start - _WINDOW_BEATS
    if k > 0:
        lo = max(lo, bps[gestures[k - 1].i_end][0])
    lo = _settled_back_to(bps, start_idx, v_from, lo, tol)

    hi = t_end + _WINDOW_BEATS
    if k + 1 < len(gestures):
        hi = min(hi, bps[gestures[k + 1].i_start][0])
    hi = _settled_forward_to(bps, g.i_end, v_to, hi, tol)

    return _Windows(lo, t_start, t_end, hi)


def verify_envelope_realization(
    env: DeclaredEnvelope,
    surface_audio: np.ndarray,
    *,
    sample_rate: int,
    beat_map: BeatSampleMap,
    master_audio: np.ndarray,
    stem_gain: float = 1.0,
) -> list[EnvelopeVerification]:
    """One verification per authored GESTURE in ``env``.

    A gesture is a run of value changes graded as one move (:func:`_gestures`):
    a lone breakpoint is a gesture of one step, and a 64-step staircase is one
    gesture of 64. Per-step grading is the ``steps == 1`` case of this, not a
    branch beside it — which is the point, because a per-step verdict is only
    valid when the step has a full analysis window on each side.

    For each gesture, window the surface ``before`` the move begins and
    ``after`` it lands (:func:`_windows_for_gesture`) and compare the
    kind-appropriate metric. The post-fader mixer kinds measure the MASTER
    windows (post-fader sum) against a prediction built from the pre-fader
    stem window (AUD-3F8M): ``mixer_volume`` from its own declared fader
    values, ``mixer_pan`` from constant-power pan gains scaled by
    ``stem_gain`` (the stem's static fader gain from the snapshot's mixer
    state; unity when unknown).
    """
    bps = env.breakpoints
    gestures = _gestures(bps)
    results: list[EnvelopeVerification] = []
    for k, g in enumerate(gestures):
        w = _windows_for_gesture(bps, gestures, k)

        # No settled window on one side: the neighbouring segment ramps
        # through where the plateau would be, so there is nothing to read the
        # old (or new) value off. Honest unmeasurable — never a verdict
        # manufactured from a window that is itself part of a move.
        if w.before_beats < _MIN_WINDOW_BEATS or w.after_beats < _MIN_WINDOW_BEATS:
            if w.before_beats < _MIN_WINDOW_BEATS:
                side, at_beat, span = "before", w.before_end, w.before_beats
                neighbour_ramps = _segment_ramps(bps, g.i_start - 1)
            else:
                side, at_beat, span = "after", w.after_start, w.after_beats
                neighbour_ramps = (
                    g.i_end + 1 < len(bps) and _segment_ramps(bps, g.i_end)
                )
            cause = (
                "the neighbouring segment ramps through it"
                if neighbour_ramps
                else "the neighbouring move leaves no settled span there"
            )
            results.append(_unmeasurable(env, bps, g, note=(
                f"no settled window {side} the move at beat {at_beat:g}: "
                f"{cause}, leaving {max(span, 0.0):.2f} beat of steady "
                f"declared value — under the {_MIN_WINDOW_BEATS:g}-beat "
                "minimum — so this move can't be confirmed or refuted here"
            )))
            continue

        before = _mono_window(
            surface_audio, beat_map, w.before_start, w.before_end)
        after = _mono_window(
            surface_audio, beat_map, w.after_start, w.after_end)
        stereo_before = _stereo_window(
            surface_audio, beat_map, w.before_start, w.before_end)
        stereo_after = _stereo_window(
            surface_audio, beat_map, w.after_start, w.after_end)

        if env.target_kind == "mixer_volume":
            results.append(_verify_mixer_volume(
                env, bps, g,
                stem_before=before,
                master_before=_mono_window(
                    master_audio, beat_map, w.before_start, w.before_end),
                master_after=_mono_window(
                    master_audio, beat_map, w.after_start, w.after_end),
            ))
            continue

        if env.target_kind == "mixer_pan":
            results.append(_verify_mixer_pan(
                env, bps, g,
                stem_before=before,
                master_before=_stereo_window(
                    master_audio, beat_map, w.before_start, w.before_end),
                master_after=_stereo_window(
                    master_audio, beat_map, w.after_start, w.after_end),
                stem_gain=stem_gain,
            ))
            continue

        # Gate on the surface's STEREO energy, not its mono sum. A near
        # anti-phase window has a near-zero mono sum at full stereo level, so a
        # mono-only gate calls it "too quiet to characterise" and skips the whole
        # verification — including the image probe, for which anti-phase is the
        # single most informative signal shape there is.
        if (
            _window_energy(stereo_before, before) < QUIET_RMS
            or _window_energy(stereo_after, after) < QUIET_RMS
        ):
            results.append(_unmeasurable(env, bps, g, note=(
                "window too quiet to characterise (the surface is near "
                "silent around this breakpoint) — can't confirm or refute "
                "realization here"
            )))
            continue

        if env.target_kind in _TIMBRE_KINDS:
            results.append(_verify_timbre(
                env, bps, g, before, after, sample_rate,
                stereo_before=stereo_before,
                stereo_after=stereo_after,
            ))
        elif env.target_kind in _LEVEL_KINDS:
            results.append(_verify_level(
                env, bps, g, before, after,
                stereo_before=stereo_before,
                stereo_after=stereo_after,
            ))
        # Unknown kinds are filtered out by the handler before reaching here;
        # if one slips through, skip it silently (no false verdict).
    return results


def _over_steps(g: _Gesture) -> str:
    """`` over N steps`` when the gesture collapsed a staircase, else empty.

    The endpoint pair a note prints is the whole move; without this clause a
    reader can't tell a single authored step from a 64-step traversal graded
    as one.
    """
    return f" over {g.steps} steps" if g.steps > 1 else ""


def _unmeasurable(
    env: DeclaredEnvelope, bps: _Breakpoints, g: _Gesture, *, note: str,
) -> EnvelopeVerification:
    """The one honest-skip shape, shared by every kind and every reason."""
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=bps[g.i_start][0],
        metric="n/a",
        before=float("nan"),
        after=float("nan"),
        measurable=False,
        realized=False,
        note=note,
        through_beat=bps[g.i_end][0],
        steps=g.steps,
    )


def _phase_robust_centroid(
    stereo: np.ndarray, mono: np.ndarray, sample_rate: int
) -> float:
    """The phase-robust centroid for this window, or the mono form when no stereo
    window is available (hand-built fixtures).

    Both centroid definitions live in ``timbre.py`` — see
    :func:`~hallucinote.audio.timbre.spectral_centroid_stereo_hz` for why the
    magnitude-spectrum average is the right one here. This is the fixture
    fallback only; it deliberately holds no centroid math of its own.
    """
    if stereo.size == 0:
        return spectral_centroid_hz(mono, sample_rate)
    return spectral_centroid_stereo_hz(stereo, sample_rate)


def _verify_timbre(
    env, bps, g, before, after, sample_rate, *, stereo_before, stereo_after,
) -> EnvelopeVerification:
    """Verify a device-parameter change on TWO probes: timbre and image.

    Spectral centroid alone is the wrong probe for an image effect. A flanger is
    a comb filter — it notches roughly symmetrically, so it barely moves the
    centroid however wet it gets. Verified on centroid alone, a working chorus
    flanger reports "no audible timbre shift (2244→2219 Hz, 1% < 12%)" and lands
    a warning on automation that provably DID happen: the parameter read back its
    exact authored value mid-sweep and the stereo appeared in the render.

    So the claim is "the declared change produced a measurable effect in some
    probed dimension", which is strictly more correct than the timbre-only test.
    Deliberately NOT selected by device class: class isn't available at this
    layer, and threading it would cross ``analyze_mix``'s DB-agnostic boundary
    for no gain.

    The reported ``metric``/``before``/``after`` stay the centroid pair so the
    field's meaning never depends on which probe happened to fire; the note names
    the probe that carried the verdict.
    """
    steps = _over_steps(g)
    c_before = _phase_robust_centroid(stereo_before, before, sample_rate)
    c_after = _phase_robust_centroid(stereo_after, after, sample_rate)
    rel = abs(c_after - c_before) / c_before if c_before > 0 else 0.0
    timbre_moved = rel >= _CENTROID_REL_THRESHOLD
    pct = rel * 100.0

    corr_delta = _image_delta(stereo_before, stereo_after)
    image_moved = corr_delta is not None and corr_delta >= CORRELATION_ABS_THRESHOLD

    realized = timbre_moved or image_moved
    if timbre_moved:
        note = (
            f"timbre shift realized: spectral centroid {c_before:.0f}→"
            f"{c_after:.0f} Hz ({pct:+.0f}%) at the declared "
            f"{env.parameter_path or 'device-parameter'} change{steps}"
        )
    elif image_moved:
        note = (
            f"image shift realized: L/R correlation moved {corr_delta:.2f} at the "
            f"declared {env.parameter_path or 'device-parameter'} change{steps}, "
            f"with no timbre move ({c_before:.0f}→{c_after:.0f} Hz, {pct:.0f}%) — expected "
            "for a comb/width effect, which changes the stereo picture rather "
            "than the brightness"
        )
    else:
        note = (
            f"no audible timbre shift ({c_before:.0f}→{c_after:.0f} Hz, "
            f"{pct:.0f}% < {_CENTROID_REL_THRESHOLD * 100:.0f}%) and no stereo "
            f"image shift — the declared "
            f"{env.parameter_path or 'device-parameter'} change{steps} may not "
            "have been realized in the render"
        )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=bps[g.i_start][0],
        metric="spectral_centroid_hz",
        before=c_before,
        after=c_after,
        measurable=True,
        realized=realized,
        note=note,
        # Which probe carried the verdict — timbre wins the tie, matching the
        # note. None when neither fired: there is no basis to name.
        probe=("timbre" if timbre_moved else "image" if image_moved else None),
        through_beat=bps[g.i_end][0],
        steps=g.steps,
    )


def _image_delta(stereo_before, stereo_after) -> float | None:
    """Absolute L/R-correlation change across the breakpoint, or ``None`` when
    either window is unmeasurable (silent/empty — ``measure_stereo`` returns NaN
    there, and a NaN must never read as "no change" and vote against realization).
    """
    if stereo_before.shape[0] == 0 or stereo_after.shape[0] == 0:
        return None
    c_before = measure_stereo(stereo_before).correlation
    c_after = measure_stereo(stereo_after).correlation
    if math.isnan(c_before) or math.isnan(c_after):
        return None
    return abs(c_after - c_before)


def _verify_mixer_volume(
    env, bps, g, *, stem_before, master_before, master_after,
) -> EnvelopeVerification:
    """AUD-3F8M: verify a post-fader volume move on the MASTER.

    The declared breakpoints are Live normalized fader values; with the
    measured pre-fader stem power around the move, the uncorrelated power
    model predicts the master step:

        P_after ≈ P_master − P_stem·g₁² + P_stem·g₂²

    A prediction below ``_MIN_DETECTABLE_MASTER_DB`` means the stem is too
    diluted (or silent) there for the master to speak — honest
    ``measurable=False``, never a false verdict.
    """
    steps = _over_steps(g)
    v_from, v_to = bps[g.i_start - 1][1], bps[g.i_end][1]
    if _rms(master_before) < QUIET_RMS or _rms(master_after) < QUIET_RMS:
        return _unmeasurable(env, bps, g, note=(
            "master window too quiet to characterise around this "
            "breakpoint — can't confirm or refute the fader move here"
        ))

    g1 = live_fader_gain(v_from)
    g2 = live_fader_gain(v_to)
    p_master = _rms(master_before) ** 2
    p_stem = _rms(stem_before) ** 2
    expected_after_p = p_master - p_stem * g1 * g1 + p_stem * g2 * g2
    if expected_after_p <= 0.01 * p_master:
        # Model breakdown: the pre-fader stem at its declared gain accounts
        # for (nearly) all the measured master power — master-chain
        # compression/limiting makes the uncorrelated sum overshoot. A
        # prediction from a broken model would manufacture a false
        # "NOT realized"; report honestly unmeasurable instead.
        return _unmeasurable(env, bps, g, note=(
            f"declared fader move ({v_from:.2f}→{v_to:.2f}{steps}): "
            "the pre-fader stem at its declared gain accounts for more "
            "power than the measured master window (master-chain "
            "compression/limiting) — the uncorrelated prediction model "
            "breaks down here, so master-bus windowing can't confirm or "
            "refute this move"
        ))
    expected_db = 10.0 * math.log10(expected_after_p / p_master)

    if abs(expected_db) < _MIN_DETECTABLE_MASTER_DB:
        return _unmeasurable(env, bps, g, note=(
            f"declared fader move ({v_from:.2f}→{v_to:.2f}{steps}) "
            f"predicts only {expected_db:+.2f} dB on the master — the "
            "stem is too diluted in the mix (or silent) around this "
            "breakpoint for master-bus windowing to confirm or refute it"
        ))

    db_before = 20.0 * math.log10(max(_rms(master_before), 1e-12))
    db_after = 20.0 * math.log10(max(_rms(master_after), 1e-12))
    delta_db = db_after - db_before
    realized = (
        (delta_db > 0) == (expected_db > 0)
        and abs(delta_db) >= _MIXER_REALIZED_FRACTION * abs(expected_db)
    )
    direction = "up" if expected_db > 0 else "down"
    note = (
        f"fader declared {direction} ({v_from:.2f}→{v_to:.2f}{steps}, "
        f"predicting {expected_db:+.1f} dB on the master); master moved "
        f"{delta_db:+.1f} dB ({db_before:.1f}→{db_after:.1f} dBFS) — "
        + ("realized" if realized else "NOT realized in the declared direction")
    )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=bps[g.i_start][0],
        metric="master_rms_db",
        before=db_before,
        after=db_after,
        measurable=True,
        realized=realized,
        note=note,
        through_beat=bps[g.i_end][0],
        steps=g.steps,
    )


def _verify_mixer_pan(
    env, bps, g, *, stem_before, master_before, master_after, stem_gain,
) -> EnvelopeVerification:
    """AUD-3F8M: verify a post-fader pan move on the MASTER's L−R balance.

    Declared breakpoints are Live pan values (−1…+1). Constant-power pan
    gains + the stem's static fader gain predict the expected per-channel
    power change, hence the expected balance shift:

        P_ch_after ≈ P_ch − P_stem·g²·g_ch1² + P_stem·g²·g_ch2²

    Same honesty rules as mixer_volume: predicted shift below the floor →
    ``measurable=False`` (too diluted); a channel where the model breaks
    down (stem-at-gain exceeding measured channel power) → honest skip.
    """
    steps = _over_steps(g)
    v_from, v_to = bps[g.i_start - 1][1], bps[g.i_end][1]

    def _ch_rms(seg: np.ndarray, ch: int) -> float:
        if seg.shape[0] == 0:
            return 0.0
        return float(np.sqrt(np.mean(seg[:, ch] ** 2)))

    rms_lb, rms_rb = _ch_rms(master_before, 0), _ch_rms(master_before, 1)
    rms_la, rms_ra = _ch_rms(master_after, 0), _ch_rms(master_after, 1)
    if min(rms_lb, rms_rb, rms_la, rms_ra) < QUIET_RMS:
        return _unmeasurable(env, bps, g, note=(
            "master window too quiet to characterise around this "
            "breakpoint — can't confirm or refute the pan move here"
        ))

    gl1, gr1 = _pan_gains(v_from)
    gl2, gr2 = _pan_gains(v_to)
    p_stem = (_rms(stem_before) * stem_gain) ** 2
    p_l, p_r = rms_lb ** 2, rms_rb ** 2
    exp_l = p_l - p_stem * gl1 * gl1 + p_stem * gl2 * gl2
    exp_r = p_r - p_stem * gr1 * gr1 + p_stem * gr2 * gr2
    if exp_l <= 0.01 * p_l or exp_r <= 0.01 * p_r:
        return _unmeasurable(env, bps, g, note=(
            f"declared pan move ({v_from:+.2f}→{v_to:+.2f}{steps}): the "
            "stem at its gain accounts for more power than a measured master "
            "channel (master-chain compression/limiting) — the prediction "
            "model breaks down here, so master-bus windowing can't confirm "
            "or refute this move"
        ))

    predicted_db = (
        10.0 * math.log10(exp_l / p_l) - 10.0 * math.log10(exp_r / p_r)
    )
    if abs(predicted_db) < _MIN_DETECTABLE_MASTER_DB:
        return _unmeasurable(env, bps, g, note=(
            f"declared pan move ({v_from:+.2f}→{v_to:+.2f}{steps}) "
            f"predicts only {predicted_db:+.2f} dB of L−R balance shift on "
            "the master — the stem is too diluted in the mix (or silent) "
            "around this breakpoint for master-bus windowing to confirm or "
            "refute it"
        ))

    balance_before = 20.0 * math.log10(rms_lb / rms_rb)
    balance_after = 20.0 * math.log10(rms_la / rms_ra)
    delta_db = balance_after - balance_before
    realized = (
        (delta_db > 0) == (predicted_db > 0)
        and abs(delta_db) >= _MIXER_REALIZED_FRACTION * abs(predicted_db)
    )
    direction = "left" if predicted_db > 0 else "right"
    note = (
        f"pan declared toward the {direction} "
        f"({v_from:+.2f}→{v_to:+.2f}{steps}, predicting "
        f"{predicted_db:+.1f} dB L−R shift); master balance moved "
        f"{delta_db:+.1f} dB ({balance_before:+.1f}→{balance_after:+.1f} dB "
        "L−R) — "
        + ("realized" if realized else "NOT realized in the declared direction")
    )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=bps[g.i_start][0],
        metric="master_balance_db",
        before=balance_before,
        after=balance_after,
        measurable=True,
        realized=realized,
        note=note,
        through_beat=bps[g.i_end][0],
        steps=g.steps,
    )


def _verify_level(
    env, bps, g, before, after, *, stereo_before, stereo_after,
) -> EnvelopeVerification:
    """Verify a send-level step on the return's own level.

    The level measured here is the window's STEREO RMS, the same quantity the
    silence gate uses (``_window_energy``). Grading the mono sum instead would
    let gate and metric measure different signals: a decorrelated return window
    — a wide reverb, a ping-pong delay — is loud in stereo and near-silent in
    its mono sum, so it clears the gate and is then judged on two cancellation
    residues, which yields a confident dB verdict from noise. That is the same
    false-verdict class STR-4C8N exists to remove, and a send into a wide return
    is the ordinary case, not a corner.
    """
    db_before = 20.0 * math.log10(max(_window_energy(stereo_before, before), 1e-12))
    db_after = 20.0 * math.log10(max(_window_energy(stereo_after, after), 1e-12))
    delta_db = db_after - db_before
    v_from, v_to = bps[g.i_start - 1][1], bps[g.i_end][1]
    declared_dir = v_to - v_from  # +ve = more send, -ve = less
    # Realized when the level moved in the declared direction by a real amount.
    realized = (
        abs(delta_db) >= _SEND_DB_THRESHOLD
        and (delta_db > 0) == (declared_dir > 0)
    )
    direction = "up" if declared_dir > 0 else "down"
    note = (
        f"send level declared {direction}{_over_steps(g)}; "
        f"return moved {delta_db:+.1f} dB "
        f"({db_before:.1f}→{db_after:.1f} dBFS) — "
        + ("realized" if realized else "NOT realized in the declared direction")
    )
    return EnvelopeVerification(
        target_surface_id=env.target_surface_id,
        target_kind=env.target_kind,
        parameter_path=env.parameter_path,
        at_beat=bps[g.i_start][0],
        metric="rms_db",
        before=db_before,
        after=db_after,
        measurable=True,
        realized=realized,
        note=note,
        through_beat=bps[g.i_end][0],
        steps=g.steps,
    )


__all__ = [
    "DeclaredEnvelope",
    "verify_envelope_realization",
]
