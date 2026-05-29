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

## Inverting a black-box formatter: validate a monotonic proxy, don't enumerate formats

**When you must invert an opaque value→string formatter that has no string→value API, don't special-case each output format. Parse a numeric proxy, VALIDATE it's monotonic over the domain by sampling, then bisect — and refuse when it isn't. One monotonicity check subsumes every "weird format" guard and auto-handles formats you haven't seen.**

`DeviceParameter` exposes `str_for_value(raw)` but no inverse, so `set_parameter`'s `value_display` ("-18 dB", "3:1") inverts it by bisecting on the number parsed from the display. The first cut parsed a leading number and then bolted on a guard per format real Live revealed — `-inf dB` (Threshold min), `inf : 1` (Ratio max), `Hz`→`kHz` (frequency). Each live probe surfaced another → whack-a-mole on the comparison layer.

Root cause: bisection only needs the parsed number to be a faithful *monotonic* proxy for the raw value. The failures were all "the proxy isn't faithful here," not distinct problems. The fix: sample `str_for_value` across `[min,max]`, verify the leading number is monotonic (varies + no reversal), bisect only then, refuse otherwise. That one check replaced the constant-leading-number and unit-scaling guards AND auto-handles unseen formats (ms→s, etc.) — a non-monotonic proxy is the general signal that display-units can't address a parameter.

**How to apply.** Inverting any black-box formatter: (1) parse a proxy; (2) validate the property the algorithm needs (here monotonicity) by sampling the domain; (3) act only when valid, refuse with a teaching error otherwise. A new branch per observed bad input is the smell that you're guarding symptoms instead of validating the invariant. And calibrate against real instances: all three traps came from real-Live probes, not the synthetic corpus — the sibling rule "Unit fakes that mirror an *assumed* Live API give false confidence" applies directly.

## When a doc or duplicated contract IS the deliverable, lock it with a drift/parity test

**A discoverable doc index or a value duplicated across surfaces only stays true if a test exercises it. When the deliverable IS documentation or a mirrored contract, the test is its teeth: a drift guard (doc ↔ source, both directions) or a parity lock (every duplicate emits the identical thing).**

