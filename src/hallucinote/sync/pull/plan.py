"""Apply orchestrator: dispatch table + `apply_pull_results` entry point.

Ties the per-domain apply helpers together. Imports from the domain submodules
(not vice-versa) so the dependency direction is acyclic.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db.connection import transaction

from ._core import ApplyResult
from .mix import (
    _apply_session_info,
    _apply_returns_list,
    _apply_return_info,
    _apply_track_info,
    _apply_track_sends,
    _apply_track_routing,
    _apply_track_monitor,
)
from .score import _apply_cue_points_list
from .devices import (
    _apply_devices_for_parent,
    _apply_nested_rack_chains_for_device,
    _apply_device_parameters_for_device,
    _apply_device_sidechain_source,
)
from .clips import (
    _apply_arrangement_clips_for_track,
    _apply_session_clips_for_track,
)
from .notes import _apply_notes_for_clip
from .envelopes import _apply_envelope


# Dispatch table: key kind -> (handler, expects-db-id)
_HANDLERS = {
    "session_info":              ("session_info",              False),
    "returns_list":              ("returns_list",              False),
    "return_info":               ("return_info",               True),   # Wave M-2: per-return mixer state
    "track_info":                ("track_info",                True),
    "track_sends":               ("track_sends",               True),
    "track_output_routing":      ("track_output_routing",      True),   # RTE-1K9T chunk 05
    "track_input_routing":       ("track_input_routing",       True),   # RTE-1K9T chunk 05
    "track_monitor":             ("track_monitor",             True),   # RTE-1K9T chunk 05
    "cue_points_list":           ("cue_points_list",           False),
    "track_devices":             ("track_devices",             True),   # W3-3: top-level chain
    "return_devices":            ("return_devices",            True),   # W3-3: top-level chain
    "nested_rack_chains":        ("nested_rack_chains",        True),   # W7-B: one level deep
    "device_parameters":         ("device_parameters",         True),   # W5-D: per-device param values
    "device_sidechain_source":   ("device_sidechain_source",   True),   # SDC-7K3M: device sidechain SOURCE
    "track_arrangement_clips":   ("track_arrangement_clips",   True),   # M+1-3b / W3-4
    "track_session_clips":       ("track_session_clips",       True),   # V1 close-out C
    "clip_notes":                ("clip_notes",                True),   # V1 close-out D — gap #4 partial
    "envelope":                  ("envelope",                  True),   # W7-A — envelope pull
}


def apply_pull_results(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    song_id: str,
    session_id: str,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> ApplyResult:
    """Ingest MCP probe results, diff against DB, write mutations.

    Each result dict shape:
        {
          "key":   "<the PullCall.key from the plan>",
          "ok":    bool,
          "tool":  "<canonical tool name>",
          "result": { ... per-key-kind shape, see PullCall docstring ... },
          "error": "...optional, only if ok=False ..."
        }

    Failed results (`ok=False`) are recorded as warnings and skipped — the
    agent layer is the source of truth for tool-side errors. Unknown key
    kinds raise `ValueError` so a new planner-emitted key can't silently
    no-op past this layer.
    """
    out = ApplyResult()
    with transaction(conn):
        for r in results:
            key = r.get("key", "")
            if not r.get("ok", False):
                out.warnings.append(
                    f"probe {key!r} failed: {r.get('error', 'no error message')}"
                )
                continue

            kind, _, db_id = key.partition(":")
            if not kind:
                raise ValueError(f"pull result missing 'key': {r!r}")
            if kind not in _HANDLERS:
                raise ValueError(
                    f"unknown pull result key kind {kind!r} (full key={key!r}). "
                    f"Declare it in _HANDLERS in sync/pull.py."
                )

            handler_name, needs_db_id = _HANDLERS[kind]
            if needs_db_id and not db_id:
                raise ValueError(
                    f"pull result key {key!r} missing db_id after {kind!r}:"
                )

            result_payload = r.get("result")
            if result_payload is None:
                out.warnings.append(f"probe {key!r} ok=True but missing 'result'")
                continue

            if handler_name == "session_info":
                _apply_session_info(
                    conn, song_id=song_id, session_id=session_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "returns_list":
                _apply_returns_list(
                    conn, song_id=song_id, session_id=session_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "return_info":
                _apply_return_info(
                    conn, session_id=session_id, return_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_info":
                _apply_track_info(
                    conn, session_id=session_id, track_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_sends":
                _apply_track_sends(
                    conn, song_id=song_id, session_id=session_id,
                    track_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_output_routing":
                _apply_track_routing(
                    conn, session_id=session_id, track_id=db_id,
                    direction="output", result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_input_routing":
                _apply_track_routing(
                    conn, session_id=session_id, track_id=db_id,
                    direction="input", result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_monitor":
                _apply_track_monitor(
                    conn, session_id=session_id, track_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "cue_points_list":
                _apply_cue_points_list(
                    conn, song_id=song_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_devices":
                _apply_devices_for_parent(
                    conn, session_id=session_id,
                    parent_kind="track", parent_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "return_devices":
                _apply_devices_for_parent(
                    conn, session_id=session_id,
                    parent_kind="return", parent_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "nested_rack_chains":
                _apply_nested_rack_chains_for_device(
                    conn, session_id=session_id,
                    rack_device_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "device_parameters":
                _apply_device_parameters_for_device(
                    conn, device_id=db_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "device_sidechain_source":
                _apply_device_sidechain_source(
                    conn, session_id=session_id, song_id=song_id,
                    device_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_arrangement_clips":
                _apply_arrangement_clips_for_track(
                    conn, song_id=song_id, session_id=session_id,
                    track_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "track_session_clips":
                _apply_session_clips_for_track(
                    conn, song_id=song_id, session_id=session_id,
                    track_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "clip_notes":
                _apply_notes_for_clip(
                    conn, song_id=song_id, session_id=session_id,
                    clip_id=db_id, result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )
            elif handler_name == "envelope":
                _apply_envelope(
                    conn, envelope_id=db_id, song_id=song_id,
                    result=result_payload, out=out,
                    actor=actor, request_id=request_id, reason=reason,
                )

    return out


__all__ = [
    "_HANDLERS",
    "apply_pull_results",
]
