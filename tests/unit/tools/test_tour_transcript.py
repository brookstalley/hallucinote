"""Tests for the tour transcript renderer.

The contract under test is a disclosure contract, not a formatting one: the
renderer's job is that nothing which was private in a session transcript becomes
public in the repo. So most of these assert *absence*, and the fixture is built
to carry one instance of every leak class so those assertions have something to
bite on.

The fixture uses a synthetic ``/Users/testuser/source/demo-repo`` throughout —
never a real account name. It ships in a public repo, so a fixture written with
real paths would itself be the bug this tool exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tour_transcript import (
    RedactionFailure,
    TranscriptError,
    UnknownBlockType,
    UnknownRecordType,
    assert_publishable,
    build_excerpt,
    load,
    redact,
    render,
    select,
    to_turns,
    tool_line,
)

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_sample.jsonl"
FIXTURE_ROOT = Path("/Users/testuser/source/demo-repo")


@pytest.fixture
def document() -> str:
    """The rendered fixture, guarded against vacuous truth.

    Almost every disclosure assertion below is of the form ``x not in document``,
    which passes trivially if rendering ever returns nothing. These two positive
    checks make the whole file depend on the renderer actually producing output:
    break rendering and the suite goes red here rather than staying green while
    asserting nothing.
    """
    rendered = build_excerpt(FIXTURE, FIXTURE_ROOT)
    assert "chorus lift" in rendered, "the fixture's prompts never reached the output"
    assert "Dragging the drums" in rendered, "the fixture's responses never reached the output"
    return rendered


# --- the disclosure contract -------------------------------------------------


def test_no_home_paths_survive(document: str) -> None:
    assert "/Users/" not in document
    assert "testuser" not in document


def test_system_reminder_body_is_stripped(document: str) -> None:
    assert "system-reminder" not in document
    assert "punk drums" not in document, "the reminder's payload leaked, not just its tags"


def test_bare_reminder_word_in_prose_is_allowed() -> None:
    """An agent explaining the mechanism is not disclosing one.

    The leak is an injected block's contents, which a surviving tag announces.
    Gating on the bare word would refuse any session that discussed its own
    harness — including the one that built this tool.
    """
    prose = "the harness injects a system-reminder before each turn"
    assert_publishable(prose)  # does not raise
    with pytest.raises(RedactionFailure, match="system-reminder tag"):
        assert_publishable("truncated <system-reminder>payload")
    with pytest.raises(RedactionFailure, match="system-reminder tag"):
        assert_publishable("orphaned </system-reminder>")


def test_slash_command_echoes_are_dropped_entirely() -> None:
    """A `/clear` must not render as though the user typed the raw XML.

    Stripping the tags alone would leave the command name behind as prose; the
    whole element goes, which empties the turn and drops it.
    """
    echo = "<command-name>/clear</command-name><command-args></command-args>"
    assert redact(echo, FIXTURE_ROOT).strip() == ""
    assert redact("<local-command-stdout>noise</local-command-stdout>", FIXTURE_ROOT).strip() == ""


def test_thinking_blocks_are_dropped(document: str) -> None:
    assert "must never be published" not in document


def test_tool_results_are_dropped(document: str) -> None:
    assert ".ssh/config" not in document
    assert "other secrets" not in document


def test_sidechain_and_meta_records_are_dropped(document: str) -> None:
    assert "Subagent chatter" not in document
    assert "local-command-stdout" not in document


def test_ignored_record_types_contribute_nothing(document: str) -> None:
    for marker in ("Hook ran", "private/notes.md", '"body"', '"diff"'):
        assert marker not in document


def test_tool_calls_render_as_one_liners_not_full_input(document: str) -> None:
    # The Bash command line carried an absolute path; only the description ships.
    assert "`Bash` — Run the suite" in document
    assert "cd " not in document


# --- redaction mechanics -----------------------------------------------------


def test_repo_paths_become_relative() -> None:
    out = redact(f"see {FIXTURE_ROOT}/songs/demo/build.py", FIXTURE_ROOT)
    assert out == "see songs/demo/build.py"


def test_non_repo_home_paths_collapse_to_tilde() -> None:
    assert redact("/Users/testuser/.cache/x", FIXTURE_ROOT) == "~/.cache/x"
    assert redact("/home/someone/.cache/x", FIXTURE_ROOT) == "~/.cache/x"


def test_repo_rewrite_precedes_home_collapse() -> None:
    """A repo path must not degrade to ``~/source/demo-repo/…``.

    Order matters: the generic home collapse would otherwise fire first and keep
    leaking the directory layout the repo sits in.
    """
    assert "source/demo-repo" not in redact(f"{FIXTURE_ROOT}/a.py", FIXTURE_ROOT)


def test_home_path_without_a_trailing_slash_is_redacted() -> None:
    """``/Users/alice`` at the end of a sentence leaks the same name as ``/Users/alice/``.

    Trailing punctuation is consumed along with the name. That over-redacts a
    sentence-final period, which is the correct side to err on: ``/Users/a.smith``
    is a legal account directory, so a regex that stopped at the first dot would
    leave half a real name behind.
    """
    assert redact("owned by /Users/alice.", FIXTURE_ROOT) == "owned by ~"
    assert redact("see /home/bob", FIXTURE_ROOT) == "see ~"


def test_bare_users_token_is_left_alone() -> None:
    """A ``/Users/`` mention with no account name discloses nothing.

    Prose about the pattern itself — ``git log -S'/Users/'`` — must survive
    verbatim: rewriting it would silently change a quoted command's meaning, and
    gating on it would refuse real sessions over a non-leak.
    """
    probe = "git log -S'/Users/' --oneline"
    assert redact(probe, FIXTURE_ROOT) == probe
    assert_publishable(probe)  # does not raise


def test_gate_catches_an_account_name_without_a_trailing_slash() -> None:
    with pytest.raises(RedactionFailure, match="account name"):
        assert_publishable("leaked /Users/alice")


def test_tool_line_redacts_and_takes_first_line_only() -> None:
    block = {"name": "Read", "input": {"file_path": f"{FIXTURE_ROOT}/a.py\nsecond line"}}
    assert tool_line(block, FIXTURE_ROOT) == "`Read` — a.py"


def test_tool_line_falls_back_to_bare_name_for_unlisted_tools() -> None:
    assert tool_line({"name": "Mystery", "input": {"x": 1}}, FIXTURE_ROOT) == "`Mystery`"


# --- fail-closed behavior ----------------------------------------------------


def test_assert_publishable_rejects_a_surviving_home_path() -> None:
    with pytest.raises(RedactionFailure, match="account name"):
        assert_publishable("line one\nleaked /Users/someone/x\n")


def test_assert_publishable_reports_the_offending_line_number() -> None:
    with pytest.raises(RedactionFailure, match="line 3"):
        assert_publishable("a\nb\n/Users/x/y\n")


def test_unknown_record_type_raises_rather_than_skipping(tmp_path: Path) -> None:
    """A new record type must stop the run.

    Claude Code adds record types over time; a silent skip would let a future one
    carrying unknown content pass unreviewed, which is the whole failure mode
    this tool exists to prevent.
    """
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "brand-new-kind", "payload": "?"}) + "\n")
    with pytest.raises(UnknownRecordType, match="brand-new-kind"):
        to_turns(load(path), tmp_path)


def test_unknown_block_type_raises(tmp_path: Path) -> None:
    record = {
        "type": "assistant",
        "message": {"content": [{"type": "hologram", "data": "?"}]},
    }
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(record) + "\n")
    with pytest.raises(UnknownBlockType, match="hologram"):
        to_turns(load(path), tmp_path)


def test_malformed_json_line_is_an_error_not_a_skip(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text('{"type": "user"}\nnot json\n')
    with pytest.raises(TranscriptError, match="malformed JSON"):
        load(path)


def test_build_excerpt_raises_rather_than_returning_leaky_output(tmp_path: Path) -> None:
    """The gate is the backstop for anything redaction does not know how to fix.

    An *unclosed* ``<system-reminder>`` is the realistic case: the stripper matches
    open/close pairs, so a truncated one survives redaction untouched and only the
    gate catches it. Nothing is returned when it fires.
    """
    record = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "see <system-reminder>leaked"}]},
    }
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(record) + "\n")
    with pytest.raises(RedactionFailure, match="system-reminder tag"):
        build_excerpt(path, tmp_path)


def test_home_paths_are_fixed_by_redaction_not_left_to_the_gate(tmp_path: Path) -> None:
    """Redaction handles account paths itself, even with no repo root to match."""
    record = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "path /Users/x/y"}]},
    }
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(record) + "\n")
    assert "~/y" in build_excerpt(path, Path("/nowhere"))


# --- selection and rendering -------------------------------------------------


def test_prompts_render_as_blockquotes(document: str) -> None:
    assert "> Add a chorus lift to songs/demo/build.py" in document


def test_start_at_trims_to_the_matching_prompt() -> None:
    turns = to_turns(load(FIXTURE), FIXTURE_ROOT)
    trimmed = select(turns, "make the drums drag", None)
    assert trimmed[0].role == "user"
    assert "drums drag" in trimmed[0].text
    assert "chorus lift" not in render(trimmed)


def test_start_at_with_no_match_is_an_error() -> None:
    turns = to_turns(load(FIXTURE), FIXTURE_ROOT)
    with pytest.raises(TranscriptError, match="no prompt containing"):
        select(turns, "never appears anywhere", None)


def test_exchanges_limits_the_number_of_prompts() -> None:
    turns = to_turns(load(FIXTURE), FIXTURE_ROOT)
    assert len([t for t in select(turns, None, 1) if t.role == "user"]) == 1
    assert len([t for t in select(turns, None, 2) if t.role == "user"]) == 2


def test_exchanges_keeps_the_assistant_turns_that_follow_a_kept_prompt() -> None:
    """Trimming by prompt count must not orphan a prompt from its answer."""
    kept = select(to_turns(load(FIXTURE), FIXTURE_ROOT), None, 1)
    assert any(t.role == "assistant" for t in kept)
