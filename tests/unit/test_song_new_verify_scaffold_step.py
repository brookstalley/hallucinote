"""Doc-drift lock for `/song-new` step 4 — the scaffold-verification command.

Step 4 used to be `pytest songs/<slug>/tests/ -v`, run with the ONE interpreter the
skill resolves (`$PY`, from `ableton://server/info`). That interpreter is the plugin's
inline env and has neither pytest nor pip, so the stage's own exit criterion — "the
scaffold builds and its shape tests pass" — could not be run as written. The fix ships
`hallucinote verify-scaffold`, which runs the shape checks in-process.

A subcommand nobody is told to run closes nothing, so this pins the instruction as well
as the tool: the skill must name `verify-scaffold`, must not send the agent back to
`pytest` with `$PY`, and its exit criterion must read as met by that command. (Project
learning: "when a doc IS the deliverable, lock it with a drift test".)
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SONG_NEW_SKILL = _REPO / "skills" / "song-new" / "SKILL.md"


def _text() -> str:
    return _SONG_NEW_SKILL.read_text(encoding="utf-8")


def test_step_four_invokes_verify_scaffold_with_the_resolved_interpreter():
    text = _text()
    assert "hallucinote.cli verify-scaffold" in text, (
        "/song-new step 4 must invoke `hallucinote.cli verify-scaffold` — the "
        "in-process shape check that $PY can actually run (#476)"
    )
    # Every verify-scaffold call form shown must go through the resolved $PY, like
    # every other engine command in this skill.
    for line in text.splitlines():
        if "hallucinote.cli verify-scaffold" in line:
            assert '"$PY" -m hallucinote.cli verify-scaffold' in line, (
                f"verify-scaffold must be shown as `\"$PY\" -m hallucinote.cli "
                f"verify-scaffold …` — agents copy these verbatim; got: {line!r}"
            )


def test_the_skill_no_longer_tells_the_agent_to_run_pytest():
    """`$PY` has no pytest and no pip — an instruction to run it is unrunnable."""
    text = _text()
    offenders = [
        ln for ln in text.splitlines()
        if re.search(r"(?<!`)\bpytest songs/", ln) and "Do not run" not in ln
    ]
    assert not offenders, (
        "/song-new must not instruct a `pytest songs/…` run: the interpreter the "
        "skill resolves ($PY) ships neither pytest nor pip (#476). Offending "
        f"line(s): {offenders}"
    )


def test_the_exit_criterion_names_the_command_that_meets_it():
    """A criterion whose check can't be run is not a criterion."""
    text = _text()
    section = text.split("## Exit criteria", 1)
    assert len(section) == 2, "expected an '## Exit criteria' section in /song-new"
    criteria = re.split(r"^## ", section[1], maxsplit=1, flags=re.MULTILINE)[0]
    assert "verify-scaffold" in criteria, (
        "the /song-new exit criterion for 'the scaffold builds and its shape checks "
        "pass' must name verify-scaffold, the command that checks it (#476)"
    )
    assert "pytest" not in criteria, (
        "the exit criterion must not rest on pytest — $PY cannot run it (#476)"
    )
