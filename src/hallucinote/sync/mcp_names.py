"""Tool-name aliases bridging current AbletonMCP surface to post-Wave-1 names.

Post-Wave-M-5 (2026-05-17): the unified hallucinote-mcp surface absorbs
nearly every Hallucinote-canonical name. Only the genuinely-blocked
multi-step emulators remain in this table.

Each remaining entry resolves to an `_emulate_*` placeholder — the agent
recognizes that prefix as a signal to decompose into multiple unified-tool
calls (since the operation is intrinsically multi-step, not a single Live
primitive). The table contracts as the orchestration prose moves into
explicit planner-side decomposition.

History (per Wave M-* sessions in `.session-reflected`):
- M-1: dropped master volume / pan aliases (unified ableton_session).
- M-2: dropped 8 entries — track + return mixer state + return creation.
- M-3: dropped set_clip_notes (unified ableton_clip(replace_notes)).
- M-4: dropped 12 entries — 4 device load/param + 8 envelope writes.
- M-5: dropped 3 entries — set_arrangement_clip_notes (unified
  ableton_clip(replace_notes, location='arrangement')), delete_session_clip
  (unified ableton_clip(delete, location='session')), create_midi_track_with
  (unified ableton_track(create, kind='midi', name=...)). The planner now
  emits the unified shapes directly.

Remaining 4 entries (≤5 target met):
"""
from __future__ import annotations

# planner emits (canonical) -> currently-callable name
ALIASES_TODAY: dict[str, str] = {
    # Multi-step emulation: atomic replace of a session clip (delete +
    # create + replace_notes). The MCP surface supports the single-call
    # path via ableton_clip(action='create', replace=True, notes=...) —
    # retarget tracked in backlog.
    "replace_session_clip": "_emulate_replace_session_clip",
    # Multi-step emulation: bulk arrangement build. Decomposes into
    # multiple ableton_clip(action='delete', location='arrangement') and
    # ableton_clip(action='duplicate_to_arrangement', ...) calls. No
    # single primitive on the MCP side; agent orchestrates.
    "batch_arrangement_layout": "_emulate_batch_arrangement_layout",
    # Tempo automation per (bar, beat) — Live exposes the global
    # `Song.tempo` and per-bar automation envelopes, but not a single
    # "set tempo at this bar" primitive. The emulator decomposes into
    # ableton_session(action='set_tempo') for single-point + envelope
    # writes for ramps; multi-point ramps remain a hard MCP gap until
    # the envelope read surface lands.
    "write_tempo_point": "_emulate_write_tempo_point",
    # Arrangement-level meter changes — no Live API primitive exists.
    # Canonical args: {bar, beat, numerator: int, denominator: int}.
    # Hard MCP gap; emulator no-ops with a warn.
    "write_time_signature_point": "_emulate_write_time_signature_point",
}


def resolve(canonical: str) -> str:
    """Return the name an agent should actually call today, or the canonical
    name if the MCP fork already supports it."""
    return ALIASES_TODAY.get(canonical, canonical)
