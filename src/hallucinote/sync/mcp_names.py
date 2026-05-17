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
    # Wave M-2: track + return mixer state and return creation are now
    # emitted directly by the planner as ableton_track(action='set_property',
    # ...), ableton_return(action='set_property', ...), and
    # ableton_return(action='create', name=...). The eight aliases that used
    # to live here (create_return_track, set_track_mute / solo / arm / color,
    # return mixer state) dropped.
    # Master-strip volume/pan (Wave M-1) is at
    # ableton_session(action='set_master_property', ...).
    # Wave M-3: in-place clip note replace (gap #1's renamed action) is now
    # emitted directly as ableton_clip(action='replace_notes', ...). The
    # `set_clip_notes` alias dropped here.
    # Wave M-4: device load + parameter writes for tracks AND returns are
    # now emitted directly by the planner as
    # ableton_device(action='load', track_index|return_index, kind, ...) and
    # ableton_device(action='set_parameter', track_index|return_index,
    #                device_index, parameter_name, value, value_type).
    # The four aliases that used to live here (load_device,
    # load_device_on_return, set_device_parameter,
    # set_return_device_parameter) dropped.
    #
    # Wave M-4: automation envelope writes are unified under
    # ableton_automation(action='write_envelope', target_kind=...). The
    # eight aliases that used to live here (write_clip_cc_envelope,
    # write_clip_pitch_bend_envelope, write_note_expression_envelope,
    # write_device_parameter_envelope, write_return_device_parameter_envelope,
    # write_mixer_volume_envelope, write_mixer_pan_envelope,
    # write_send_envelope) dropped.
    # NOTE on tools called directly (no alias entry needed):
    # - `create_cue_point(bar: int 1-based, beat: float 0-based, name: str)`.
    #   Planner output for this tool MUST match this signature.
    # - `set_track_volume(track_index: int 1-based, volume: float 0.0-1.0)`.
    # - `set_track_panning(track_index: int 1-based, panning: float -1.0..1.0)`.
    # - `set_track_send(track_index: int 1-based, return_index: int 1-based,
    #     value: float 0.0-1.0)`.
}


def resolve(canonical: str) -> str:
    """Return the name an agent should actually call today, or the canonical
    name if the MCP fork already supports it."""
    return ALIASES_TODAY.get(canonical, canonical)
