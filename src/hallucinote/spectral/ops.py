"""Carve and vocode: one mask from one field, applied to a target's magnitudes.

``build_mask`` turns a reference field into a time-varying gain surface on the
field's own grid. At every bin where the reference has energy it cuts a notch:
``notch_width_cents`` wide on the pitch axis, with a transition whose width is
a fraction of the Bark band the bin sits in, ``depth_db`` deep, smoothed over
``smoothing_s``. Carve attenuates inside the notches; vocode attenuates
everywhere else. One surface, one polarity — there is no vocoder, only the
same profile inverted. Every ``MaskParams`` float may be a per-frame array on
the field's time axis, so the carve itself can open and close as a gesture.

``apply`` STFTs the target, resamples the mask onto the target's grid,
multiplies the magnitudes and resynthesizes against the target's own phase.
When the mask's resolution carries a low-band window, the target is split at
the knee, the bass is carved through the longer window, and the two bands sum
back — the multi-resolution path ``resolution.py`` chooses.

Discipline: the mask lives in Hz and seconds, never in bins, so a field and a
target need not share a grid. A notch is never narrower than the bin that
carries it, and the mask says what width it achieved (``Mask.precision``)
rather than implying the request was met. Phase is never touched. Where the
notch is cut in Hz the pitch axis is the ruler: scaling the whole width by the
Bark band would turn a semitone at 55 Hz into ten of them, so the band shapes
only the notch's edges.
"""
from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
from scipy.ndimage import convolve1d
from scipy.signal.windows import hann

from hallucinote.audio.bark import BarkMap
from hallucinote.spectral.resolution import (
    PrecisionClaim,
    bin_hz_over,
    choose_resolution,
    claim_precision,
    split_bands,
)
from hallucinote.spectral.types import MaskParams, Polarity, ResolutionReport, SpectralField

# A field bin counts as reference energy when it lies within this many dB of
# the field's loudest bin. Global, not per frame: a per-frame floor would read
# the noise floor of a silent frame as a reference.
ENERGY_FLOOR_DB = 40.0

# The notch's transition from full depth to none spans this fraction of the
# Bark band around the reference bin. The ear resolves nothing finer than a
# critical band, so a sharper edge is inaudible detail that only pre-rings.
SKIRT_BAND_FRACTION = 0.05


@dataclass(frozen=True, eq=False)
class Mask:
    """A linear gain surface ``gain[f, t]`` on ``freqs_hz[f]``, ``times_s[t]``.

    ``rest_gain[t]`` is the gain wherever the reference is silent — unity for a
    carve, the depth floor for a vocode — and is what ``apply`` uses outside
    the field's frequency coverage. ``resolution`` is the window pair
    ``apply`` must use; ``precision`` is the honest claim at the lowest
    reference pitch, or ``None`` when the field holds no energy at all.
    ``fingerprint`` is the field's, so a derived asset can record what it was
    carved against.
    """

    freqs_hz: np.ndarray
    times_s: np.ndarray
    gain: np.ndarray
    rest_gain: np.ndarray
    polarity: Polarity
    resolution: ResolutionReport
    precision: PrecisionClaim | None
    fingerprint: str

    def __post_init__(self) -> None:
        f = np.asarray(self.freqs_hz, dtype=np.float64)
        t = np.asarray(self.times_s, dtype=np.float64)
        g = np.asarray(self.gain, dtype=np.float64)
        r = np.asarray(self.rest_gain, dtype=np.float64)
        if g.shape != (f.shape[0], t.shape[0]):
            raise ValueError(
                f"Mask.gain must be (n_freqs, n_times) = {(f.shape[0], t.shape[0])}; got {g.shape}"
            )
        if r.shape != t.shape:
            raise ValueError(f"Mask.rest_gain must be per frame {t.shape}; got {r.shape}")
        if g.size and (g.min() < 0.0 or g.max() > 1.0):
            raise ValueError("Mask.gain must lie in [0, 1]: a mask attenuates, it never boosts")
        if self.polarity not in ("carve", "vocode"):
            raise ValueError(f"polarity must be 'carve' or 'vocode'; got {self.polarity!r}")
        object.__setattr__(self, "freqs_hz", f)
        object.__setattr__(self, "times_s", t)
        object.__setattr__(self, "gain", g)
        object.__setattr__(self, "rest_gain", r)


