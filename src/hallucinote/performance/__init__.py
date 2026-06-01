"""hallucinote.performance — the performance realization layer.

Phase 2a ships the SYMBOLIC performance lens (``lens``): a build-time,
render-independent read-side analyzer over the authored notes, the rhythmic/
dynamic analog of ``theory.lint``. See ``.prawduct/artifacts/performance-model.md``.

Phase 2b's first authoring primitive ships in ``realization``: the declared
:class:`PerformanceProfile` + :func:`apply_profile` — the GERM "Random" channel
(correlated 1/f breathing) that turns a mechanical part *human* (closing the
both-sides loop the lens reads). The genre-baseline profile field, energy↔
performance coupling, and the audio-ground-truth extension (phase 2c) remain
friction-driven follow-ons.
"""
from __future__ import annotations

from hallucinote.performance.lens import (
    EnsemblePair,
    PartPerformance,
    PerfFinding,
    PerformanceReport,
    SectionPerf,
    SectionPerformance,
    analyze_performance,
)
from hallucinote.performance.realization import (
    BREATH,
    HUMAN,
    LOOSE,
    PerformanceProfile,
    apply_profile,
    pink_noise,
)

__all__ = [
    "PerfFinding",
    "PartPerformance",
    "EnsemblePair",
    "SectionPerformance",
    "PerformanceReport",
    "SectionPerf",
    "analyze_performance",
    # authoring (phase 2b)
    "PerformanceProfile",
    "apply_profile",
    "pink_noise",
    "BREATH",
    "HUMAN",
    "LOOSE",
]