The "Pattern sweeps are tree-wide" learning names the disease (agent-facing surfaces aren't exercised by tests, so drift ships). This is the structural cure for the case where the surface is itself the thing being built. Two instances in the bulk-note-authoring work: B2's `/compose-part` "Authoring API" doc index is the discoverable surface, so a bidirectional test asserts every documented `module.func` is importable AND every public generator fn is documented (`test_authoring_api_surface.py`); B4's inline-notes warning is emitted by two MCP actions, so a parity lock asserts both emit the identical text at the same threshold (`test_actions_clip.py`). Both turn "I hope this stays in sync" into a gate.

**How to apply.** (1) If you wrote a doc that catalogs a code surface, write a test that parses the doc and resolves each reference — and fails when the code grows a member the doc doesn't list (the reverse direction catches *undiscoverable* additions, which a one-directional test misses). (2) If a constant/message/shape is duplicated across N call sites, route them through one shared helper and lock parity with a test that compares all N outputs — and leave a comment at the helper telling the next author "new call site? route it here and add it to the parity test." (3) Prefer the threshold/source-of-truth as a single named constant the test imports, so the doc can reference it qualitatively (~32) without brittle numeric coupling.

## DSP with a detection front-end: calibrate against real cases, don't assert from intuition

**For any analyzer whose input is *detected* (onset detection, pitch tracking, beat tracking) rather than given, run real/representative cases through the actual pipeline and read the numbers BEFORE writing test assertions. The detection stage has latency and failure modes that abstract reasoning misses, and a fixture chosen for convenience can hide them.**

C7 (timing analyzer) almost shipped two bugs that only a calibration pass exposed. (1) The synthetic `kick_onset` fixture — picked because it already existed — is a *terrible* onset target: its slow low-frequency attack makes librosa detect it 0.13–0.49 beat late and multi-trigger, so on-grid material read as wildly off-grid. (2) Swing read 1.35 for a triplet feel that should be ~2.0, because spurious double-onsets polluted the mean off-beat phase. Both were invisible to intuition and to a "looks reasonable" fixture; both were obvious the moment real grooves (a user's "can we be Phish / Dead / Marley?") were run through the real module and the numbers printed. Fixes followed directly: a sharp `click` fixture (accurate onset), finer hop, onset dedup, MEDIAN (not mean) swing phase, tightness-based (not grid-aligned) confidence.

**How to apply.** (1) Build a tiny calibration script that runs representative inputs through the real analyzer and prints the metrics; eyeball them against what the music *is* before locking assertions. (2) Choose fixtures for *detection accuracy*, not convenience — a synthetic transient with an instant attack tests the analyzer's math; the real-world detection-accuracy limit (slow-attack instruments) becomes a documented caveat, not silent fixture bias. (3) Prefer robust statistics (median over mean) and robustness-to-constant-offset designs (measure tightness/relative timing, not absolute) when the front-end has systematic error. (4) Treat a user's "can it do X?" as a design stress-test — answer it by running X, not by reasoning about X.

## A staleness/version signature must be content-derived, never hand-bumped

**When you surface a "version" or "signature" so a consumer can tell whether loaded code is stale, derive it from the content (hash the source), not a hand-maintained string. Forgetting to bump a manual version is the exact failure mode the signature exists to catch — a manual bump and the stale-reload it's meant to detect are indistinguishable.**

The masking-arc backlog item "surface the loaded `analyzer_signature` so a stale MCP server is obvious" pointed at an existing field — but reading the code showed that field is a hardcoded capture-device label (`"hallucinote-analyzer-v1"` in `render.py`) that never moves when analysis-pipeline code changes. It structurally cannot detect staleness. The cheap fix (a hand-bumped `__version__`) has the identical defect. The correct fix hashes the `hallucinote/audio/` package source, frozen at import (= the code the subprocess actually loaded) and compared against a per-call disk recompute (`audio/codeversion.py`). The freeze-at-import-vs-recompute split is the load-bearing part: hashing only on-disk source would report "fresh" while the process runs old code. Aligns with "prefer structural fixes over patches."

**How to apply.** (1) If the signal is "is the running code current?", capture the signature when the code loads (module-import-time constant) and compare to a live recompute — two reads, not one. (2) Hash content, never a manual label; a manual label re-creates the forget-to-update gap. (3) Verify the import-freeze claim in a *live process* (edit real source, watch the flag flip, revert), not just with monkeypatched functions — patching hides whether the freeze actually captures loaded vs on-disk bytes. (4) Don't conflate provenance concepts: "which device captured this" (capture signature) and "which code interpreted it" (analysis-code signature) are different surfaces — name them apart.

## DB-UUID → capture-surface-ID lifts must key by surface ID, and be tested with distinct IDs

**When an analysis handler lifts DB rows into something the capture/analysis layer consumes, key the result by the capture SURFACE ID (`track:N` via `track_id_for_surface(track_index)`), never the DB UUID (`row['id']`). Test with UUIDs deliberately distinct from the index so a wrong-key no-op fails loudly.**

The audio captures are keyed by structurally-stable surface IDs (`track:N`/`return:N`); the DB is keyed by UUID. `analyze_mix` and `apply_stem_gains` look up by the capture key. C3's `_collect_stem_gains` keyed the gains dict by `row['id']` (UUID), so `apply_stem_gains` never matched → the F1 level correction was a **silent no-op on every real song**, and CI stayed green because the unit tests used self-consistent IDs on both sides and the integration test relied on the empty-map no-op path. The cumulative Critic caught it; the sibling `_collect_declared_sends` already did the lift correctly via `track_id_for_surface`. The regression test seeds UUIDs ≠ `track_index` and asserts `track:N` keys — it would have failed against the old keying.

**How to apply.** (1) Any `_collect_*` helper feeding the capture/analysis boundary lifts via `track_id_for_surface(kind, index)`. (2) Its test uses UUIDs distinct from indices so a no-op keying can't pass. (3) A "validation" that runs the real pipeline but prints the *gains dict* (UUID-keyed) isn't proof the gains *applied* — assert the corrected output differs from the uncorrected one.

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

## Live parameters are float / int / enum only — strings need an out-of-band channel

**When designing an M4L device's exposed parameters, never assume a "string parameter" can exist as a Live parameter. Live's Remote Script API and automation system only carry float, int, and enum values. `live.text` exposes a string *as a UI element*, but not as something the Remote Script can `set_parameter` against — its parameter type field literally won't accept "Symbol/String".**

**Why:** the M4L parameter mapping layer (the thing that shows knobs in Live's device view and lets Remote Scripts write them) is fundamentally numeric. Strings can be displayed in a `live.text` UI object but cannot be the value of a Live parameter. The spec for `HallucinoteAnalyzer.amxd` originally assumed `output_path` could be a string Live parameter; it can't.

**How to apply:**
1. Any string config (file paths, IDs, signatures) the Python side wants to push to the device must go through an out-of-band channel — typically OSC via `udpreceive` + `OSC-route` (CNMAT package), with the OSC port itself an int Live parameter.
2. When sketching a new M4L device spec, audit the parameter table: every row must be coercible to float/int/enum. Anything string-typed must be re-homed onto an OSC inbound or onto the device's filename / class metadata.
3. When updating the spec mid-authoring, also amend any Python harness that assumed the old shape — the harness's `set_parameter(name='Output Path', ...)` becomes an OSC client + `set_parameter(name='OSC Port', ...)`.

Confirmed during Chunk 1 of the audio-analysis MVP: the `live.text` inspector's Type dropdown only offers float / int / enum, which surfaced the constraint. Spec was amended, OSC inbound chain was specified, and Chunk 2's reserved list was updated (signature and track_id have the same string constraint and were re-routed onto the same inbound channel).

## Live's Remote Script API surfaces parameters by short name, not long name

**When writing or driving an M4L device parameter from the Python side (`ableton_device.set_parameter`, `get_parameters`), the parameter address must be the `parameter_shortname` value from the Max patch, NOT the `parameter_longname`. The Remote Script API's `Parameter.name` attribute reads from `parameter_shortname` if set; the long name only appears in Live's UI parameter list for humans.**

**Why:** the spec for `HallucinoteAnalyzer.amxd` originally specified long name "Record Arm" as the addressing key, and the Chunk 1 harness wrote `parameter_name="Record Arm"`. The authored `.amxd` set both `parameter_longname: "Record Arm"` and `parameter_shortname: "Arm"`. `ableton_device(action='get_parameters', ...)` returned `{name: "Arm", ...}` — the short name. A `set_parameter` call against "Record Arm" raises an unknown-parameter error; against "Arm" succeeds. Same for "OSC Port" / "Port".

**How to apply:**
1. When specifying an M4L device's parameter table, declare both names but mark the **short name** as the addressing key. The long name is documentation; the short name is the contract.
2. Always verify by calling `get_parameters` against a loaded instance — the returned `name` field is the address future writes will use.
3. If both names are the same (no `parameter_shortname` set in the patch JSON), the long name IS the short name; no ambiguity. The gotcha only bites when authoring picks distinct names for UI compactness.

Confirmed Chunk 1 in-Live verification, audio-analysis MVP: only after probing the live device did the address mismatch surface. The harness and spec were both updated; this rule applies to Chunk 2's `ensure_analyzers_loaded` and any future M4L device the project authors.

## sfrecord~ control API: bare integers (1 / 0), not `record N`

**When driving Max's `sfrecord~` from a patch, use the documented bare-integer left-inlet API: `1` (integer) starts recording, `0` (integer) stops AND finalizes the WAV header in one operation. There is no `close` message, no `stop` message, and no `record 0` stop variant — those are not part of sfrecord~'s API and are either silently ignored or rejected with "doesn't understand". The `record <N>` message is a SEPARATE API for fixed-duration recording (`record 100` = "record for 100 ms then auto-stop"); using `record 1` as if it meant "start recording" produces a 1-millisecond capture, not an indefinite one.**

**Why:** the [Max sfrecord~ docs](https://docs.cycling74.com/max8/refpages/sfrecord~) say "A non-zero value begins recording, and 0 stops recording and closes the file." The number-to-left-inlet API is the documented control surface. The `record <duration>` message is for timed recordings only. Confirmed via Max Console output during Chunk 1 of the audio-analysis MVP — both `stop` and `close` produced explicit "sfrecord~: doesn't understand" prints, and `record 0` failed to stop a recording that kept growing for 127 s past the patch's "stop" command. Switching to bare `0` immediately produced clean, properly-finalized WAVs.

**How to apply:**
1. Wire `live.toggle` (or whatever produces the 0/1 trigger) so the bare integer reaches `sfrecord~`'s left inlet. On rising edge, sequence `open <path>` BEFORE the `1` via `[t b b]` right-then-left ordering (right outlet fires first in Max).
2. On falling edge, just send `0` — no separate close needed. The file is finalized atomically.
3. After a `0`, sfrecord~ requires a fresh `open <path>` before the next `1`. If you need to record twice without reloading the patch, send a new `open` each time.
4. Never use `record 1` to mean "start". It means "record for 1 millisecond." If you see a 44-frame capture at 44.1 kHz (≈ 1 ms), this is the bug.

This rule applies to any future Max for Live audio-effect device the project authors. The trap is high-leverage because `record 1`/`record 0` *looks* like a sensible API by analogy with bool toggles, and the docs bury the bare-integer API in prose rather than highlighting it as the canonical control surface.

## M4L Int parameter range capped at 256 — use Float + Unit Style Int

**Live encodes Int-typed `live.numbox` parameter automation as a single byte (0-255), so an Int-typed Live parameter's range can hold at most 256 distinct values. Setting `Range: 11000 11400` on an Int-typed `live.numbox` silently clamps to `11000 11255` in Max's Inspector — the cap is not surfaced as an error, just a quiet snap. Per Max's documentation: "By convention, the Live application uses floating point numbers for its calculations; the native integer representation is limited to 256 values, with a default range of 0-255. When working with Live UI objects whose integer values will exceed this range, the Type attribute should be set to Float, and the Unit Style attribute should be set to Int." Float type removes the 256-step cap; Unit Style = Int renders the float as a whole number in the UI.**

**Why:** Chunk 2 of the audio-analysis MVP needed `Port` and `EmitPort` ranges of 11000-11400 to accommodate the deterministic per-surface port allocation (100 audio tracks + 100 returns + master + emit). Setting the range with `Type = Int` clamped Max's Inspector to 11000-11255 silently, breaking the allocation. The Max docs explicitly call out Float+UnitStyle-Int as the documented convention for Int-displayed values exceeding 256 — this is not a workaround, it's the supported path.

**How to apply:**
1. For any `live.numbox` whose `max - min` will exceed 255, set Type = Float in the Inspector BEFORE setting Range. (Setting Range first under Type = Int clamps silently.)
2. Set Unit Style = Int so the UI still renders whole numbers.
3. The Remote Script's `set_parameter(value_type='continuous', value='11042.0')` writes through normally — Float-typed parameters accept float values via the existing continuous path. No client-side change needed.
4. The patch's downstream handling should `[i]`-coerce the `live.numbox` outlet wherever an int is required (sample counts, port numbers as `[udpreceive]` arg, etc.).
5. Symptom that triggers this rule: setting a `live.numbox` max to a value that's `> min + 255` and watching the Inspector snap it back to `min + 255` instead. Don't waste time looking for a "hidden" cap setting — switch Type to Float.

This rule applies to any future Max for Live device the project authors with Int-displayed values exceeding 256 distinct steps (sample counts, port numbers, MIDI buffer sizes, etc.).

## M4L device source belongs in `Presets/Audio Effects/Max Audio Effect/`, not Remote Scripts

**When installing an M4L `.amxd` into Live, copy it to `<User Library>/Presets/Audio Effects/Max Audio Effect/` and nowhere else. If the same `.amxd` is also present anywhere else under `<User Library>` (e.g., inside the Remote Script's vendored package directory), Live's browser indexes BOTH copies and shows the device twice with the same display name. Users can then accidentally drag a stale copy onto a track and waste hours wondering why their Max edits don't show up — Max's editor saves to the file the device was loaded from, but the running instance is whichever file Live happened to load when the device was dragged from the browser.**

**Why:** Live's User Library indexer is recursive — every `.amxd` anywhere under the User Library tree shows up in the browser's "Max Audio Effect" section. There's no "preferred location" priority; identical filenames in different directories appear as separate-but-identical entries. The Remote Script copy of the package (via the install skill's rsync/robocopy step) needs to EXCLUDE the `m4l/` source directory; otherwise the device file ends up duplicated. Confirmed audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26): user saw two `HallucinoteAnalyzer` entries in browser, only one (the Remote Scripts copy) was stale, and the running instance was the stale one — Max edits to the Presets copy were invisible to the device for hours of debugging until the user noticed the duplicate.

**How to apply:**
1. Install skill's Remote Script copy step must EXCLUDE the `m4l/` source subdirectory (along with `cli/`, `tests/`, `__pycache__/`). See `install_paths.py:REMOTE_SCRIPT_EXCLUDE_DIRS_ANY`.
2. Install skill's Step 3d (analyzer copy) targets ONLY `Presets/Audio Effects/Max Audio Effect/`. There's no second target location.
3. Uninstall skill should remove BOTH the Remote Script Python files AND the `Presets/.../HallucinoteAnalyzer.amxd`. (Currently W12-D-scoped — the uninstall skill removes Remote Scripts; analyzer cleanup is a follow-up.)
4. When debugging "my edits aren't showing up," the FIRST check is: are there multiple `.amxd` files with the same name under `<User Library>`? `find ~/Music/Ableton/"User Library" -name HallucinoteAnalyzer.amxd` surfaces them quickly. The running device is whichever path Live's browser entry points at; the user's edits go to whichever path Max's editor has open.

## M4L `[value]` doesn't emit on write — use `[i]` / `[f]` for cold-inlet storage

**Max for Live's `[value]` object in current Max versions stores writes silently — its outlet only emits when banged, not on receive. This breaks any chain that feeds `[value]` and expects downstream consumers to react (cold inlets of `[expr]`, `[gate]` control inputs, `[print]` boxes, etc.). Use `[i]` (int) or `[f]` (float) instead — both emit on every write.** The trade-off is losing named-shared-variable semantics across patchers; for local-only use within a single patcher that doesn't matter.

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B in-Live verification (2026-05-26), the patch's `[loadbang] → [0] → [value has_path] → [print has_path_now]` chain didn't fire `has_path_now: 0` at load. We bypassed `[value has_path]` with a direct `[loadmess 0] → [print has_path_now]` connection and the print fired. Putting `[value has_path]` back in the chain stopped the print again. Swapping `[value]` for `[i]` fixed it. Same fix applied to `v_arm`, `v_start_at_beat`, `v_stop_at_beat`, and `prev_beat` (the last using `[f]` since prev_beat is a float). Without the fix, expr cold inlets latched their default values (0) and the crossing-detection never returned true.

**How to apply:**
1. When wiring a storage box whose outlet must trigger downstream on receive, prefer `[i]` / `[f]` over `[value]`.
2. ~~Reserve `[value <name>]` for read-only public state that other parts of the patcher will explicitly bang for retrieval~~ — see next learning. `[value]` is unsafe even with explicit bang-to-emit when multiple device instances coexist.
3. If you inherit a patch with `[value]` boxes in trigger chains, swap them as a one-line fix.

## M4L `[value <name>]` is GLOBAL-by-name across all device instances — never use for per-instance state

**`[value <name>]` in M4L's bundled Max is a GLOBAL SHARED VARIABLE keyed by `<name>` across the entire Live session. Every `[value foo]` box in every device instance reads/writes the SAME underlying global. Storing per-instance state in `[value <name>]` causes silent cross-instance clobbering: the LAST writer wins; all OTHER instances see that last write when they bang their local `[value]` box. Fix: feed the value DIRECTLY to its consumer at receipt time (no intermediate storage), or use `[zl reg]` / `[coll]` / a `[message]` box scoped to the patcher.**

**Why:** audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-27) — with N analyzer instances loaded across tracks + returns + master, `ableton_render(action='render')` produced only ONE WAV per render, always for whichever analyzer received its `/path` LAST. The patch design: `OSC-route /path → value hallucinote_path` for storage; transport-cross detector → `[t b b] → bang value → emits stored path → prepend open → sfrecord~`. Worked in single-instance verification (G.5, Chunk 1). Failed silently for multi-instance because all N `[value hallucinote_path]` boxes shared one global; the LAST `/path` write overwrote everyone's stored path; at cross-detect time, all N sfrecord~ instances raced to open the SAME file path (only one wins the file-open race). Deterministic and order-dependent: OSC to track 1 then track 2 → only track 2 records; reverse order → only track 1 records. Same bug present in `[value track_id_retained]` (used for `/signature` reply target host:port).

**How to apply:**
1. Audit `[value <name>]` boxes in any patch intended to load as multiple instances in the same Live set. Replace per-instance ones with direct wiring (path → consumer at receipt time) or `[zl reg]` / `[message]`.
2. Specifically for the Hallucinote analyzer: wire `OSC-route /path` outlet 0 → `prepend open` inlet 0 directly so each instance's sfrecord~ opens its own file immediately on `/path` arrival. Remove the `[t b b]` outlet → `[value]` bang patchline (no longer needed — sfrecord~ already has the per-instance file handle).
3. Pre-MVP check: any new `[value <name>]` box on a multi-instance device should be flagged in code review with "is this state PER-INSTANCE or GLOBAL?" If per-instance, do not use `[value]`.
4. Other M4L per-patcher storage options worth knowing: `[zl reg]` (per-instance list storage, banged for emit), `[message]` (set with `set <value>`, banged to emit), `[pattr <name> @bindto ...]` (per-patcher attribute storage with optional Live param binding).

## M4L `live.toggle` outlet emits int (0/1) directly — no `[== on]` shim needed

**In current Max versions, `[live.toggle]`'s outlet emits int 0 (off) or int 1 (on) directly when its bound Live parameter changes. NOT the symbol "off"/"on". Adding a `[== on]` symbol-to-int converter shim between live.toggle and downstream INVERTS the value, because `[== on]` coerces the symbol arg `on` to int 0 — so `0==0→1` and `1==0→0`. Wire `[live.toggle]` outlet DIRECTLY to downstream `[i]` storage or trigger chains.**

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26), early debugging surfaced "off: bad number" errors in the Max console — which looked like live.toggle was emitting the symbol "off" to a numeric destination. We added `[== on]` to convert symbols to ints, and the chain APPEARED to work. But on closer inspection (a `[print TOGGLE_RAW]` placed directly on live.toggle's outlet showed `TOGGLE_RAW: 0`), live.toggle was already emitting int 0. `[== on]` then compared int 0 to symbol arg `on` (coerced to int 0), returned 1 — inverted. With `[== on]` removed, the chain worked correctly. The "off: bad number" errors were a separate event (perhaps a parameter-init flow we never fully traced) and didn't actually flow through the downstream chain.

**How to apply:**
1. Wire `[live.toggle]` outlet directly to int-consuming downstream (`[i]`, `[change]`, `[sel 0 1]`, `[expr ... $i ...]`).
2. If you see "off: bad number" or similar console errors during M4L load, don't assume they're from the chain you care about. Probe with a `[print TOGGLE_RAW]` directly on the live.toggle outlet to see what's actually being emitted.
3. The `[== on]` pattern shows up in some older Max for Live tutorials. Treat those tutorials as potentially stale.

## M4L `live.observer` needs runtime `property <name>` message; outputs bare value

**`[live.observer @property current_song_time]` as a single box with the property as an @attribute silently fails to fire in current Max versions. The `@property` attribute isn't honored at load. Also: when configured correctly, `live.observer` outputs ONLY the value (a bare float/int), not `<property_name> <value>` as some Max documentation suggests — so `[route <prop>]` downstream filters everything out.**

**Canonical pattern that works:**

```
[live.thisdevice]                 ← fires bang when device fully embedded in Live
        │
        ▼
   [t b b]
   ├── outlet 1 (right, fires FIRST)
   │      ▼
   │   [live.path live_set]
   │      │
   │      ▼
   │   [live.observer] inlet 0    ← receives "id <N>", configures object
   │
   └── outlet 0 (left, fires SECOND)
          ▼
      [message property current_song_time]
          │
          ▼
      [live.observer] inlet 0     ← receives property message, starts observing
```

Then `[live.observer]` outlet emits the bare float every time the property changes — wire it DIRECTLY to downstream consumers (no `[route]`).

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B in-Live verification (2026-05-26), the patch's transport observer chain didn't fire. Adding `[print OBS_RAW]` directly on live.observer's outlet showed nothing during transport play. Restructuring to the canonical thisdevice→path→observer pattern with `property` as a runtime message made OBS_RAW fire with bare float values (e.g., `OBS_RAW: 4.493`). `[route current_song_time]` downstream of observer was filtering everything because there's no property-name prefix in the output.

**How to apply:**
1. Use `[live.thisdevice] → [live.path <path>] → [live.observer]` as separate boxes; don't compress into a single `live.observer @path @property` box.
2. Send `property <name>` as a runtime message (via `[message property <name>]`) to live.observer's inlet at load time.
3. Don't add `[route]` after live.observer — the output is bare value, no symbol prefix to match.
4. To diagnose "is the observer firing?", add `[print OBS_RAW]` directly on its outlet. If nothing prints during the property's actual change, the chain isn't configured correctly — re-check the multi-box pattern.

## M4L patcher editor and Live runtime fight over udpreceive — close the editor before testing

**When a Max for Live patcher is open in Max's patcher editor (the window that opens when you click Live's "Edit" button on a device), Max-editor and Live-runtime each have an instance of the patcher. They compete for the `udpreceive` socket binding. Symptoms: multiple "binding to port N" then "bind unsuccessful" console messages; OSC messages reach SOMETHING but unpredictably; `live.observer` may silently not fire; saving the patch doesn't reliably propagate changes to the running instance.**

**Workflow rule: ALWAYS close the patcher editor window before runtime testing.**
1. Make changes in Max's patcher editor.
2. `Cmd-S` to save.
3. `Cmd-W` to close the patcher window — NOT `Cmd-Q` on Max as a whole. Keep `Window → Max Console` open (it's a separate window that persists).
4. In Live, click the device's on/off LED off+on to force a fresh device instantiation.
5. Test from outside (MCP, Python OSC sender, etc.).
6. Re-open the patcher editor (Live's Edit button) only when you need to make further changes.

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B verification (2026-05-26), the patcher's OSC chain behaved inconsistently for hours of debugging. Reference thread on the Cycling '74 forum confirms this is a documented M4L issue: "max4live device opened for editing is never going to behave same way as when it is just loaded in Live" (Cycling '74 forum, Nov 2021). The udpreceive object can't bind from two patcher instances simultaneously. With editor closed, all behavior stabilized — signature reply, has_path flag, observer all worked cleanly.

**How to apply:**
1. Treat patcher editor and runtime as mutually exclusive for testing purposes.
2. If you must keep the editor open (e.g., to watch a `[print]` while testing), accept that observed behavior may not match what end-users will see.
3. The Max console window (Window → Max Console) is independent of the patcher editor window — close patcher, keep console.
4. For complex M4L debugging cycles, the close-patcher / open-patcher dance is part of the workflow, not optional.

## M4L device identity is in `device.name`, not `device.class_display_name`

**Every M4L audio-effect device in Live has `device.class_display_name = "Max Audio Effect"` — that's the device CLASS, not the specific .amxd identity. The .amxd filename (sans extension) lives in `device.name`. Code that detects "is this analyzer/device a HallucinoteAnalyzer instance?" by comparing against `class_display_name` will be permanently False for every real M4L device, with no error — just silent always-add behavior. The correct check is `device.name == "<.amxd filename>"` (with `class_display_name == "Max Audio Effect"` as a secondary anchor proving it's an M4L device, not a similarly-named user preset).**

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B end-to-end verification (2026-05-27), `ableton_render(ensure_loaded)` hung Live's main thread when called on a session with 5 tracks + 3 returns + master. The trace showed `_find_analyzer_index` returning None on EVERY pre-existing analyzer, so `ensure_loaded` was triggering a fresh load on every surface every call — including surfaces that already had one. Live MCP probe of a loaded analyzer revealed the actual attribute shape: `{"name": "HallucinoteAnalyzer", "class_name": "MxDeviceAudioEffect", "class_display_name": "Max Audio Effect"}` — confirming `class_display_name` is the device class ("Max Audio Effect"), not the .amxd identity. The earlier docstring claim ("Live surfaces the .amxd filename as `class_display_name`") was wrong, and the test fakes mirrored the buggy claim — so all 11 analyzer-setup tests passed while production was permanently broken against real Live.

**How to apply:**
1. For M4L device identity comparisons (detection, deduplication, "is this analyzer mine?"), compare BOTH `device.class_display_name == "Max Audio Effect"` (proves M4L audio-effect class) AND `device.name == "<filename>"` (proves the specific .amxd). Either alone is insufficient: just-class-display-name matches every M4L; just-name could match a user-renamed device of any class.
2. The combined check has one edge: if a user renames the device in their session, `name` no longer matches and detection breaks. For truly canonical identity, use the OSC `/signature/query` round-trip the analyzer spec defines — heavier but rename-proof. Pick the simpler `class+name` check unless you have evidence renames are common.
3. **Test fakes MUST mirror real Live's attribute shape, not the production code's (possibly buggy) assumptions.** When constructing a fake M4L device, set `class_display_name="Max Audio Effect"` and `name=<filename>` — NOT `class_display_name=<filename>`. A fake that defaults `name = class_display_name` (the easy mistake) will pass tests that fail against real Live.
4. The same trap structure (production code asserting one attribute shape; test fake conforming to the buggy assertion; both pass tests; real Live disagrees) is a general M4L authoring pitfall — when adopting any new Live device API surface, probe a real instance via `ableton_device(action='info', ...)` BEFORE writing the production check, and seed the test fake from the probe output.

## M4L devices installed under User Library require `preset_query`, not `kind=`, in `ableton_device(action='load')`

**When the device-load handler is given just `kind='<DeviceName>'`, it walks ONLY the built-in `_BROWSER_LOAD_ROOTS = (instruments, audio_effects, midi_effects, drums)` — it does NOT walk `user_library`, `plugins`, `samples`, or `packs`. M4L devices installed via the project's own install skill (e.g. HallucinoteAnalyzer.amxd → `User Library/Presets/Audio Effects/Max Audio Effect/`) live under `user_library` and are therefore invisible to `kind=`-based lookup. The fix is to pass `preset_query={'root': 'user_library', 'pattern': '<DeviceName>', 'path_prefix': [<exact install path segments>]}` instead. `kind` must STILL be passed (it's required by the handler signature) but `preset_query` takes precedence and selects the actual item.**

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B close-out (2026-05-27), `ableton_render(action='ensure_loaded')` failed on a fresh Live session with `"no loadable browser item found for kind='HallucinoteAnalyzer'"` despite the `.amxd` being correctly placed at `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd` (verified via `installed_analyzer_amxd()` and via `ableton_browser(action='search', root='user_library', pattern='hallucinote')` returning `is_loadable: True`). Root cause: `analyzer/setup.py::_ensure_on_surface` passed `kind=ANALYZER_DEVICE_NAME` to `device_handlers.load_handler`, which walks only `_BROWSER_LOAD_ROOTS`. The fix narrowed the lookup to the exact User Library subpath via `preset_query`, including a `path_prefix` to prevent shadowing by user-saved presets with the same display name elsewhere in their library.

**How to apply:**
1. When the project's install skill places an .amxd under User Library, the analyzer-load chain MUST use `preset_query` (not `kind=`) with `root='user_library'` and `path_prefix` pinning the install location.
2. The `path_prefix` value should mirror the install path exactly — codify it as a module-level constant (e.g. `ANALYZER_BROWSER_PATH_PREFIX = ("Presets", "Audio Effects", "Max Audio Effect")`) and reference both the install skill and the loader from it. Drift between install location and loader location is silent (the device just won't be found).
3. Test fakes (e.g. `_FakeBrowser` in `tests/unit/test_analyzer_setup.py`) must mirror the real install layout — populate `user_library` with the nested `Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer` subtree, NOT a top-level `audio_effects` child. A fake that puts the analyzer in the "wrong" root will pass tests that the production code fails.
4. If you DO want to extend `kind=` lookup to walk User Library, modify `_BROWSER_LOAD_ROOTS` cautiously — it adds search cost on every device-load and risks name collisions with user-saved presets. The narrow built-in set was an explicit design choice. For user-library-installed devices, `preset_query` is the proper surface.
5. The same logic applies to any future M4L device the project ships: the install skill places it under `user_library/<something>`; the loader must use `preset_query` with that path_prefix.

## M4L `[peakamp~]` is self-clocked via a reporting-interval arg, not banged

**Max's `[peakamp~]` object does NOT reliably emit on bang to its left inlet in M4L's bundled Max runtime, despite some documentation suggesting it should. The canonical control surface is its constructor argument (an int in milliseconds): `[peakamp~ <interval>]` auto-emits the peak + resets every `<interval>` ms. With no constructor arg, the object may default to a state where it doesn't emit at all.**

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26), the feature emitter's sample-peak extractor was initially designed to be metro-banged at 30 Hz (`[t b b b b]` → bang to `[peakamp~]` inlet 0). In M4L, `[peakamp~]` ignored the bangs entirely — no output reached downstream `[expr]` / `[send]` / `[receive]` / `[pack]` chains. Switching to `[peakamp~ 33]` (auto-emit every 33 ms) made peak values flow continuously into `[pack]`'s cold inlet. The metro fan-out simplified from `[t b b b b]` (4 outlets — three extractor bangs + address) to `[t b b b]` (3 outlets — two snapshot bangs + address), since peak no longer needs a metro tick.

**How to apply:**
1. For `[peakamp~]`, use the constructor-arg interval form (e.g., `[peakamp~ 33]` for ~30 Hz). Don't try to bang it.
2. The interval should match the consumer's polling rate so the latched value is at most `<interval>` ms old when read. For a 30 Hz consumer, 33 ms is a good match.
3. Self-clocked extractors are asynchronous to a metro-driven `[pack]` fire path. That's fine — cold-inlet writes always succeed (they latch); `[pack]` only fires when the hot inlet hits. The latched value is at most one interval stale at fire time.
4. If precise phase alignment matters (it usually doesn't for peak reporting), use a shorter interval — `[peakamp~ 10]` updates at 100 Hz, so the metro-tick read is at most 10 ms stale. Trade off CPU for freshness.
5. The same self-clocking pattern shows up in other Max audio-rate "report periodically" objects (e.g., `[meter~]`, `[snapshot~]` with `[metro]` upstream). When an object provides an "interval" or "rate" arg, prefer it over bang-driven polling — the docs may say bang works, but in M4L it often doesn't.

## M4L `[average~]` has one inlet, not two — window-size message shares the signal inlet

**`[average~]` exposes a single inlet that multiplexes the audio signal (entered via `~` connection) with control messages (entered via non-`~` connection). The window size in samples is set by sending an int message to that SAME inlet — there is no separate right inlet for window configuration despite what some Max object references imply. Max disambiguates by message type: `~` carries signal flow; non-`~` carries control messages, and the two coexist in the same inlet without colliding.**

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26), the SR-adaptive `[average~]` window-update chain (`[adstatus sr] → [expr $f1 * 0.4] → [i] → [average~]`) was first designed to feed the int into `[average~]`'s "right inlet 1" — but `[average~]` only shows one inlet in the patcher editor. The correct topology wires the int message to the same LEFT inlet that the audio signal enters. Same single-inlet multiplexing as `[peakamp~]` (which shares its inlet for signal + bang).

**How to apply:**
1. When wiring a control-rate parameter update to a `~` audio object, check whether the object has a separate parameter inlet OR multiplexes on the signal inlet. `[average~]` and `[peakamp~]` multiplex; `[*~]` (in some configurations) has a separate right inlet for the multiplier signal. The patcher editor shows the truth — count inlets in the GUI.
2. When the same inlet accepts both signal and control messages, wire both connections to it. Max's scheduler keeps them separate.
3. If you find yourself thinking "the docs say there's a right inlet for X" and the editor disagrees, trust the editor. Max docs sometimes describe an idealized object that doesn't quite match the runtime.
4. Companion pattern: `[peakamp~]` shares inlet 0 for signal + bang. The bang triggers read+reset; the signal flows continuously. Same multiplex shape.

## M4L `[expr]` function vocabulary is narrow — no conditionals, no min/max; use `[clip <floor> <ceiling>]` upstream for log-of-zero protection

**Max's `[expr]` object in M4L's bundled runtime has a NARROW function vocabulary: `abs, ceil, floor, int, float, exp, log, log10, fact, ln, pow, sqrt, rand, random` + the trig family. It does NOT have `if(cond, then, else)` (returns `function if not found`), does NOT have `max(a, b)` or `min(a, b)` (also `function max not found`), and the C-style ternary `? :` is unreliable. Some Max documentation lists `max()` as an `[expr]` function but it's empirically absent in M4L's bundled Max — do not trust the docs over the runtime. For "compute `log10(x)` but produce a sentinel when x is zero" conversions, clamp the input UPSTREAM with `[clip <floor> <ceiling>]` (a Max control-rate object, space-separated args, single inlet/outlet) and keep the expr as plain arithmetic.**

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26 → 2026-05-27), the LUFS-M / peak / low-mid extractors all needed a "log of mean-square, with -120 dB sentinel for silence" conversion. Four failed attempts established the function-vocabulary boundary empirically:
1. C-style ternary `($f1 > 0.) ? (10. * log10($f1)) - 0.691 : -120.` — Max rejected with a syntax error.
2. `if($f1 > 0., 10. * log10($f1) - 0.691, -120.)` — Max rejected with `expr: function if not found`.
3. Wiring a separate `[max 1e-12]` clamp box upstream — Max's object lookup in the user's version didn't resolve `[max]`, only `[maximum]` (list-max — wrong semantics) and `[maximum~]` (signal-rate).
4. `expr 10. * log10(max($f1, 1e-12)) - 0.691` (using `max()` as a function inside the expr) — Max rejected with `expr: function max not found`.

The successful pattern uses `[clip <floor> <ceiling>]` upstream: `[snapshot~] → [clip 1e-12 1e10] → [expr 10. * log10($f1) - 0.691]`. `[clip]` is a standard Max control-rate object (space-separated args, no comma-escape headaches), single inlet/outlet, exactly the floor-clamp semantics needed. `log10` is safe because `[clip]` guarantees the input is at least the floor; the output at the floor (`10·log10(1e-12) - 0.691 = -120.69`) is the sidecar's "effectively silent" sentinel.

**How to apply:**
1. For "log-of-X with silence sentinel" conversions in `[expr]`, clamp the input UPSTREAM with `[clip <floor> <ceiling>]`. Pick `<floor>` so `log10(<floor>) * <gain>` equals your silence sentinel:
   - Mean-square inputs (power) with `10·log10`: `[clip 1e-12 1e10]` → silence floor = -120 dB
   - Linear amplitude inputs (0–1) with `20·log10`: `[clip 1e-6 1.0]` → silence floor = -120 dB
   The ceiling is a far-from-real-audio safety net needed because `[clip]` requires two args; pick something well above any real-world input.
2. Keep the expr as plain arithmetic: `expr 10. * log10($f1) - 0.691`. No conditionals; no `max()` / `min()` calls inside.
3. Reliable `[expr]` functions in M4L: `abs, ceil, floor, int, float, exp, log, log10, fact, ln, pow, sqrt, rand, random` + the trig family (`sin, cos, tan, asin, acos, atan, atan2, sinh, cosh, tanh, asinh, acosh, atanh`). Anything else (`if`, `max`, `min`, `clip` as a function, ternary `? :`) — assume absent and reach for a separate Max object.
4. The conditional-via-separate-object catalog:
   - **`[clip <low> <high>]`** — range clamp (this learning's primary fix)
   - **`[gate]`** — conditional pass-through (used in F.9 for emit + has_track_id gates)
   - **`[sel <values>]`** — bang when input matches any listed value (used in F.11 for SR mismatch detection)
   - **`[<= N]` / `[>= N]`** — boolean comparison (outputs 0/1)
5. The `[clip]` upstream pattern doubles as a safety net for floating-point edge cases — `[average~]`'s output can rarely be slightly negative due to FP roundoff, which would make `log10` return NaN. `[clip <positive_floor> ...]` upstream catches that too.

**Earlier-learning correction:** an earlier version of this entry claimed `max(a, b)` was in `[expr]`'s function vocabulary. That was wrong — it was cited from standard Max docs without verifying against M4L's runtime. M4L's bundled `[expr]` does not have `max()`. The lesson: when documenting M4L objects, trust empirical results from the user's Max console over docs that claim object behavior. M4L's bundled runtime is a subset of standalone Max, and the subset boundaries aren't always documented.

## Splitting a monolith into a package: the facade contract is every name, private ones included

**When a module grows past ~3kLOC and you split it into a per-domain package, the re-export `__init__.py` is a contract: it must surface EVERY name the old module exposed — public AND private. Before moving anything, grep the whole tree for every name imported from the module (`from x import _helper`, `x.SOME_CONST`, `x._priv`); that list is the contract. The existing test suite is the correctness oracle — a behavior-preserving split adds zero tests and changes zero test files; if a test breaks it's a missing re-export or a circular import, never a reason to touch the test.**

The split-large-modules wave (mutations.py 4164 / pull.py 3401 / push.py 3166 → packages) stayed invisible to ~38 callers because almost all use `from hallucinote.db import mutations` then `mutations.create_clip(...)` (attribute access) — a package `__init__` that re-exports everything resolves those unchanged. The traps were the minority: private helpers imported by name from *other* modules (`handlers/analysis.py` does `from ...sync.push import _position_bar_to_beats`; a property test imports `pull._beats_to_position_bar`) and the one same-module **monkeypatch seam** — `plan_push_clips` called `plan_push_clip` as a module global that a test patches via `push.plan_push_clip`. A naive submodule split turns that into a direct import that the patch can't reach; preserve it with a function-local `from hallucinote.sync import push; push.plan_push_clip(...)` re-import (also breaks the load-time cycle).

**How to apply.** (1) Grep first, build the name contract, re-export the superset — don't trust "looks public." (2) Keep a leaf `_core` (shared helpers/types/transaction machinery) that imports from no sibling, so domain modules depend only downward — no cycles. (3) Watch for a function that's monkeypatched through the module object; route its internal calls through the package facade. (4) A split also surfaces latent coupling worth fixing in the same wave: this one exposed `pull` importing geometry helpers from `push` (inbound depending on outbound) plus a duplicated `_beats_per_bar` — both resolved by extracting a neutral `sync/geometry.py` leaf. Run the full suite after EACH module's split, not just at the end, so a break is bisected to one move.