def _per_frame(value: float | np.ndarray, n_times: int, *, name: str) -> np.ndarray:
    """A parameter as one value per field frame, whether it came in scalar or automated."""
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim == 0:
        return np.full(n_times, float(arr))
    if arr.shape != (n_times,):
        raise ValueError(
            f"MaskParams.{name} is an array of shape {arr.shape} but the field has "
            f"{n_times} frames; an automated parameter is aligned to the field's time axis"
        )
    return arr


def _band_width_hz(freqs_hz: np.ndarray, bark: BarkMap) -> np.ndarray:
    """Width of the Bark band each frequency sits in; above the top edge, the top band's."""
    edges = np.asarray(bark.edges_hz, dtype=np.float64)
    widths = np.diff(edges)
    idx = np.searchsorted(edges, freqs_hz, side="right") - 1
    idx = np.clip(idx, 0, widths.shape[0] - 1)
    return widths[idx]


def _notch_attenuation(
    freqs_hz: np.ndarray, presence: np.ndarray, half_hz: np.ndarray, skirt_hz: np.ndarray
) -> np.ndarray:
    """Attenuation fraction ``[f, t]`` in [0, 1] from every present bin's notch.

    A bin's notch is flat at full depth within ``half_hz`` of it and falls off
    as a raised cosine over ``skirt_hz`` beyond that. Overlapping notches take
    the maximum, never the sum: depth is bounded, and two partials a bin apart
    are one carved region, not a deeper one. The loop runs over bin offsets,
    so a field of any monotone grid is handled and the cost is the notch's
    footprint in bins, not the number of bins squared.
    """
    n_f, n_t = presence.shape
    att = np.zeros((n_f, n_t), dtype=np.float64)
    present_any = presence.any(axis=1)
    if not present_any.any():
        return att
    # Only a bin that is ever present cuts a notch, so only those bins set how
    # far the loop must reach; a silent top bin's wide notch would otherwise
    # cost every frame the whole spectrum.
    reach = np.where(present_any, half_hz.max(axis=1) + skirt_hz, 0.0)
    upper = np.searchsorted(freqs_hz, freqs_hz + reach, side="right") - 1 - np.arange(n_f)
    lower = np.arange(n_f) - np.searchsorted(freqs_hz, freqs_hz - reach, side="left")
    footprint = int(max(upper.max(), lower.max(), 0))
    for d in range(-footprint, footprint + 1):
        if d >= 0:
            src, dst = slice(0, n_f - d), slice(d, n_f)
        else:
            src, dst = slice(-d, n_f), slice(0, n_f + d)
        dist = np.abs(freqs_hz[dst] - freqs_hz[src])[:, None]
        x = (dist - half_hz[src]) / skirt_hz[src][:, None]
        profile = np.where(x <= 0.0, 1.0, np.where(x >= 1.0, 0.0, np.cos(0.5 * np.pi * np.clip(x, 0.0, 1.0)) ** 2))
        np.maximum(att[dst], profile * presence[src], out=att[dst])
    return att


def _smooth_over_time(att: np.ndarray, times_s: np.ndarray, smoothing_s: float) -> np.ndarray:
    """Hann-average the attenuation along time so a notch opens and closes over ``smoothing_s``."""
    if smoothing_s <= 0.0 or times_s.shape[0] < 2:
        return att
    dt = float(np.median(np.diff(times_s)))
    if dt <= 0.0:
        return att
    n = int(round(smoothing_s / dt))
    if n < 2:
        return att
    # A symmetric Hann's end taps are zero, so an odd length of n + 2 leaves
    # about n frames of real weight, centred: the notch fades symmetrically.
    kernel = hann((n + 2) | 1, sym=True)
    kernel = kernel / kernel.sum()
    return convolve1d(att, kernel, axis=1, mode="nearest")


