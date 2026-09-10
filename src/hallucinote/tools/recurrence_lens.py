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

Occurrences below the analysis's coverage floor are reported as PARTIALS and folded
into a per-section count in this render (`--all` lists them; `--json` always carries
them). The matcher finds a low-coverage partial for nearly every motif × layer pair,
so listing them straight buries the whole-motif recalls that describe the form. What
is filtered is the reading, never the facts — and the economy summary counts only the
occurrences that clear the floor, so a motif that recurs only as partials still
raises its coaching question.

Usage:
    python3 -m hallucinote.tools.recurrence_lens <slug>
    python3 -m hallucinote.tools.recurrence_lens <slug> --section integration
    python3 -m hallucinote.tools.recurrence_lens <slug> --all
    python3 -m hallucinote.tools.recurrence_lens <slug> --json

Exit codes: 0 = report printed · 2 = no such song · 3 = song has not wired the
recurrence lens (no `recurrence_report()` in its build.py — the exit-3 message
carries both ways to write one).
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


def render(report, *, section_filter: str | None = None, show_partials: bool = False) -> str:
    """Human-readable rendering of a RecurrenceReport for `/compose-review` to read.
    `section_filter` (if given) limits the per-section block to that one section; the
    economy summary + header are whole-song facts and always print.

    Sub-threshold partials are FOLDED into a per-section count unless
    `show_partials`. The transform group finds a low-coverage partial for nearly
    every (motif × layer) pair, so listing them straight makes the render say every
    motif recurs everywhere and buries the whole-motif recalls that actually
    describe the form — on the report that motivated this, by five to one. They are
    counted and offered, never dropped: the reading is what gets filtered, not the
    facts."""
    lines: list[str] = []
    recalls = [r for r in report.recalls if not r.is_home and not r.partial]
    # Counted with the same predicate the per-section folds use, so the header's
    # total and the section lines can't disagree. A partial is not a recall, so the
    # home/later split that governs `recalls` does not apply to it.
    partials = [r for r in report.recalls if r.partial]
    n_sections = len({r.section for r in recalls})
    floor = getattr(report, "min_coverage", None)
    partial_note = ""
    if partials and not show_partials:
        floor_txt = f"below {floor:.0%} coverage; " if floor is not None else ""
        partial_note = (
            f", {len(partials)} partial(s) folded ({floor_txt}--all to list)"
        )
    elif partials:
        partial_note = f", {len(partials)} partial(s) listed"
    lines.append(
        f"recurrence lens — {report.song_slug}: {len(recalls)} recall(s) across "
        f"{n_sections} section(s), {len(report.findings)} coaching "
        f"question(s){partial_note}"
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
        f"(COSIATEC empirical band ~2–4; a raw fact, no target; counts recalls "
        f"only — partials are not evidence of recall)"
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
        shown = [r for r in s.recalls if show_partials or not r.partial]
        folded = [] if show_partials else [r for r in s.recalls if r.partial]
        later = [r for r in shown if not r.is_home]
        home = [r for r in shown if r.is_home]
        if not later and not home and not folded:
            continue
        lines.append(f"\n[{s.section}]")
        for r in home:
            lines.append(
                f"  · {r.motif} — home (first appearance) on {r.layer} "
                f"[{r.variation}]"
            )
        for r in later:
            mark = "~" if r.partial else "↩"
            lines.append(
                f"  {mark} {r.motif} recurs on {r.layer} as {r.variation} "
                f"(coverage {r.coverage:.0%}, beat {r.cell_offset_beats:.1f})"
            )
        if folded:
            best = max(r.coverage for r in folded)
            lines.append(
                f"  + {len(folded)} partial(s) folded, best coverage {best:.0%}"
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
    parser.add_argument("--all", dest="show_partials", action="store_true",
                        help="list sub-threshold partials inline instead of folding "
                             "them into a per-section count (they are always in --json)")
    args = parser.parse_args(argv)

    try:
        mod = _load_build_module(args.slug)
    except FileNotFoundError:
        print(f"recurrence-lens: no such song {args.slug!r} "
              f"(expected songs/{args.slug}/build.py)", file=sys.stderr)
        return 2

    report_fn = getattr(mod, "recurrence_report", None)
    if not callable(report_fn):
        # Two authoring shapes, and naming only the Arrangement one sent songs that
        # never build an Arrangement (notes authored straight into the DB) chasing a
        # one-liner they cannot use. Both are spelled out here rather than pointed
        # at, because a pointer to a song file is a claim about a workspace this
        # package does not ship and cannot check.
        print(
            f"recurrence-lens: {args.slug!r} has not wired the recurrence lens — its "
            f"build.py defines no recurrence_report(). Add one, returning a "
            f"RecurrenceReport:\n"
            f"  - if the song builds an in-memory Arrangement:\n"
            f"      from hallucinote.recurrence.lens import analyze_arrangement\n"
            f"      def recurrence_report():\n"
            f"          return analyze_arrangement(build_arrangement(), "
            f"song_slug={args.slug!r})\n"
            f"  - if its notes go straight to the DB (no Arrangement): build one "
            f"SectionRecurrenceInput\n"
            f"    per section and call analyze_recurrence directly:\n"
            f"      from hallucinote.recurrence.lens import (\n"
            f"          SectionRecurrenceInput, analyze_recurrence,\n"
            f"      )\n"
            f"      def recurrence_report():\n"
            f"          secs = [SectionRecurrenceInput(name, start_beat, "
            f"{{layer: notes}}), ...]\n"
            f"          return analyze_recurrence(secs, motifs, "
            f"song_slug={args.slug!r})\n"
            f"  Only REGISTERED motifs are read — `motifs` maps name -> an object "
            f"with .notes.",
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
        print(render(report, section_filter=args.section,
                     show_partials=args.show_partials))
    return 0


if __name__ == "__main__":
    sys.exit(main())
