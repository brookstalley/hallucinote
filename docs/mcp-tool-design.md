# MCP Tool Design — A Consolidation Plan for AbletonMCP

**Status:** Plan (not yet implemented). Date: 2026-05-16.
**Audience:** Builders on `ableton-mcp-extended`; consumers (notably Hallucinote).
**Goal:** Cut AbletonMCP's tool surface from **51 → ~10 unified tools** without losing capability, and add the discovery primitives (resources, prompts, help) that let an agent navigate the surface without ballooning context.

---

## TL;DR

- **Where we are.** 51 MCP tools on AbletonMCP today. Many are per-property setters (`set_track_volume`, `set_track_panning`, ...) that should collapse into one tool with an action grammar. Hallucinote's `sync/mcp_names.py` already encodes ~20 of these as `_emulate_*` placeholders — the pain is visible.
- **Where we're going.** Ten unified tools — `ableton_session`, `ableton_track`, `ableton_return`, `ableton_clip`, `ableton_note`, `ableton_device`, `ableton_automation`, `ableton_arrangement`, `ableton_browser`, `ableton_help` — each with an `action` parameter and self-service help. The narrow setters fold into actions (`ableton_track(action='set_property', track_index=5, property='volume', value=0.7)`). Reads that don't need per-call parameters become **resources** (`ableton://browser/instruments`, `ableton://plugins/installed`, `ableton://session/snapshot`). Multi-step recipes become **prompts** (`setup_sidechain_compression`, `build_return_bus`).
- **Why now.** The research is unambiguous: tool count past ~25 measurably degrades model effectiveness, and past ~50 collapses it. AbletonMCP sits at 51 and growing. Hallucinote (the primary consumer) has been the canary.
- **Cost of inaction.** Every chunk of Hallucinote (W3-3, W3-4, future note pull) carries an "MCP gap" appendix that's actually a tool-count problem in disguise. Each new capability adds a new narrow tool. Consolidation pays the cost once and then becomes a free side-effect of every future capability.
- **Hallucinote-side cost of the change.** Small. `mcp_names.ALIASES_TODAY` was designed for exactly this transition — the table is the boundary. Push planners already emit canonical names; we just retarget the aliases. The `apply_push_results._ACK_ONLY_KINDS` set shrinks; `mcp_names.py` line count drops by ~half.

---

## 1. The Problem, Quantified

### 1.1 Current tool count

51 tools in `MCP_Server/server.py` (verified by grep on `@mcp.tool()`). Domain distribution:

