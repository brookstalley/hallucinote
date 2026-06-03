#!/usr/bin/env python3
"""Run the symbolic melody lens over a song and print the line-level reading.

The read-side surface that brings `hallucinote.melody` to `/compose-review`: it
imports a song's `build.py`, calls its `melody_report()` convention (which builds
the in-memory arrangement and runs the lens — harmony-fit needs the in-memory
progression, which is not in the DB; see melody-model.md §7 *Read-side surface*),
and prints the per-line facts (contour, intervals, harmony-fit) + the coaching
questions. The facts are NEUTRAL measurements, never a verdict — `/compose-review`
reads them AGAINST the line's declared intent (there is no universal "good
melody"; melody-model.md §1).

Usage:
    python3 -m hallucinote.tools.melody_lens sun-zone-done
    python3 -m hallucinote.tools.melody_lens sun-zone-done --section chorus1
    python3 -m hallucinote.tools.melody_lens sun-zone-done --json

Exit codes: 0 = report printed · 2 = no such song · 3 = song has not wired the
melody lens (no `melody_report()` in its build.py — add one; see the scaffold
template / sun-zone-done for the pattern).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from hallucinote.workspace import resolve_song_dir


def _load_build_module(slug: str):
    """Import a song's `build.py` as a throwaway module (the same
    spec-from-file pattern the per-song tests use; `songs/` is not a package).
    The song dir resolves via the project-root contract (env / hallucinote.toml
    marker / legacy `songs/<slug>`), so this finds the song whether it lives in
    the engine monorepo or its own repo. Raises FileNotFoundError when absent."""
    build_path = resolve_song_dir(slug) / "build.py"
    if not build_path.is_file():
        raise FileNotFoundError(build_path)
    spec = importlib.util.spec_from_file_location(f"_melody_lens_{slug}", build_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise FileNotFoundError(build_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fmt_frac(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _harmony_line(harmony: Any) -> str:
    """One-line harmony-fit summary, or a degraded note when the section declared
    no progression (the lens reads contour/intervals only — graceful, not a flaw)."""
    if harmony is None:
        return "harmony: (no declared progression — contour/interval read only)"
    return (
        f"harmony: {_fmt_frac(harmony.chord_tone_fraction)} chord-tone · "
        f"{_fmt_frac(harmony.non_chord_tone_fraction)} non-chord-tone · "
        f"NCT-resolves-by-step {_fmt_frac(harmony.nct_resolves_by_step)} · "
        f"chord-tone-on-strong-beat {_fmt_frac(harmony.chord_tone_on_strong_beat)}"
    )


def render(report: Any, *, section_filter: str | None = None) -> str:
    """Human-readable rendering of a MelodyReport for `/compose-review` to read.
    `section_filter` (if given) limits output to that one section."""
    lines: list[str] = []
    sections = [
        s for s in report.sections
        if section_filter is None or s.section == section_filter
    ]
    n_lines = sum(len(s.lines) for s in sections)
    n_findings = sum(len(s.findings) for s in sections)
    lines.append(
        f"melody lens — {report.song_slug}: {len(sections)} section(s), "
        f"{n_lines} line(s), {n_findings} coaching question(s)"
    )
    lines.append(
        "  (neutral measurements, NOT a verdict — read each against the line's "
        "declared intent; there is no universal \"good melody\")"
    )
    if section_filter is not None and not sections:
        lines.append(f"  (no section named {section_filter!r})")
        return "\n".join(lines)

    for s in sections:
        lines.append(f"\n[{s.section}]")
        if not s.lines:
            lines.append("  (no melodic line in this section)")
        for ln in s.lines:
            apex = (
                f"{ln.apex_pitch}@{ln.apex_position:.0%}"
                if ln.apex_pitch is not None and ln.apex_position is not None
                else "—"
            )
            lines.append(
                f"  {ln.track_name} — {ln.classification} "
                f"(confidence {ln.confidence:.0%}, {ln.onset_count} notes)"
            )
            lines.append(
                f"    contour: {ln.contour_shape} · apex {apex} · "
                f"{ln.direction_changes} direction-changes · "
                f"gradient-stdev {ln.gradient_stdev:.2f}"
            )
            lines.append(
                f"    intervals: step {_fmt_frac(ln.step_fraction)} / "
                f"leap {_fmt_frac(ln.leap_fraction)} · "
                f"post-skip-reversal {_fmt_frac(ln.post_skip_reversal)} · "
                f"alphabet {ln.pitch_alphabet_size} · ambitus {ln.ambitus} semitones"
            )
            lines.append(f"    {_harmony_line(ln.harmony)}")
        for f in s.findings:
            lines.append(f"    ? {f.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slug", help="song slug under songs/ (e.g. sun-zone-done)")
    parser.add_argument("--section", help="limit the report to one section by name")
    parser.add_argument("--json", action="store_true",
                        help="emit the full MelodyReport as JSON (report.to_dict())")
    args = parser.parse_args(argv)

    try:
        mod = _load_build_module(args.slug)
    except FileNotFoundError:
        print(f"melody-lens: no such song {args.slug!r} "
              f"(expected songs/{args.slug}/build.py)", file=sys.stderr)
        return 2

    report_fn = getattr(mod, "melody_report", None)
    if not callable(report_fn):
        print(
            f"melody-lens: {args.slug!r} has not wired the melody lens — its "
            f"build.py defines no melody_report(). Add one (one line via "
            f"hallucinote.melody.analyze_arrangement); see the scaffold template "
            f"or songs/sun-zone-done/build.py.",
            file=sys.stderr,
        )
        return 3

    report = report_fn()
    if args.json:
        out = report.to_dict()
        if args.section is not None:
            out["sections"] = [s for s in out["sections"]
                               if s["section"] == args.section]
        print(json.dumps(out, indent=2))
    else:
        print(render(report, section_filter=args.section))
    return 0


if __name__ == "__main__":
    sys.exit(main())
