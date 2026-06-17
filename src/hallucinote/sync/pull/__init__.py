"""Ableton -> DB planner. Mirror of `push.py` for the inbound direction.

Produces a list of `PullCall` objects describing MCP *read* probes the agent
should run. After the agent executes the plan, it calls `apply_pull_results`
to diff each probe response against the DB and write mutations through the
standard mutator path — so events fall out naturally.

Why a plan rather than direct calls: same reason as push. MCP tools run in
the agent, not in Python. Returning a plan keeps this layer pure, testable,
and lets the skill orchestrate without inlining MCP shape knowledge.

Conflict policy (V1): **Ableton-authoritative on pull**. If the DB and Ableton
disagree on a field, the Ableton value wins and a mutation is emitted with
`actor='sync'` (matching push). Pull-vs-push provenance lives in the event's
`reason` field — callers should pass `reason="pull from <session>"` or similar.
Three-way merge with a last-pushed snapshot is the right long-term answer for
multi-collaborator workflows but is over-scope for a single-user authoring
tool right now (see docs/VISION.md "What this costs").

Sessions: every plan/apply takes a `session_id` (an `ableton_sessions` row).
Reverse lookups (Ableton index -> DB id) go through `ableton_links` via
`queries.get_db_id_by_ableton_index`. Unlinked Ableton rows are reported but
not ingested — V1 does not auto-create DB rows for tracks/returns the user
made in Ableton outside of a session.

Package layout (behavior-preserving split of the original `pull.py`):
  - `_core`     — PullCall / PullPlan / ApplyResult, shared float/diff +
                  bar/beat helpers (no domain imports → no cycles).
  - `mix`       — mix-state + global score (tempo/signature) planners + apply.
  - `score`     — cue-point planner + apply.
  - `devices`   — device chains, nested rack chains, device parameters.
  - `clips`     — arrangement + session clip-placement planners + apply.
  - `notes`     — per-clip note planner + apply.
  - `envelopes` — envelope planner, read-addressing emitters, apply.
  - `plan`      — `_HANDLERS` dispatch table + `apply_pull_results`.

The public import surface (`from hallucinote.sync import pull`) is unchanged;
every name the original module exposed is re-exported here.
"""
from __future__ import annotations

from ._core import (
    _FLOAT_EPS,
    PullCall,
    PullPlan,
    ApplyResult,
    _floats_differ,
    _normalized_values_match,
    _raw_values_match,
    _bool_db,
    _ints_differ,
    _parse_signature,
    _beats_per_bar,
    _join_bar_beat,
    _is_numeric_id_name,
    _beats_to_position_bar,
)
from .mix import (
    plan_pull_mix,
    plan_pull_score_globals,
    _apply_session_info,
    _apply_session_master,
    _apply_session_tempo,
    _apply_session_signature,
    _apply_returns_list,
    _apply_return_info,
    _apply_track_info,
    _apply_track_sends,
)
from .score import (
    plan_pull_cue_points,
    _apply_cue_points_list,
)
from .devices import (
    plan_pull_devices,
    plan_pull_nested_rack_chains,
    plan_pull_device_parameters,
    plan_pull_device_sidechain,
    _apply_devices_for_parent,
    _diff_chain_devices,
    _apply_nested_rack_chains_for_device,
    _apply_device_parameters_for_device,
    _apply_device_sidechain_source,
)
from .clips import (
    plan_pull_arrangement_clips,
    plan_pull_session_clips,
    _apply_arrangement_clips_for_track,
    _apply_session_clips_for_track,
)
from .notes import (
    plan_pull_notes_for_clips,
    _apply_notes_for_clip,
)
from .envelopes import (
    _ENVELOPE_TIME_EPS_SLACK,
    _ENVELOPE_VALUE_EPS,
    _ENVELOPE_KINDS_READ_BLOCKED,
    plan_pull_envelopes,
    _emit_pull_note_expression,
    _emit_pull_device_parameter,
    _emit_pull_mixer,
    _emit_pull_send,
    _envelope_needs_arrangement_translation,
    _arrangement_time_breakpoints,
    _resolve_envelope_offset,
    _merge_envelope_breakpoints,
    _apply_envelope,
)
from .plan import (
    _HANDLERS,
    apply_pull_results,
)

__all__ = [
    # Core
    "_FLOAT_EPS",
    "PullCall",
    "PullPlan",
    "ApplyResult",
    "_floats_differ",
    "_normalized_values_match",
    "_raw_values_match",
    "_bool_db",
    "_ints_differ",
    "_parse_signature",
    "_beats_per_bar",
    "_join_bar_beat",
    "_is_numeric_id_name",
    "_beats_to_position_bar",
    # Mix + score globals
    "plan_pull_mix",
    "plan_pull_score_globals",
    "_apply_session_info",
    "_apply_session_master",
    "_apply_session_tempo",
    "_apply_session_signature",
    "_apply_returns_list",
    "_apply_return_info",
    "_apply_track_info",
    "_apply_track_sends",
    # Score (cue points)
    "plan_pull_cue_points",
    "_apply_cue_points_list",
    # Devices
    "plan_pull_devices",
    "plan_pull_nested_rack_chains",
    "plan_pull_device_parameters",
    "plan_pull_device_sidechain",
    "_apply_devices_for_parent",
    "_diff_chain_devices",
    "_apply_nested_rack_chains_for_device",
    "_apply_device_parameters_for_device",
    "_apply_device_sidechain_source",
    # Clips
    "plan_pull_arrangement_clips",
    "plan_pull_session_clips",
    "_apply_arrangement_clips_for_track",
    "_apply_session_clips_for_track",
    # Notes
    "plan_pull_notes_for_clips",
    "_apply_notes_for_clip",
    # Envelopes
    "_ENVELOPE_TIME_EPS_SLACK",
    "_ENVELOPE_VALUE_EPS",
    "_ENVELOPE_KINDS_READ_BLOCKED",
    "plan_pull_envelopes",
    "_emit_pull_note_expression",
    "_emit_pull_device_parameter",
    "_emit_pull_mixer",
    "_emit_pull_send",
    "_envelope_needs_arrangement_translation",
    "_arrangement_time_breakpoints",
    "_resolve_envelope_offset",
    "_merge_envelope_breakpoints",
    "_apply_envelope",
    # Orchestrator
    "_HANDLERS",
    "apply_pull_results",
]
