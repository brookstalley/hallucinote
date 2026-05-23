# Learnings

Accumulated wisdom from building this product.

## Pattern sweeps are tree-wide or they don't count

**When changing a convention (a kind, name, or shape used across many surfaces), audit every reference with a tree-wide grep before declaring the sweep done. Partial sweeps create self-contradicting docs that ship.**

Refactors that touch a wide pattern (e.g. "rename internal class name → display name in every `kind=` site") are easy to get 80% right and hard to finish. Stale references survive in agent-facing surfaces (skill markdown, action descriptions, conventions guides, snapshot examples) that aren't exercised by the test suite, then ship as contract drift the next user sees first.

Arc 4 / D4 hit this hard. The cumulative Critic round 1 caught the BLOCKING (`actions/device.py` recommending `kind='Compressor2'` while the new test pinned exactly that as a FAILURE). Round 2 then caught NEW BLOCKING — round 1's response had only updated the cumulative-Critic's named files but missed sibling surfaces with the same pre-D4 advice (`.claude/skills/return-new/SKILL.md`, `track-new-with-instrument/SKILL.md` Step 2 self-contradicting its own Notes). Round 3 added a tree-wide grep across `.claude/`, `docs/`, and `hallucinote_mcp/.../resources/` as a structural completeness check.

**How to apply.** For any change-the-convention refactor:
1. Before declaring done, run a tree-wide grep for the OLD pattern (`grep -rn '<old>' .claude/ docs/ src/`).
2. Each hit must be either (a) updated to new convention, (b) intentional historical/archaeology reference with explicit "no longer X" framing, or (c) backlogged with rationale.
3. Pin the NEW convention with a regression test that names what now FAILS (`test_load_internal_class_name_fails_under_new_convention`). The test makes the deletion semantic, not accidental — but only the grep catches surfaces the test doesn't exercise.

The agent-facing surfaces (action descriptions, skill markdown, conventions guides) are read at every session start. Stale recommendations there are higher-impact than test-fixture drift, because they shape what the next agent tries first.

## Sync planner discipline

**When emitting a `ToolCall` for an MCP tool that has no `ALIASES_TODAY` entry, verify the actual MCP signature against the planner's args before considering the planner complete.**

The "canonical name + alias" pattern in `sync/mcp_names.py` is for tools that don't yet exist or need emulation; tools called directly (no alias) trust the planner to match the real signature. There's no schema check, no aliased emulator, no runtime mismatch — the call just fails at push time. Chunk 2 shipped a `plan_push_cue_points` that emitted `{time, name}` while real MCP `create_cue_point` takes `(bar: int 1-based, beat: float 0-based, name: str)`; the Critic caught it. Inspect the tool's MCP schema (via `ToolSearch` for `mcp__hallucinote-mcp__*`) when writing a planner for a directly-callable tool, and add a one-line signature note in `mcp_names.py` if absent.

## Detection that replaces a user question must enumerate every state

**When you refactor "ask the user X" into "detect X programmatically," the detector must enumerate every state the user would have known to mention — including the ones that look the same from outside.**

Conflating two states the consumer needs to distinguish is silently broken: the wrong branch fires, or no branch fires, with no error. The fix is shape, not effort: return a tagged value (tuple, dataclass, enum) so the consumer has to handle each state explicitly.