| Domain | Tools | Tool names |
|---|---|---|
| Session / global reads | 4 | `get_session_info`, `get_arrangement_info`, `get_cue_points`, `probe_live_object` |
| Track management | 3 | `create_midi_track`, `delete_track`, `set_track_name`, `get_track_deletion_status` |
| Track mixer | 4 | `get_track_volume`, `set_track_volume`, `set_track_panning`, (mute/solo/arm/color absent — listed as gaps in `docs/mcp-requirements.md` chunk-3) |
| Return tracks | 1 | `list_return_tracks` |
| Sends | 2 | `get_track_sends`, `set_track_send` |
| Session clips | 4 | `create_clip`, `fire_clip`, `stop_clip`, `set_clip_name` |
| Arrangement clips | 4 | `create_arrangement_midi_clip`, `create_arrangement_audio_clip`, `delete_arrangement_clip`, `set_arrangement_clip_property`, `duplicate_clip_to_arrangement` |
| Notes | 1 | `add_notes_to_clip` (truly: replaces; see Hallucinote `mcp-requirements.md` gap #1) |
| Automation | 1 | `manage_clip_automation` (action-based — precedent) |
| Devices | 9 | `delete_device`, `enable_device`, `disable_device`, `get_device_parameters`, `set_device_parameter`, `get_device_routing_info`, `set_device_sidechain`, `navigate_device_preset`, `load_instrument_or_effect` |
| Device-load specialized | 2 | `load_external_plugin`, `load_drum_kit` |
| Device chains | 1 | `get_chain_info` |
| Drum pads | 1 | `get_drum_pad_info` |
| Transport | 3 | `start_playback`, `stop_playback`, `set_song_time` |
| Cue points | 3 | `create_cue_point`, `delete_cue_point`, `jump_to_cue_point` |
| Arrangement UI | 2 | `control_arrangement_view`, `set_arrangement_loop` |
| Browser | 2 | `get_browser_tree`, `get_browser_items_at_path` |
| Tempo | 1 | `set_tempo` |
| View | 1 | `set_ableton_view` |
| Plugin discovery | 1 | `list_external_plugins` |

Most tools have one or two parameters and a one-line docstring. The selection space the LLM searches at every Ableton call is 51-wide.

### 1.2 Evidence the surface is too wide

Three independent signals all point the same way:

**Anthropic's own threshold.** The 2025 "advanced tool use" guidance recommends deferred Tool Search "when tool definitions consume >10K tokens" and notes internal testing showed Opus 4 accuracy improving "from 49% to 74%" with Tool Search enabled.<sup>[1]</sup> The implicit message: at ~10K tokens of tool definitions, you have too many tools to load eagerly. AbletonMCP's 51 tools easily clear that.

**Speakeasy Pet Store experiment.** At 10 tools performance is perfect; at 20 tools large models scored 19/20; at 107 tools "both large and small models failed completely, and task success collapsed."<sup>[2]</sup> AbletonMCP is in the failing region.

**GitHub Copilot reduced its MCP from 40 → 13 tools** and saw "2 to 5 percentage point improvement across SWE-Lancer and SWEbench-Verified benchmarks, plus a 400ms latency reduction."<sup>[2]</sup>

**Client-side caps confirm the constraint is industry-wide.** Cursor caps at 40 tools (silent drops above); Copilot caps at 128. AbletonMCP at 51 exceeds Cursor's cap.

**Hallucinote-internal evidence.**
- `mcp_names.ALIASES_TODAY` (the planner's name-rewrite table) has **22 entries** today, mostly `_emulate_*` placeholders for narrow setters that don't yet exist on the MCP side. Every new narrow setter Hallucinote needs adds one alias.
- `sync/push.py`'s `_DIRECT_MIXER_TOOLS` carves out just `volume`/`pan` because those are the only mixer fields with direct MCP tools today — the rest are gap-flagged. The dual-path code is friction.
- `mcp-requirements.md` lists ≥10 narrow setters that "would be a new tool" — every one collapses into a single action on a unified tool under this proposal.

### 1.3 What "model effectiveness degrades" looks like in practice

When the LLM has 51 tools to choose from, three failure modes appear:

1. **Wrong tool selected.** Near-twin tools (`set_track_volume` vs `set_track_panning` vs hypothetical `set_track_mute`) compete for the LLM's attention. Selection accuracy drops as the count rises.<sup>[3]</sup>
2. **Tool unused, hallucinated parameters instead.** If the agent can't find the right tool quickly, it sometimes invokes a near-match with guessed parameters — `set_track_volume(track_index=5, mute=True)` is the kind of error this produces.
3. **Context bloat.** Every tool's schema lives in the prompt for every Ableton interaction. At 51 tools, that's a significant fraction of the context window paid for capabilities not used in this turn.

---

## 2. The Cordyceps Precedent

The sibling project [`cordyceps`](https://github.com/...) bridges Claude to Rhino Grasshopper. Its design has been refined through real bugs (cluster-editor corruption, see `CHANGELOG.md` v1.4.6–v1.4.9) and lands at a pattern we should copy almost verbatim. Key takeaways from a deep read of the codebase:

### 2.1 Numbers

- **7 unified tools, 111 actions** ([README.md line 128](https://github.com/...)): *"Cordyceps provides 7 tools with 110+ actions — consolidated to minimize context window usage."*
- 95% smaller tool-list response vs one-tool-per-action; tool-definition tokens drop from ~10K to ~2K range.

### 2.2 The Unified Tool pattern

Each tool has one MCP entry point (`gh_canvas`, `gh_wire`, `gh_document`, `gh_script`, `gh_inspect`, `rhino_scene`, `rhino_render`) that dispatches on a string `action` parameter (`Tools/Unified/GhCanvasTool.cs`). A `UnifiedToolInfo` metadata layer describes every action's required/optional parameters, an example, and tips. The dispatch is a switch statement; the help text is generated from the metadata.

**Why it works:** The metadata is the single source of truth for the action surface. Help is self-serve (`action='help'`), errors echo the valid action list, the help generator and the dispatch share the same data structure so they can't drift.

### 2.3 Discovery layered, not flat

Cordyceps stacks **four discovery mechanisms**, each at a different granularity:

1. **Server instructions.** On `initialize`, the server returns a primer string listing all tool names with their action names and the 3 most-load-bearing warnings (`McpServer.cs:545–571`). Agent's first read.
2. **Per-tool help.** `tool(action='help')` returns structured JSON with every action, required/optional params, an example, and tips. Agent's go-to during use.
3. **Resources** (`Resources/ResourceRegistry.cs:49–103`). 13 static + 1 dynamic. Examples: `gh://docs/getting-started`, `gh://docs/data-trees`, `gh://docs/common-errors`, `gh://component/{name}` (dynamic per-component documentation). Resources are model-pulled, not model-selected — they don't crowd the tool-selection space.
4. **Prompts** (`Prompts/PromptRegistry.cs:50–102`). 5 multi-step workflow templates (`create_parametric_geometry`, `debug_data_mismatch`, `setup_script_component`, `optimize_canvas`, `plan_definition`). Prompts are user-invoked; they encode workflows without taking tool slots.

### 2.4 Error responses teach

Cordyceps' errors carry recovery information (`Core/UnifiedToolHelpers.cs:82–133`):

```json
{
  "success": false,
  "error": "Missing required params for 'connect': sourceId, targetId",
  "required": ["sourceId", "targetId"],
  "optional": ["sourceParam", "targetParam"],
  "example": "action='connect', sourceId='a', sourceParam='0', targetId='b'",
  "hint": "Use action='help' to see all gh_wire actions"
}
```

The agent gets the valid action list, the missing params, an example, and a self-service hint — all in one response. No second round-trip needed to know what to do.

### 2.5 The anti-pattern gallery — gold

Cordyceps explicitly names anti-patterns it has burned through. From `BestPracticesGuide.md`:

| Don't | Do |
|---|---|
| Guess component names | `gh_canvas(action='search', query='...')` |
| Ignore orange warnings | `gh_inspect(action='status')` |
| Chain without checking | Verify `result.success` |

And from `CHANGELOG.md` v1.4.6: *"Fixed critical bug where modifying components inside clusters (scripts, values, wires, etc.) would corrupt cluster inputs, turning them all to null. Two issues fixed: (1) Operations now use the component's owning document via `OnPingDocument()` rather than assuming the active canvas document."*

These are not hypotheticals; they're scars. The doc surfaces them so future builders don't repeat them. **We should do the same with AbletonMCP's known gotchas** (e.g., `add_notes_to_clip` actually replaces, not adds — Hallucinote gap #1).

### 2.6 Documentation as contract

Cordyceps treats documentation as part of the API. `CLAUDE.md` lines 88–102 list a mandatory audit checklist for every code change: tool help metadata, server instructions, knowledge guides, resource registry, prompt templates, common-errors guide, CHANGELOG. The contract is: **if the action surface changes, all seven targets get updated together.**

---

## 3. Principles

These are the rules we'll hold the redesign to. Each is borrowed from cordyceps, the external research, or both, and bears a one-line reason.

1. **Tools are a budget. Aim for ≤10.** Empirical evidence and Anthropic's own threshold both point here. (Cordyceps: 7. Block: 2. Copilot: 13.)
2. **One tool per domain, many actions per tool.** Action dispatch is the consolidation engine. Domains in AbletonMCP are obvious: session, track, return, clip, note, device, automation, arrangement, browser, plus a meta-tool.
3. **Resources for read-only state and reference data.** Anything that doesn't take a parameter (browser tree, plugin list, session snapshot) or only takes a slow-changing identifier (device parameter catalogs) belongs in resources. Resources don't compete with tools for selection.
4. **Prompts for multi-step workflows.** Anything an agent does in a recognizable 3-5-step sequence is a prompt. "Create a MIDI track, load an instrument, name the track, set initial volume" is one prompt, not four tool calls.
5. **Self-service help (`action='help'`) on every tool.** The action metadata IS the documentation — no drift between code and docs because both read the same structure.
6. **Errors teach.** Every error response carries: the valid action list, required/optional params, an example, and a recovery hint. Inspired by cordyceps + Alpic.<sup>[4]</sup>
7. **Names are prompts.** `ableton_track(action='set_property')` reads cleanly to the LLM. `do_track_thing(action='vol')` does not. Be specific.
8. **Hard constraints visible everywhere.** Anything the agent must not do (e.g., "`add_notes_to_clip` REPLACES the clip's notes") goes in: the tool's help text, the server instructions, a resource, and the error message when misuse is detected. Repetition beats subtle.
9. **Stable identifiers, additive evolution.** Tool names never change. Actions never change (deprecated, yes; renamed, no). New actions are added freely. This is how Hallucinote's existing alias table can evolve cleanly.
10. **Validate at the boundary.** Use typed enums for action and property strings. Coerce string-encoded numbers (cordyceps v1.4.9 lesson). Don't trust the agent to enforce constraints — fail loudly at the MCP boundary.

---

## 4. The Target Tool Surface

Ten unified tools. Each has an `action` parameter (string enum), plus per-action parameters. Action `'help'` exists on every tool.

### 4.1 The ten tools

| Tool | Scope | Action count (approx) |
|---|---|---|
| `ableton_session` | Global state, master strip, tempo, time signature, transport, view, song time, arrangement loop | ~12 |
| `ableton_track` | Track lifecycle, mixer state (volume/pan/mute/solo/arm/color), sends, name, info | ~10 |
| `ableton_return` | Return-track lifecycle, mixer state, devices via cross-tool | ~6 |
| `ableton_clip` | Session + arrangement clips: create, delete, fire/stop, rename, properties, duplicate-to-arrangement | ~10 |
| `ableton_note` | Within-clip note operations: get, add, update, delete (note pull is gap #4) | ~5 |
| `ableton_device` | Track + return devices: list, info, load, delete, enable/disable, parameter set, navigate preset, routing, sidechain | ~12 |
| `ableton_automation` | Envelope CRUD across all seven target families (clip CC, pitch bend, note expression, device parameter, mixer volume/pan, send level) | ~10 |
| `ableton_arrangement` | Arrangement layout, cue points (locators), loop region, view control | ~8 |
| `ableton_browser` | Instruments, effects, drum kits, plugins. Search, list, fetch. | ~6 |
| `ableton_help` | Meta: list tools, describe tool, list resources, list prompts. Returns navigational guidance. | ~4 |

Total: ~83 actions in 10 tools. ~84% reduction in selection-space width.

### 4.2 Per-tool action breakdown (proposed)

#### `ableton_session`

| Action | Args | Replaces |
|---|---|---|
| `help` | — | — |
| `info` | — | `get_session_info` |
| `set_master_property` | `property: volume\|panning\|mute`, `value` | gap-flagged today |
| `set_view` | `view: arranger\|session\|detail\|browser` | `set_ableton_view` |
| `set_tempo` | `bpm` | `set_tempo` |
| `set_signature` | `numerator`, `denominator` (global) | gap today |
| `play` | — | `start_playback` |
| `stop` | — | `stop_playback` |
| `seek` | `bar: int 1-based`, `beat: float 0-based` | `set_song_time` |
| `set_arrangement_loop` | `enabled`, `start_bar`, `end_bar` | `set_arrangement_loop` |

#### `ableton_track`

| Action | Args | Replaces |
|---|---|---|
| `help` | — | — |
| `list` | — | (new — derived from `get_session_info`) |
| `info` | `track_index` | `get_track_info` |
| `create` | `kind: midi\|audio`, `name?`, `index?`, `instrument_uri?` | `create_midi_track` + `set_track_name` + `load_instrument_or_effect` (replaces 3) |
| `delete` | `track_index` | `delete_track` |
| `rename` | `track_index`, `name` | `set_track_name` |
| `set_property` | `track_index`, `property: volume\|panning\|mute\|solo\|arm\|color`, `value` | `set_track_volume`, `set_track_panning`, **+4 gap-flagged** today |
| `get_property` | `track_index`, `property: volume\|panning\|mute\|solo\|arm\|color` | `get_track_volume`, **+5 gap-flagged** today |
| `set_send` | `track_index`, `return_index`, `value` | `set_track_send` |
| `get_sends` | `track_index` | `get_track_sends` |
| `deletion_status` | `track_indices?` | `get_track_deletion_status` |

**Replaces 7 current tools + 6 gap-flagged future tools. Net surface reduction: 13 → 1.**

#### `ableton_return`

| Action | Args | Replaces |
|---|---|---|
| `help`, `list`, `info` | similar | `list_return_tracks` + gaps |
| `create` | `name?` | gap-flagged today |
| `delete` | `return_index` | gap-flagged today |
| `set_property` | `return_index`, `property: volume\|panning\|mute\|solo\|color`, `value` | gap-flagged today (5 tools collapse) |

#### `ableton_clip`

| Action | Args | Replaces |
|---|---|---|
| `help` | — | — |
| `create` | `track_index`, `location: session\|arrangement`, `clip_index?`, `start_bar?`, `length`, `name?`, `kind: midi\|audio`, `audio_path?` | `create_clip`, `create_arrangement_midi_clip`, `create_arrangement_audio_clip` |
| `delete` | `track_index`, `location`, `clip_index` | `delete_arrangement_clip` (+ gap for session) |
| `rename` | `track_index`, `clip_index`, `location`, `name` | `set_clip_name` |
| `fire` | `track_index`, `clip_index` | `fire_clip` |
| `stop` | `track_index`, `clip_index` | `stop_clip` |
| `set_property` | `track_index`, `clip_index`, `location`, `property: gain\|pitch\|warp\|loop_start\|loop_end\|muted\|color`, `value` | `set_arrangement_clip_property` (already action-style on one tool, generalized) |
| `duplicate_to_arrangement` | `track_index`, `clip_index`, `start_bar` | `duplicate_clip_to_arrangement` |
| `replace_notes` | `track_index`, `location`, `clip_index`, `notes` | `add_notes_to_clip` (renamed to reflect actual replace semantics — gap #1 resolved) |

#### `ableton_note`

| Action | Args | Replaces |
|---|---|---|
| `help`, `list` | `track_index`, `clip_index`, `location` | (new — gap #4 dependent) |
| `add` | `track_index`, `clip_index`, `location`, `notes` | new — gap #4 dependent (true append, not replace) |
| `update` | `track_index`, `clip_index`, `location`, `note_ids`, `changes` | new — gap #4 |
| `delete` | `track_index`, `clip_index`, `location`, `note_ids` | new — gap #4 |

Note pull/edit is structurally blocked until `get_clip_notes_extended` exposes stable note IDs (Hallucinote gap #4). The `ableton_note` tool exists with stubs returning a clear "blocked-by-gap-4" error until the underlying capability lands.

#### `ableton_device`

| Action | Args | Replaces |
|---|---|---|
| `help`, `list`, `info` | `track_index`, `device_index` | `get_chain_info`, `get_device_parameters` |
| `load` | `track_index`, `position`, `kind`, `preset_uri?` (general) | `load_instrument_or_effect`, `load_external_plugin`, `load_drum_kit` |
| `delete` | `track_index`, `device_index` | `delete_device` |
| `enable`, `disable` | `track_index`, `device_index` | `enable_device`, `disable_device` |
| `set_parameter` | `track_index`, `device_index`, `parameter_name`, `value`, `value_type: continuous\|enum` | `set_device_parameter` (+ gap for enum) |
| `get_parameters` | `track_index`, `device_index`, `detail: summary\|full` | `get_device_parameters` |
| `set_sidechain` | `track_index`, `device_index`, `enabled`, `source_track_index?`, `gain_db?` | `set_device_sidechain` |
| `get_routing` | `track_index`, `device_index` | `get_device_routing_info` |
| `navigate_preset` | `track_index`, `device_index`, `direction: next\|previous\|current` | `navigate_device_preset` |
| `pad_info` | `track_index`, `device_index` (drum rack) | `get_drum_pad_info` |

#### `ableton_automation`

| Action | Args |
|---|---|
| `help`, `list`, `clear`, `clear_all` | inherit `manage_clip_automation` shape |
| `write_envelope` | `target_kind: clip_cc\|clip_pitch_bend\|note_expression\|device_parameter\|mixer_volume\|mixer_pan\|send_level`, target identifiers, `breakpoints` |
| `get_envelope` | `target_kind`, target identifiers (new — gap today) |

The seven-target envelope shape Hallucinote's `mcp_names.ALIASES_TODAY` already models (`write_clip_cc_envelope`, `write_clip_pitch_bend_envelope`, ..., 8 entries) collapses into one `ableton_automation(action='write_envelope', target_kind=...)`.

**8 alias entries → 1 action.**

#### `ableton_arrangement`

| Action | Args | Replaces |
|---|---|---|
| `help`, `info` | — | `get_arrangement_info` |
| `set_loop` | `enabled`, `start_bar?`, `end_bar?` | `set_arrangement_loop` |
| `control_view` | `action_kind: zoom_in\|zoom_out\|scroll_left\|scroll_right\|follow_on\|follow_off\|collapse_track\|expand_track`, `track_index?` | `control_arrangement_view` (already nested-action; promoted to top-level) |
| `cue_list` | — | `get_cue_points` |
| `cue_create` | `bar`, `beat`, `name?` | `create_cue_point` |
| `cue_delete` | `bar`, `beat?` | `delete_cue_point` |
| `cue_jump` | `direction?`, `name?` | `jump_to_cue_point` |

#### `ableton_browser`

| Action | Args | Replaces |
|---|---|---|
| `help`, `tree` | `category?` | `get_browser_tree` |
| `at_path` | `path` | `get_browser_items_at_path` |
| `plugins_list` | `search?`, `refresh?` | `list_external_plugins` |

Heavy candidates here for **conversion to resources** — see §5.

#### `ableton_help`

| Action | Args |
|---|---|
| `list_tools` | returns all 10 tools with one-line descriptions |
| `describe_tool` | `tool_name` → returns the tool's action menu |
| `list_resources` | returns resource URIs and descriptions |
| `list_prompts` | returns prompt names and descriptions |
| `welcome` | (zero-arg primer for new sessions) |

---

## 5. Resources

Resources are MCP's read-only, model-addressable, application-controlled primitive.<sup>[5]</sup> They don't crowd the tool-selection space — they're pulled on demand by the agent.

### 5.1 Proposed resource set

```
ableton://session/snapshot         — Current full session state (tracks, returns, devices,
                                     parameters, sends). Lazy; refreshes on read.
ableton://browser/instruments      — Hierarchical instrument tree (replaces most
                                     get_browser_tree calls).
ableton://browser/effects          — Hierarchical effect tree.
ableton://browser/drums            — Drum kits.
ableton://plugins/installed        — VST/AU list (replaces list_external_plugins for
                                     non-search-y reads).
ableton://reference/device-params  — Parameter catalog by device class (helps the agent
                                     spell parameter names correctly, mitigates
                                     "Filter Freq" vs "Cutoff" ambiguity).
ableton://reference/scales         — Live's scale dictionary.
ableton://guides/getting-started   — First-touch agent primer.
ableton://guides/conventions       — 1-based indexing, value ranges, name/slug conventions.
ableton://guides/error-recovery    — Common errors and fixes. Linked from every error message.
ableton://guides/gaps              — Current MCP gaps (mirrors docs/mcp-requirements.md so
                                     agents can reason about what NOT to attempt).
```

### 5.2 Why these specifically

- **Browser tree as resource.** The instrument/effect browser is mostly-static reference data. Every agent that loads an instrument needs it. Today it's a tool call per query; as a resource, it's one fetch + cached for the session.
- **Plugins list as resource.** Plugins change rarely; the discovery scan is expensive. As a resource, the agent reads once and remembers.
- **Device-params catalog as resource.** The hardest part of `set_device_parameter` today is naming the parameter correctly ("Filter Freq" vs "Cutoff" — both are real on different Live devices). A parameter catalog by device class lets the agent look up the right name without trial-and-error.
- **Guides as resources.** Onboarding, conventions, error recovery — pulled when the agent senses uncertainty, ignored otherwise.

### 5.3 Conversion candidates

These tools should become resource reads, not tool calls:

| Tool today | Resource tomorrow |
|---|---|
| `get_browser_tree` | `ableton://browser/{category}` |
| `get_browser_items_at_path` | (sub-path of resource above, or kept as `ableton_browser(action='at_path')` for parameterized fetch) |
| `list_external_plugins` (no-search form) | `ableton://plugins/installed` |
| `get_session_info` (no-arg full read) | `ableton://session/snapshot` (kept as tool too for "give me this slice" usage) |

---

## 6. Prompts

Prompts are MCP's user-controlled workflow templates.<sup>[5]</sup> They don't crowd tool selection; they're invoked by name.

### 6.1 Proposed prompt set

| Prompt | Args | Workflow |
|---|---|---|
| `create_midi_track_with_instrument` | `name`, `instrument_uri`, `index?`, `initial_volume?` | One-shot: track create + name + instrument load + volume set + return new index |
| `setup_sidechain_compression` | `target_track`, `source_track`, `compressor_uri?` | Load compressor, dial conservative defaults, configure sidechain, return device_index |
| `build_return_bus` | `name`, `effect_uri`, `initial_sends_from?` (list of track_index) | Create return, load effect, set initial sends from listed tracks at conservative level |
| `humanize_clip_velocity` | `track_index`, `clip_index`, `jitter_percent?` | Read clip notes, jitter velocity within range, write back |
| `compose_section_pattern` | `track_index`, `pattern_kind: trip-hop\|tresillo\|bossa\|...`, `bars`, `start_bar` | One-shot: create clip + generate notes + place in arrangement |

### 6.2 Why prompts and not tools

Prompts are workflows the user *invokes by name*. A user-typed "set up sidechain on my synth bass from drums" maps cleanly to `setup_sidechain_compression(target_track=7, source_track=5)`. The LLM doesn't have to plan the 4-call sequence — the prompt does.

This shifts complexity out of the LLM's decision space and into reusable artifacts. The cost is naming and discoverability — solved by `ableton_help(action='list_prompts')`.

---

## 7. Discovery Strategy

Four layers, descending in granularity, mirroring cordyceps:

### 7.1 Server instructions (initialize)

On `initialize`, AbletonMCP returns a primer:

```
AbletonMCP — 10 tools, structured for low-context-cost agent interaction.

Tools:
  ableton_session     — global state, master, transport, view, tempo, signature
  ableton_track       — tracks: lifecycle, mixer state, sends
  ableton_return      — return tracks
  ableton_clip        — session + arrangement clips
  ableton_note        — within-clip note operations (gap #4 blocked)
  ableton_device      — devices on tracks/returns
  ableton_automation  — envelopes (7 target families)
  ableton_arrangement — arrangement layout + cue points
  ableton_browser     — instruments, effects, plugins
  ableton_help        — meta-discovery

Every tool: action='help' returns its full action menu.

Resources: ableton://session/snapshot, ableton://browser/{cat},
ableton://plugins/installed, ableton://reference/device-params,
ableton://guides/{name}.

Prompts: create_midi_track_with_instrument, setup_sidechain_compression,
build_return_bus, humanize_clip_velocity, compose_section_pattern.

Hard constraints:
  - 1-based indexing throughout (track_index >= 1).
  - Note operations REPLACE the clip's full note array — there is no
    note-level addressing until gap #4 lands. To preserve manual edits,
    pull first, mutate, push.
  - Cue point names round-trip as numeric IDs (gap #13). Names are
    write-only-DB-side; do not trust pulled names.
```

This is the agent's first read on every session. ~250 tokens to orient against any of the 10 tools.

### 7.2 Per-tool help

`tool(action='help')` returns the tool's action menu with required/optional params, examples, tips. Generated from a metadata layer (analog to cordyceps' `UnifiedToolInfo`) that's the single source of truth shared with the dispatch.

### 7.3 Resources

`resources/list` and `resources/read` are the primary mechanism for static / slow-changing knowledge. The agent learns what's there from server instructions (§7.1) and uses on demand.

### 7.4 Prompts

`prompts/list` and `prompts/get` for workflow templates. Same pattern as resources.

### 7.5 Error responses

Every error response carries the four recovery hints:

```
{
  "success": false,
  "error": "<concise diagnosis>",
  "valid_actions": ["a", "b", "c", ...],
  "example": "tool_name(action='b', param=value)",
  "hint": "Use action='help' for the full menu, or read
           ableton://guides/error-recovery for common fixes."
}
```

---

## 8. Error Design — Concrete Patterns

Drawing from cordyceps + Alpic + MCPcat:<sup>[4],[6]</sup>

### 8.1 Patterns to adopt

- **Did-you-mean for names.** Device parameter names ("Filter Freq" vs "Cutoff"), instrument URIs, cue-point names. Levenshtein distance on the canonical list, suggest the top match.
- **Order-of-operations hints.** "Cannot set track property: track 5 does not exist. Create it first via `ableton_track(action='create', kind='midi', index=5)`."
- **Schema teaching.** When the agent passes a wrong-shape parameter, the error includes the schema, not just "invalid argument."
- **Retry strategy bounding.** Where transient failures happen, include "If this fails 3 times, surface the failure to the user; do not retry indefinitely."
- **No `isError: false, success: false`.** Per MCP spec, tool execution errors go in the result with `isError: true`. Protocol-level errors are reserved for unknown tools / bad arguments.<sup>[7]</sup>

### 8.2 Hallucinote gap #1 as a worked example

Today: `add_notes_to_clip` silently replaces all notes in the clip. Agents get burned because the name lies.

Under this proposal:
- Tool renamed to `ableton_clip(action='replace_notes', ...)` — name tells the truth.
- Description: "Replaces ALL notes in the clip with the provided array. To append, use `ableton_note(action='add')` (gap #4 dependent)."
- When the agent calls the old name (alias kept for one major version), warning returned in the result: *"`add_notes_to_clip` is deprecated and was renamed to `ableton_clip(action='replace_notes')` to reflect actual replace semantics. The old name still works but will be removed in a future version."*
- Resource `ableton://guides/error-recovery` links the rename in its "common surprises" section.

---

## 9. Versioning and Evolution

The MCP spec uses date-stamped protocol versions. Tool-level versioning is still being formalized (SEP-986, SEP-1575).<sup>[8]</sup>

### 9.1 Rules we adopt

- **Tool names are stable.** Never rename, only alias.
- **Action names are stable.** Never rename, only deprecate-and-add.
- **Parameters are additive.** New optional parameters are non-breaking. Removing or renaming a parameter is breaking.
- **Aliases live for at least one major version,** with a deprecation warning surfaced in the tool result.
- **CHANGELOG is part of the API.** Every action surface change is logged.

### 9.2 Hallucinote-side coordination

Hallucinote's `sync/mcp_names.py` already exists for exactly this. The `ALIASES_TODAY` table maps Hallucinote's canonical names (post-Wave-1) to currently-callable AbletonMCP names. As AbletonMCP lands these unified tools, the alias table contracts toward zero. No planner changes needed on the Hallucinote side — the planner already emits canonical names.

---

## 10. Migration Plan

### Phase 0 — Alignment (this doc)

- Land this doc on `develop`.
- Open a tracking issue on `ableton-mcp-extended`.
- Confirm with Hallucinote: which gap-flagged setters Hallucinote actively needs vs would-be-nice.

### Phase 1 — Unified tool shells alongside narrow tools

- Implement `ableton_track`, `ableton_session`, `ableton_help` first (highest ROI; covers ~15 of the current tools).
- Both old and new tools live in parallel. No removals yet.
- Hallucinote's `mcp_names.ALIASES_TODAY` retargets to the new tools as they land.

### Phase 2 — Resources + prompts

- Land the `ableton://browser/*` resources and the `ableton_help` tool.
- Land the first three prompts (`create_midi_track_with_instrument`, `setup_sidechain_compression`, `build_return_bus`).
- Update server `initialize` instructions.

### Phase 3 — Remaining domains

- `ableton_clip`, `ableton_device`, `ableton_automation`, `ableton_arrangement`, `ableton_browser`, `ableton_return`.
- Gap-flagged setters (mute/solo/arm/color, master, returns) land as actions on the new tools — they didn't have narrow tools to remove, so this is net-new capability via consolidation.

### Phase 4 — Deprecation warnings on narrow tools

- Each old tool's response carries a deprecation note pointing at the unified equivalent.
- Hallucinote planners verified emitting only canonical names.

### Phase 5 — Removal

- After at least one minor release at Phase 4, narrow tools removed.
- Hallucinote's `mcp_names.ALIASES_TODAY` drops to a handful (or empty).

### Phase 6 — Note + envelope pulls

- Once `ableton_note` and `ableton_automation` are exposed, the MCP-gap-blocked Hallucinote chunks (note pull, envelope pull, device parameter pull) unblock and Hallucinote ships those wave-3 chunks.

---

## 11. Hallucinote-Side Impact

### 11.1 What changes

- **`sync/mcp_names.py`**: shrinks from 22 entries to ~3-5 as unified tools land. The structure stays the same; the entries contract.
- **`sync/push.py`**: `_DIRECT_MIXER_TOOLS` dictionary collapses — every mixer field becomes direct, dispatched via action on `ableton_track`. `plan_push_mix` emits ~30% fewer ToolCalls (combining mixer-property writes into batched-action shape if MCP supports it).
- **`sync/push.py`**: `apply_push_results._ACK_ONLY_KINDS` shrinks for the same reason — fewer narrow keys to maintain.
- **`sync/pull.py`**: pull planners' probe lists shrink; `get_session_info` may move to a resource read where appropriate.
- **`docs/mcp-requirements.md`**: most of the "P2" sections get marked resolved as the unified tools land. The gap doc shifts from "missing tools" to "missing capabilities" (e.g., note-level addressing, envelope read surface).
- **`.claude/skills/ableton-pull/SKILL.md`**: simpler — the skill's `allowed-tools` list contracts to the 10 unified tools.

### 11.2 What doesn't change

- The DB schema. Pull and push semantics. Conflict policy. Generator API. Build governance.
- The plan-and-apply architecture stays — only the call shape underneath changes.

### 11.3 Estimated Hallucinote-side LOC delta

- ~200-line reduction in `sync/push.py` (consolidated emitters)
- ~50-line reduction in `sync/pull.py`
- ~60-line reduction in `sync/mcp_names.py`
- ~30-line reduction in `apply_push_results` dispatch tables
- Net: **~340 lines deleted** from Hallucinote when the migration completes.

---

## 12. Anti-Patterns Explicitly Rejected

Naming these so we don't reinvent them.

1. **REST→MCP 1:1 mapping.** The current 51-tool surface is exactly this anti-pattern — Live API methods became MCP tools 1:1. Don't extend the pattern; reverse it.<sup>[9]</sup>
2. **One mega-tool with a free-form query.** Block-style `execute_mutation_query(graphql)` is elegant for some domains but wrong for Ableton — it pushes Live API expertise onto the LLM and weakens schema validation. We want **typed actions with enums**, not freeform queries.
3. **Magic strings.** Action and property parameters are documented enums, not free strings. `'volume'` is a valid value; `'vol'` is not. The error response tells the agent which is which.
4. **Hidden coupling.** No "you must call X before Y" requirements that aren't surfaced in the tool's help text and the error message when violated.
5. **State in the wire.** No session tokens, no opaque cursors. Each tool call is self-contained.<sup>[10]</sup>
6. **Generic names.** No `do_thing`, `manage_state`, `process`. Every tool name names a domain; every action names an operation.
7. **"Single-operation tools that force agents into repetitive looping instead of batch support."**<sup>[3]</sup> Where it makes sense, an action accepts a list. `ableton_track(action='set_property', updates=[{track_index, property, value}, ...])`.

---

## 13. Open Questions

1. **Coordination with the AbletonMCP fork.** This redesign is upstream work on `ableton-mcp-extended`. Who owns the implementation timeline? Hallucinote can model the alias table around any cadence, but the migration needs a counterpart on the MCP side.
2. **Backwards compat scope.** Phase 4 deprecation warnings live for how long? One minor release feels right for a single-user authoring tool; if there are other consumers, longer.
3. **Note pull when gap #4 lands.** The `ableton_note` tool design here assumes note IDs become available. Validate against whatever shape the MCP gap fix actually delivers — adjust the action signatures before exposing them.
4. **Drum-rack chains.** Cordyceps handles nested clusters carefully. AbletonMCP's nested rack chains (`InstrumentGroupDevice`, `DrumGroupDevice`) are the analog — should `ableton_device` action `info` recurse into chains, or is that a separate action `chain_info`? Lean toward recursive `info` with a depth parameter.
5. **Resource caching semantics.** `ableton://session/snapshot` — every read scans Live, or cached? Caching helps performance but risks staleness during agent edits. Probably: no cache, re-scan on every read; agents stay light because they call `info` actions for specific slices instead.
6. **Should `ableton_help` itself be a tool, or just server instructions + per-tool help?** Cordyceps doesn't have a top-level help tool — it relies on initialize instructions + per-tool action='help'. We may not need `ableton_help` either; drop to 9 tools if so.
7. **Prompt vs Tool boundary.** `create_midi_track_with_instrument` is a prompt in this design. Should it instead be `ableton_track(action='create', instrument_uri=...)` with the load folded into create? Arguably yes — and the prompt becomes thinner. Worth a design pass during Phase 1.

---

## 14. Decision Log

These are the load-bearing choices, captured so we can revisit later if needed.

| Decision | Rationale | Alternatives considered |
|---|---|---|
| 10 unified tools, not 5, not 20 | Cordyceps lands at 7 with comparable domain complexity. 10 keeps domain boundaries clean (session ≠ track ≠ clip ≠ device); fewer would force awkward overlap. | 5 (forced overlap), 15 (under-collapsed) |
| Action dispatch with string enums | Matches cordyceps; concrete + LLM-readable; preserves typed validation per action | Single-tool-per-action (current), free-form query (Block), nested commands |
| Browser → resources | Static, parametric, used-on-every-load. Resources don't crowd selection space. | Keep as tool (current); accept the selection-space cost |
| `ableton_note` exists even though blocked | Stable surface for agents; "blocked" responses teach the gap | Omit until gap #4 lands; problem: surprises agents who don't read the gap doc |
| Aliases for one major version | Cordyceps practice; gives consumers time to migrate | Hard cutover (breaks Hallucinote at the moment of release) |
| Errors carry valid_actions + example + hint | Cordyceps + Alpic both converge on this; measurable accuracy lift | Bare error string (status quo) |

---

## 15. Success Criteria

Numbers we'll measure after Phase 5:

- Tool count: 51 → 10
- Hallucinote `mcp_names.ALIASES_TODAY` entries: 22 → ≤5
- Hallucinote LOC delta: net -~340 lines
- Server instructions token count: ≤500 tokens (initialize response)
- Per-tool description size: ≤200 tokens (so 10 tools × 200 ≈ 2000 tokens total tool-definition cost, vs ~10,000+ today)
- Agent task-success rate on a fixed benchmark (e.g., "create a sidechained synth bass"): measurable lift, not just feel. Baseline first, then measure post-migration.

---

## Sources

1. [Anthropic — Introducing advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
2. [Demiliani — MCP and the "too many tools" problem](https://demiliani.com/2025/09/04/model-context-protocol-and-the-too-many-tools-problem/) (cites Speakeasy Pet Store experiment, Copilot reduction)
3. [Arcade.dev — 54 Patterns for Building Better MCP Tools](https://www.arcade.dev/blog/mcp-tool-patterns)
4. [Alpic — Better MCP tool call error responses](https://alpic.ai/blog/better-mcp-tool-call-error-responses-ai-recover-gracefully)
5. [Apigene — What Are MCP Resources?](https://apigene.ai/blog/mcp-resources), [Exo Technologies — Tools vs Resources vs Prompts](https://exotechnologies.xyz/research/mcp-tools-resources-prompts)
6. [MCPcat — Error Handling in MCP Servers](https://mcpcat.io/guides/error-handling-custom-mcp-servers/)
7. [MCP spec — Tools (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
8. [MCP spec — Versioning](https://modelcontextprotocol.io/specification/versioning), [SEP-986](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/986), [SEP-1382](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1382)
9. [Block — Playbook for Designing MCP Servers](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers)
10. [Zeo — MCP Server Architecture: State Management](https://zeo.org/resources/blog/mcp-server-architecture-state-management-security-tool-orchestration)
11. [Eclipsesource — MCP and Context Overload](https://eclipsesource.com/blogs/2026/01/22/mcp-context-overload/)
12. Cordyceps source: `/Users/brookstalley/source/cordyceps` — internal reference implementation. Key files: `Tools/Unified/*.cs`, `Core/UnifiedToolHelpers.cs`, `Resources/ResourceRegistry.cs`, `Prompts/PromptRegistry.cs`, `McpServer.cs`, `Knowledge/*.md`, `CHANGELOG.md`.
