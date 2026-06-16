"""All state-changing operations on the hallucinote DB.

Every function here:
  1. Performs its state change.
  2. Emits an `events` row describing the change in the same transaction.

Callers MUST use these instead of raw SQL. The discipline is the only thing
that makes a future event-store flip cheap rather than a rewrite.

Conventions:
- Functions take `conn` as first positional arg; everything else keyword-only.
- IDs are UUIDv4 hex strings, generated here via `_uuid()`. Mutators return the
  new id (for creates), the list of new ids (for bulk), or None (otherwise).
- Every mutator accepts `actor`, `request_id`, `reason` kwargs. Defaults
  (`'system'`, None, None) keep tests terse; agent code threads explicit
  values to make audit trails readable.
- Notes use canonical field names: pitch, start_beats, duration_beats, velocity,
  mute (0/1), tags (list[str] | None). NOT start_time / duration — convert at
  the porter / generator boundary.

This module was split from a single 4000-line file into a package for
maintainability. The split is behavior-preserving: every name the old module
exposed (`from hallucinote.db import mutations` then `mutations.create_clip`)
re-exports here, so callers see no difference.
"""
from __future__ import annotations

# Shared infrastructure (id gen, event emit, MutatorResult, build-session
# ContextVar machinery, module-level constants, transaction).
from ._core import (
    MutatorResult,
    NoteDict,
    REQUEST_KINDS,
    REQUEST_OUTCOMES,
    _current_build_session,
    _emit,
    _record_touch_if_session,
    _require_bar_floor,
    _resolve_actor_and_request,
    _touch_clip,
    _touch_song,
    _uuid,
    transaction,
)

# Domain submodules.
from .arrangement import (
    add_arrangement_clip,
    add_cue_point,
    remove_arrangement_clip,
    remove_cue_point,
)
from .build import (
    BuildSession,
    _latest_actor_for,
    build_session,
)
from .clips import (
    WARP_MODES,
    create_audio_clip,
    create_clip,
    delete_clip,
    update_clip,
)
from .devices import (
    BREAKPOINT_CURVE_KINDS,
    ENVELOPE_TARGET_KINDS,
    NOTE_EXPRESSION_AXES,
    add_breakpoint,
    create_device,
    create_device_chain,
    create_enum_envelope,
    create_envelope,
    delete_device,
    delete_device_chain,
    delete_envelope,
    performed_automation_fingerprint,
    record_performed_automation,
    remove_breakpoint,
    remove_device_parameter,
    replace_breakpoints,
    replace_drum_pad_mappings,
    set_chain_properties,
    set_device_parameter,
    set_device_sidechain,
)
from .links import (
    ABLETON_LINK_KINDS,
    create_ableton_session,
    link_db_to_ableton,
    reset_song_content,
    unlink_db_from_ableton,
)
from .notes import (
    _normalize_note,
    delete_notes,
    insert_notes,
    replace_clip_notes,
    update_note,
    update_notes_by_tag,
)
from .requests import (
    close_request,
    create_request,
    provenance_metadata,
    record_markdown_ref,
    request,
)
from .returns import (
    create_return,
    delete_return,
    remove_send,
    set_send_intended_rt60,
    set_send_level,
    update_return,
)
from .score import (
    TEMPO_RAMP_KINDS,
    add_tempo_point,
    add_time_signature_point,
    create_section,
    delete_section,
    remove_tempo_point,
    remove_time_signature_point,
    update_section,
    update_tempo_point,
    update_time_signature_point,
)
from .songs import (
    TIMING_MODES,
    create_song,
    set_song_timing_mode,
    set_song_tuning,
)
from .tracks import (
    INPUT_ROUTING_KINDS,
    MONITORING_STATES,
    OUTPUT_ROUTING_KINDS,
    TRACK_KINDS,
    _delete_track,
    create_track,
    set_track_mixer,
    set_track_routing,
)


__all__ = [
    # _core
    "MutatorResult",
    "NoteDict",
    "REQUEST_KINDS",
    "REQUEST_OUTCOMES",
    "transaction",
    # songs
    "TIMING_MODES",
    "create_song",
    "set_song_timing_mode",
    "set_song_tuning",
    # tracks
    "INPUT_ROUTING_KINDS",
    "MONITORING_STATES",
    "OUTPUT_ROUTING_KINDS",
    "TRACK_KINDS",
    "create_track",
    "set_track_mixer",
    "set_track_routing",
    # clips
    "WARP_MODES",
    "create_audio_clip",
    "create_clip",
    "delete_clip",
    "update_clip",
    # notes
    "delete_notes",
    "insert_notes",
    "replace_clip_notes",
    "update_note",
    "update_notes_by_tag",
    # arrangement
    "add_arrangement_clip",
    "add_cue_point",
    "remove_arrangement_clip",
    "remove_cue_point",
    # score
    "TEMPO_RAMP_KINDS",
    "add_tempo_point",
    "add_time_signature_point",
    "create_section",
    "delete_section",
    "remove_tempo_point",
    "remove_time_signature_point",
    "update_section",
    "update_tempo_point",
    "update_time_signature_point",
    # returns + sends
    "create_return",
    "delete_return",
    "remove_send",
    "set_send_intended_rt60",
    "set_send_level",
    "update_return",
    # devices + automation
    "BREAKPOINT_CURVE_KINDS",
    "ENVELOPE_TARGET_KINDS",
    "NOTE_EXPRESSION_AXES",
    "add_breakpoint",
    "create_device",
    "create_device_chain",
    "create_enum_envelope",
    "create_envelope",
    "delete_device",
    "delete_device_chain",
    "delete_envelope",
    "performed_automation_fingerprint",
    "record_performed_automation",
    "remove_breakpoint",
    "remove_device_parameter",
    "replace_breakpoints",
    "replace_drum_pad_mappings",
    "set_device_parameter",
    "set_chain_properties",
    "set_device_sidechain",
    # links + reset
    "ABLETON_LINK_KINDS",
    "create_ableton_session",
    "link_db_to_ableton",
    "reset_song_content",
    "unlink_db_from_ableton",
    # requests / provenance
    "close_request",
    "create_request",
    "provenance_metadata",
    "record_markdown_ref",
    "request",
    # build session
    "BuildSession",
    "build_session",
]
