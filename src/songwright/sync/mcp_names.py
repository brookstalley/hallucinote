"""Tool-name aliases bridging current AbletonMCP surface to post-Wave-1 names.

Until MCP Wave 1 ships, the planner emits the *new* names (per docs/mcp-requirements.md
PRs A/C/D/G/H) and the agent / shim resolves them via this table to whatever is
actually callable today.

When the MCP server in our fork ships the renamed tools, drop the right column
and have the planner emit the canonical names directly.
"""
from __future__ import annotations

# planner emits (canonical) -> currently-callable name
ALIASES_TODAY: dict[str, str] = {
    # PR H: rename
    "set_clip_notes": "add_notes_to_clip",
    # PR C: not yet exposed at MCP layer (registered in remote script only)
    "set_arrangement_clip_notes": "add_notes_to_arrangement_clip",  # not exposed yet!
    # PR D: doesn't exist yet — must be emulated as delete_clip + create_clip + add_notes_to_clip
    "replace_session_clip": "_emulate_replace_session_clip",
    "delete_session_clip": "_emulate_delete_session_clip",
    # PR G: create_midi_track currently doesn't accept name/instrument_uri
    # — must follow with set_track_name + load_instrument_or_effect
    "create_midi_track_with": "_emulate_create_midi_track_with",
    # PR B: doesn't exist yet — agent must loop through ops manually
    "batch_arrangement_layout": "_emulate_batch_arrangement_layout",
    # Chunk 2: tempo automation per (bar, beat) — only `set_tempo` exists today
    # (global, single value, no ramp). Canonical args:
    #   {bar: int 1-based, beat: float 0-based-within-bar, bpm: float, ramp: str}.
    # Single-point/hold-ramp maps can emulate via set_tempo; multi-point /
    # linear ramps are a hard MCP gap.
    "write_tempo_point": "_emulate_write_tempo_point",
    # Chunk 2: arrangement-level meter changes are not exposed by MCP at all.
    # Canonical args: {bar, beat, numerator: int, denominator: int}.
    "write_time_signature_point": "_emulate_write_time_signature_point",
    # NOTE on tools called directly (no alias entry needed):
    # - `create_cue_point(bar: int 1-based, beat: float 0-based, name: str)`.
    #   Planner output for this tool MUST match this signature.
}


def resolve(canonical: str) -> str:
    """Return the name an agent should actually call today, or the canonical
    name if the MCP fork already supports it."""
    return ALIASES_TODAY.get(canonical, canonical)
