"""The unified ``hallucinote`` CLI dispatcher (PLUGIN-SELF-CONTAINED).

The dispatcher forwards each subcommand's args verbatim to the engine module's
``main(argv)`` and returns its exit code — a thin router, not a black box. These
tests pin routing, the help/unknown paths, and that every mapped target resolves
(guards a typo'd module path / entry name).
"""
from __future__ import annotations

import importlib

from hallucinote import cli


def test_help_and_empty_print_usage_and_succeed(capsys):
    for argv in ([], ["--help"], ["-h"], ["help"]):
        assert cli.main(argv) == 0
        out = capsys.readouterr().out
        assert "Usage: hallucinote" in out
        for sub in cli._SUBCOMMANDS:
            assert sub in out, f"usage must list the {sub!r} command"


def test_unknown_command_errors_with_code_2(capsys):
    rc = cli.main(["bogus"])
    assert rc == 2
    assert "unknown command 'bogus'" in capsys.readouterr().err


def test_dispatch_forwards_argv_and_returns_code(monkeypatch):
    """`push execute --song x` → push_cli.main(["execute", "--song", "x"])."""
    import hallucinote.sync.push_cli as push_cli

    seen: dict[str, object] = {}

    def spy(argv):
        seen["argv"] = argv
        return 7

    monkeypatch.setattr(push_cli, "main", spy)
    rc = cli.main(["push", "execute", "--song", "x"])
    assert rc == 7
    assert seen["argv"] == ["execute", "--song", "x"]


def test_none_return_is_treated_as_success(monkeypatch):
    import hallucinote.tools.reindex_markdown as reindex

    monkeypatch.setattr(reindex, "main", lambda argv: None)
    assert cli.main(["reindex", "songs/x"]) == 0


def test_every_subcommand_target_resolves():
    """Each mapped (module, entry) must import and expose a callable entry."""
    for sub, (module_path, func_name) in cli._SUBCOMMANDS.items():
        module = importlib.import_module(module_path)
        func = getattr(module, func_name, None)
        assert callable(func), f"{sub} → {module_path}.{func_name} is not callable"


def test_capture_cli_main_accepts_argv():
    """capture_cli.main gained an argv param (was sys.argv-only) so the dispatcher
    can forward to it like every other subcommand."""
    import inspect

    from hallucinote.tools import capture_cli

    assert "argv" in inspect.signature(capture_cli.main).parameters


def test_every_subcommand_appears_in_the_running_the_engine_table():
    """`docs/running-the-engine.md`'s command table is the user-facing list, and
    `cli._SUMMARY` is the `--help` list. They were fixed by hand once (the
    `overview-drift` row under-claimed while `--help` over-claimed), and nothing
    stopped them drifting apart again — the same rot class `overview-drift`
    itself exists to catch, one level up.
    """
    import re
    from pathlib import Path

    from hallucinote import cli

    table = (Path(__file__).resolve().parents[2] / "docs" / "running-the-engine.md").read_text()
    # Row cells open with the command in backticks: `| \`push …\` | … |`.
    documented: set[str] = set()
    for row in re.findall(r"^\|([^|]+)\|", table, re.MULTILINE):
        for name in re.findall(r"`([a-z][a-z-]*)", row):
            documented.add(name)

    missing = sorted(n for n in cli._SUBCOMMANDS if n not in documented)
    assert not missing, (
        f"subcommand(s) absent from docs/running-the-engine.md's table: {missing}. "
        "The table is how a user discovers the command; an undocumented "
        "subcommand is an undiscoverable one."
    )
