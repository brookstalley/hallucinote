"""hallucinote.performance.realization — the authoring side (phase 2b, first primitive).

The read-side lens (``lens`` + ``correlation``) answers *"is this part mechanical,
human, or sloppy?"*. This module is its authoring counterpart: it lets a composer
**declare** a performance profile and have the part **realized** so the lens reads
it as *human* — closing the both-sides loop (performance-model §4, §7; principle
4, "both sides, always").

**The gap this fills.** The generators already bake a *deterministic* feel — the
``lazy`` / ``push`` / ``lag`` constant offsets (proto-profiles, §4.4). But a
constant offset is a *precisely-shifted grid*, and the lens correctly reads that
as **mechanical** ("tightness, not lateness, is the mechanical signal"). The
white-noise clip-humanize path reads as **sloppy**. Neither produces *human*. The
missing piece — the one the research names as decisive (§3.8, Hennig 2011) — is
the **GERM "Random" term: a small, additive, _1/f-correlated_ deviation**, never
white noise. The correlation STRUCTURE (not the magnitude) is what reads human.

**Ruler, not stamp (§2.1, the KTH metaperformer pattern).** The composer declares
a :class:`PerformanceProfile` (the *what* — magnitude, genre calibration); this
module computes the per-onset deviations (the *how*). The intelligence is in the
declared profile choice, not a trained model — honoring prefer-LLM-over-
deterministic-module: the LLM picks the profile, a deterministic ruler realizes it.

**Deterministic by seed.** A song build must be reproducible (author-as-code, the
build re-runs and events fall out). The profile carries a ``seed``; same
``(notes, profile, seed)`` always yields the same realization. Vary the seed
per part so two parts don't share an identical breathing stream (which would read
as artificial ensemble lock).

**Scope (this primitive).** Adds zero-mean **correlated timing + velocity
breathing** on top of whatever deterministic feel the generators already baked —
it does NOT re-author the constant lay-back (the generators own that; one source
of truth). The genre-baseline-as-declared-profile-field, the energy↔performance
coupling (§5), and phrase-arc curves (§4.3) are deferred 2b/2c follow-ons, built
when a genre forces them (discovered-from-friction). See
``.prawduct/artifacts/performance-model.md`` §8.

Pure stdlib — no numpy — matching the rest of ``performance`` + ``theory``.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Sequence

NoteDict = dict[str, Any]

# The lens reads timing deviation against the 16th-note grid (lens.GRID_SUBDIVISION_
# BEATS = 0.25); an onset more than half a cell off snaps to the neighbour and
# corrupts the recovered deviation. We clamp each breathing offset well inside the
# half-cell (0.125) so that even stacked on a generator's baked lay-back (~0.04)
# the total stays in-cell. With the calibrated sigmas below a clamp is a rare-tail
# guard, never the common path.
_MAX_TIMING_OFFSET = 0.08

# Floor the lens uses to call a part mechanically tight (lens._MECHANICAL_STDEV_MAX).
# A profile whose realized timing stdev sits at/below this would still read
# mechanical, defeating the purpose — so the presets sit comfortably above it and
# __post_init__ warns nobody below it by construction (timing_sigma documented as
# "must exceed ~0.01 beat to escape the mechanical floor").
_MECHANICAL_FLOOR = 0.01


def pink_noise(n: int, *, seed: int, octaves: int = 5) -> list[float]:
    """Voss-McCartney pink (1/f) noise — deviation correlated across time scales.

    The canonical generator of *structured* deviation: a fluctuation influences
    later fluctuations (the long-range correlation the lens reads as human, vs the
    memoryless white noise it reads as sloppy — performance-model §3.8). Pure
    stdlib, deterministic by ``seed``. Returns a length-``n`` series whose
    magnitude is arbitrary (≈ ``sqrt(octaves)`` stdev); callers normalize + scale.

    This is the production home of the algorithm the correlation calibration was
    measured against — ``correlation``'s thresholds (``STRUCTURED_ACF_MIN`` etc.)
    are valid precisely because realization emits *this* series.
    """
    if n <= 0:
        return []
    rng = random.Random(seed)
    rows = [rng.gauss(0, 1) for _ in range(octaves)]
    out: list[float] = []
    for i in range(n):
        for b in range(octaves):
            if i % (1 << b) == 0:
                rows[b] = rng.gauss(0, 1)
        out.append(sum(rows))
    return out


def _normalized(series: Sequence[float]) -> list[float]:
    """Zero-mean, unit population-stdev. A linear transform — so it preserves the
    lag-1 autocorrelation EXACTLY (human-vs-sloppy is a property of structure, not
    magnitude), while letting the profile dial magnitude independently. Returns
    all-zeros for a series too short or flat to have a spread to normalize."""
    n = len(series)
    if n < 2:
        return [0.0] * n
    mean = sum(series) / n
    centered = [x - mean for x in series]
    var = sum(c * c for c in centered) / n
    if var == 0.0:
        return [0.0] * n
    sd = math.sqrt(var)
    return [c / sd for c in centered]


def _scaled_pink(n: int, *, seed: int, sigma: float, octaves: int) -> list[float]:
    """A length-``n`` 1/f series with population-stdev ``sigma`` (and zero mean)."""
    if sigma <= 0.0:
        return [0.0] * max(0, n)
    return [v * sigma for v in _normalized(pink_noise(n, seed=seed, octaves=octaves))]


@dataclass(frozen=True)
class PerformanceProfile:
    """A declared performance profile — the ruler's input (performance-model §4.1).

    The composer/LLM declares *what* the feel should be; :func:`apply_profile`
    computes *how* (the per-onset deviations). This first primitive carries the
    GERM "Random" channel — correlated 1/f breathing — plus the KTH magnitude dial.

    Fields:
      ``name`` — a human label for the profile (``"reggae-pocket"``, ``"human"``).
        Names are how profiles become reusable, declared intent rather than raw
        numbers; record it alongside the part in the song's decision corpus.
      ``timing_sigma`` — population-stdev of the timing breathing, in **beats**.
        Small and genre-calibrated, never maximized (§3.9: exaggerated microtiming
        *lowers* groove). Must exceed ~0.01 beat to escape the lens's mechanical
        floor; the calibrated presets do.
      ``velocity_sigma`` — population-stdev of the velocity breathing, in **MIDI
        units**. Human dynamic shaping runs ~8–20; >2 escapes the flat-dynamics
        floor.
      ``k`` — the KTH metaperformer magnitude dial (default 1.0) scaling BOTH
        sigmas at once. One knob to make a whole profile more/less pronounced.
      ``seed`` — determinism. Vary it per part.
      ``octaves`` — Voss-McCartney depth; the calibration used 5. Rarely changed.
    """

    name: str
    timing_sigma: float
    velocity_sigma: float
    k: float = 1.0
    seed: int = 0
    octaves: int = 5

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PerformanceProfile.name must be non-empty")
        if self.timing_sigma < 0.0 or self.velocity_sigma < 0.0:
            raise ValueError(
                f"PerformanceProfile sigmas must be non-negative; got "
                f"timing_sigma={self.timing_sigma}, velocity_sigma={self.velocity_sigma}"
            )
        if self.k < 0.0:
            raise ValueError(f"PerformanceProfile.k must be non-negative; got {self.k}")
        if self.octaves < 1:
            raise ValueError(f"PerformanceProfile.octaves must be >= 1; got {self.octaves}")

    @property
    def effective_timing_sigma(self) -> float:
        return self.timing_sigma * self.k

    @property
    def effective_velocity_sigma(self) -> float:
        return self.velocity_sigma * self.k

    def to_dict(self) -> dict[str, Any]:
        """The declared profile as a plain dict — the boundary for recording it in
        the song's decision/annotation corpus (the *why* lives in markdown)."""
        return {
            "name": self.name,
            "timing_sigma": self.timing_sigma,
            "velocity_sigma": self.velocity_sigma,
            "k": self.k,
            "seed": self.seed,
            "octaves": self.octaves,
        }


