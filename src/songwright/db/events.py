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
CLIP_CREATED = "clip_created"
CLIP_UPDATED = "clip_updated"
CLIP_DELETED = "clip_deleted"

# Mix: track kind, mixer state, returns, sends
TRACK_MIXER_SET = "track_mixer_set"
RETURN_CREATED = "return_created"
RETURN_UPDATED = "return_updated"
RETURN_DELETED = "return_deleted"
SEND_SET = "send_set"
SEND_REMOVED = "send_removed"

# Mix: device chains, devices, parameters
DEVICE_CHAIN_CREATED = "device_chain_created"
DEVICE_CHAIN_DELETED = "device_chain_deleted"
DEVICE_CREATED = "device_created"
DEVICE_DELETED = "device_deleted"
DEVICE_PARAMETER_SET = "device_parameter_set"
DEVICE_PARAMETER_REMOVED = "device_parameter_removed"

# Score: sections, tempo map, time-signature map, cue points
SECTION_CREATED = "section_created"
SECTION_UPDATED = "section_updated"
SECTION_DELETED = "section_deleted"
TEMPO_POINT_ADDED = "tempo_point_added"
TEMPO_POINT_REMOVED = "tempo_point_removed"
TIME_SIGNATURE_POINT_ADDED = "time_signature_point_added"
TIME_SIGNATURE_POINT_REMOVED = "time_signature_point_removed"
CUE_POINT_ADDED = "cue_point_added"
CUE_POINT_REMOVED = "cue_point_removed"

# Notes
NOTES_INSERTED = "notes_inserted"
CLIP_NOTES_REPLACED = "clip_notes_replaced"
NOTE_UPDATED = "note_updated"
NOTES_DELETED = "notes_deleted"
NOTES_BULK_UPDATED = "notes_bulk_updated"

# Arrangement
ARRANGEMENT_ADDED = "arrangement_added"
ARRANGEMENT_REMOVED = "arrangement_removed"

# Provenance
REQUEST_CREATED = "request_created"

# Ableton projection (sessions + links replace the per-row link kinds)
ABLETON_SESSION_CREATED = "ableton_session_created"
ABLETON_LINK_SET = "ableton_link_set"

# Valid actor values for events.actor / requests.actor.
ACTORS = frozenset({"user", "llm", "sync", "generator", "system"})
