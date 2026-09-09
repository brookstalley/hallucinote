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
