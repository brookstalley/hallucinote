"""Spectral operations — carve and vocode a sample against an addressable reference.

A spectral operation is one mechanism: take a reference field (what is present,
where, in time and frequency), build a time-varying mask from it, apply the mask
to the target's magnitude spectrum, resynthesize against the original phase.
Carve attenuates where the reference has energy; vocode keeps only there — one
parameter apart.

The reference field comes from two places and the operations consume either:
**symbolic** (the score's sounding pitches expanded to harmonics — exact,
instant, timbre-blind) or **measured** (the STFT of a captured surface — the
full truth, at the cost of a render). The reference is addressed like any
other node — a track, a return, the main mix, the mix minus the target — and
may change over time as a schedule. Shapes in ``types.py``.
"""
from __future__ import annotations

# ``symbolic`` and ``measured`` read the score and the capture set by design
# and are imported by module path, never from here — importing this package
# must stay free of DB and sync code (tests/unit/test_sample_packages_isolation.py).
from .ops import Mask, apply, build_mask
from .resolution import PrecisionClaim, bin_hz_over, choose_resolution, claim_precision, split_bands
from .schedule import (
    constant_schedule,
    node_ref_from_addr,
    schedule_digest,
    schedule_from_sections,
    schedule_from_spans,
)
from .types import (
    MAX_DEPTH_DB,
    MaskParams,
    NodeRef,
    ReferenceSchedule,
    ReferenceSpan,
    ResolutionReport,
    SpectralField,
    validate_node_ref,
)

__all__ = [
    "MAX_DEPTH_DB", "MaskParams", "NodeRef", "ReferenceSchedule", "ReferenceSpan",
    "ResolutionReport", "SpectralField", "validate_node_ref",
    "Mask", "apply", "build_mask",
    "PrecisionClaim", "bin_hz_over", "choose_resolution", "claim_precision", "split_bands",
    "constant_schedule", "node_ref_from_addr", "schedule_digest",
    "schedule_from_sections", "schedule_from_spans",
]
