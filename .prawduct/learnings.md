# Learnings

Accumulated wisdom from building this product.

## Sync planner discipline

**When emitting a `ToolCall` for an MCP tool that has no `ALIASES_TODAY` entry, verify the actual MCP signature against the planner's args before considering the planner complete.**

The "canonical name + alias" pattern in `sync/mcp_names.py` is for tools that don't yet exist or need emulation; tools called directly (no alias) trust the planner to match the real signature. There's no schema check, no aliased emulator, no runtime mismatch — the call just fails at push time. Chunk 2 shipped a `plan_push_cue_points` that emitted `{time, name}` while real MCP `create_cue_point` takes `(bar: int 1-based, beat: float 0-based, name: str)`; the Critic caught it. Inspect the tool's MCP schema (via `ToolSearch` for `mcp__AbletonMCP__*`) when writing a planner for a directly-callable tool, and add a one-line signature note in `mcp_names.py` if absent.
