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

from .automation import CORRELATION_ABS_THRESHOLD
from .reconcile import SumReconciliation, master_is_not_stem_sum

# Calibrated significance floors (dB). See module docstring for evidence.
SIGNIFICANCE_DEFAULT_DB = 0.5
SIGNIFICANCE_SHORT_TERM_DB = 1.0

SIGNIFICANCE_DB: dict[str, float] = {
    "lufs_i": SIGNIFICANCE_DEFAULT_DB,
    "lufs_s_median": SIGNIFICANCE_SHORT_TERM_DB,
    "lufs_m_peak": SIGNIFICANCE_DEFAULT_DB,
    "true_peak_dbtp": SIGNIFICANCE_DEFAULT_DB,
}

# PROVISIONAL timbre significance floors (AUD-8T3K). Unlike SIGNIFICANCE_DB —
# calibrated against the sun-zone-done re-capture jitter set — there is no
# render-jitter baseline for centroid / flatness / rolloff yet, so these are
# conservative first guesses. Every timbre delta carries ``provisional: true``
# so a consumer treats a "significant" timbre verdict as a hint, not a measured
# noise/signal threshold. A re-capture-jitter calibration is a filed follow-up
# (AUD-TIMBRE-CALIB); until then the raw before/after/delta is the honest signal.
SIGNIFICANCE_TIMBRE: dict[str, float] = {
    "spectral_centroid_hz": 50.0,   # Hz
    "spectral_flatness": 0.02,      # 0..1 Wiener entropy
    "spectral_rolloff_hz": 100.0,   # Hz
    # Sharpness: an EQ move of a couple of dB on a shrill surface's 3-6 kHz
    # region moved a rendered stem ~0.15-0.3 acum in the alien dogfood pass;
    # re-render jitter on an unchanged stem sat well under 0.05. Provisional.
    "sharpness_acum": 0.10,         # acum
}

# PROVISIONAL transient-shape significance floors (the kick-class lens). Sized
# from the alien dogfood pass: an EQ move on the kick's own chain moved
# ``click_minus_sub_db`` ~0.5 dB and ``low_minus_sub_db`` ~2 dB (below and above
# the floor respectively — the floor is meant to separate "the chain changed"
# from re-render jitter, which sat under 0.3 dB / 1 ms); an authored attack
# layer moved ``click_minus_sub_db`` +6.5 dB. No jitter calibration set exists.
SIGNIFICANCE_TRANSIENTS: dict[str, float] = {
    "rise_ms": 3.0,                 # ms
    "t20_ms": 25.0,                 # ms
    "click_minus_sub_db": 1.5,      # dB
    "low_minus_sub_db": 1.5,        # dB
}

# Stereo-image significance (STR-4C8N). Carries ``provisional: true`` for the
# same reason as timbre: no render-jitter calibration set exists for these yet.
# The dB floor is sized so the worked case reads as significant — reducing an
# over-wide element moved its mono-sum loss ~1 dB — while re-render jitter on a
# stable image, which sits far below that, does not.
SIGNIFICANCE_STEREO: dict[str, float] = {
    # IS the image-probe floor, imported rather than restated — the two answer
    # the same question ("is this correlation move real, or jitter?"), and a
    # recalibration of one that left the other behind would have an A/B and the
    # automation verifier disagree about the same audio.
    "correlation": CORRELATION_ABS_THRESHOLD,
    "mono_sum_loss_db": 0.5,    # dB lost summed to mono
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

    # A master the analyzer measured as not-the-sum-of-its-stems is not the
    # mix, so a master delta would report the difference between one wrong
    # reading and one right one as though the mix had moved. On the 2026-09-10
    # `alien` incident that produced "26 significant deltas / 112 section-level
    # deltas" against a song nobody had touched. The stems stay: on that same
    # incident every stem was within 0.4 dB, which is the evidence that proves
    # the master is the odd one out.
    master_disqualified = (
        _master_disqualification(current, side="current")
        or _master_disqualification(baseline, side="baseline")
    )

    deltas: list[dict[str, Any]] = []
    if master_disqualified is None:
        deltas.extend(_surface_deltas(current["master"], baseline["master"]))

    current_surfaces = _by_track_id(current)
    baseline_surfaces = _by_track_id(baseline)
    for track_id in sorted(current_surfaces.keys() & baseline_surfaces.keys()):
        deltas.extend(
            _surface_deltas(current_surfaces[track_id], baseline_surfaces[track_id])
        )

    overshoots_before = len(baseline.get("overshoots", []))
    overshoots_after = len(current.get("overshoots", []))

    section_deltas = _section_deltas(
        current, baseline, include_master=master_disqualified is None,
    )

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
            # An overshoot appearing or disappearing is always worth a look —
            # UNLESS the master it was measured from is disqualified. An
            # overshoot is a master-bus true-peak window, so this is a master
            # delta by another name: on the incident's numbers the soloed
            # master sat ~14 dB low and every overshoot vanished, which would
            # report a real headline change sourced entirely from a capture
            # the same payload has just declared is not the mix. The counts
            # stay (they are evidence); only the claim that the change means
            # something is withheld.
            "significant": (
                overshoots_after != overshoots_before
                if master_disqualified is None else False
            ),
        },
        "added_surfaces": sorted(current_surfaces.keys() - baseline_surfaces.keys()),
        "missing_surfaces": sorted(baseline_surfaces.keys() - current_surfaces.keys()),
        # Per-SECTION rows (matched by section name, then track_id): the timbre
        # family on every surface the window measured — stems, returns and the
        # master, so a "de-shrill chorus 3" edit is A/B-able where it was made,
        # on the whole mix as well as per part — and the transient shape per
        # part. Surfaces-only deltas above cannot carry either (they average the
        # whole song; transients exist only per section). See _section_deltas.
        "section_deltas": section_deltas,
        # Present only when the master was disqualified, and then it is the
        # reason there are no master deltas above to read. Absent on a healthy
        # comparison rather than null, so a consumer that does not know about
        # this key behaves exactly as before.
        **(
            {"master_deltas_refused": master_disqualified}
            if master_disqualified is not None
            else {}
        ),
    }


