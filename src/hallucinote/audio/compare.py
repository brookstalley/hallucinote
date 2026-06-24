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

import json
from pathlib import Path
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


def ensure_comparable(
    schema_version: Any,
    song_slug: Any,
    baseline: dict[str, Any],
    *,
    baseline_ref: str | None = None,
) -> None:
    """Refuse a comparison that can't be made honestly.

    The single home for the two comparability invariants (schema_version
    equality, same song) — called by ``diff_reports`` at diff time and by
    ``analyze_mix`` up front so the refusal lands before the expensive DSP
    passes. If the semantics ever loosen (e.g. schema-version range
    tolerance), this is the one place to change.

    Raises ``ValueError`` on schema-version or song mismatch.
    """
    where = f"baseline {baseline_ref}" if baseline_ref else "baseline"
    if baseline.get("schema_version") != schema_version:
        raise ValueError(
            f"cannot diff schema_version={schema_version!r} against "
            f"{where} schema_version={baseline.get('schema_version')!r} — "
            "incomparable shapes refuse up front"
        )
    if baseline.get("song_slug") != song_slug:
        raise ValueError(
            f"{where} is for song {baseline.get('song_slug')!r}, current is "
            f"for {song_slug!r} — cross-song baselines are not supported "
            "(reference-track comparison is a separate backlog item)"
        )


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
    ensure_comparable(
        current.get("schema_version"),
        current.get("song_slug"),
        baseline,
        baseline_ref=baseline_ref,
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


def resolve_baseline(analysis_dir: Path | str, seq: int) -> Path:
    """Find the analysis JSON whose ``db_seq`` matches ``seq``.

    Analysis filenames are ISO-8601 UTC (lex order == chronological), so
    when several reports carry the same seq (re-analyses of one capture,
    or re-renders with no DB change between), the LATEST wins — it
    reflects the newest capture/analysis of that DB state.

    Raises ``ValueError`` with the available seqs when nothing matches —
    explicit refusal, no fuzzy nearest-seq matching. Reports without a
    ``db_seq`` (pre-tagging) are skipped here but remain usable as
    explicit-path baselines.
    """
    analysis_dir = Path(analysis_dir)
    # Exclude status.json — the BUG3 completion heartbeat the analyze handler
    # (hallucinote_mcp.server_side.analysis) writes into this same dir. It carries
    # no db_seq so the loop below already skips it, but excluding it by name
    # keeps it out of the candidate set entirely (no stray read, clearer intent).
    candidates = (
        sorted(p for p in analysis_dir.glob("*.json") if p.name != "status.json")
        if analysis_dir.exists() else []
    )
    if not candidates:
        raise ValueError(
            f"no analysis reports in {analysis_dir} — baselines are the "
            f"JSONs ableton_analysis(analyze) writes there"
        )
    available: list[int] = []
    match: Path | None = None
    for path in candidates:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # an unreadable report can't be a baseline; keep scanning
        report_seq = report.get("db_seq")
        if not isinstance(report_seq, int) or isinstance(report_seq, bool):
            continue  # None, or a malformed/hand-edited value — not a key
        available.append(report_seq)
        if report_seq == seq:
            match = path  # keep scanning — latest match wins
    if match is None:
        seqs_note = (
            str(sorted(set(available)))
            if available
            else "none (reports predate seq tagging — pass an explicit baseline path)"
        )
        raise ValueError(
            f"no analysis report in {analysis_dir} has db_seq={seq}; "
            f"available seqs: {seqs_note}"
        )
    return match


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