# ---------------------------------------------------------------------------
# Calibrated magnitude presets (NOT genre grooves — those are friction-driven).
# All three read `human` on the lens: the lag-1 acf of 1/f noise is magnitude-
# invariant (~0.35–0.55 at N>=32 >= STRUCTURED_ACF_MIN), so they differ only in
# how pronounced the breathing is, never in the human/sloppy verdict. Genre
# baselines (reggae drag, jazz swing) stay the generators' job until a genre
# forces a declared profile field for them.
# ---------------------------------------------------------------------------

#: A hair of life — barely-there breathing, still clear of the mechanical floor.
BREATH = PerformanceProfile(name="breath", timing_sigma=0.015, velocity_sigma=5.0)

#: The general-purpose human pocket — the sensible default.
HUMAN = PerformanceProfile(name="human", timing_sigma=0.020, velocity_sigma=8.0)

#: A looser, more pronounced pocket — still correlated (human, not sloppy).
LOOSE = PerformanceProfile(name="loose", timing_sigma=0.030, velocity_sigma=12.0)


def _onset_offsets(
    onsets: Sequence[float], *, seed: int, sigma: float, octaves: int
) -> dict[float, float]:
    """One clamped 1/f timing offset per distinct onset, in time order. Notes that
    share an onset (a block chord) move together — the chord's *placement* carries
    the feel; its verticality is preserved."""
    series = _scaled_pink(len(onsets), seed=seed, sigma=sigma, octaves=octaves)
    return {
        onset: max(-_MAX_TIMING_OFFSET, min(_MAX_TIMING_OFFSET, off))
        for onset, off in zip(onsets, series)
    }


