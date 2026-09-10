"""The unified ``hallucinote`` command — a thin dispatcher over the engine's CLIs.

Each subcommand forwards its remaining args **verbatim** to the corresponding
module's ``main(argv)`` and returns that exit code, with the module's output
**unchanged**. It is a dispatcher, not a black box: build errors, the push
phase-halt cause, and every other result the agent acts on stay visible. The only
thing it hides is the plumbing — which Python entry point to call.

Why this exists (PLUGIN-SELF-CONTAINED): the engine ships *inside the plugin's uv
env*, so the agent runs it as ``uv run --project <plugin-root> --frozen hallucinote
<subcommand> …`` — one CLI instead of a dozen ``python -m hallucinote.<module>``
mouthfuls, and no separate clone or PyPI install. Targets are **lazy-imported** so
``hallucinote --help`` and unrelated commands don't pull the whole engine (or its
numpy/librosa analysis stack).
"""
from __future__ import annotations

import importlib
import sys

# subcommand -> (module path, entry-function name). The entry takes ``argv`` and
# returns an int exit code (every engine CLI already follows this; capture_cli
# gained the argv param, inventory's entry is ``_main``).
_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "push": ("hallucinote.sync.push_cli", "main"),
    "pull": ("hallucinote.sync.pull_cli", "main"),
    "verify-arrangement": ("hallucinote.sync.verify_arrangement_cli", "main"),
    "tuning-pull": ("hallucinote.tuning.pull_cli", "main"),
    "compat": ("hallucinote.sync.compat", "main"),
    "capture": ("hallucinote.tools.capture_cli", "main"),
    "captures": ("hallucinote.tools.captures_cli", "main"),
    "context": ("hallucinote.tools.song_context", "main"),
    "decisions": ("hallucinote.tools.decisions_cli", "main"),
    "melody": ("hallucinote.tools.melody_lens", "main"),
    "recurrence": ("hallucinote.tools.recurrence_lens", "main"),
    "reindex": ("hallucinote.tools.reindex_markdown", "main"),
    "scaffold": ("hallucinote.tools.scaffold_song", "main"),
    "overview-drift": ("hallucinote.tools.overview_drift", "main"),
    "init-workspace": ("hallucinote.tools.init_workspace", "main"),
    "inventory": ("hallucinote.inventory", "_main"),
    # Sampling (SMP-6V2K wave 2): a song's audio sources, its derived cache,
    # the reading of a line, and the R6.2 listening harness.
    "asset": ("hallucinote.tools.asset_ingest", "main"),
    "derived": ("hallucinote.tools.derived_cli", "main"),
    "sample-lens": ("hallucinote.tools.sample_lens", "main"),
    "stretch-ab": ("hallucinote.tools.stretch_ab", "main"),
}

_SUMMARY: dict[str, str] = {
    "push": "build → Live: probe-and-link, execute (14 phases), push-notes",
    "pull": "fold manual Live edits back into the DB",
    "verify-arrangement": "audit the DB arrangement against Live (collapsed-set; exit 1 on divergence)",
    "tuning-pull": "capture Live's loaded alternate tuning onto a song (rare; 0.01%)",
    "compat": "check a song's device and sample requirements before sharing/pushing",
    "capture": "acquire the live set into a song's captured_session.json",
    "captures": "list/prune/pin rendered audio takes (disk retention)",
    "context": "query a song's composer intent + decision rationale",
    "decisions": "query a song's compose-time decision/request log",
    "melody": "symbolic melody lens (contour, intervals, harmony-fit)",
    "recurrence": "symbolic recurrence lens (motif reuse, form)",
    "reindex": "rebuild a song's markdown FTS index",
    "scaffold": "scaffold a new song directory from templates",
    "overview-drift": "report a <slug>.md Structure table or build.py docstring layout that has drifted from the form",
    "init-workspace": "create a hallucinote.toml songs-workspace marker (+ git init)",
    "inventory": "refresh the offline browser/instrument cache",
    "asset": "add a sample to a song's assets/sources with its provenance; list / verify the manifest",
    "derived": "verify or prune a song's derived-audio cache (assets/derived/)",
    "sample-lens": "read a line — pitch centre, phrases, where a detector would fire — against bars",
    "stretch-ab": "render one stretch/pitch move through every available backend, to listen to",
}


def _usage() -> str:
    width = max(len(s) for s in _SUBCOMMANDS)
    lines = [
        "hallucinote — author and produce music in Ableton Live, as code.",
        "",
        "Usage: hallucinote <command> [args...]",
        "       hallucinote <command> --help    (per-command help)",
        "",
        "Commands:",
    ]
    for name in _SUBCOMMANDS:
        lines.append(f"  {name.ljust(width)}  {_SUMMARY.get(name, '')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0

    sub, rest = argv[0], argv[1:]
    target = _SUBCOMMANDS.get(sub)
    if target is None:
        print(f"hallucinote: unknown command {sub!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    module_path, func_name = target
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    # The subcommand owns its own output (we forward stdout/stderr untouched) and
    # its exit code; None is treated as success.
    return int(func(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
