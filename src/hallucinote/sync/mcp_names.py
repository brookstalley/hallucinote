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
    # Chunk 3: return-track creation is not exposed by MCP. Canonical args:
    #   {name: str}. Emulation must create the track via the Live UI/API and
    #   return its 1-based `return_index`.
    "create_return_track": "_emulate_create_return_track",
    # Chunk 3: per-track mute/solo/arm and color writes are not exposed by MCP.
    # Canonical args: {track_index: int 1-based, value: bool|int}. Today these
    # are manual-knob operations.
    "set_track_mute": "_emulate_set_track_mute",
    "set_track_solo": "_emulate_set_track_solo",
    "set_track_arm": "_emulate_set_track_arm",
    "set_track_color": "_emulate_set_track_color",
    # NOTE: master-strip volume/pan writes (formerly `set_master_volume` /
    # `set_master_panning`) are now emitted directly by the planner as
    # `ableton_session(action='set_master_property', property=..., value=...)`.
    # Wave M-1 retargeted these — no alias entry needed.
    # Chunk 4a: device chain construction. Canonical args:
    #   load_device(track_index: int 1-based, position: int 1-based,
    #               kind: str, preset_uri: str | null)
    # MCP today: `load_instrument_or_effect(track_index, uri)` appends to the
    # end of the chain — no `position` control and no precise `kind` selection.
    # Emulation must order loads / use named presets to land in the right slot.
    "load_device": "_emulate_load_device",
    # Chunk 4a: same shape, but for return tracks. No MCP equivalent today.
    "load_device_on_return": "_emulate_load_device_on_return",
    # Chunk 4a: device parameter writes for tracks. Canonical args:
    #   set_device_parameter(track_index, device_index: int 1-based,
    #                        parameter_name: str, value: float 0.0-1.0).
    # MCP today: `set_device_parameter` is registered but BROKEN per #17b
    # (raises `No module named 'MCP_Server'`). Planner emits canonically;
    # the agent / shim handles the broken state until the fork patches it.
    "set_device_parameter": "_emulate_set_device_parameter",
    # Chunk 4a: same shape, for return tracks. No MCP equivalent today.
    "set_return_device_parameter": "_emulate_set_return_device_parameter",
    # Chunk 4b: automation envelope writes. Today MCP exposes only
    # `manage_clip_automation(track_index, clip_index, action, parameter_name)`
    # which creates an empty envelope on a single named parameter; it has no
    # breakpoint write surface. The canonical names below carry the full
    # (target, breakpoints) shape and expect the emulator to drive
    # `manage_clip_automation` + low-level Live API calls per breakpoint.
    # All canonical args use 1-based indices; breakpoints is a list of dicts:
    #   [{time_beats: float, value: float, curve_kind: 'linear'|'hold'|'fast'|'slow'}, ...].
    # The result dict should carry `envelope_index: int` so apply_push_results
    # can record an `envelope:` link binding.
    "write_clip_cc_envelope": "_emulate_write_clip_cc_envelope",
    # write_clip_cc_envelope(track_index, clip_index, cc_number: int, breakpoints)
    "write_clip_pitch_bend_envelope": "_emulate_write_clip_pitch_bend_envelope",
    # write_clip_pitch_bend_envelope(track_index, clip_index, breakpoints)
    "write_note_expression_envelope": "_emulate_write_note_expression_envelope",
    # write_note_expression_envelope(track_index, clip_index, note_pitch: int,
    #                                note_start_beats: float,
    #                                axis: 'pitch'|'pressure'|'timbre', breakpoints)
    "write_device_parameter_envelope": "_emulate_write_device_parameter_envelope",
    # write_device_parameter_envelope(track_index, device_index, parameter_name, breakpoints)
    "write_return_device_parameter_envelope":
        "_emulate_write_return_device_parameter_envelope",
    # write_return_device_parameter_envelope(return_index, device_index,
    #                                        parameter_name, breakpoints)
    "write_mixer_volume_envelope": "_emulate_write_mixer_volume_envelope",
    # write_mixer_volume_envelope(track_index, breakpoints)
    "write_mixer_pan_envelope": "_emulate_write_mixer_pan_envelope",
    # write_mixer_pan_envelope(track_index, breakpoints)
    "write_send_envelope": "_emulate_write_send_envelope",
    # write_send_envelope(track_index, return_index, breakpoints)
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