The install-skill hardening (PR #15) hit this twice in two Critic rounds:

- `hallucinote_mcp_command()` initially returned `Path | None`, conflating "found on PATH" with "found via venv fallback." The SKILL.md's tri-state branch — bare command vs absolute path in `.mcp.json` — was unreachable; venv-only installs would silently write a bare name that Claude Code couldn't launch. Fix: return `(path, on_path)` so the consumer must handle each case explicitly.
- `existing_mcp_config_files()` initially scanned only top-level `mcpServers`, missing `claude mcp add`'s default `projects.<cwd>.mcpServers` scope. A real, common registration shape was invisible to the uninstaller. Fix: scan all three scopes and tag each hit with a `json_pointer` so the consumer knows which scope to edit.

**Test discipline:** for each detection helper, write at least one test that distinguishes the conflated states (not just "found" vs "not found"). If you can't articulate the second state in a test, you haven't enumerated yet.

## Never use `is` for Live API object identity

**When a handler creates a Live API object and then needs to find its index or reference, NEVER scan for `obj is new_obj` against `song.X` / `track.X` — Live re-wraps API objects on every property access. The scan returns False even for the same underlying Live object, and the handler silently fails or returns a result missing a field.**

Fixes for the post-create resolution are deterministic-from-semantics: `len(song.X)` after an append, `insert_at + 1` for an insert, or a stable value match (e.g., `start_time` for arrangement clips, name + position for cues). Hit five times in one session (track / scene / return / clip-arrangement create handlers all had this shape; a sixth had it in cue_create's post-toggle scan). Each fix shipped with a regression test using a `_ReWrappingFake*` pattern that returns fresh Python wrappers on every `song.X` access — those tests pass with the fix and fail convincingly without it. **Make the wrapper-recreating fake a shared helper** in `hallucinote_mcp.testing` so future handlers can write the same regression in one line.

The fakes that DON'T simulate wrapper recreation still pass when `is` is used — that's why the bug existed for so long. Treat any fake that uses a plain `list.append(obj)` for a Live-collection-shaped attribute as suspect, because real Live's collection accessor returns a fresh wrapper sequence.

## Live API: trust the side effect, not the getter readback

**When writing a Live property (especially anything bound to transport — `current_song_time`, anything that affects the audio thread), do NOT verify success by reading the same property back in the same callback. Verify by inspecting the actual side effect (e.g., `song.cue_points` after a `set_or_delete_cue` toggle).**

`Song.current_song_time` (and likely other transport-coupled properties) is an audio-thread-mediated value. The setter completes synchronously on the main thread but the audio thread picks up the new value on the next audio buffer (~5-10ms). Within the same main-thread callback, the getter still returns the audio thread's last-flushed value — which is the OLD position. `Song.set_or_delete_cue()` reads the same audio-thread state, so it fires against the OLD position too unless wall-clock time passes between the write and the toggle.

**The fix that works**: `time.sleep(0.2)` between the write and the dependent operation. Main thread blocks; audio thread runs (separate OS thread, real-time priority, no GIL). After the sleep, the audio thread has the new value. Then trust the write — don't verify via the getter — and inspect the actual side effect (the cue list) to confirm success.

**What doesn't work**: `schedule_message(0, fn)` chains. Multiple deferred callbacks fire back-to-back within a single engine tick; no wall-clock time passes. The deferred-completion infrastructure (`DeferredCompletion`, `LiveContext.schedule_after_tick`) is still a useful primitive for other async patterns, but it doesn't solve cross-thread real-time settles.

**Diagnostic discipline**: when a handler writes a transport-coupled property, always include `target`, `last_observed`, and `prior` in any error response. The "each call observes the previous call's target" race pattern is visible in 30 seconds with these fields, invisible without them.

## Unit fakes that mirror an *assumed* Live API give false confidence

**Test fakes for Live's Remote Script API must simulate the real API's quirks — not the API's documented or assumed shape. Without an integration smoke test against a real Live process, the unit suite gives a green light to handlers that crash empirically.**

The 2026-05-17 push session shipped five handler fixes (the B-1/B-2/B-10/B-11/B-12 bug bucket; original triage doc deleted in the v0.9.0 hygiene sweep — `git log -- .prawduct/artifacts/bug-triage.md` recovers it) that each had passing unit tests. The fakes mirrored what we *thought* Live exposed: collection appends preserved identity, `set_or_delete_cue` accepted a time argument, `Track.load_device` existed, etc. Real Live 12.4 differs on every count. The unit suite never saw the divergence.

**Required for any handler that wraps a Live API operation**: at least one of (a) a fake that simulates the *quirk* (wrapper recreation, no-arg signatures, missing methods), or (b) an integration smoke test run against a real Live instance. Smoke tests cost ~30s wall-clock per release; they catch a class of bugs the unit suite literally cannot see.

Track potential smoke-test coverage in a `tests/integration/test_live_smoke.py` file. Don't gate on it for every PR (too slow); gate on it for "ready to release" / pre-merge of large refactors.

## Link, don't summarize

**When an artifact needs to reference a fact that lives in another artifact, file, or code path, link to the source — don't restate the fact in this artifact's prose.**

Restating creates a second source of truth that drifts independently. J-5 caught this concretely: `project-state.yaml` copied "hypothesis (parked in conftest.py, commented)" from `project-preferences.md` line 26 — but the preferences doc was itself already stale relative to `tests/conftest.py`, which had enabled Hypothesis in Wave M-4. One stale phrase → two stale artifacts; each maintenance pass that re-summarizes can compound the drift instead of resolving it. The same shape appeared in J-2 (`project-preferences.md` Test-location block contradicted its own Dev-commands block 18 lines down) and J-3 (the README rewrite verified each claim against `.mcp.json` / `pyproject.toml` / actual file paths rather than trusting the prior README). **When writing or auditing an artifact, treat any prose summary as suspicious if the underlying fact lives elsewhere.** Prefer "see `X` for current values" over restatement. Restate only invariants that can't be derived, and only at the canonical source-of-truth file. The corollary for audit chunks: re-read code, never trust prior summarizations of code.

## Human-authoring boundaries split the chunk

**When a chunk's deliverables cross a Claude-cannot-author boundary (binary Max for Live `.amxd`, Logic Pro patch, image asset, anything that requires a visual/proprietary editor), restructure the chunk into two passes BEFORE building. Claude lands a written contract + the driver code + the verification math; the human authors the binary; Claude resumes for verification + Critic.**

Chunk 1 of the audio-analysis MVP hit this in shape: the "Done when" list mixed Claude-doable items (the PDC alignment test, the throwaway capture harness) with human-only items (the `.amxd` itself, the in-Live GO/NO-GO test). Build-governance treats a chunk as a single atomic unit ending in Critic — but a chunk that straddles a binary-authoring boundary cannot Critic at the natural Python-code-complete moment because the verification math has nothing to verify *against* yet. Inverting the order (write the spec first as an explicit handoff artifact, treat the binary as a dependency the human supplies, run Critic only after in-tool verification produces real captures) keeps the discipline intact without forcing a half-context review.

**How to apply.** When planning or starting a chunk:
1. Audit the "Done when" list for boundaries. Any deliverable that requires Max, Logic, a DAW patch editor, an image editor, a visual schema builder, or "user clicks something in a proprietary GUI" is a boundary.
2. If a boundary exists, split mentally into "spec + driver + verification" (Claude) and "binary/visual asset" (human). The spec is the artifact future Claude (and the human authoring the binary) reads — it must be precise enough that the human can author against it without coming back to ask.
3. Update the chunk's "Done when" to make the split explicit. Critic runs after the verification pass on real human-authored output, not on the spec.
4. Don't commit the spec-and-driver pass alone — leave the work uncommitted so the chunk commit lands atomically when verification passes. (Or commit the pass with an explicit `chunk: 1 of 2` marker so the next session knows the binary handoff is mid-flight.)

The failure mode this prevents: shipping a "Chunk 1 complete" claim that's actually 60% done because the binary authoring slipped to "later" and the verification was waved through.