def build_mask(
    field: SpectralField,
    params: MaskParams,
    *,
    bark: BarkMap,
    resolution: ResolutionReport | None = None,
    energy_floor_db: float = ENERGY_FLOOR_DB,
) -> Mask:
    """Build the gain surface for ``params`` from where ``field`` has energy.

    ``resolution`` is the window pair ``apply`` will use. Left ``None``, it is
    chosen from the lowest reference pitch and the narrowest requested notch —
    a longer low-band window when the field's base window cannot resolve the
    request below the knee — so the bass gets the precision it was asked for
    when a window can give it, and an honest claim when none can. Pass the
    field's own resolution to force a single window.
    """
    if energy_floor_db <= 0.0:
        raise ValueError(f"energy_floor_db must be > 0; got {energy_floor_db}")
    freqs = field.freqs_hz
    times = field.times_s
    n_f, n_t = field.magnitude.shape
    cents = _per_frame(params.notch_width_cents, n_t, name="notch_width_cents")
    depth = _per_frame(params.depth_db, n_t, name="depth_db")

    peak = float(field.magnitude.max()) if field.magnitude.size else 0.0
    presence = (
        (field.magnitude >= peak * 10.0 ** (-energy_floor_db / 20.0)).astype(np.float64)
        if peak > 0.0
        else np.zeros((n_f, n_t), dtype=np.float64)
    )

    present_freqs = freqs[(presence.any(axis=1)) & (freqs > 0.0)]
    lowest_hz = float(present_freqs.min()) if present_freqs.size else None
    if resolution is None:
        base = field.resolution
        resolution = (
            choose_resolution(
                lowest_hz,
                base.sample_rate,
                n_fft=base.n_fft,
                hop=base.hop,
                target_cents=float(cents.min()),
            )
            if lowest_hz is not None
            else base
        )
    precision = (
        claim_precision(lowest_hz, float(cents.min()), field.resolution, resolution)
        if lowest_hz is not None
        else None
    )

    # The plateau is the requested width on the pitch axis, floored at the bin
    # of whichever window is coarsest there: a notch cannot be narrower than
    # the bin that carries it, and the claim above says so.
    half_hz = freqs[:, None] * (2.0 ** (cents[None, :] / 1200.0) - 1.0) / 2.0
    bin_floor = np.maximum(bin_hz_over(field.resolution, freqs), bin_hz_over(resolution, freqs))
    half_hz = np.maximum(half_hz, bin_floor[:, None] / 2.0)
    skirt_hz = SKIRT_BAND_FRACTION * _band_width_hz(freqs, bark)

    att = _notch_attenuation(freqs, presence, half_hz, skirt_hz)
    att = _smooth_over_time(att, times, float(params.smoothing_s))
    inside = att if params.polarity == "carve" else 1.0 - att
    gain = 10.0 ** (-depth[None, :] * inside / 20.0)
    rest_gain = np.ones(n_t) if params.polarity == "carve" else 10.0 ** (-depth / 20.0)
    return Mask(
        freqs_hz=freqs,
        times_s=times,
        gain=np.clip(gain, 0.0, 1.0),
        rest_gain=rest_gain,
        polarity=params.polarity,
        resolution=resolution,
        precision=precision,
        fingerprint=field.fingerprint,
    )


def _interp_along(
    x_new: np.ndarray,
    x_old: np.ndarray,
    values: np.ndarray,
    *,
    axis: int,
    outside: np.ndarray | None = None,
) -> np.ndarray:
    """Linear interpolation of a 2-D surface along one axis onto a new grid.

    Beyond the old grid's ends the surface clamps to its edge values, unless
    ``outside`` is given — then those positions take ``outside`` (per column
    when interpolating along frequency), which is how a mask says "no
    reference here" beyond the field's coverage rather than smearing its edge.
    """
    if x_old.shape[0] == 1:
        return np.repeat(values, x_new.shape[0], axis=axis)
    idx = np.searchsorted(x_old, x_new, side="right") - 1
    idx = np.clip(idx, 0, x_old.shape[0] - 2)
    x0, x1 = x_old[idx], x_old[idx + 1]
    span = x1 - x0
    w = np.where(span > 0.0, (x_new - x0) / np.where(span > 0.0, span, 1.0), 0.0)
    w = np.clip(w, 0.0, 1.0)
    v0 = np.take(values, idx, axis=axis)
    v1 = np.take(values, idx + 1, axis=axis)
    w_b = w[:, None] if axis == 0 else w[None, :]
    out = v0 + (v1 - v0) * w_b
    if outside is not None:
        beyond = (x_new < x_old[0]) | (x_new > x_old[-1])
        if axis == 0:
            out[beyond, :] = outside[None, :]
        else:
            out[:, beyond] = outside[:, None]
    return out


