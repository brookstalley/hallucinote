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
    IGNORED_BLOCKS,
    IGNORED_TYPES,
    RENDERED_BLOCKS,
    RENDERED_TYPES,
    RedactionFailure,
    TranscriptError,
    UnknownBlockType,
    UnknownRecordType,
    assert_publishable,
    build_excerpt,
    latest_session,
    load,
    main,
    redact,
    repo_root_of,
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


def test_dash_encoded_home_paths_are_redacted() -> None:
    """Claude Code flattens the cwd into its own directory names.

    ``~/.claude/projects/-Users-alice-source-repo/`` and the matching task
    scratchpad carry the account name in a form no slash-based pattern sees. The
    first version of this tool passed its own ``grep -c '/Users/'`` acceptance
    check while this form would have shipped straight into published output.
    """
    out = redact("~/.claude/projects/-Users-alice-source-repo/s.jsonl", FIXTURE_ROOT)
    assert "alice" not in out
    assert redact("/private/tmp/claude-501/-Users-alice-source-repo/t", FIXTURE_ROOT).count(
        "alice"
    ) == 0


def test_hyphenated_account_name_is_fully_redacted() -> None:
    """A hyphenated username breaks the generic dash pattern, so a literal layer runs first.

    ``-`` is the delimiter of the slug encoding, so for ``mary-jane`` the generic
    pattern matches only ``-Users-mary`` and emits ``-REDACTED-jane-source-repo``
    — half the name shipping, undetectably, because the gate re-scans with that
    same pattern and finds no ``-Users-`` left. A shared pattern cannot catch its
    own blind spot; knowing the real name removes the ambiguity.
    """
    slug = "-Users-mary-jane-source-repo"
    out = redact(f"~/.claude/projects/{slug}/s.jsonl", FIXTURE_ROOT, account="mary-jane")
    assert "jane" not in out, "the second half of the account name survived"
    assert "mary" not in out
    assert redact("/Users/mary-jane/x", FIXTURE_ROOT, account="mary-jane") == "~/x"


def test_gate_refuses_an_unredacted_hyphenated_account_name() -> None:
    """The gate must know the literal name too, or it inherits the same blind spot."""
    with pytest.raises(RedactionFailure, match="account name"):
        assert_publishable("-Users-mary-jane-source-repo/x", account="mary-jane")
    with pytest.raises(RedactionFailure, match="account name"):
        assert_publishable("/Users/mary-jane/x", account="mary-jane")


def test_no_account_name_available_degrades_to_the_generic_patterns() -> None:
    """An empty account must not crash or match everything — the generic layer still applies."""
    assert redact("/Users/alice/x", FIXTURE_ROOT, account="") == "~/x"
    with pytest.raises(RedactionFailure):
        assert_publishable("/Users/alice/x", account="")


def test_gate_catches_a_dash_encoded_account_name() -> None:
    with pytest.raises(RedactionFailure, match="dash-encoded"):
        assert_publishable("path -Users-alice-source-repo/x")


def test_repo_root_rewrite_is_anchored_at_a_path_boundary() -> None:
    """A sibling repo sharing the root's prefix must not be mangled into it.

    Unanchored, a root of ``…/source/demo-repo`` also matches inside
    ``…/source/demo-repo-songs/x``, yielding ``.-songs/x`` — garbled output that
    still discloses the shape of a private sibling workspace.
    """
    out = redact(f"{FIXTURE_ROOT}-songs/x/build.py", FIXTURE_ROOT)
    assert ".-songs" not in out
    assert "testuser" not in out, "the sibling path must still be redacted, just not mangled"


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


# --- the CLI -----------------------------------------------------------------


def test_main_writes_the_excerpt_and_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "excerpt.md"
    code = main(["--session", str(FIXTURE), "--repo-root", str(FIXTURE_ROOT), "--out", str(out)])
    assert code == 0
    assert "chorus lift" in out.read_text()


def test_main_writes_nothing_when_the_gate_trips(tmp_path: Path) -> None:
    """The no-write-on-refusal contract: a refusal must leave no partial file."""
    record = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "truncated <system-reminder>x"}]},
    }
    session = tmp_path / "t.jsonl"
    session.write_text(json.dumps(record) + "\n")
    out = tmp_path / "excerpt.md"
    assert main(["--session", str(session), "--repo-root", str(tmp_path), "--out", str(out)]) == 1
    assert not out.exists(), "a refused run left a file behind"


def test_main_removes_a_stale_out_file_on_refusal(tmp_path: Path) -> None:
    """A refusal must not leave last run's output looking like this run's.

    Worse than writing nothing is leaving a plausible file behind: the command
    failed, but a later step reads the path and publishes stale content.
    """
    record = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "truncated <system-reminder>x"}]},
    }
    session = tmp_path / "t.jsonl"
    session.write_text(json.dumps(record) + "\n")
    out = tmp_path / "excerpt.md"
    out.write_text("stale content from a previous successful run\n")
    assert main(["--session", str(session), "--repo-root", str(tmp_path), "--out", str(out)]) == 1
    assert not out.exists(), "a refused run left the previous run's output in place"


def test_rendered_and_ignored_type_sets_are_disjoint() -> None:
    """A type in both sets would be silently ignored, since ignore is checked first."""
    assert not (RENDERED_TYPES & IGNORED_TYPES.keys())
    assert not (RENDERED_BLOCKS & IGNORED_BLOCKS.keys())


def test_every_ignored_record_type_actually_produces_no_output(tmp_path: Path) -> None:
    """Each classified ignored type is exercised, not just the ones the fixture happens to carry.

    The fixture cannot practically hold a realistic instance of all thirteen, so
    this drives them synthetically: a classification that stops working shows up
    here rather than the next time that type appears in a real session.
    """
    for rtype in IGNORED_TYPES:
        path = tmp_path / f"{rtype}.jsonl"
        path.write_text(json.dumps({"type": rtype, "content": "/Users/alice/secret"}) + "\n")
        assert to_turns(load(path), tmp_path) == [], f"{rtype} produced output"


def test_main_reports_a_resolution_failure_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty project dir must be a clean message, not a stack trace.

    A traceback quotes the absolute project path in its frames — precisely what
    this tool exists to keep out of the open.
    """
    assert main(["--project-dir", str(tmp_path)]) == 1
    assert "tour_transcript:" in capsys.readouterr().err


# --- source resolution -------------------------------------------------------


def test_latest_session_picks_the_newest_transcript(tmp_path: Path) -> None:
    older, newer = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    older.write_text("{}\n")
    newer.write_text("{}\n")
    import os

    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    assert latest_session(tmp_path) == newer


def test_latest_session_errors_on_an_empty_project_dir(tmp_path: Path) -> None:
    with pytest.raises(TranscriptError, match="no .* transcripts"):
        latest_session(tmp_path)


def test_repo_root_of_falls_back_when_not_a_git_repo(tmp_path: Path) -> None:
    """A non-repo directory is not an error — the home collapse still applies."""
    assert repo_root_of(tmp_path) == tmp_path


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
