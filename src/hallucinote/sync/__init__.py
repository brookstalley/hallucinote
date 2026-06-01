"""Bridge between the hallucinote DB and Ableton (via MCP).

Direction:
- `push`: DB -> Ableton (this module). Produces a plan of MCP tool calls; the
  agent runs them and feeds results back via `apply_push_results`. We keep the
  plan as pure data so this layer is testable without Live running.
- `pull`: Ableton -> DB. Supported via the mutator + event path — ingests
  mixer, devices, params, arrangement, and notes (per-note diff via stable Live
  note IDs). Conflict policy is "Ableton wins" (no three-way merge yet); a note
  pitch/time *move* rotates the DB note's UUID, while velocity/mute edits
  preserve it. See `docs/collaboration.md` and the `/ableton-pull` skill.

Tool names below assume the renamed surface from MCP Wave 1 (PRs A/C/D/G/H).
A shim layer can map them onto the current pre-rename names in the meantime —
see `sync.mcp_names`.
"""
