"""MixReport baseline diffs — the ``compare_to`` resolver (AUD-4W7K).

Diffs two MixReports at the ``to_json_dict()`` boundary: both sides are the
serialized wire format (the baseline is read back from
``songs/<slug>/analysis/<iso-ts>.json``, the current report is serialized
in-process), so the JSON schema is the contract and no deserializer is
needed. Consumers discriminate by ``schema_version`` per the report module
docstring — a version mismatch refuses loudly rather than diffing
incomparable shapes.

Deltas are NEUTRAL EVIDENCE, not verdicts. A −0.6 dB master move is good in
one song and a regression in another; only declared intent can grade it, so
this module emits no findings — the interpreter (or the user) reads the
deltas against intent like every other lens.

Significance thresholds were calibrated against the sun-zone-done analysis
set (6 real reports, 2026-05-29..06-03): re-captures of the same mix sit at
|Δ| ≈ 0.02–0.13 dB for lufs_i / lufs_m_peak / true_peak_dbtp while real
mix-version changes span 0.4–2.5 dB, so 0.5 dB separates noise from signal
with margin. lufs_s_median is the exception — it wobbles up to ~0.6 dB
between near-identical takes (3 s short-term blocks are sensitive to
arrangement timing), so it carries a 1.0 dB threshold of its own.
"""
from __future__ import annotations

from typing import Any

# Calibrated significance floors (dB). See module docstring for evidence.
SIGNIFICANCE_DEFAULT_DB = 0.5
SIGNIFICANCE_SHORT_TERM_DB = 1.0

SIGNIFICANCE_DB: dict[str, float] = {
    "lufs_i": SIGNIFICANCE_DEFAULT_DB,
    "lufs_s_median": SIGNIFICANCE_SHORT_TERM_DB,
    "lufs_m_peak": SIGNIFICANCE_DEFAULT_DB,
    "true_peak_dbtp": SIGNIFICANCE_DEFAULT_DB,
}


def diff_reports(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    baseline_ref: str | None = None,
) -> dict[str, Any]:
    """Diff two ``to_json_dict()``-shaped MixReports → a ``compare_to`` payload.

    Per-surface loudness deltas (master + stems + returns, keyed by
    ``track_id`` so added/removed surfaces surface explicitly instead of
    misaligning) plus the overshoot count. A metric that is ``null`` on
    either side (the honest non-finite sentinel) yields ``delta: null,
    significant: false`` — never a fabricated number.

    ``baseline_ref`` is provenance for the consumer (the path or seq the
    caller resolved the baseline from); this function never does IO.

    Raises ``ValueError`` on schema-version or song mismatch — a comparison
    that can't be made honestly is refused, not approximated. (Cross-song /
    reference-track baselines are explicitly out of AUD-4W7K's scope.)
    """
    if current.get("schema_version") != baseline.get("schema_version"):
        raise ValueError(
            f"cannot diff schema_version={current.get('schema_version')!r} "
            f"against baseline schema_version={baseline.get('schema_version')!r}"
        )
    if current.get("song_slug") != baseline.get("song_slug"):
        raise ValueError(
            f"baseline is for song {baseline.get('song_slug')!r}, current report "
            f"is for {current.get('song_slug')!r} — cross-song baselines are not "
            "supported (reference-track comparison is a separate backlog item)"
        )

    deltas = _surface_deltas(current["master"], baseline["master"])

    current_surfaces = _by_track_id(current)
    baseline_surfaces = _by_track_id(baseline)
    for track_id in sorted(current_surfaces.keys() & baseline_surfaces.keys()):
        deltas.extend(
            _surface_deltas(current_surfaces[track_id], baseline_surfaces[track_id])
        )

    overshoots_before = len(baseline.get("overshoots", []))
    overshoots_after = len(current.get("overshoots", []))

    return {
        "baseline": {
            "ref": baseline_ref,
            "captured_at": baseline.get("captured_at"),
            "analyzer_signature": baseline.get("analyzer_signature"),
            "schema_version": baseline.get("schema_version"),
        },
        "deltas": deltas,
        "overshoot_count": {
            "before": overshoots_before,
            "after": overshoots_after,
            "delta": overshoots_after - overshoots_before,
            # An overshoot appearing or disappearing is always worth a look.
            "significant": overshoots_after != overshoots_before,
        },
        "added_surfaces": sorted(current_surfaces.keys() - baseline_surfaces.keys()),
        "missing_surfaces": sorted(baseline_surfaces.keys() - current_surfaces.keys()),
    }


def _by_track_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        s["track_id"]: s
        for s in [*report.get("stems", []), *report.get("returns", [])]
    }


def _surface_deltas(
    current_surface: dict[str, Any],
    baseline_surface: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for metric, threshold in SIGNIFICANCE_DB.items():
        before = baseline_surface["loudness"][metric]
        after = current_surface["loudness"][metric]
        if before is None or after is None:
            delta: float | None = None
            significant = False
        else:
            delta = after - before
            significant = abs(delta) >= threshold
        rows.append(
            {
                "track_id": current_surface["track_id"],
                "surface_kind": current_surface["surface_kind"],
                "surface_name": current_surface["surface_name"],
                "metric": metric,
                "before": before,
                "after": after,
                "delta": delta,
                "significant": significant,
            }
        )
    return rows
