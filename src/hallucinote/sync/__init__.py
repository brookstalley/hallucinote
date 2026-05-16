"""Bridge between the hallucinote DB and Ableton (via MCP).

Direction:
- `push`: DB -> Ableton (this module). Produces a plan of MCP tool calls; the
  agent runs them and feeds results back via `apply_push_results`. We keep the
  plan as pure data so this layer is testable without Live running.
- `pull`: Ableton -> DB. Deferred until MCP PR A (note-level addressing) lands;
  without stable note IDs, sync-back is destructive.

Tool names below assume the renamed surface from MCP Wave 1 (PRs A/C/D/G/H).
A shim layer can map them onto the current pre-rename names in the meantime —
see `sync.mcp_names`.
"""
