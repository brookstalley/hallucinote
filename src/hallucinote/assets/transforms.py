"""The transform set a recipe is made of — each one a frozen, exactly-recorded step.

A transform is a value: construct it with its parameters, and ``params()``
returns every one of them, because that dict is hashed into the derived
address. The discipline is that nothing a transform does may depend on state
its ``params()`` does not carry — a parameter left out cannot invalidate the
cache, and a cache that cannot be invalidated is a stale file with a current
name. Audio arrives and leaves as float32 ``(n_samples, n_channels)``; the
librosa-backed steps transpose to ``(n_channels, n_samples)`` at the call and
back, so the convention never leaks past this module.

The backend for stretch and pitch is librosa's phase vocoder. It is the
default because it is installed, not because it is good enough for dialogue:
formants smear under it, and whether that is audible is decided by ear on
real material through ``hallucinote stretch-ab``. Until that decision lands,
asking for formant preservation here refuses and points at the harness.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hallucinote.assets.types import TransformContext, validate_audio_array
from hallucinote.audio.onsets import DEFAULT_HOP, detect_onsets_with_strength

STRETCH_AB_COMMAND = "hallucinote stretch-ab"

# The transforms are lowercase on purpose: a recipe in build.py reads as a
# sentence — derive(line, trim(0.4, 2.1), normalize(peak_dbfs=-1.0)) — and
# each name is the step, not a class the author thinks about.


def _refuse_formant_preserve(kind: str) -> None:
    raise ValueError(
        f"{kind}(formant_preserve=True) is not available yet: the librosa backend "
        f"cannot preserve formants, and whether that is audible on your material "
        f"is a listening decision, not a default. Run `{STRETCH_AB_COMMAND}` on the "
        f"source to hear librosa against Rubber Band, then either drop "
        f"formant_preserve or install the winning backend."
    )


def _to_backend(audio: np.ndarray) -> np.ndarray:
    """Our (n, channels) to librosa's (channels, n); mono stays 2-D on purpose."""
    return np.ascontiguousarray(audio.T)


