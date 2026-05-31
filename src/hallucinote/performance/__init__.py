"""hallucinote.performance — the performance realization layer (read side first).

Phase 2a ships the SYMBOLIC performance lens (``lens``): a build-time,
render-independent read-side analyzer over the authored notes, the rhythmic/
dynamic analog of ``theory.lint``. See ``.prawduct/artifacts/performance-model.md``.

Authoring profiles (phase 2b) and the audio-ground-truth extension (phase 2c)
are deliberately not here yet — they are friction-driven follow-ons.
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

__all__ = [
    "PerfFinding",
    "PartPerformance",
    "EnsemblePair",
    "SectionPerformance",
    "PerformanceReport",
    "SectionPerf",
    "analyze_performance",
]