def _resample(mask: Mask, freqs_hz: np.ndarray, times_s: np.ndarray) -> np.ndarray:
    """The mask's gain on a target STFT grid, refusing a field that does not span it."""
    if mask.times_s.shape[0] > 1:
        tol = float(np.median(np.diff(mask.times_s)))
        if mask.times_s[0] > times_s[0] + tol or mask.times_s[-1] < times_s[-1] - tol:
            raise ValueError(
                f"the mask's time axis [{mask.times_s[0]:.3f}, {mask.times_s[-1]:.3f}] s does "
                f"not cover the target's [{times_s[0]:.3f}, {times_s[-1]:.3f}] s; build the "
                f"field over the target's whole span, or trim the target to the field"
            )
    over_time = _interp_along(times_s, mask.times_s, mask.gain, axis=1)
    rest = (
        np.interp(times_s, mask.times_s, mask.rest_gain)
        if mask.times_s.shape[0] > 1
        else np.full(times_s.shape[0], float(mask.rest_gain[0]))
    )
    return _interp_along(freqs_hz, mask.freqs_hz, over_time, axis=0, outside=rest)


def _filter_stft(mono: np.ndarray, sr: int, mask: Mask, n_fft: int, hop: int) -> np.ndarray:
    """One channel through one window: magnitudes scaled, phase kept."""
    spec = librosa.stft(mono, n_fft=n_fft, hop_length=hop, window="hann", center=True)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(spec.shape[1]), sr=sr, hop_length=hop)
    gain = _resample(mask, freqs, times)
    return librosa.istft(
        spec * gain, hop_length=hop, n_fft=n_fft, window="hann", center=True, length=mono.shape[0]
    )


def apply(target: np.ndarray, sr: int, mask: Mask, *, n_fft: int, hop: int) -> np.ndarray:
    """Carve or vocode ``target`` through ``mask``; same shape back, float32.

    ``n_fft`` / ``hop`` / ``sr`` must be the mask's own: the mask's precision
    claim was made for those windows, and a different pair would silently
    change what the notch achieves. With a low-band window on the mask, the
    target is split at the knee and the bass is carved through the long
    window, then summed back with the rest.
    """
    x = np.asarray(target, dtype=np.float64)
    if x.ndim not in (1, 2) or x.shape[0] == 0:
        raise ValueError(
            f"target must be (n_samples,) or (n_samples, n_channels) with n_samples > 0; "
            f"got shape {x.shape}"
        )
    res = mask.resolution
    if (n_fft, hop, sr) != (res.n_fft, res.hop, res.sample_rate):
        raise ValueError(
            f"apply's window (n_fft={n_fft}, hop={hop}, sr={sr}) is not the mask's "
            f"(n_fft={res.n_fft}, hop={res.hop}, sr={res.sample_rate}); the mask's "
            f"precision claim holds only for its own windows — pass those, or rebuild "
            f"the mask with resolution=ResolutionReport({n_fft}, {hop}, {sr})"
        )
    n = x.shape[0]
    if n_fft > n:
        raise ValueError(
            f"target has {n} samples, shorter than the {n_fft}-point window; "
            f"choose a window no longer than the target"
        )
    if res.low_n_fft is not None and res.low_n_fft > n:
        raise ValueError(
            f"target has {n} samples, shorter than the {res.low_n_fft}-point low-band "
            f"window; rebuild the mask with resolution=ResolutionReport({n_fft}, {hop}, {sr}) "
            f"to carve it through the base window alone"
        )
    channels = x[:, None] if x.ndim == 1 else x
    out = np.empty_like(channels)
    for ch in range(channels.shape[1]):
        mono = channels[:, ch]
        if res.low_knee_hz is None or res.low_n_fft is None:
            out[:, ch] = _filter_stft(mono, sr, mask, n_fft, hop)
        else:
            low, high = split_bands(mono, sr, res.low_knee_hz)
            out[:, ch] = _filter_stft(low, sr, mask, res.low_n_fft, hop) + _filter_stft(
                high, sr, mask, n_fft, hop
            )
    result = out[:, 0] if x.ndim == 1 else out
    return result.astype(np.float32)
