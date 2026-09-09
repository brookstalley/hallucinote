"""Carve and vocode as recipe steps — the reference's fingerprint rides in the address.

A spectral step is a transform like any other: a frozen value whose
``params()`` is hashed into the derived address. What makes it different is
that its result depends on the score. A carve against the bassline is stale
the moment the bassline changes, and nothing in the audio says so — so the
fingerprint of the reference field (the notes and placements the schedule
reaches for a symbolic field; the capture take and analysis code for a
measured one) is a parameter here, and a changed reference is a changed
address. The file cannot outlive what it was carved against.

Two routes build the field and they are never confused: ``field='symbolic'``
reads the score through the DB and costs nothing; ``field='measured'`` reads
a capture set and is what gets committed. A measured step without a capture
refuses, and a symbolic step handed a capture refuses too — the capture it
would silently ignore is the one the author thinks is in use.

The circular dependency R4.5 names — a part derived from a sample that is
then carved against that part — is declared by the order of ``derive`` calls
in ``build.py``: the follower runs, its notes land, the carve reads them.
There is no pipeline object to build; the order in the file is the order.

Discipline: this module must import without the DB (``build.py`` and the
generators open it), so the two field builders that read state are imported
inside the calls that need them, never at the top. ``conn``, ``beat_map``
and ``capture`` are how the step reaches the score and the capture; they are
objects, not parameters, and ``params()`` says exactly what stands in for
them.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import cached_property
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from hallucinote.assets.types import TransformContext, validate_audio_array
from hallucinote.audio.bark import bark_band_map
from hallucinote.audio.io import CaptureSet
from hallucinote.audio.section import TempoSegment
from hallucinote.features.types import BeatMap
from hallucinote.spectral import ops
from hallucinote.spectral.resolution import DEFAULT_HOP, DEFAULT_N_FFT
from hallucinote.spectral.schedule import schedule_digest
from hallucinote.spectral.types import (
    MaskParams,
    ReferenceSchedule,
    ResolutionReport,
    SpectralField,
)

logger = logging.getLogger("hallucinote.assets.transforms_spectral")

FieldRoute = Literal["symbolic", "measured"]
_ROUTES: tuple[FieldRoute, ...] = ("symbolic", "measured")

# The beat map enters the address as its answer over the schedule: one
# ``[beat, seconds]`` pair per beat, rounded to a microsecond, which is finer
# than any hop and coarse enough that float noise cannot move an address.
_CLOCK_DECIMALS = 6


def _jsonable(value: float | np.ndarray) -> float | list[float]:
    """A mask parameter as the address sees it — a float, or a per-frame list."""
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim == 0:
        return float(arr)
    return [float(v) for v in arr.tolist()]


@dataclass(frozen=True, eq=False)
class _spectral_step:
    """What carve and vocode share: a schedule, a mask, and a route to a field.

    ``mask`` carries the musical parameters (harmonic depth, notch width in
    cents, depth, smoothing — each may be a per-frame array); its polarity
    must agree with the step, so a recipe never reads ``carve`` while doing
    a vocode. ``n_fft`` / ``hop`` are the analysis window: the raster the
    field is placed on and the window the target is carved through. A longer
    ``n_fft`` is the author's lever for a finer bass notch, at the cost of
    time resolution; the precision the window achieves at the lowest
    reference pitch is logged at apply time and readable from ``mask_for``.
    """

    schedule: ReferenceSchedule
    mask: MaskParams
    field: FieldRoute = "symbolic"
    capture: CaptureSet | None = None
    conn: sqlite3.Connection | None = None
    beat_map: BeatMap | None = None
    song_id: str | None = None
    stem_gains: Mapping[str, float] | None = None
    tempo_segments: Sequence[TempoSegment] = ()
    n_fft: int = DEFAULT_N_FFT
    hop: int = DEFAULT_HOP
    # A tuned song's TuningData (the core never imports the tuning bolt-on, so
    # the author passes it in). Not a parameter of the mask: what it changes is
    # which frequencies the reference sounds at, and that is what `fingerprint`
    # digests.
    tuning: Any = None
    kind: str = dc_field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.kind not in ("carve", "vocode"):
            raise ValueError("a spectral step is built with carve(...) or vocode(...)")
        if self.mask.polarity != self.kind:
            raise ValueError(
                f"{self.kind}() got MaskParams(polarity={self.mask.polarity!r}); the step "
                f"decides the polarity, so build the params with polarity={self.kind!r} "
                f"or use {self.mask.polarity}() instead"
            )
        if self.field not in _ROUTES:
            raise ValueError(
                f"{self.kind}(field={self.field!r}): field must be 'symbolic' (the score, "
                "read from the DB) or 'measured' (a capture set)"
            )
        if self.field == "measured" and self.capture is None:
            raise ValueError(
                f"{self.kind}(field='measured') needs capture=<CaptureSet>: the measured "
                "field is the STFT of a render, and there is none to read. Load one with "
                "hallucinote.audio.io.load_capture(<captures>/manifest.json), or iterate "
                "with field='symbolic' until there is a render to commit against"
            )
        if self.field == "symbolic" and self.capture is not None:
            raise ValueError(
                f"{self.kind}(field='symbolic') was given a capture it would not read; "
                "the two routes are never substituted for each other. Pass "
                "field='measured' to carve against the capture, or drop capture="
            )
        if self.field == "symbolic" and (self.stem_gains is not None or self.tempo_segments):
            raise ValueError(
                f"{self.kind}(field='symbolic') takes no stem_gains or tempo_segments: "
                "they shape how a capture's surfaces are summed and placed, and the "
                "symbolic field reads the score, not a capture"
            )
        if self.conn is None:
            raise ValueError(
                f"{self.kind}() needs conn=<sqlite3.Connection> to the song's DB: the "
                "symbolic field reads the notes the schedule's nodes play, and the "
                "measured field resolves each node to its captured surface through it"
            )
        if self.beat_map is None:
            raise ValueError(
                f"{self.kind}() needs beat_map=<BeatMap> anchoring the target's seconds to "
                "song beats — hallucinote.features.beatmap.beat_map_for_placement(...) "
                "for a clip placed at a beat; without it no note can be placed on the "
                "sample's clock"
            )
        if self.n_fft <= 0 or self.hop <= 0:
            raise ValueError(f"{self.kind}() n_fft and hop must be > 0; got {self.n_fft}, {self.hop}")
        object.__setattr__(self, "tempo_segments", tuple(self.tempo_segments))

    # ------------------------------------------------------------------ #
    # the address
    # ------------------------------------------------------------------ #

    def params(self) -> dict[str, Any]:
        """Every parameter the result depends on, and nothing that is an object.

        ``conn``, ``capture`` and ``beat_map`` are excluded: a connection is
        not a value, a capture is identified by its take in ``fingerprint``,
        and the beat map is recorded as ``clock`` — its answer at every beat
        of the schedule — because the map is the one input that moves the
        whole reference on the sample without changing a note. ``song_id``
        is excluded too: it selects what is read, and what was read is what
        ``fingerprint`` digests.
        """
        return {
            "field": self.field,
            "fingerprint": self.fingerprint(),
            "schedule": schedule_digest(self.schedule),
            "clock": self._clock(),
            "harmonic_depth": int(self.mask.harmonic_depth),
            "notch_width_cents": _jsonable(self.mask.notch_width_cents),
            "depth_db": _jsonable(self.mask.depth_db),
            "smoothing_s": float(self.mask.smoothing_s),
            "n_fft": int(self.n_fft),
            "hop": int(self.hop),
            "stem_gains": (
                None if self.stem_gains is None
                else {str(k): float(v) for k, v in sorted(self.stem_gains.items())}
            ),
            "tempo_segments": [
                [float(s.start_beat), float(s.bpm), str(s.ramp)] for s in self.tempo_segments
            ],
        }

    def fingerprint(self) -> str:
        """What the reference field is built from, as the field builder digests it.

        Symbolic: the notes, placements, schedule and tuning the schedule
        reaches — read afresh on every call, because the DB can change under
        a step that ``build.py`` constructed earlier, and a cached digest
        would name a stale file. Measured: the capture take, the analysis
        code and the schedule, read once — a loaded capture never changes.
        """
        if self.field == "measured":
            return self._measured_field.fingerprint
        return self._probe_symbolic_fingerprint()

    def _clock(self) -> list[list[float]]:
        assert self.beat_map is not None
        beats = np.arange(self.schedule.start_beat, self.schedule.end_beat, 1.0).tolist()
        beats.append(self.schedule.end_beat)
        return [
            [round(float(b), _CLOCK_DECIMALS), round(self.beat_map.beats_to_seconds(float(b)), _CLOCK_DECIMALS)]
            for b in beats
        ]

    def _probe_symbolic_fingerprint(self) -> str:
        """The symbolic digest, read from the score without rasterizing a field."""
        from hallucinote.spectral.symbolic import symbolic_fingerprint

        assert self.conn is not None
        return symbolic_fingerprint(
            self.conn, self.schedule, song_id=self.song_id, tuning=self.tuning,
        )

    @cached_property
    def _measured_field(self) -> SpectralField:
        from hallucinote.spectral.measured import measured_field

        assert self.capture is not None and self.conn is not None and self.beat_map is not None
        return measured_field(
            self.capture,
            self.schedule,
            self.beat_map,
            conn=self.conn,
            n_fft=self.n_fft,
            hop=self.hop,
            tempo_segments=self.tempo_segments,
            stem_gains=self.stem_gains,
        )

    def _symbolic_field(self, duration_s: float, sample_rate: int) -> SpectralField:
        """The score rasterized onto the STFT grid the target will be carved on,
        spanning the whole target so the mask covers every frame of it."""
        from hallucinote.spectral.symbolic import symbolic_axes, symbolic_field

        assert self.conn is not None and self.beat_map is not None
        resolution = ResolutionReport(n_fft=self.n_fft, hop=self.hop, sample_rate=sample_rate)
        freqs, times = symbolic_axes(resolution, duration_s=duration_s)
        return symbolic_field(
            self.conn,
            self.schedule,
            self.beat_map,
            freqs_hz=freqs,
            times_s=times,
            harmonic_depth=self.mask.harmonic_depth,
            resolution=resolution,
            song_id=self.song_id,
            tuning=self.tuning,
        )

    def field_for(self, n_samples: int, sample_rate: int) -> SpectralField:
        """The reference field for a target of ``n_samples`` at ``sample_rate``.

        Refuses a field with no energy: a schedule that reaches no sounding
        note over the target is almost always a misplaced beat map, and a
        carve that changes nothing would be cached under a current name.
        """
        if n_samples <= 0 or sample_rate <= 0:
            raise ValueError(f"target needs n_samples > 0 and sample_rate > 0; got {n_samples}, {sample_rate}")
        if self.field == "measured":
            field = self._measured_field
            if field.resolution.sample_rate != sample_rate:
                raise ValueError(
                    f"{self.kind}(field='measured'): the capture is {field.resolution.sample_rate} Hz "
                    f"but the target is {sample_rate} Hz, and a mask holds only at its own "
                    "rate. Render the capture at the source's rate, or ingest the source at "
                    "the capture's"
                )
        else:
            field = self._symbolic_field(n_samples / sample_rate, sample_rate)
        if not field.magnitude.size or float(field.magnitude.max()) <= 0.0:
            raise ValueError(
                f"{self.kind}(): the {self.field} reference sounds nothing over the target "
                f"(schedule beats [{self.schedule.start_beat:g}, {self.schedule.end_beat:g}), "
                f"target beats [{self._beat_at(0.0):g}, {self._beat_at(n_samples / sample_rate):g})). "
                "Check the beat_map anchors the sample where it is placed, and that the "
                "schedule's nodes play there"
            )
        return field

    def _beat_at(self, seconds: float) -> float:
        assert self.beat_map is not None
        return self.beat_map.seconds_to_beats(seconds)

    def mask_for(self, n_samples: int, sample_rate: int) -> ops.Mask:
        """The mask ``apply`` will use on such a target; ``.precision`` is the R3.8 claim.

        The mask is built through the step's own window, not a longer
        low-band one: both field builders raster on the base window's bins,
        so a longer apply window cannot narrow a notch below that bin and
        would only make a short target refuse. The claim reports the width
        the base window resolves at the lowest reference pitch; a finer
        notch there is a finer field raster, which ``n_fft`` buys.
        """
        field = self.field_for(n_samples, sample_rate)
        return ops.build_mask(
            field,
            self.mask,
            bark=bark_band_map(sample_rate, self.n_fft),
            resolution=field.resolution,
        )

    # ------------------------------------------------------------------ #
    # the transform
    # ------------------------------------------------------------------ #

    def apply(
        self, audio: np.ndarray, sample_rate: int, ctx: TransformContext
    ) -> np.ndarray | list[np.ndarray]:
        audio = validate_audio_array(audio)
        mask = self.mask_for(audio.shape[0], sample_rate)
        if mask.precision is not None:
            message = f"{self.kind} of {ctx.source.name!r} ({self.field}): {mask.precision.describe()}"
            if mask.precision.met:
                logger.info(message)
            else:
                logger.warning(message)
        out = ops.apply(
            audio, sample_rate, mask, n_fft=mask.resolution.n_fft, hop=mask.resolution.hop
        )
        return validate_audio_array(out, where=f"{self.kind} output")


@dataclass(frozen=True, eq=False)
class carve(_spectral_step):
    """Attenuate the target where the reference has energy.

    ``carve(schedule, MaskParams('carve', ...), conn=conn, beat_map=bm)`` reads
    the score; add ``field='measured', capture=load_capture(...)`` to commit
    against a render. The field's fingerprint is in ``params()``, so the
    derived file's address changes when the reference does.
    """

    kind: str = dc_field(default="carve", init=False, repr=False, compare=False)


@dataclass(frozen=True, eq=False)
class vocode(_spectral_step):
    """Keep the target only where the reference has energy — the same mask, inverted."""

    kind: str = dc_field(default="vocode", init=False, repr=False, compare=False)


__all__ = ["FieldRoute", "carve", "vocode"]
