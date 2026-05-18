"""Tool-name aliases bridging planner-canonical names to currently-callable
emulator placeholders.

As of W5-A (2026-05-18): the alias table is empty. The two prior entries
(``write_tempo_point`` / ``write_time_signature_point``) were retired when
``plan_push_tempo_map`` / ``plan_push_time_signature_map`` were rewritten
to emit ``ableton_session(set_tempo)`` / ``ableton_session(set_signature)``
for bar-1 rows directly. Multi-bar tempo / meter automation remains a real
MCP gap (no ``song_tempo`` / ``song_signature`` ``target_kind`` on
``ableton_automation`` — see ``hallucinote_mcp/.../guides/gaps.md``) — the
planner warns and skips those rows; no ToolCall is emitted, so no alias
is needed.

The module + :func:`resolve` are kept as the seam: if a future Live gap
forces a multi-call decomposition that can't be expressed as a single
canonical MCP tool, this is where the seam lives.

History (per Wave M-* / Wave W2-* / Wave W3-* / W5-* sessions in
``.session-reflected``):

- M-1: dropped master volume / pan aliases (unified ableton_session).
- M-2: dropped 8 entries — track + return mixer state + return creation.
- M-3: dropped set_clip_notes (unified ableton_clip(replace_notes)).
- M-4: dropped 12 entries — 4 device load/param + 8 envelope writes.
- M-5: dropped 3 entries — set_arrangement_clip_notes (unified
  ableton_clip(replace_notes, location='arrangement')), delete_session_clip
  (unified ableton_clip(delete, location='session')), create_midi_track_with
  (unified ableton_track(create, kind='midi', name=...)).
- M+1-1: dropped replace_session_clip (atomic single-call retarget).
- W3-B: dropped ``create_cue_point`` — planner emits batched
  ``ableton_arrangement(cue_create_batch)`` directly.
- W3-D: dropped ``batch_arrangement_layout`` — planner decomposes into
  N ``ableton_clip(duplicate_to_arrangement)`` calls itself.
- W5-A: dropped ``write_tempo_point`` and ``write_time_signature_point`` —
  planner emits ``ableton_session(set_tempo/set_signature)`` for bar-1
  directly; multi-bar is a real MCP gap, planner warns + skips.

The :data:`ALIASES_TODAY` size is part of the wave-coverage contract —
:func:`test_known_emulators_allowlist_stays_audited` in
``tests/unit/sync/test_planner_mcp_coverage.py`` pins the count so a
silent new emulator can't sneak in.
"""
from __future__ import annotations

# planner emits (canonical) -> currently-callable name
ALIASES_TODAY: dict[str, str] = {}


def resolve(canonical: str) -> str:
    """Return the name an agent should actually call today, or the canonical
    name if the MCP fork already supports it."""
    return ALIASES_TODAY.get(canonical, canonical)
