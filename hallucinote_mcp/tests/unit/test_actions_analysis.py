"""Action-registration + schema tests for ``ableton_analysis``.

End-to-end handler behavior is covered in
``test_handlers_analysis.py``; this file pins the action-surface
contract (params, runs_server_side, help-action present, tool added to
TOOLS) so future schema drift fails loud.
"""
from __future__ import annotations

import pytest

from hallucinote_mcp.schema import (
    TOOLS,
    actions_for,
    get,
    register_help_actions,
)


@pytest.fixture(autouse=True)
def _ensure_actions_registered():
    """Import the actions package so registration side effects fire."""
    # Import inside the fixture to defer until test collection — at
    # module load time the registry may have stale state from another
    # test's isolation context.
    import hallucinote_mcp.actions  # noqa: F401
    register_help_actions()


def test_ableton_analysis_in_tools_tuple():
    assert "ableton_analysis" in TOOLS


def test_ableton_analysis_action_surface():
    action_names = {a.name for a in actions_for("ableton_analysis")}
    assert action_names == {
        "help", "analyze", "start", "status", "get_latest_report", "extract",
    }


def test_start_action_is_server_side_sharing_analyze_params():
    start = get("ableton_analysis", "start")
    assert start is not None
    assert start.runs_server_side is True
    assert start.runs_on_worker is False
    # No events — async start is a read-side DSP background, like analyze.
    assert start.db_writes is False
    # `start` shares analyze's params (it backgrounds the same work).
    analyze = get("ableton_analysis", "analyze")
    assert {p.name for p in start.params} == {p.name for p in analyze.params}
    song_slug = next(p for p in start.params if p.name == "song_slug")
    assert song_slug.required is True


def test_status_action_is_server_side_with_job_id():
    status = get("ableton_analysis", "status")
    assert status is not None
    assert status.runs_server_side is True
    assert status.runs_on_worker is False
    assert {p.name for p in status.params} == {"job_id"}
    job_id = next(p for p in status.params if p.name == "job_id")
    assert job_id.required is True


def test_analyze_tips_point_to_async_for_large_captures():
    """The sync-vs-async trigger is documented on the synchronous action so the
    agent learns when to reach for start/status (Chunk 2 disposition)."""
    analyze = get("ableton_analysis", "analyze")
    joined = " ".join(analyze.tips).lower()
    assert "start" in joined and "status" in joined
    assert "60s" in joined or "timeout" in joined


def test_analyze_action_is_server_side_with_song_slug_param():
    analyze = get("ableton_analysis", "analyze")
    assert analyze is not None
    assert analyze.runs_server_side is True
    assert analyze.runs_on_worker is False
    param_names = {p.name for p in analyze.params}
    assert "song_slug" in param_names
    assert "captures_dir" in param_names
    # song_slug must be required for the song-disambiguation contract;
    # captures_dir optional so the default-to-latest path works.
    song_slug_param = next(p for p in analyze.params if p.name == "song_slug")
    assert song_slug_param.required is True
    captures_dir_param = next(p for p in analyze.params if p.name == "captures_dir")
    assert captures_dir_param.required is False


def test_get_latest_report_action_is_server_side_with_song_slug():
    glr = get("ableton_analysis", "get_latest_report")
    assert glr is not None
    assert glr.runs_server_side is True
    param_names = {p.name for p in glr.params}
    assert "song_slug" in param_names


def test_extract_action_is_server_side_with_song_slug():
    extract = get("ableton_analysis", "extract")
    assert extract is not None
    assert extract.runs_server_side is True
    assert extract.runs_on_worker is False
    # Read-only: no db_writes (the extract emits no events).
    assert extract.db_writes is False
    param_names = {p.name for p in extract.params}
    assert "song_slug" in param_names
    song_slug_param = next(p for p in extract.params if p.name == "song_slug")
    assert song_slug_param.required is True


def test_help_action_lists_under_ableton_analysis():
    """register_help_actions() should give every tool a help entry."""
    help_action = get("ableton_analysis", "help")
    assert help_action is not None
    assert help_action.name == "help"
    assert help_action.handler is None  # help is dispatcher-special
    assert help_action.declarative_op is None


def test_analyze_action_description_mentions_mvp_scope():
    """The action description is what the agent sees in tool discovery.
    Sanity-check it names the actual MVP analyses so the agent's mental
    model lines up with what the handler does."""
    analyze = get("ableton_analysis", "analyze")
    assert analyze is not None
    desc = analyze.description.lower()
    assert "loudness" in desc
    assert "overshoot" in desc or "attribut" in desc
    assert "reverb" in desc