def _from_backend(y: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(y.T).astype(np.float32, copy=False)


def _fit_length(audio: np.ndarray, n_samples: int) -> np.ndarray:
    """Trim or zero-pad so a stretch lands on exactly the bars it was asked for."""
    if audio.shape[0] == n_samples:
        return audio
    if audio.shape[0] > n_samples:
        return audio[:n_samples]
    pad = np.zeros((n_samples - audio.shape[0], audio.shape[1]), dtype=audio.dtype)
    return np.concatenate([audio, pad], axis=0)


@dataclass(frozen=True)
class trim:
    """Keep ``[start_s, end_s)``; ``end_s=None`` keeps to the end of the file.

    An end past the file is clamped to it — an author writing ``trim(0.4, 2.1)``
    against a 2.0 s line wants the tail, not an error — but a start past the
    file is refused, because nothing of the line is left to keep.
    """

    start_s: float
    end_s: float | None = None
    kind: str = field(default="trim", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise ValueError(f"trim start_s must be >= 0; got {self.start_s}")
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError(
                f"trim end_s must be after start_s; got start_s={self.start_s}, "
                f"end_s={self.end_s}"
            )

    def params(self) -> dict[str, Any]:
        return {"start_s": float(self.start_s), "end_s": None if self.end_s is None else float(self.end_s)}

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        audio = validate_audio_array(audio)
        n = audio.shape[0]
        start = int(round(self.start_s * sample_rate))
        if start >= n:
            raise ValueError(
                f"trim start_s={self.start_s} is past the end of {ctx.source.name!r} "
                f"({n / sample_rate:.3f} s); nothing would be left"
            )
        end = n if self.end_s is None else min(n, int(round(self.end_s * sample_rate)))
        return audio[start:end]


@dataclass(frozen=True)
class fade:
    """Linear fade-in over ``in_s`` and fade-out over ``out_s``; zero means none.

    The two ramps may not overlap: a fade that crosses itself is two
    parameters fighting over the same samples, and the author should say
    which one they meant.
    """

    in_s: float = 0.0
    out_s: float = 0.0
    kind: str = field(default="fade", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.in_s < 0 or self.out_s < 0:
            raise ValueError(
                f"fade in_s and out_s must be >= 0; got in_s={self.in_s}, out_s={self.out_s}"
            )

    def params(self) -> dict[str, Any]:
        return {"in_s": float(self.in_s), "out_s": float(self.out_s)}

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        audio = validate_audio_array(audio)
        n = audio.shape[0]
        n_in = int(round(self.in_s * sample_rate))
        n_out = int(round(self.out_s * sample_rate))
        if n_in + n_out > n:
            raise ValueError(
                f"fade in_s={self.in_s} + out_s={self.out_s} exceeds the "
                f"{n / sample_rate:.3f} s of {ctx.source.name!r}; the ramps would overlap. "
                f"Shorten one, or trim less first."
            )
        out = audio.copy()
        if n_in:
            out[:n_in] *= np.linspace(0.0, 1.0, n_in, endpoint=False, dtype=np.float32)[:, None]
        if n_out:
            out[n - n_out:] *= np.linspace(1.0, 0.0, n_out, endpoint=False, dtype=np.float32)[:, None]
        return out


@dataclass(frozen=True)
class normalize:
    """Scale so the sample peak sits at ``peak_dbfs``.

    Silence is returned as it came: there is no gain that gives silence a
    peak, and refusing would make a recipe fail on a line whose only fault
    is a quiet source.
    """

    peak_dbfs: float = -1.0
    kind: str = field(default="normalize", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.peak_dbfs > 0:
            raise ValueError(
                f"normalize peak_dbfs must be <= 0 (0 dBFS is full scale); got {self.peak_dbfs}"
            )

    def params(self) -> dict[str, Any]:
        return {"peak_dbfs": float(self.peak_dbfs)}

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        audio = validate_audio_array(audio)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak == 0.0:
            return audio
        target = 10.0 ** (self.peak_dbfs / 20.0)
        return (audio * np.float32(target / peak)).astype(np.float32, copy=False)


@dataclass(frozen=True)
class reverse:
    """Play the line backwards. Its own inverse, which the cache test relies on."""

    kind: str = field(default="reverse", init=False, repr=False, compare=False)

    def params(self) -> dict[str, Any]:
        return {}

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        return np.ascontiguousarray(validate_audio_array(audio)[::-1])


@dataclass(frozen=True)
class pitch_shift:
    """Shift by ``semitones`` (fractional allowed) without changing duration.

    ``formant_preserve`` is recorded even while it can only be ``False``, so a
    file made without it can never be confused for one made with it once a
    backend that honours it exists.
    """

    semitones: float
    formant_preserve: bool = False
    kind: str = field(default="pitch_shift", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.semitones):
            raise ValueError(f"pitch_shift semitones must be finite; got {self.semitones}")
        if self.formant_preserve:
            _refuse_formant_preserve("pitch_shift")

    def params(self) -> dict[str, Any]:
        return {"semitones": float(self.semitones), "formant_preserve": bool(self.formant_preserve)}

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        import librosa

        audio = validate_audio_array(audio)
        if self.semitones == 0.0:
            return audio
        shifted = librosa.effects.pitch_shift(
            _to_backend(audio), sr=sample_rate, n_steps=float(self.semitones)
        )
        return _fit_length(_from_backend(shifted), audio.shape[0])


@dataclass(frozen=True)
class stretch_to_bars:
    """Stretch or compress the whole line to exactly ``bars`` at ``bpm``.

    The target is a length in samples, so the result is trimmed or padded to
    it after the vocoder — a clip that is asked for two bars gets two bars,
    not two bars and a frame. ``beats_per_bar`` defaults to four because that
    is the meter most lines are cut against; a song in seven says so here.
    """

    bars: float
    bpm: float
    beats_per_bar: int = 4
    formant_preserve: bool = False
    kind: str = field(default="stretch_to_bars", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.bars <= 0:
            raise ValueError(f"stretch_to_bars bars must be > 0; got {self.bars}")
        if self.bpm <= 0:
            raise ValueError(f"stretch_to_bars bpm must be > 0; got {self.bpm}")
        if self.beats_per_bar < 1:
            raise ValueError(f"stretch_to_bars beats_per_bar must be >= 1; got {self.beats_per_bar}")
        if self.formant_preserve:
            _refuse_formant_preserve("stretch_to_bars")

    def params(self) -> dict[str, Any]:
        return {
            "bars": float(self.bars),
            "bpm": float(self.bpm),
            "beats_per_bar": int(self.beats_per_bar),
            "formant_preserve": bool(self.formant_preserve),
        }

    def target_seconds(self) -> float:
        return self.bars * self.beats_per_bar * 60.0 / self.bpm

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        import librosa

        audio = validate_audio_array(audio)
        n = audio.shape[0]
        if n == 0:
            raise ValueError(f"stretch_to_bars cannot stretch an empty {ctx.source.name!r}")
        target_n = int(round(self.target_seconds() * sample_rate))
        if target_n < 1:
            raise ValueError(
                f"stretch_to_bars target of {self.target_seconds():.6f} s is shorter than one sample"
            )
        # librosa's rate > 1 shortens; the ratio is source length over target.
        rate = n / target_n
        stretched = librosa.effects.time_stretch(_to_backend(audio), rate=rate)
        return _fit_length(_from_backend(stretched), target_n)


@dataclass(frozen=True)
class chop_at_onsets:
    """Split the line into one piece per onset; a splitting transform.

    Each piece runs from one onset to the next, the last to the end of the
    file, and whatever precedes the first onset is discarded — it is not a
    hit. ``min_gap_s`` is the musical guard: spectral-flux detection also
    fires on a hard offset and on a double-trigger, and onsets closer than
    the gap to the previous kept one are folded into it.

    Detection calls ``hallucinote.audio.onsets.detect_onsets_with_strength``
    directly — the calibrated front-end the timing and cross-rhythm lenses
    share — rather than a segments layer of the features package, so this
    module has no import on anything built beside it.
    """

    min_gap_s: float
    kind: str = field(default="chop_at_onsets", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.min_gap_s < 0:
            raise ValueError(f"chop_at_onsets min_gap_s must be >= 0; got {self.min_gap_s}")

    def params(self) -> dict[str, Any]:
        return {"min_gap_s": float(self.min_gap_s)}

    def onset_samples(self, audio: np.ndarray, sample_rate: int) -> list[int]:
        """The kept onsets, in samples — exposed so a lens can show the cuts."""
        audio = validate_audio_array(audio)
        mono = audio.mean(axis=1).astype(np.float32, copy=False)
        samples, _strengths = detect_onsets_with_strength(mono, sample_rate, hop_length=DEFAULT_HOP)
        min_gap = int(round(self.min_gap_s * sample_rate))
        kept: list[int] = []
        for s in samples:
            s_int = int(s)
            if not kept or s_int - kept[-1] >= min_gap:
                kept.append(s_int)
        return kept

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        audio = validate_audio_array(audio)
        kept = self.onset_samples(audio, sample_rate)
        if not kept:
            raise ValueError(
                f"chop_at_onsets found no onsets in {ctx.source.name!r}: the material "
                f"has no transients to cut at. Cut it by hand with trim(), or chop a "
                f"line that has attacks."
            )
        bounds = kept + [audio.shape[0]]
        return [np.ascontiguousarray(audio[a:b]) for a, b in zip(bounds, bounds[1:])]


__all__ = [
    "STRETCH_AB_COMMAND",
    "trim",
    "fade",
    "normalize",
    "reverse",
    "pitch_shift",
    "stretch_to_bars",
    "chop_at_onsets",
]