def _master_disqualification(
    report: dict[str, Any], *, side: str,
) -> dict[str, Any] | None:
    """Why this report's master cannot be diffed, or ``None``.

    Checked on BOTH sides. A stored report is re-used as a baseline for as
    long as it is the newest good one, so a capture made under a solo does not
    stop being wrong when it becomes the thing later renders are measured
    against — the next healthy render diffed against it would reproduce the
    same wall of false master deltas, with the sign flipped and nothing to say
    why. A diff is only as honest as its worse side.

    Prefers the report's own ``master_not_stem_sum`` finding and falls back to
    judging its stored ``sum_reconciliation`` through the same lens in
    ``reconcile``. Both routes end at one owner, which is the point: a second
    threshold here would be free to disagree with the report's own findings
    about the same numbers.
    """
    # The three values are read off a STORED report's JSON, so they are `Any` to
    # the type checker even though this module's own writer always sets all
    # three — `analyze.py` builds the finding from the same
    # `master_is_not_stem_sum` tuple this function's other branch calls. Widened
    # rather than cast, because the widening is the honest answer: a report that
    # carries the finding without its numbers is still DISQUALIFIED — the
    # finding's presence is the verdict, not its arithmetic — so a missing value
    # travels as None instead of being fabricated or raising on `float(None)`.
    verdict: tuple[str | None, float | None, float | None] | None = None
    for finding in report.get("findings", []) or []:
        if isinstance(finding, dict) and finding.get("kind") == "master_not_stem_sum":
            verdict = (
                finding.get("metric"),
                finding.get("observed"),
                finding.get("expected"),
            )
            break
    else:
        # A report written before this gate existed carries a fully populated
        # `sum_reconciliation` and no finding — and `resolve_baseline` filters
        # on `db_seq` alone, so those reports stay selectable as baselines
        # indefinitely. The three stored `alien` reports that motivated this
        # work are exactly that case. Judge them through the SAME lens rather
        # than a second threshold here, so an old baseline and a new one cannot
        # disagree about the same numbers.
        verdict = master_is_not_stem_sum(
            _reconciliation_from_json(report.get("sum_reconciliation"))
        )
    if verdict is not None:
        metric, observed, expected = verdict
        return {
            "reason": "master_not_stem_sum",
            "side": side,
            "metric": metric,
            "observed": observed,
            "expected": expected,
            "detail": (
                f"the {side} report's master is not the sum of its stems, "
                "so a master delta would compare a capture of something "
                "other than the mix against one of the mix. Stem deltas "
                "below are unaffected."
            ),
        }
    return None


def _reconciliation_from_json(raw: Any) -> SumReconciliation | None:
    """Rehydrate just enough of a serialized reconciliation to judge it.

    Only the fields the lens reads are needed; the band residuals and the
    worst offender are evidence for a human, not inputs to the verdict. A
    payload missing either judged field is not a disqualification — the same
    rule the lens applies to a skipped measurement.
    """
    if not isinstance(raw, dict):
        return None
    try:
        correlation = float(raw["correlation"])
        gain_offset_db = float(raw["gain_offset_db"])
        # Inside the try with the other two so a rehydration cannot raise on a
        # field the verdict never reads. `is not None` rather than a truthiness
        # test: a stored residual of exactly 0.0 is a real measurement, and
        # `or` would silently turn it into NaN.
        raw_residual = raw.get("residual_db")
        residual_db = (
            float(raw_residual) if raw_residual is not None else float("nan")
        )
    except (KeyError, TypeError, ValueError):
        return None
    return SumReconciliation(
        residual_db=residual_db,
        correlation=correlation,
        best_lag_samples=int(raw.get("best_lag_samples", 0) or 0),
        gain_offset_db=gain_offset_db,
        band_residuals=[],
        worst_offender=raw.get("worst_offender"),
        skipped=raw.get("skipped"),
    )


