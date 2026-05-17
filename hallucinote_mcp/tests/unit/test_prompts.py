"""M-7 prompt registration + per-prompt shape tests."""
from __future__ import annotations

import pytest

from hallucinote_mcp.prompts import (
    PROMPT_NAMES,
    _build_return_bus,
    _compose_section_pattern,
    _create_midi_track_with_instrument,
    _humanize_clip_velocity,
    _setup_sidechain_compression,
)
from hallucinote_mcp.server import create_server, registered_prompt_names


# ---------- Surface lock ----------


_EXPECTED_PROMPTS = {
    "create_midi_track_with_instrument",
    "setup_sidechain_compression",
    "build_return_bus",
    "humanize_clip_velocity",
    "compose_section_pattern",
}


def test_prompt_name_list_matches_design():
    """Lock the M-7 surface: exactly these 5 prompts, no more, no less.

    Carry-forward principle #3 (lock-the-surface negative test). A future
    PR that adds an unlisted prompt OR drops one gets caught here.
    """
    assert set(PROMPT_NAMES) == _EXPECTED_PROMPTS


def test_create_server_registers_all_five_prompts():
    """End-to-end: create_server wires every prompt into FastMCP."""
    mcp = create_server()
    assert set(registered_prompt_names(mcp)) == _EXPECTED_PROMPTS


# ---------- Per-prompt shape ----------


def _check_message_list(messages, expected_substrings: list[str]) -> None:
    """Common shape check: returns a non-empty list of {role, content} dicts
    with the user role, plus each expected substring appears in the
    concatenated content (sanity that the template wasn't trivially empty).
    """
    assert isinstance(messages, list)
    assert len(messages) >= 1
    for m in messages:
        assert m["role"] == "user"
        assert isinstance(m["content"], str)
        assert len(m["content"]) > 50
    blob = "\n".join(m["content"] for m in messages)
    for sub in expected_substrings:
        assert sub in blob, f"expected {sub!r} in prompt output, not found"


def test_create_midi_track_with_instrument_minimal():
    out = _create_midi_track_with_instrument(
        name="Lead",
        instrument_uri="query:Operator/Bass",
    )
    _check_message_list(out, [
        "ableton_track(action='create'",
        "kind='midi'",
        "'Lead'",
        "'query:Operator/Bass'",
        "ableton_device(action='load'",
    ])


def test_create_midi_track_with_instrument_with_index_and_volume():
    out = _create_midi_track_with_instrument(
        name="Lead", instrument_uri="x", index=3, initial_volume=0.75,
    )
    blob = out[0]["content"]
    assert "index=3" in blob
    assert "0.75" in blob
    assert "set_property" in blob


def test_setup_sidechain_compression_includes_full_workflow():
    out = _setup_sidechain_compression(target_track=4, source_track=1)
    _check_message_list(out, [
        "ableton_device(action='list'",
        "Compressor2",
        "ableton_device(action='set_sidechain'",
        "source_track_index=1",
        "track_index=4",
    ])


def test_setup_sidechain_compression_with_preset():
    out = _setup_sidechain_compression(
        target_track=2, source_track=5, compressor_uri="query:Compressor/Drum Glue",
    )
    assert "'query:Compressor/Drum Glue'" in out[0]["content"]


def test_build_return_bus_minimal():
    out = _build_return_bus(name="A-Reverb", effect_uri="query:Reverb/Hall")
    _check_message_list(out, [
        "ableton_return(action='create'",
        "'A-Reverb'",
        "ableton_device(action='load'",
        "'query:Reverb/Hall'",
    ])


def test_build_return_bus_with_initial_sends():
    out = _build_return_bus(
        name="A-Delay", effect_uri="x",
        initial_sends_from=[2, 4, 5],
    )
    blob = out[0]["content"]
    assert "ableton_track(action='set_send'" in blob
    # Lists the source tracks
    assert "2" in blob and "4" in blob and "5" in blob


def test_humanize_clip_velocity_is_honest_about_gap_4():
    """humanize must explicitly call out the gap #4 limitation rather
    than silently assuming notes are readable.
    """
    out = _humanize_clip_velocity(track_index=2, clip_index=1)
    blob = out[0]["content"]
    assert "gap #4" in blob.lower()
    assert "replace_notes" in blob
    assert "track_index=2" in blob
    assert "clip_index=1" in blob


def test_humanize_clip_velocity_uses_custom_jitter():
    out = _humanize_clip_velocity(
        track_index=1, clip_index=1, jitter_percent=25.0,
    )
    assert "25.0" in out[0]["content"]


def test_humanize_clip_velocity_defaults_to_10_percent():
    out = _humanize_clip_velocity(track_index=1, clip_index=1)
    assert "10.0" in out[0]["content"]


def test_compose_section_pattern_known_kind():
    out = _compose_section_pattern(
        track_index=2, pattern_kind="trip-hop", bars=8, start_bar=5,
    )
    blob = out[0]["content"]
    assert "trip-hop" in blob
    assert "ableton_clip(action='create'" in blob
    assert "location='arrangement'" in blob
    # Length should be bars*4 beats (4/4 assumption flagged in the prompt)
    assert "32.0" in blob
    # start_beats expression cites the 4/4 assumption
    assert "4/4" in blob


def test_compose_section_pattern_unknown_kind_returns_friendly_error():
    """Unknown pattern_kind returns a teaching message listing valid choices —
    NOT a raised exception. FastMCP wraps prompt exceptions opaquely; the
    friendly path is more useful to the agent.
    """
    out = _compose_section_pattern(
        track_index=1, pattern_kind="quasiperiodic-bossa-nova",
        bars=4, start_bar=1,
    )
    blob = out[0]["content"]
    assert "quasiperiodic-bossa-nova" in blob
    assert "tresillo" in blob and "trip-hop" in blob  # lists valid options


# ---------- PRIMER budget + prompts advertised ----------


def test_primer_advertises_prompts():
    """The server PRIMER (sent on initialize) must mention prompts so
    clients see them at connect time alongside tools + resources.
    """
    from hallucinote_mcp.server import PRIMER
    assert "Prompts" in PRIMER or "prompts" in PRIMER.lower()
    # At least one prompt name appears
    assert "create_midi_track_with_instrument" in PRIMER


def test_primer_under_500_token_budget():
    """M-7 Done-when: initialize message ≤500 tokens (~2000 chars at
    4 chars/token avg). Modeling tokens as chars/4 is rough; allow some
    slop in the assertion.
    """
    from hallucinote_mcp.server import PRIMER
    approx_tokens = len(PRIMER) // 4
    assert approx_tokens <= 500, (
        f"PRIMER is ~{approx_tokens} tokens ({len(PRIMER)} chars); "
        "the M-7 budget is 500 tokens. Trim, or revisit the budget if "
        "the new content is load-bearing."
    )