def apply_profile(
    notes: Sequence[NoteDict],
    profile: PerformanceProfile,
    *,
    seed: int | None = None,
) -> list[NoteDict]:
    """Realize ``profile`` over ``notes`` — add 1/f-correlated timing + velocity
    breathing so the lens reads the part as *human*.

    Returns NEW note dicts (input untouched; the build re-runs and re-realizes).
    Timing breathing is per **onset** (a chord moves as a unit); velocity breathing
    is per **note** (each voice breathes). Both are zero-mean and deterministic.

    ``seed`` overrides ``profile.seed`` for this call — the ergonomic way to give
    each part its own breathing stream without ``dataclasses.replace``. Timing and
    velocity draw from independent streams derived from the seed, so they don't
    move in lockstep.

    Onsets are clamped to ``>= 0`` (the mutator boundary rejects negative absolute
    beats); with sub-grid sigmas this touches at most a single bar-1 downbeat and
    leaves the deviation structure intact.
    """
    if not notes:
        return []
    base_seed = profile.seed if seed is None else seed
    ordered = sorted(notes, key=lambda n: (float(n["start_beats"]), int(n["pitch"])))

    # Timing: one offset per distinct onset (stream A).
    distinct_onsets = sorted({float(n["start_beats"]) for n in ordered})
    offset_by_onset = _onset_offsets(
        distinct_onsets,
        seed=base_seed,
        sigma=profile.effective_timing_sigma,
        octaves=profile.octaves,
    )

    # Velocity: one delta per note in time order (stream B — a distinct seed so
    # timing and dynamics breathe independently).
    vel_deltas = _scaled_pink(
        len(ordered),
        seed=base_seed + 1_000_003,
        sigma=profile.effective_velocity_sigma,
        octaves=profile.octaves,
    )

    realized: list[NoteDict] = []
    for note, dvel in zip(ordered, vel_deltas):
        start = float(note["start_beats"])
        new_start = max(0.0, start + offset_by_onset[start])
        new_vel = max(1, min(127, round(float(note["velocity"]) + dvel)))
        realized.append({**note, "start_beats": new_start, "velocity": new_vel})
    return realized
