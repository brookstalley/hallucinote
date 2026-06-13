"""Event-kind constants.

Append new kinds here when adding a mutator. Strings (not enums) so the audit
table stays portable; treat the constant as the only sanctioned source.

Naming: <noun>_<past-tense-verb>. Payload schemas live with each kind as a
docstring-style comment near the emitting mutator.
"""
from __future__ import annotations

# Songs / structure
SONG_CREATED = "song_created"
SONG_UPDATED = "song_updated"
SONG_TIMING_MODE_SET = "song_timing_mode_set"
TRACK_CREATED = "track_created"
TRACK_UPDATED = "track_updated"
TRACK_DELETED = "track_deleted"
CLIP_CREATED = "clip_created"
CLIP_UPDATED = "clip_updated"
CLIP_DELETED = "clip_deleted"

# Mix: track kind, mixer state, returns, sends
TRACK_MIXER_SET = "track_mixer_set"
# RTE-1K9T: track signal routing (output + input) + monitor switch. Payload
# {track_id, changes} mirrors TRACK_MIXER_SET — `changes` is the subset of
# routing/monitor fields that actually changed (semantic reference, not Live
# display_name; see set_track_routing).
TRACK_ROUTING_SET = "track_routing_set"
RETURN_CREATED = "return_created"
RETURN_UPDATED = "return_updated"
RETURN_DELETED = "return_deleted"
SEND_SET = "send_set"
SEND_REMOVED = "send_removed"
SEND_INTENT_SET = "send_intent_set"

# Mix: device chains, devices, parameters
DEVICE_CHAIN_CREATED = "device_chain_created"
DEVICE_CHAIN_DELETED = "device_chain_deleted"
DEVICE_CREATED = "device_created"
DEVICE_DELETED = "device_deleted"
DEVICE_PARAMETER_SET = "device_parameter_set"
DEVICE_PARAMETER_REMOVED = "device_parameter_removed"
# SDC-7K3M: a device's sidechain SOURCE (input routing) — a semantic FK to the
# source track, symmetric with TRACK_ROUTING_SET (resolved to/from Live's
# display_name at push/pull). The S/C On / Gain / Mix params round-trip
# separately as ordinary DEVICE_PARAMETER_SET events.
DEVICE_SIDECHAIN_SET = "device_sidechain_set"
DRUM_PAD_MAPPINGS_REPLACED = "drum_pad_mappings_replaced"

# Mix: automation envelopes + breakpoints
ENVELOPE_CREATED = "envelope_created"
ENVELOPE_DELETED = "envelope_deleted"
BREAKPOINT_ADDED = "breakpoint_added"
BREAKPOINT_REMOVED = "breakpoint_removed"
BREAKPOINTS_REPLACED = "breakpoints_replaced"
# ENV-7G4K: a perform-routed arc was gesture-recorded into Live's
# arrangement automation (sync-state, like ABLETON_LINK_SET).
AUTOMATION_PERFORMED = "automation_performed"

# Score: sections, tempo map, time-signature map, cue points
SECTION_CREATED = "section_created"
SECTION_UPDATED = "section_updated"
SECTION_DELETED = "section_deleted"
TEMPO_POINT_ADDED = "tempo_point_added"
TEMPO_POINT_UPDATED = "tempo_point_updated"
TEMPO_POINT_REMOVED = "tempo_point_removed"
TIME_SIGNATURE_POINT_ADDED = "time_signature_point_added"
TIME_SIGNATURE_POINT_UPDATED = "time_signature_point_updated"
TIME_SIGNATURE_POINT_REMOVED = "time_signature_point_removed"
CUE_POINT_ADDED = "cue_point_added"
CUE_POINT_REMOVED = "cue_point_removed"

# Notes
NOTES_INSERTED = "notes_inserted"
CLIP_NOTES_REPLACED = "clip_notes_replaced"
NOTE_UPDATED = "note_updated"
NOTES_DELETED = "notes_deleted"
NOTES_BULK_UPDATED = "notes_bulk_updated"

# Arrangement clips
ARRANGEMENT_CLIP_ADDED = "arrangement_clip_added"
ARRANGEMENT_CLIP_REMOVED = "arrangement_clip_removed"

# Provenance
REQUEST_CREATED = "request_created"
REQUEST_CLOSED = "request_closed"

# Song metadata layer: markdown ref records (the audit-side companion to
# the markdown_refs projection table). Emitted when an LLM-driven write
# produces or updates a decision/annotation file under songs/<name>/.
# Reindex of pre-existing files DOES NOT emit this event — that's a
# projection rebuild, not a domain change.
MARKDOWN_REF_RECORDED = "markdown_ref_recorded"

# Ableton projection (sessions + links replace the per-row link kinds)
ABLETON_SESSION_CREATED = "ableton_session_created"
ABLETON_LINK_SET = "ableton_link_set"
# W18-B: strict link reconciliation — probe-and-link removes links whose
# ableton_index no longer matches a Live entity in the fresh probe.
ABLETON_LINK_REMOVED = "ableton_link_removed"

# Valid actor values for events.actor / requests.actor.
# 'build' marks rows created/updated by a song's build.py running under
# M.build_session (W12-A). The build-session uses this actor to discriminate
# build-owned rows (tombstone-eligible when not touched in the latest build)
# from pulled rows (actor='sync', authoritative for Live's state) and from
# user/LLM edits (preserved across build re-runs).
ACTORS = frozenset({"user", "llm", "sync", "generator", "system", "build"})