def _section_surfaces(
    section: dict[str, Any], *, include_master: bool = True,
) -> list[dict[str, Any]]:
    """Every surface a section window measured: its stems, its returns, and its
    master. All three carry the timbre family; only stems carry transients.

    ``include_master=False`` drops the master rows for a report whose master was
    disqualified — the per-section master readings come from the same capture as
    the whole-song one and are wrong in the same way.
    """
    out = list(section.get("stems", []) or [])
    out.extend(section.get("returns", []) or [])
    master = section.get("master") if include_master else None
    if isinstance(master, dict) and master.get("track_id"):
        out.append(master)
    return out


def _section_deltas(
    current: dict[str, Any], baseline: dict[str, Any],
    *, include_master: bool = True,
) -> list[dict[str, Any]]:
    """Per-section, per-surface deltas: timbre (sharpness and the rest) on every
    surface the window measured — stems, returns AND the master — plus transient
    shape per part (stems only; that is where hits are picked). Sections are
    matched by name (a renamed or added section yields no rows — the
    surface-level ``added/missing`` lists are the place structure changes are
    named); surfaces by ``track_id``. Null on either side yields
    ``delta: null, significant: false``, like every other family."""
    cur = {s.get("section_name"): s for s in current.get("per_section", []) or []}
    base = {s.get("section_name"): s for s in baseline.get("per_section", []) or []}
    rows: list[dict[str, Any]] = []
    for name in [n for n in cur if n in base]:
        cs, bs = cur[name], base[name]
        # Every surface the section measured, not just its stems: the master's
        # per-section timbre is the whole-mix read a "de-shrill chorus 3" edit
        # is judged on, and a return's is how a send bus moved. `_measure_window`
        # produces all three; iterating stems alone left the two that carry the
        # section's summary with no A/B row at all.
        cstems = {
            s["track_id"]: s
            for s in _section_surfaces(cs, include_master=include_master)
        }
        bstems = {
            s["track_id"]: s
            for s in _section_surfaces(bs, include_master=include_master)
        }
        for tid in [t for t in cstems if t in bstems]:
            for row in _family_deltas(cstems[tid], bstems[tid], "timbre",
                                      SIGNIFICANCE_TIMBRE, provisional=True):
                rows.append({"section": name, **row})
        ctr = {t["track_id"]: t for t in cs.get("transients", []) or []}
        btr = {t["track_id"]: t for t in bs.get("transients", []) or []}
        for tid in [t for t in ctr if t in btr]:
            # _family_deltas reads the surface identity off the dict it is
            # given; a transient entry names only its track_id, so wrap it in
            # a surface shell (the name comes from the section's stem when
            # that stem is present).
            def shell(entry):
                stem = cstems.get(tid) or {}
                return {"track_id": tid, "surface_kind": stem.get("surface_kind", "track"),
                        "surface_name": stem.get("surface_name", tid), "transients": entry}
            for row in _family_deltas(shell(ctr[tid]), shell(btr[tid]), "transients",
                                      SIGNIFICANCE_TRANSIENTS, provisional=True):
                rows.append({"section": name, **row})
    return rows


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
    rows = _family_deltas(
        current_surface, baseline_surface, "loudness", SIGNIFICANCE_DB,
        provisional=False,
    )
    # Timbre deltas (AUD-8T3K) ride alongside loudness, flagged provisional. A
    # surface with no timbre (silent stem → null, or a pre-timbre baseline that
    # lacks the key) yields delta null / significant false — never a fabricated
    # number, symmetric with the loudness null-sentinel handling.
    rows.extend(_family_deltas(
        current_surface, baseline_surface, "timbre", SIGNIFICANCE_TIMBRE,
        provisional=True,
    ))
    # Stereo image deltas (STR-4C8N). Without these an A/B is blind to exactly
    # the change the lens exists to make visible — reducing an over-wide element
    # moved Brass Section from -3.84 dB to -2.86 dB mono loss, and a comparison
    # that enumerates families by name showed it as no delta at all.
    rows.extend(_family_deltas(
        current_surface, baseline_surface, "stereo", SIGNIFICANCE_STEREO,
        provisional=True,
    ))
    return rows


def _family_deltas(
    current_surface: dict[str, Any],
    baseline_surface: dict[str, Any],
    family: str,
    thresholds: dict[str, float],
    *,
    provisional: bool,
) -> list[dict[str, Any]]:
    current_metrics = current_surface.get(family) or {}
    baseline_metrics = baseline_surface.get(family) or {}
    rows = []
    for metric, threshold in thresholds.items():
        before = baseline_metrics.get(metric)
        after = current_metrics.get(metric)
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
                "provisional": provisional,
            }
        )
    return rows
