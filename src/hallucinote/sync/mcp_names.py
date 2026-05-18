"""Tool-name aliases bridging planner-canonical names to currently-callable
emulator placeholders.

Post-Wave-3 (2026-05-18): only TWO aliases remain — both for genuine Live
API gaps where no single MCP primitive exists. The other entries that
used to live here were either absorbed into unified-tool actions (most of
Wave M) or decomposed at the planner level (W3-D dropped
``batch_arrangement_layout``; the planner now emits N
``ableton_clip(duplicate_to_arrangement)`` calls directly).

Each remaining entry resolves to an ``_emulate_*`` placeholder. The agent
recognizes the prefix as a signal that the operation is multi-step or
Live-gap-blocked and consults the planner's emitted ``purpose`` /
``notes`` for what to do.

History (per Wave M-* / Wave W2-* / Wave W3-* sessions in `.session-reflected`):
- M-1: dropped master volume / pan aliases (unified ableton_session).
- M-2: dropped 8 entries — track + return mixer state + return creation.
- M-3: dropped set_clip_notes (unified ableton_clip(replace_notes)).
- M-4: dropped 12 entries — 4 device load/param + 8 envelope writes.
- M-5: dropped 3 entries — set_arrangement_clip_notes (unified
  ableton_clip(replace_notes, location='arrangement')), delete_session_clip
  (unified ableton_clip(delete, location='session')), create_midi_track_with
  (unified ableton_track(create, kind='midi', name=...)).
- M+1-1: dropped replace_session_clip (atomic single-call retarget).
- W3-B: dropped `create_cue_point` — planner emits batched
  ``ableton_arrangement(cue_create_batch)`` directly.
- W3-D: dropped `batch_arrangement_layout` — planner decomposes into
  N ``ableton_clip(duplicate_to_arrangement)`` calls itself.

The :data:`ALIASES_TODAY` size is part of the wave-coverage contract —
:func:`test_known_emulators_allowlist_stays_audited` in
``tests/unit/sync/test_planner_mcp_coverage.py`` pins the count so a
silent new emulator can't sneak in.
"""
from __future__ import annotations

# planner emits (canonical) -> currently-callable name
ALIASES_TODAY: dict[str, str] = {
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
