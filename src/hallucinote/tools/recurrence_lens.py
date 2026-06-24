#!/usr/bin/env python3
"""Run the symbolic recurrence lens over a song and print the recurrence/recap reading.

The read-side surface that brings `hallucinote.recurrence` to `/compose-review`: it
imports a song's `build.py`, calls its `recurrence_report()` convention (which builds
the in-memory arrangement and runs the lens — the motif registry + per-section layers
are authored in build.py, not in the DB), and prints which registered motifs recur
where, on which layer, and as which variation, plus the motivic-economy summary. The
facts are NEUTRAL measurements, never a verdict: `/compose-review` reads them AGAINST
the song's declared recurrence intent. Economy is STYLE-RELATIVE (a through-composed
piece is legitimately less economical than a minimalist one — research.md §2), so the
summary is reported, never graded.

Known blind spot (reported plainly): only *registered* motifs are read. A recurring
free function (never `arr.motif(...)`) is invisible — register it to track its recall
(an authoring choice, not a lens limitation to paper over).

Usage:
    python3 -m hallucinote.tools.recurrence_lens sun-zone-done
    python3 -m hallucinote.tools.recurrence_lens sun-zone-done --section integration
    python3 -m hallucinote.tools.recurrence_lens sun-zone-done --json

Exit codes: 0 = report printed · 2 = no such song · 3 = song has not wired the
recurrence lens (no `recurrence_report()` in its build.py — add one; see
sun-zone-done for the pattern).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys

from hallucinote.tools.tuning_caveat import lens_caveat, song_tuning_ref
from hallucinote.workspace import resolve_song_dir


def _load_build_module(slug: str):
    """Import a song's `build.py` as a throwaway module (the same spec-from-file
    pattern `tools/melody_lens.py` and the per-song tests use; `songs/` is not a
    package). The song dir resolves via the project-root contract, so this finds the
    song whether it lives in the engine monorepo or its own repo. Raises
    FileNotFoundError when absent."""
    build_path = resolve_song_dir(slug) / "build.py"
    if not build_path.is_file():
        raise FileNotFoundError(build_path)
    spec = importlib.util.spec_from_file_location(f"_recurrence_lens_{slug}", build_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise FileNotFoundError(build_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def render(report, *, section_filter: str | None = None) -> str:
    """Human-readable rendering of a RecurrenceReport for `/compose-review` to read.
    `section_filter` (if given) limits the per-section block to that one section; the
    economy summary + header are whole-song facts and always print."""
    lines: list[str] = []
    recalls = [r for r in report.recalls if not r.is_home]
    n_sections = len({r.section for r in recalls})
    lines.append(
        f"recurrence lens — {report.song_slug}: {len(recalls)} recall(s) across "
        f"{n_sections} section(s), {len(report.findings)} coaching question(s)"
    )
    lines.append(
        "  (neutral measurements, NOT a verdict — read each against the song's "
        "declared recurrence intent; economy is style-relative, never graded)"
    )
    lines.append(
        "  (blind spot: only REGISTERED motifs are read — a recurring free function "
        "never arr.motif(...) is invisible; register it to track its recall)"
    )

    econ = report.economy
    lines.append(
        f"\neconomy: cell-set {econ.recurring_motifs}/{econ.registered_motifs} motifs "
        f"recur · coverage {econ.recall_coverage:.0%} · "
        f"compression-proxy {econ.compression_ratio:.2f} "
        f"(COSIATEC empirical band ~2–4; a raw fact, no target)"
    )
    if econ.never_recalled:
        lines.append(
            f"  never recalled: {', '.join(econ.never_recalled)} "
            f"(intended one-shot, or a planned recall that didn't land?)"
        )

    sections = [
        s for s in report.sections
        if section_filter is None or s.section == section_filter
    ]
    if section_filter is not None and not sections:
        lines.append(f"\n  (no section named {section_filter!r})")
        return "\n".join(lines)

    for s in sections:
        later = [r for r in s.recalls if not r.is_home]
        home = [r for r in s.recalls if r.is_home]
        if not later and not home:
            continue
        lines.append(f"\n[{s.section}]")
        for r in home:
            lines.append(
                f"  · {r.motif} — home (first appearance) on {r.layer} "
                f"[{r.variation}]"
            )
        for r in later:
            lines.append(
                f"  ↩ {r.motif} recurs on {r.layer} as {r.variation} "
                f"(coverage {r.coverage:.0%}, beat {r.cell_offset_beats:.1f})"
            )

    for f in report.findings:
        lines.append(f"\n  ? {f.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slug", help="song slug under songs/ (e.g. sun-zone-done)")
    parser.add_argument("--section", help="limit the per-section block to one section")
    parser.add_argument("--json", action="store_true",
                        help="emit the full RecurrenceReport as JSON (report.to_dict())")
    args = parser.parse_args(argv)

    try:
        mod = _load_build_module(args.slug)
    except FileNotFoundError:
        print(f"recurrence-lens: no such song {args.slug!r} "
              f"(expected songs/{args.slug}/build.py)", file=sys.stderr)
        return 2

    report_fn = getattr(mod, "recurrence_report", None)
    if not callable(report_fn):
        print(
            f"recurrence-lens: {args.slug!r} has not wired the recurrence lens — its "
            f"build.py defines no recurrence_report(). Add one (one line via "
            f"hallucinote.recurrence.analyze_arrangement); see "
            f"songs/sun-zone-done/build.py.",
            file=sys.stderr,
        )
        return 3

    report = report_fn()
    # MICROTUNE Chunk 3: gate a one-line honesty caveat on the song carrying an
    # alternate tuning — recurrence variations (transpositions) are read in
    # 12-TET semitones. Inert (None) for the 99.99% with tuning_ref NULL.
    caveat = lens_caveat(song_tuning_ref(args.slug))
    if args.json:
        out = report.to_dict()
        if args.section is not None:
            out["sections"] = [s for s in out["sections"]
                               if s["section"] == args.section]
        if caveat is not None:
            out["tuning_caveat"] = caveat
        print(json.dumps(out, indent=2))
    else:
        if caveat is not None:
            print(caveat)
        print(render(report, section_filter=args.section))
    return 0


if __name__ == "__main__":
    sys.exit(main())
