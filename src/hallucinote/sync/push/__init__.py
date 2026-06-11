"""DB -> Ableton planner.

Produces a list of `ToolCall` objects describing what the agent should run.
After the agent executes the plan, it calls `apply_push_results` to write
Ableton-side IDs back into the DB.

Why a plan rather than direct calls: MCP tools are invoked by the agent, not
by Python. Returning a plan keeps this layer pure, testable, and reorder-safe.

Sessions: every plan/apply takes a `session_id` (an `ableton_sessions` row).
Bindings live in `ableton_links`, not on core rows — so a song can be bound
to multiple Live sets at the same time without aliasing. Open one with
`mutations.create_ableton_session`.

Package layout (behavior-preserving split of the original `push.py`):
  - `_core`       — ToolCall / PushPlan, shared constants + bar/beat helpers
                    + note/breakpoint wire converters (no domain imports →
                    no cycles).
  - `tempo`       — tempo-map + time-signature-map planners.
  - `tracks`      — track + return create pre-passes.
  - `scenes`      — scene-provisioning pre-pass (ensure_count before clips).
  - `clips`       — per-clip + song-wide session-clip planners.
  - `arrangement` — arrangement-clip + cue-point + section planners.
  - `mix`         — mixer state + returns + master + sends planner.
  - `devices`     — device-chain planner + per-device emit.
  - `envelopes`   — automation-envelope planner + per-kind emitters.
  - `probe`       — probe-and-link, default-scaffold cleanup, clip prune,
                    coherence check.
  - `plan`        — `plan_push_song` orchestrator + `apply_push_results`.

The public import surface (`from hallucinote.sync import push`) is unchanged;
every name the original module exposed is re-exported here.
"""
from __future__ import annotations

# Module aliases preserved as attributes of the original push.py — external
# code accesses `push.Q` directly.
import json
from hallucinote.db import mutations as M, queries as Q

from ._core import (
    _DEFAULT_NUMERATOR,
    _DEFAULT_DENOMINATOR,
    ToolCall,
    PushPlan,
    _beats_per_bar,
    _meter_at_bar,
    _split_bar,
    _position_bar_to_beats,
    _notes_for_mcp,
    _breakpoints_for_mcp,
)
from .tempo import (
    plan_push_tempo_map,
    plan_push_time_signature_map,
)
from .tracks import (
    plan_push_song_tracks,
    plan_push_song_returns,
)
from .clips import (
    plan_push_clip,
    plan_push_clips,
)
from .scenes import (
    plan_push_scenes,
)
from .arrangement import (
    plan_push_arrangement,
    plan_push_cue_points,
    plan_push_sections,
)
from .mix import (
    _MIXER_FIELDS,
    plan_push_mix,
)
from .devices import (
    plan_push_devices,
    _emit_device_calls,
)
from .envelopes import (
    _LOSSY_CURVE_HINTS,
    plan_push_envelopes,
    _track_kind_for_envelope,
    classify_envelope_route,
    _clip_and_track_indices,
    _CoveringPlacement,
    _resolve_envelope_session_clip,
    _clip_local_breakpoints,
    _envelope_beat_range,
    _emit_note_expression_envelope,
    _warn_lossy_curve_hints,
    _warn_multiple_covering_clips,
    _warn_trimmed_placement,
    _warn_extra_placements,
    _resolve_and_translate_to_session_clip,
    _emit_session_clip_envelope_post_warnings,
    _emit_device_parameter_envelope,
    _emit_mixer_envelope,
    _emit_send_envelope,
)
from .perform import (
    envelope_fingerprint,
    plan_push_performed_automation,
    record_perform_result,
)
from .probe import (
    CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES,
    CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES,
    CleanupScaffoldPlan,
    plan_cleanup_default_scaffold,
    ClipPruneTarget,
    ClipPrunePlan,
    plan_clip_prune,
    ProbeAndLinkResult,
    probe_and_link,
    _match_devices_for_linked_parents,
    _flag_case_near_matches,
    CoherenceResult,
    check_coherence,
)
from .plan import (
    PushPhase,
    _PHASE_NAMES,
    plan_push_song,
    _LINK_KINDS,
    _ACK_ONLY_KINDS,
    apply_push_results,
)

__all__ = [
    # Module aliases (attribute-accessible)
    "json",
    "M",
    "Q",
    # Core
    "_DEFAULT_NUMERATOR",
    "_DEFAULT_DENOMINATOR",
    "ToolCall",
    "PushPlan",
    "_beats_per_bar",
    "_meter_at_bar",
    "_split_bar",
    "_position_bar_to_beats",
    "_notes_for_mcp",
    "_breakpoints_for_mcp",
    # Tempo / meter
    "plan_push_tempo_map",
    "plan_push_time_signature_map",
    # Tracks / returns
    "plan_push_song_tracks",
    "plan_push_song_returns",
    # Clips
    "plan_push_clip",
    "plan_push_clips",
    # Scenes
    "plan_push_scenes",
    # Arrangement / cues / sections
    "plan_push_arrangement",
    "plan_push_cue_points",
    "plan_push_sections",
    # Mix
    "_MIXER_FIELDS",
    "plan_push_mix",
    # Devices
    "plan_push_devices",
    "_emit_device_calls",
    # Envelopes
    "_LOSSY_CURVE_HINTS",
    "plan_push_envelopes",
    "plan_push_performed_automation",
    "envelope_fingerprint",
    "record_perform_result",
    "_track_kind_for_envelope",
    "classify_envelope_route",
    "_clip_and_track_indices",
    "_CoveringPlacement",
    "_resolve_envelope_session_clip",
    "_clip_local_breakpoints",
    "_envelope_beat_range",
    "_emit_note_expression_envelope",
    "_warn_lossy_curve_hints",
    "_warn_multiple_covering_clips",
    "_warn_trimmed_placement",
    "_warn_extra_placements",
    "_resolve_and_translate_to_session_clip",
    "_emit_session_clip_envelope_post_warnings",
    "_emit_device_parameter_envelope",
    "_emit_mixer_envelope",
    "_emit_send_envelope",
    # Probe-and-link / cleanup / clip prune / coherence
    "CANONICAL_DEFAULT_SCAFFOLD_TRACK_NAMES",
    "CANONICAL_DEFAULT_SCAFFOLD_RETURN_NAMES",
    "CleanupScaffoldPlan",
    "plan_cleanup_default_scaffold",
    "ClipPruneTarget",
    "ClipPrunePlan",
    "plan_clip_prune",
    "ProbeAndLinkResult",
    "probe_and_link",
    "_match_devices_for_linked_parents",
    "_flag_case_near_matches",
    "CoherenceResult",
    "check_coherence",
    # Orchestrator + apply
    "PushPhase",
    "_PHASE_NAMES",
    "plan_push_song",
    "_LINK_KINDS",
    "_ACK_ONLY_KINDS",
    "apply_push_results",
]
