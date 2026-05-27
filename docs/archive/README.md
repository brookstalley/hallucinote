# docs/archive/ — historical docs

Completed plans and pre-v1 design history. Preserved for audit, not maintained.

## Live equivalents

| Archived | What replaced it |
|---|---|
| `mcp-requirements.md` | `hallucinote_mcp/.../resources/guides/gaps.md` (live API gap reference) |
| `mcp-tool-design.md` | The shipped 12-tool MCP surface itself + the PRIMER in `hallucinote_mcp/.../server.py` |
| `pre-v1-walkthrough.md` | All FINDINGS shipped; current behavior is documented in active docs |
| `v11-requirements.md` | Arc 1 + Arc 2 shipped (see `change-log.md`) |
| `canary-songs/` | The songs themselves under `songs/<slug>/`; their `build.py` is the source of truth |

## When you'd read these

- Auditing a design decision ("why did we pick the unified 12-tool surface?").
- Understanding terminology in old commits or change-log entries.

For current behavior, always start from the live docs.
