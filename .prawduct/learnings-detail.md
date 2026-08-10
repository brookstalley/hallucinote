# Learnings — Detail

Incident narratives and how-to-apply guidance for the rules in
[learnings.md](learnings.md). Headings mirror that file's, in the same order — every
heading here matches one there (a rule with no narrative simply has no entry here).
**Never delete an entry here** — this is the long-term memory the index points at.

## Threading a new param means making the test doubles faithful — not weakening tests

ENV-8K2R #5 added `ToolCall.read_timeout` (forwarded to `client.send`) and ENV-2T9K added `plan_push_song(perform_slowdown_factor=...)`. Two 1-arg doubles broke — `_make_send_fn`'s `send(req)` and a `plan_without_scenes(conn, *, song_id, session_id)` monkeypatch. Both were resolved by widening the double to the real contract (`send(req, *, read_timeout=None)` recording the value; `plan_without_scenes(..., **kwargs)` forwarding through), and the `send` double additionally grew the `arc_count` field the real handler returns so the new apply-layer cross-check (#4) was exercised. The executor's own forwarding was written to pass the new kwarg ONLY when set, so the *non*-perform path still hits 1-arg doubles untouched — pick the conditional at the production boundary, the faithful-signature widening at the test boundary.

**How to apply.** (1) After threading a param through a doubled seam, grep the test tree for the doubled callable's construction sites and update each signature to mirror the real one — don't special-case the production code to dodge old doubles. (2) If the double simulates a return shape (a fake handler response), add the new field the real producer now returns, or the consuming assertion never runs. (3) Widening a double to accept+record a new kwarg lets you ALSO assert it was forwarded — turn the break into coverage. (4) A faithful double tracks the real signature; a `getattr(args, "x", default)` fallback or a try/except-TypeError around the call is the smell that you weakened the seam instead.

## A collision/ordering guarantee needs a test per visit-order, and a single pass can't encode "this class always wins"

ENV-8K2R #3's first cut moved the duplicate-target claim before the fingerprint gate and "seeded skipped-unchanged targets too" — which reads like it protects the already-recorded lane, and the one test (skipped arc first) passed. But a CHANGED arc earlier in envelope order claimed the target first and recorded over the correct lane (alerted, but clobbered). The cumulative Critic caught it; the test's own docstring claimed "regardless of visit order" while only covering one order. Fix: a two-pass — Pass A claims every skipped lane, Pass B queues changed arcs against the now-complete claim set — plus the changed-first-order test.

**How to apply.** (1) Write the order-independence test FIRST and in both directions — if the guarantee is "skipped wins," test skipped-first AND changed-first; a passing favorable-order test plus a confident docstring is exactly how the gap hides. (2) "Claim as you iterate" can't express "this class always wins" across a heterogeneous list — split into classify → claim-the-privileged-class → process-the-rest. (3) Beware a test docstring that asserts a property ("regardless of order") the test body doesn't exercise; that mismatch is a finding waiting for the Critic.

## A "trivial" fix can key off a value another layer's policy depends on — trace the consumer first

**How to apply.** (1) When a fix mutates a returned/recorded field, grep for that field name across consumers before taking the literal change — a value that looks like a local counter may be a cross-layer signal. (2) "Do exactly what the backlog says" is not a license to skip the blast-radius check the backlog author may not have run. (3) The conditional that preserves the other layer's contract usually also reads as the more correct behavior (here: a sub-tick arc the perform path can't faithfully record SHOULD re-perform, not record a lone endpoint and mark itself done).

## Install/setup skills do filesystem mutations in tested Python, never hand-authored shell

`/ableton-mcp-install` hand-authored its Remote Script copy as `rsync --exclude=...` interpolated into a shell line. `install_paths.rsync_exclude_args()` correctly produced `--exclude=*.pyc`, but pasted unquoted into a zsh command the `*.pyc` glob-expanded with no match → zsh aborted the whole line *after* the preceding `rm -rf` + stub-write had run, leaving a half-installed Control Surface (stub present, vendored package missing) that Live would fail to load. Three platform variants (rsync / robocopy / PowerShell) were kept in sync only by a brittle SKILL.md string-drift test. The fix moved all mutation into `install_ops.py` / `mcp_config.py` (atomic stage → verify → swap, one cross-platform code path), exposed as CLI subcommands; the skill became orchestration-only.

**How to apply.** (1) The split: Python *mutates* (testable, atomic, cross-platform via `shutil`/`os.replace` — not `subprocess` to a copy tool); the skill *orchestrates* (preflight → confirm → invoke CLI → render). (2) Atomic = stage into a sibling temp dir, VERIFY it, then swap with rollback — a failure leaves the live target complete-old or complete-new, never half. (3) A SKILL.md "drift test" that asserts the doc contains the right shell *string* is a smell — assert the *behavior* in a unit test, and let the consistency test only check "the skill calls the CLI, no mutation shell in command blocks." (4) Exclude/anchoring is a value-correctness concern: reproduce it in code with a predicate, don't push it across the shell boundary where quoting/globbing can silently change it.

## A permission to collaborate must restate precedence in the same breath

C3 (onboarding teaching norms) added a "pedagogical carve-out" to CLAUDE.md legitimizing collaborative musical proposals at creative forks. The scenario harness immediately caught the leak: the `dev` brief (a fully-directed "build the skeleton, I'll take it from there") FAILED — the agent forked the already-specified drop structure into an A/B and withheld the build, reading the new carve-out as blanket license to propose. The fix wasn't to remove the carve-out but to bound it: "Precedence dominates this carve-out — if they directed it or signalled they'll handle the rest, execute and hand back." `dev` then passed; `theo` (the carve-out's intended beneficiary) stayed passing.

**How to apply.** (1) Any edit that widens "when to stop / ask / propose" pairs with the bounding case in the same paragraph — permissions and their limits travel together, or the permission overgeneralizes. (2) Regression-test the *opposite* persona: the change is meant to help the under-articulated/novice case, so verify it didn't tax the directed/expert case. The behavioral harness's value is exactly this — the friction was invisible to inspection and obvious the moment the directed persona was run against the edited norm. (3) "Drive end-to-end" and "collaborate by default" both need the precedence carve-out, for the same reason: neither means "decide silently," but neither means "stop at every fork" either.

## Pattern sweeps are tree-wide or they don't count

Refactors that touch a wide pattern (e.g. "rename internal class name → display name in every `kind=` site") are easy to get 80% right and hard to finish. Stale references survive in agent-facing surfaces (skill markdown, action descriptions, conventions guides, snapshot examples) that aren't exercised by the test suite, then ship as contract drift the next user sees first.

Arc 4 / D4 hit this hard. The cumulative Critic round 1 caught the BLOCKING (`actions/device.py` recommending `kind='Compressor2'` while the new test pinned exactly that as a FAILURE). Round 2 then caught NEW BLOCKING — round 1's response had only updated the cumulative-Critic's named files but missed sibling surfaces with the same pre-D4 advice (`.claude/skills/return-new/SKILL.md`, `track-new-with-instrument/SKILL.md` Step 2 self-contradicting its own Notes). Round 3 added a tree-wide grep across `.claude/`, `docs/`, and `hallucinote_mcp/.../resources/` as a structural completeness check.

**How to apply.** For any change-the-convention refactor:
1. Before declaring done, run a tree-wide grep for the OLD pattern (`grep -rn '<old>' .claude/ docs/ src/`). Grep for EVERY phrasing of the old teaching, not one token — ENV-7G4K chunk 04 swept `skills/` but only for "envelope"/"sub-bus" patterns and missed song-new's "Master automation isn't supported" (caught as a cumulative-Critic BLOCKING). A capability flip ("can't"→"can") needs the capability named every way the docs ever said it.
2. Each hit must be either (a) updated to new convention, (b) intentional historical/archaeology reference with explicit "no longer X" framing, or (c) backlogged with rationale.
3. Pin the NEW convention with a regression test that names what now FAILS (`test_load_internal_class_name_fails_under_new_convention`). The test makes the deletion semantic, not accidental — but only the grep catches surfaces the test doesn't exercise.

The agent-facing surfaces (action descriptions, skill markdown, conventions guides) are read at every session start. Stale recommendations there are higher-impact than test-fixture drift, because they shape what the next agent tries first.

## Inverting a black-box formatter: validate a monotonic proxy, don't enumerate formats

`DeviceParameter` exposes `str_for_value(raw)` but no inverse, so `set_parameter`'s `value_display` ("-18 dB", "3:1") inverts it by bisecting on the number parsed from the display. The first cut parsed a leading number and then bolted on a guard per format real Live revealed — `-inf dB` (Threshold min), `inf : 1` (Ratio max), `Hz`→`kHz` (frequency). Each live probe surfaced another → whack-a-mole on the comparison layer.

Root cause: bisection only needs the parsed number to be a faithful *monotonic* proxy for the raw value. The failures were all "the proxy isn't faithful here," not distinct problems. The fix: sample `str_for_value` across `[min,max]`, verify the leading number is monotonic (varies + no reversal), bisect only then, refuse otherwise. That one check replaced the constant-leading-number and unit-scaling guards AND auto-handles unseen formats (ms→s, etc.) — a non-monotonic proxy is the general signal that display-units can't address a parameter.

**How to apply.** Inverting any black-box formatter: (1) parse a proxy; (2) validate the property the algorithm needs (here monotonicity) by sampling the domain; (3) act only when valid, refuse with a teaching error otherwise. A new branch per observed bad input is the smell that you're guarding symptoms instead of validating the invariant. And calibrate against real instances: all three traps came from real-Live probes, not the synthetic corpus — the sibling rule "Unit fakes that mirror an *assumed* Live API give false confidence" applies directly.

## When a doc or duplicated contract IS the deliverable, lock it with a drift/parity test

The "Pattern sweeps are tree-wide" learning names the disease (agent-facing surfaces aren't exercised by tests, so drift ships). This is the structural cure for the case where the surface is itself the thing being built. Two instances in the bulk-note-authoring work: B2's `/compose-part` "Authoring API" doc index is the discoverable surface, so a bidirectional test asserts every documented `module.func` is importable AND every public generator fn is documented (`test_authoring_api_surface.py`); B4's inline-notes warning is emitted by two MCP actions, so a parity lock asserts both emit the identical text at the same threshold (`test_actions_clip.py`). Both turn "I hope this stays in sync" into a gate.

**How to apply.** (1) If you wrote a doc that catalogs a code surface, write a test that parses the doc and resolves each reference — and fails when the code grows a member the doc doesn't list (the reverse direction catches *undiscoverable* additions, which a one-directional test misses). (2) If a constant/message/shape is duplicated across N call sites, route them through one shared helper and lock parity with a test that compares all N outputs — and leave a comment at the helper telling the next author "new call site? route it here and add it to the parity test." (3) Prefer the threshold/source-of-truth as a single named constant the test imports, so the doc can reference it qualitatively (~32) without brittle numeric coupling.

## DSP with a detection front-end: calibrate against real cases, don't assert from intuition

C7 (timing analyzer) almost shipped two bugs that only a calibration pass exposed. (1) The synthetic `kick_onset` fixture — picked because it already existed — is a *terrible* onset target: its slow low-frequency attack makes librosa detect it 0.13–0.49 beat late and multi-trigger, so on-grid material read as wildly off-grid. (2) Swing read 1.35 for a triplet feel that should be ~2.0, because spurious double-onsets polluted the mean off-beat phase. Both were invisible to intuition and to a "looks reasonable" fixture; both were obvious the moment real grooves (a user's "can we be Phish / Dead / Marley?") were run through the real module and the numbers printed. Fixes followed directly: a sharp `click` fixture (accurate onset), finer hop, onset dedup, MEDIAN (not mean) swing phase, tightness-based (not grid-aligned) confidence.

**How to apply.** (1) Build a tiny calibration script that runs representative inputs through the real analyzer and prints the metrics; eyeball them against what the music *is* before locking assertions. (2) Choose fixtures for *detection accuracy*, not convenience — a synthetic transient with an instant attack tests the analyzer's math; the real-world detection-accuracy limit (slow-attack instruments) becomes a documented caveat, not silent fixture bias. (3) Prefer robust statistics (median over mean) and robustness-to-constant-offset designs (measure tightness/relative timing, not absolute) when the front-end has systematic error. (4) Treat a user's "can it do X?" as a design stress-test — answer it by running X, not by reasoning about X.

## A staleness/version signature must be content-derived, never hand-bumped

The masking-arc backlog item "surface the loaded `analyzer_signature` so a stale MCP server is obvious" pointed at an existing field — but reading the code showed that field is a hardcoded capture-device label (`"hallucinote-analyzer-v1"` in `render.py`) that never moves when analysis-pipeline code changes. It structurally cannot detect staleness. The cheap fix (a hand-bumped `__version__`) has the identical defect. The correct fix hashes the `hallucinote/audio/` package source, frozen at import (= the code the subprocess actually loaded) and compared against a per-call disk recompute (`audio/codeversion.py`). The freeze-at-import-vs-recompute split is the load-bearing part: hashing only on-disk source would report "fresh" while the process runs old code. Aligns with "prefer structural fixes over patches."

**How to apply.** (1) If the signal is "is the running code current?", capture the signature when the code loads (module-import-time constant) and compare to a live recompute — two reads, not one. (2) Hash content, never a manual label; a manual label re-creates the forget-to-update gap. (3) Verify the import-freeze claim in a *live process* (edit real source, watch the flag flip, revert), not just with monkeypatched functions — patching hides whether the freeze actually captures loaded vs on-disk bytes. (4) Don't conflate provenance concepts: "which device captured this" (capture signature) and "which code interpreted it" (analysis-code signature) are different surfaces — name them apart.

## DB-UUID → capture-surface-ID lifts must key by surface ID, and be tested with distinct IDs

The audio captures are keyed by structurally-stable surface IDs (`track:N`/`return:N`); the DB is keyed by UUID. `analyze_mix` and `apply_stem_gains` look up by the capture key. C3's `_collect_stem_gains` keyed the gains dict by `row['id']` (UUID), so `apply_stem_gains` never matched → the F1 level correction was a **silent no-op on every real song**, and CI stayed green because the unit tests used self-consistent IDs on both sides and the integration test relied on the empty-map no-op path. The cumulative Critic caught it; the sibling `_collect_declared_sends` already did the lift correctly via `track_id_for_surface`. The regression test seeds UUIDs ≠ `track_index` and asserts `track:N` keys — it would have failed against the old keying.

**How to apply.** (1) Any `_collect_*` helper feeding the capture/analysis boundary lifts via `track_id_for_surface(kind, index)`. (2) Its test uses UUIDs distinct from indices so a no-op keying can't pass. (3) A "validation" that runs the real pipeline but prints the *gains dict* (UUID-keyed) isn't proof the gains *applied* — assert the corrected output differs from the uncorrected one.

## Sync planner discipline

The "canonical name + alias" pattern in `sync/mcp_names.py` is for tools that don't yet exist or need emulation; tools called directly (no alias) trust the planner to match the real signature. There's no schema check, no aliased emulator, no runtime mismatch — the call just fails at push time. Chunk 2 shipped a `plan_push_cue_points` that emitted `{time, name}` while real MCP `create_cue_point` takes `(bar: int 1-based, beat: float 0-based, name: str)`; the Critic caught it. Inspect the tool's MCP schema (via `ToolSearch` for `mcp__hallucinote-mcp__*`) when writing a planner for a directly-callable tool, and add a one-line signature note in `mcp_names.py` if absent.

## Round-trip pull's default-detection rests on the external system's default — probe it or narrow scope

This is "verify the premise before mirroring it" (the RTE-1K9T chunk-04 D7 trap) applied to the INVERSE direction. RTE-1K9T chunk 05 pulls track routing back into the DB. Output routing has a closed, live-probed default ("Main" → `master`), so `NULL ≡ master` is safe — a default-routed track is a clean no-op. Input routing does NOT: Live's non-track input default is open and hardware-bound (a MIDI track likely defaults to "All Ins", an audio track to an interface channel), and it was never live-probed. A `NULL ≡ no_input` rule built on that guess would churn every track's input the first time anyone pulls. The Critic flagged it as unverified. The fix wasn't to flag-and-hope the pending Live smoke would catch it — it was to make the premise moot: V1 pull persists ONLY a track→track input (the one input case that is never a default and needs no default constant), and the fixed-kind pull is gated behind a live-probe enqueued in operator-verification. Narrowing to the default-independent case is cheaper and more honest than shipping an unprobed default when you can't probe it in-session.

## A new authorable event kind must be registered in the tombstone-protection map

The state-converger tombstones any build-owned row build.py didn't touch this run, UNLESS the row's *latest* event is from a non-build actor (that's what protects pulled / LLM-authored edits). `_latest_actor_for` only considers the event kinds listed per row-kind, so an unlisted kind is invisible to the protection: the lookup falls back to the latest *listed* event (e.g. `track_created`, actor=`build`) and greenlights the delete. RTE-1K9T shipped `track_routing_set` (chunk 03) but didn't add it to the `track` tuple alongside `track_mixer_set`; a user who rerouted a build-owned track in Live and pulled would have lost the track + the reroute on the next build. The final-mode Critic caught it — a per-chunk review of the routing mutator can't see the cross-cutting build.py interaction. Rule: a new authorable event kind is not "done" at its mutator + planner; it has cross-cutting consumers (tombstone protection, and any planner's skip/include lists), and each must be updated and tested (a protection test: build-owns row → sync edit → re-build drops it → row survives).

## Detection that replaces a user question must enumerate every state

Conflating two states the consumer needs to distinguish is silently broken: the wrong branch fires, or no branch fires, with no error. The fix is shape, not effort: return a tagged value (tuple, dataclass, enum) so the consumer has to handle each state explicitly.

The install-skill hardening (PR #15) hit this twice in two Critic rounds:

- `hallucinote_mcp_command()` initially returned `Path | None`, conflating "found on PATH" with "found via venv fallback." The SKILL.md's tri-state branch — bare command vs absolute path in `.mcp.json` — was unreachable; venv-only installs would silently write a bare name that Claude Code couldn't launch. Fix: return `(path, on_path)` so the consumer must handle each case explicitly.
- `existing_mcp_config_files()` initially scanned only top-level `mcpServers`, missing `claude mcp add`'s default `projects.<cwd>.mcpServers` scope. A real, common registration shape was invisible to the uninstaller. Fix: scan all three scopes and tag each hit with a `json_pointer` so the consumer knows which scope to edit.

**Test discipline:** for each detection helper, write at least one test that distinguishes the conflated states (not just "found" vs "not found"). If you can't articulate the second state in a test, you haven't enumerated yet.

## Never use `is` for Live API object identity

Fixes for the post-create resolution are deterministic-from-semantics: `len(song.X)` after an append, `insert_at + 1` for an insert, or a stable value match (e.g., `start_time` for arrangement clips, name + position for cues). Hit five times in one session (track / scene / return / clip-arrangement create handlers all had this shape; a sixth had it in cue_create's post-toggle scan). Each fix shipped with a regression test using a `_ReWrappingFake*` pattern that returns fresh Python wrappers on every `song.X` access — those tests pass with the fix and fail convincingly without it. **Make the wrapper-recreating fake a shared helper** in `hallucinote_mcp.testing` so future handlers can write the same regression in one line.

The fakes that DON'T simulate wrapper recreation still pass when `is` is used — that's why the bug existed for so long. Treat any fake that uses a plain `list.append(obj)` for a Live-collection-shaped attribute as suspect, because real Live's collection accessor returns a fresh wrapper sequence.

## Live API: trust the side effect, not the getter readback

`Song.current_song_time` (and likely other transport-coupled properties) is an audio-thread-mediated value. The setter completes synchronously on the main thread but the audio thread picks up the new value on the next audio buffer (~5-10ms). Within the same main-thread callback, the getter still returns the audio thread's last-flushed value — which is the OLD position. `Song.set_or_delete_cue()` reads the same audio-thread state, so it fires against the OLD position too unless wall-clock time passes between the write and the toggle.

**The fix that works**: `time.sleep(0.2)` between the write and the dependent operation. Main thread blocks; audio thread runs (separate OS thread, real-time priority, no GIL). After the sleep, the audio thread has the new value. Then trust the write — don't verify via the getter — and inspect the actual side effect (the cue list) to confirm success.

**What doesn't work**: `schedule_message(0, fn)` chains. Multiple deferred callbacks fire back-to-back within a single engine tick; no wall-clock time passes. The deferred-completion infrastructure (`DeferredCompletion`, `LiveContext.schedule_after_tick`) is still a useful primitive for other async patterns, but it doesn't solve cross-thread real-time settles.

**Diagnostic discipline**: when a handler writes a transport-coupled property, always include `target`, `last_observed`, and `prior` in any error response. The "each call observes the previous call's target" race pattern is visible in 30 seconds with these fields, invisible without them.

## Unit fakes that mirror an *assumed* Live API give false confidence

The 2026-05-17 push session shipped five handler fixes (the B-1/B-2/B-10/B-11/B-12 bug bucket; original triage doc deleted in the v0.9.0 hygiene sweep — `git log -- .prawduct/artifacts/bug-triage.md` recovers it) that each had passing unit tests. The fakes mirrored what we *thought* Live exposed: collection appends preserved identity, `set_or_delete_cue` accepted a time argument, `Track.load_device` existed, etc. Real Live 12.4 differs on every count. The unit suite never saw the divergence.

**Required for any handler that wraps a Live API operation**: at least one of (a) a fake that simulates the *quirk* (wrapper recreation, no-arg signatures, missing methods), or (b) an integration smoke test run against a real Live instance. Smoke tests cost ~30s wall-clock per release; they catch a class of bugs the unit suite literally cannot see.

Track potential smoke-test coverage in a `tests/integration/test_live_smoke.py` file. Don't gate on it for every PR (too slow); gate on it for "ready to release" / pre-merge of large refactors.

## A shipped "can't" is a dated snapshot — re-probe a challenged capability verdict before defending it

DEV-2M9K shipped "master device loading is impossible (`song.view.selected_track = master` silently refuses; master devices forever-manual)" and gated four surfaces (`handlers/device.py`, `analyzer/setup.py`, `render`, `sync/push/devices.py`) plus a hand-built workaround (TPL-2D8K). When the user pushed back, I defended it twice from the artifact (even claiming Push couldn't do it either). A ~5-minute live re-probe on **Live 12.4.2** refuted it end-to-end: `selected_track = master` STICKS (`name`→"Main", old≠new object — NOT the claimed silent no-op), `browser.load_item` lands a device on the master chain, `delete_device` removes it. Root cause: treated a shipped artifact's empirical platform claim as durable truth across versions.

**How to apply.** (1) A recorded capability verdict ("can't / not supported / impossible") is a *dated snapshot of a specific build*, not a law — when it's challenged and the platform is live, re-probe (cost: minutes) before citing the artifact. (2) Capability claims in artifacts MUST record the platform build they were verified against (e.g. "refused on Live 12.4.0"); a build-less verdict is untrustable on a later build. (3) The asymmetry favors the probe — minutes to confirm vs. a shipped false premise spanning many surfaces — so bias toward cheap empirical re-verification over artifact-citation for version-sensitive platform behavior. (4) On a confirmed flip, the sibling rules fire: sweep every doc phrasing of the old "can't" (see "Pattern sweeps are tree-wide"), audit the WHY/intent layer (see "When a capability ships, audit the planning + intent artifacts"), and re-triage workarounds built on the false premise. Reinforces Honest Confidence + Verify-don't-guess + Root Cause Discipline.

## Link, don't summarize

Restating creates a second source of truth that drifts independently. J-5 caught this concretely: `project-state.yaml` copied "hypothesis (parked in conftest.py, commented)" from `project-preferences.md` line 26 — but the preferences doc was itself already stale relative to `tests/conftest.py`, which had enabled Hypothesis in Wave M-4. One stale phrase → two stale artifacts; each maintenance pass that re-summarizes can compound the drift instead of resolving it. The same shape appeared in J-2 (`project-preferences.md` Test-location block contradicted its own Dev-commands block 18 lines down) and J-3 (the README rewrite verified each claim against `.mcp.json` / `pyproject.toml` / actual file paths rather than trusting the prior README). **When writing or auditing an artifact, treat any prose summary as suspicious if the underlying fact lives elsewhere.** Prefer "see `X` for current values" over restatement. Restate only invariants that can't be derived, and only at the canonical source-of-truth file. The corollary for audit chunks: re-read code, never trust prior summarizations of code.

## Human-authoring boundaries split the chunk

Chunk 1 of the audio-analysis MVP hit this in shape: the "Done when" list mixed Claude-doable items (the PDC alignment test, the throwaway capture harness) with human-only items (the `.amxd` itself, the in-Live GO/NO-GO test). Build-governance treats a chunk as a single atomic unit ending in Critic — but a chunk that straddles a binary-authoring boundary cannot Critic at the natural Python-code-complete moment because the verification math has nothing to verify *against* yet. Inverting the order (write the spec first as an explicit handoff artifact, treat the binary as a dependency the human supplies, run Critic only after in-tool verification produces real captures) keeps the discipline intact without forcing a half-context review.

**How to apply.** When planning or starting a chunk:
1. Audit the "Done when" list for boundaries. Any deliverable that requires Max, Logic, a DAW patch editor, an image editor, a visual schema builder, or "user clicks something in a proprietary GUI" is a boundary.
2. If a boundary exists, split mentally into "spec + driver + verification" (Claude) and "binary/visual asset" (human). The spec is the artifact future Claude (and the human authoring the binary) reads — it must be precise enough that the human can author against it without coming back to ask.
3. Update the chunk's "Done when" to make the split explicit. Critic runs after the verification pass on real human-authored output, not on the spec.
4. Don't commit the spec-and-driver pass alone — leave the work uncommitted so the chunk commit lands atomically when verification passes. (Or commit the pass with an explicit `chunk: 1 of 2` marker so the next session knows the binary handoff is mid-flight.)

The failure mode this prevents: shipping a "Chunk 1 complete" claim that's actually 60% done because the binary authoring slipped to "later" and the verification was waved through.

## Live parameters are float / int / enum only — strings need an out-of-band channel

**Why:** the M4L parameter mapping layer (the thing that shows knobs in Live's device view and lets Remote Scripts write them) is fundamentally numeric. Strings can be displayed in a `live.text` UI object but cannot be the value of a Live parameter. The spec for `HallucinoteAnalyzer.amxd` originally assumed `output_path` could be a string Live parameter; it can't.

**How to apply:**
1. Any string config (file paths, IDs, signatures) the Python side wants to push to the device must go through an out-of-band channel — typically OSC via `udpreceive` + `OSC-route` (CNMAT package), with the OSC port itself an int Live parameter.
2. When sketching a new M4L device spec, audit the parameter table: every row must be coercible to float/int/enum. Anything string-typed must be re-homed onto an OSC inbound or onto the device's filename / class metadata.
3. When updating the spec mid-authoring, also amend any Python harness that assumed the old shape — the harness's `set_parameter(name='Output Path', ...)` becomes an OSC client + `set_parameter(name='OSC Port', ...)`.

Confirmed during Chunk 1 of the audio-analysis MVP: the `live.text` inspector's Type dropdown only offers float / int / enum, which surfaced the constraint. Spec was amended, OSC inbound chain was specified, and Chunk 2's reserved list was updated (signature and track_id have the same string constraint and were re-routed onto the same inbound channel).

## Live's Remote Script API surfaces parameters by short name, not long name

**Why:** the spec for `HallucinoteAnalyzer.amxd` originally specified long name "Record Arm" as the addressing key, and the Chunk 1 harness wrote `parameter_name="Record Arm"`. The authored `.amxd` set both `parameter_longname: "Record Arm"` and `parameter_shortname: "Arm"`. `ableton_device(action='get_parameters', ...)` returned `{name: "Arm", ...}` — the short name. A `set_parameter` call against "Record Arm" raises an unknown-parameter error; against "Arm" succeeds. Same for "OSC Port" / "Port".

**How to apply:**
1. When specifying an M4L device's parameter table, declare both names but mark the **short name** as the addressing key. The long name is documentation; the short name is the contract.
2. Always verify by calling `get_parameters` against a loaded instance — the returned `name` field is the address future writes will use.
3. If both names are the same (no `parameter_shortname` set in the patch JSON), the long name IS the short name; no ambiguity. The gotcha only bites when authoring picks distinct names for UI compactness.

Confirmed Chunk 1 in-Live verification, audio-analysis MVP: only after probing the live device did the address mismatch surface. The harness and spec were both updated; this rule applies to Chunk 2's `ensure_analyzers_loaded` and any future M4L device the project authors.

## sfrecord~ control API: bare integers (1 / 0), not `record N`

**Why:** the [Max sfrecord~ docs](https://docs.cycling74.com/max8/refpages/sfrecord~) say "A non-zero value begins recording, and 0 stops recording and closes the file." The number-to-left-inlet API is the documented control surface. The `record <duration>` message is for timed recordings only. Confirmed via Max Console output during Chunk 1 of the audio-analysis MVP — both `stop` and `close` produced explicit "sfrecord~: doesn't understand" prints, and `record 0` failed to stop a recording that kept growing for 127 s past the patch's "stop" command. Switching to bare `0` immediately produced clean, properly-finalized WAVs.

**How to apply:**
1. Wire `live.toggle` (or whatever produces the 0/1 trigger) so the bare integer reaches `sfrecord~`'s left inlet. On rising edge, sequence `open <path>` BEFORE the `1` via `[t b b]` right-then-left ordering (right outlet fires first in Max).
2. On falling edge, just send `0` — no separate close needed. The file is finalized atomically.
3. After a `0`, sfrecord~ requires a fresh `open <path>` before the next `1`. If you need to record twice without reloading the patch, send a new `open` each time.
4. Never use `record 1` to mean "start". It means "record for 1 millisecond." If you see a 44-frame capture at 44.1 kHz (≈ 1 ms), this is the bug.

This rule applies to any future Max for Live audio-effect device the project authors. The trap is high-leverage because `record 1`/`record 0` *looks* like a sensible API by analogy with bool toggles, and the docs bury the bare-integer API in prose rather than highlighting it as the canonical control surface.

## M4L Int parameter range capped at 256 — use Float + Unit Style Int

**Why:** Chunk 2 of the audio-analysis MVP needed `Port` and `EmitPort` ranges of 11000-11400 to accommodate the deterministic per-surface port allocation (100 audio tracks + 100 returns + master + emit). Setting the range with `Type = Int` clamped Max's Inspector to 11000-11255 silently, breaking the allocation. The Max docs explicitly call out Float+UnitStyle-Int as the documented convention for Int-displayed values exceeding 256 — this is not a workaround, it's the supported path.

**How to apply:**
1. For any `live.numbox` whose `max - min` will exceed 255, set Type = Float in the Inspector BEFORE setting Range. (Setting Range first under Type = Int clamps silently.)
2. Set Unit Style = Int so the UI still renders whole numbers.
3. The Remote Script's `set_parameter(value_type='continuous', value='11042.0')` writes through normally — Float-typed parameters accept float values via the existing continuous path. No client-side change needed.
4. The patch's downstream handling should `[i]`-coerce the `live.numbox` outlet wherever an int is required (sample counts, port numbers as `[udpreceive]` arg, etc.).
5. Symptom that triggers this rule: setting a `live.numbox` max to a value that's `> min + 255` and watching the Inspector snap it back to `min + 255` instead. Don't waste time looking for a "hidden" cap setting — switch Type to Float.

This rule applies to any future Max for Live device the project authors with Int-displayed values exceeding 256 distinct steps (sample counts, port numbers, MIDI buffer sizes, etc.).

## M4L device source belongs in `Presets/Audio Effects/Max Audio Effect/`, not Remote Scripts

**Why:** Live's User Library indexer is recursive — every `.amxd` anywhere under the User Library tree shows up in the browser's "Max Audio Effect" section. There's no "preferred location" priority; identical filenames in different directories appear as separate-but-identical entries. The Remote Script copy of the package (via the install skill's rsync/robocopy step) needs to EXCLUDE the `m4l/` source directory; otherwise the device file ends up duplicated. Confirmed audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26): user saw two `HallucinoteAnalyzer` entries in browser, only one (the Remote Scripts copy) was stale, and the running instance was the stale one — Max edits to the Presets copy were invisible to the device for hours of debugging until the user noticed the duplicate.

**How to apply:**
1. Install skill's Remote Script copy step must EXCLUDE the `m4l/` source subdirectory (along with `cli/`, `tests/`, `__pycache__/`). See `install_paths.py:REMOTE_SCRIPT_EXCLUDE_DIRS_ANY`.
2. Install skill's Step 3d (analyzer copy) targets ONLY `Presets/Audio Effects/Max Audio Effect/`. There's no second target location.
3. Uninstall skill should remove BOTH the Remote Script Python files AND the `Presets/.../HallucinoteAnalyzer.amxd`. (Currently W12-D-scoped — the uninstall skill removes Remote Scripts; analyzer cleanup is a follow-up.)
4. When debugging "my edits aren't showing up," the FIRST check is: are there multiple `.amxd` files with the same name under `<User Library>`? `find ~/Music/Ableton/"User Library" -name HallucinoteAnalyzer.amxd` surfaces them quickly. The running device is whichever path Live's browser entry points at; the user's edits go to whichever path Max's editor has open.

## M4L `[value]` doesn't emit on write — use `[i]` / `[f]` for cold-inlet storage

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B in-Live verification (2026-05-26), the patch's `[loadbang] → [0] → [value has_path] → [print has_path_now]` chain didn't fire `has_path_now: 0` at load. We bypassed `[value has_path]` with a direct `[loadmess 0] → [print has_path_now]` connection and the print fired. Putting `[value has_path]` back in the chain stopped the print again. Swapping `[value]` for `[i]` fixed it. Same fix applied to `v_arm`, `v_start_at_beat`, `v_stop_at_beat`, and `prev_beat` (the last using `[f]` since prev_beat is a float). Without the fix, expr cold inlets latched their default values (0) and the crossing-detection never returned true.

**How to apply:**
1. When wiring a storage box whose outlet must trigger downstream on receive, prefer `[i]` / `[f]` over `[value]`.
2. ~~Reserve `[value <name>]` for read-only public state that other parts of the patcher will explicitly bang for retrieval~~ — see next learning. `[value]` is unsafe even with explicit bang-to-emit when multiple device instances coexist.
3. If you inherit a patch with `[value]` boxes in trigger chains, swap them as a one-line fix.

## M4L `[value <name>]` is GLOBAL-by-name across all device instances — never use for per-instance state

**Why:** audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-27) — with N analyzer instances loaded across tracks + returns + master, `ableton_render(action='render')` produced only ONE WAV per render, always for whichever analyzer received its `/path` LAST. The patch design: `OSC-route /path → value hallucinote_path` for storage; transport-cross detector → `[t b b] → bang value → emits stored path → prepend open → sfrecord~`. Worked in single-instance verification (G.5, Chunk 1). Failed silently for multi-instance because all N `[value hallucinote_path]` boxes shared one global; the LAST `/path` write overwrote everyone's stored path; at cross-detect time, all N sfrecord~ instances raced to open the SAME file path (only one wins the file-open race). Deterministic and order-dependent: OSC to track 1 then track 2 → only track 2 records; reverse order → only track 1 records. Same bug present in `[value track_id_retained]` (used for `/signature` reply target host:port).

**How to apply:**
1. Audit `[value <name>]` boxes in any patch intended to load as multiple instances in the same Live set. Replace per-instance ones with direct wiring (path → consumer at receipt time) or `[zl reg]` / `[message]`.
2. Specifically for the Hallucinote analyzer: wire `OSC-route /path` outlet 0 → `prepend open` inlet 0 directly so each instance's sfrecord~ opens its own file immediately on `/path` arrival. Remove the `[t b b]` outlet → `[value]` bang patchline (no longer needed — sfrecord~ already has the per-instance file handle).
3. Pre-MVP check: any new `[value <name>]` box on a multi-instance device should be flagged in code review with "is this state PER-INSTANCE or GLOBAL?" If per-instance, do not use `[value]`.
4. Other M4L per-patcher storage options worth knowing: `[zl reg]` (per-instance list storage, banged for emit), `[message]` (set with `set <value>`, banged to emit), `[pattr <name> @bindto ...]` (per-patcher attribute storage with optional Live param binding).

## M4L `live.toggle` outlet emits int (0/1) directly — no `[== on]` shim needed

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26), early debugging surfaced "off: bad number" errors in the Max console — which looked like live.toggle was emitting the symbol "off" to a numeric destination. We added `[== on]` to convert symbols to ints, and the chain APPEARED to work. But on closer inspection (a `[print TOGGLE_RAW]` placed directly on live.toggle's outlet showed `TOGGLE_RAW: 0`), live.toggle was already emitting int 0. `[== on]` then compared int 0 to symbol arg `on` (coerced to int 0), returned 1 — inverted. With `[== on]` removed, the chain worked correctly. The "off: bad number" errors were a separate event (perhaps a parameter-init flow we never fully traced) and didn't actually flow through the downstream chain.

**How to apply:**
1. Wire `[live.toggle]` outlet directly to int-consuming downstream (`[i]`, `[change]`, `[sel 0 1]`, `[expr ... $i ...]`).
2. If you see "off: bad number" or similar console errors during M4L load, don't assume they're from the chain you care about. Probe with a `[print TOGGLE_RAW]` directly on the live.toggle outlet to see what's actually being emitted.
3. The `[== on]` pattern shows up in some older Max for Live tutorials. Treat those tutorials as potentially stale.

## M4L `live.observer` needs runtime `property <name>` message; outputs bare value

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

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B end-to-end verification (2026-05-27), `ableton_render(ensure_loaded)` hung Live's main thread when called on a session with 5 tracks + 3 returns + master. The trace showed `_find_analyzer_index` returning None on EVERY pre-existing analyzer, so `ensure_loaded` was triggering a fresh load on every surface every call — including surfaces that already had one. Live MCP probe of a loaded analyzer revealed the actual attribute shape: `{"name": "HallucinoteAnalyzer", "class_name": "MxDeviceAudioEffect", "class_display_name": "Max Audio Effect"}` — confirming `class_display_name` is the device class ("Max Audio Effect"), not the .amxd identity. The earlier docstring claim ("Live surfaces the .amxd filename as `class_display_name`") was wrong, and the test fakes mirrored the buggy claim — so all 11 analyzer-setup tests passed while production was permanently broken against real Live.

**How to apply:**
1. For M4L device identity comparisons (detection, deduplication, "is this analyzer mine?"), compare BOTH `device.class_display_name == "Max Audio Effect"` (proves M4L audio-effect class) AND `device.name == "<filename>"` (proves the specific .amxd). Either alone is insufficient: just-class-display-name matches every M4L; just-name could match a user-renamed device of any class.
2. The combined check has one edge: if a user renames the device in their session, `name` no longer matches and detection breaks. For truly canonical identity, use the OSC `/signature/query` round-trip the analyzer spec defines — heavier but rename-proof. Pick the simpler `class+name` check unless you have evidence renames are common.
3. **Test fakes MUST mirror real Live's attribute shape, not the production code's (possibly buggy) assumptions.** When constructing a fake M4L device, set `class_display_name="Max Audio Effect"` and `name=<filename>` — NOT `class_display_name=<filename>`. A fake that defaults `name = class_display_name` (the easy mistake) will pass tests that fail against real Live.
4. The same trap structure (production code asserting one attribute shape; test fake conforming to the buggy assertion; both pass tests; real Live disagrees) is a general M4L authoring pitfall — when adopting any new Live device API surface, probe a real instance via `ableton_device(action='info', ...)` BEFORE writing the production check, and seed the test fake from the probe output.

## M4L devices installed under User Library require `preset_query`, not `kind=`, in `ableton_device(action='load')`

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B close-out (2026-05-27), `ableton_render(action='ensure_loaded')` failed on a fresh Live session with `"no loadable browser item found for kind='HallucinoteAnalyzer'"` despite the `.amxd` being correctly placed at `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd` (verified via `installed_analyzer_amxd()` and via `ableton_browser(action='search', root='user_library', pattern='hallucinote')` returning `is_loadable: True`). Root cause: `analyzer/setup.py::_ensure_on_surface` passed `kind=ANALYZER_DEVICE_NAME` to `device_handlers.load_handler`, which walks only `_BROWSER_LOAD_ROOTS`. The fix narrowed the lookup to the exact User Library subpath via `preset_query`, including a `path_prefix` to prevent shadowing by user-saved presets with the same display name elsewhere in their library.

**How to apply:**
1. When the project's install skill places an .amxd under User Library, the analyzer-load chain MUST use `preset_query` (not `kind=`) with `root='user_library'` and `path_prefix` pinning the install location.
2. The `path_prefix` value should mirror the install path exactly — codify it as a module-level constant (e.g. `ANALYZER_BROWSER_PATH_PREFIX = ("Presets", "Audio Effects", "Max Audio Effect")`) and reference both the install skill and the loader from it. Drift between install location and loader location is silent (the device just won't be found).
3. Test fakes (e.g. `_FakeBrowser` in `tests/unit/test_analyzer_setup.py`) must mirror the real install layout — populate `user_library` with the nested `Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer` subtree, NOT a top-level `audio_effects` child. A fake that puts the analyzer in the "wrong" root will pass tests that the production code fails.
4. If you DO want to extend `kind=` lookup to walk User Library, modify `_BROWSER_LOAD_ROOTS` cautiously — it adds search cost on every device-load and risks name collisions with user-saved presets. The narrow built-in set was an explicit design choice. For user-library-installed devices, `preset_query` is the proper surface.
5. The same logic applies to any future M4L device the project ships: the install skill places it under `user_library/<something>`; the loader must use `preset_query` with that path_prefix.

## M4L `[peakamp~]` is self-clocked via a reporting-interval arg, not banged

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26), the feature emitter's sample-peak extractor was initially designed to be metro-banged at 30 Hz (`[t b b b b]` → bang to `[peakamp~]` inlet 0). In M4L, `[peakamp~]` ignored the bangs entirely — no output reached downstream `[expr]` / `[send]` / `[receive]` / `[pack]` chains. Switching to `[peakamp~ 33]` (auto-emit every 33 ms) made peak values flow continuously into `[pack]`'s cold inlet. The metro fan-out simplified from `[t b b b b]` (4 outlets — three extractor bangs + address) to `[t b b b]` (3 outlets — two snapshot bangs + address), since peak no longer needs a metro tick.

**How to apply:**
1. For `[peakamp~]`, use the constructor-arg interval form (e.g., `[peakamp~ 33]` for ~30 Hz). Don't try to bang it.
2. The interval should match the consumer's polling rate so the latched value is at most `<interval>` ms old when read. For a 30 Hz consumer, 33 ms is a good match.
3. Self-clocked extractors are asynchronous to a metro-driven `[pack]` fire path. That's fine — cold-inlet writes always succeed (they latch); `[pack]` only fires when the hot inlet hits. The latched value is at most one interval stale at fire time.
4. If precise phase alignment matters (it usually doesn't for peak reporting), use a shorter interval — `[peakamp~ 10]` updates at 100 Hz, so the metro-tick read is at most 10 ms stale. Trade off CPU for freshness.
5. The same self-clocking pattern shows up in other Max audio-rate "report periodically" objects (e.g., `[meter~]`, `[snapshot~]` with `[metro]` upstream). When an object provides an "interval" or "rate" arg, prefer it over bang-driven polling — the docs may say bang works, but in M4L it often doesn't.

## M4L `[average~]` has one inlet, not two — window-size message shares the signal inlet

**Why:** during audio-analysis MVP Chunk 2 sub-chunk 2B (2026-05-26), the SR-adaptive `[average~]` window-update chain (`[adstatus sr] → [expr $f1 * 0.4] → [i] → [average~]`) was first designed to feed the int into `[average~]`'s "right inlet 1" — but `[average~]` only shows one inlet in the patcher editor. The correct topology wires the int message to the same LEFT inlet that the audio signal enters. Same single-inlet multiplexing as `[peakamp~]` (which shares its inlet for signal + bang).

**How to apply:**
1. When wiring a control-rate parameter update to a `~` audio object, check whether the object has a separate parameter inlet OR multiplexes on the signal inlet. `[average~]` and `[peakamp~]` multiplex; `[*~]` (in some configurations) has a separate right inlet for the multiplier signal. The patcher editor shows the truth — count inlets in the GUI.
2. When the same inlet accepts both signal and control messages, wire both connections to it. Max's scheduler keeps them separate.
3. If you find yourself thinking "the docs say there's a right inlet for X" and the editor disagrees, trust the editor. Max docs sometimes describe an idealized object that doesn't quite match the runtime.
4. Companion pattern: `[peakamp~]` shares inlet 0 for signal + bang. The bang triggers read+reset; the signal flows continuously. Same multiplex shape.

## M4L `[expr]` function vocabulary is narrow — no conditionals, no min/max; use `[clip <floor> <ceiling>]` upstream for log-of-zero protection

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

The split-large-modules wave (mutations.py 4164 / pull.py 3401 / push.py 3166 → packages) stayed invisible to ~38 callers because almost all use `from hallucinote.db import mutations` then `mutations.create_clip(...)` (attribute access) — a package `__init__` that re-exports everything resolves those unchanged. The traps were the minority: private helpers imported by name from *other* modules (`handlers/analysis.py` does `from ...sync.push import _position_bar_to_beats`; a property test imports `pull._beats_to_position_bar`) and the one same-module **monkeypatch seam** — `plan_push_clips` called `plan_push_clip` as a module global that a test patches via `push.plan_push_clip`. A naive submodule split turns that into a direct import that the patch can't reach; preserve it with a function-local `from hallucinote.sync import push; push.plan_push_clip(...)` re-import (also breaks the load-time cycle).

**How to apply.** (1) Grep first, build the name contract, re-export the superset — don't trust "looks public." (2) Keep a leaf `_core` (shared helpers/types/transaction machinery) that imports from no sibling, so domain modules depend only downward — no cycles. (3) Watch for a function that's monkeypatched through the module object; route its internal calls through the package facade. (4) A split also surfaces latent coupling worth fixing in the same wave: this one exposed `pull` importing geometry helpers from `push` (inbound depending on outbound) plus a duplicated `_beats_per_bar` — both resolved by extracting a neutral `sync/geometry.py` leaf. Run the full suite after EACH module's split, not just at the end, so a break is bisected to one move.

## Pulling enforcement earlier shadows a downstream guard — migrate its tests, keep a bypass backstop

TMP-1R7K added a `_require_bar_floor` teaching `ValueError` at all five bar-position mutators, ahead of the schema `CHECK (start_bar >= 1.0)` that previously did the rejecting. The existing `test_bar_constraints.py` asserted `sqlite3.IntegrityError` — but the mutator now raises `ValueError` before any SQL runs, so those assertions would only pass by accident (wrong error) or fail. Mechanically "fixing" them to expect `ValueError` is right for the mutator path but would leave the schema CHECK with zero coverage: it's still there as a backstop for raw inserts, and a future schema edit could drop it unnoticed.

**How to apply.** Restructure the suite into two layers that mirror the enforcement: (1) **mutator/primary** tests assert the new teaching error (`pytest.raises(ValueError, match="must be >= 1.0")`) and acceptance at the boundary; (2) **backstop** tests do a raw `conn.execute(INSERT ...)` that bypasses the mutator (FKs off so the CHECK, not a missing FK, is what rejects) to prove the schema layer still fires. This is the inverse of "Never weaken a test": the contract genuinely changed (earlier + clearer error), so the old assertion is now wrong, not weakened — but dropping the shadowed layer's coverage IS weakening, so keep the bypass test.

## Variation ops are tiling-safe only on single-cycle motifs

In the sun-zone-done arrangement build, recurrence deltas (verse2/chorus2) used `transpose` on the full tiled section layer and composed cleanly — per-note pitch math doesn't care how many cycles are present. But `fragment(notes, 0, 4)` on a tiled list keeps the windowed onset across EVERY cycle and rebases them all to 0 (they pile up); `retrograde`/`augment` likewise reinterpret the whole span as one gesture. The outro double-time bursts only worked because the "no-time" hook was registered as a single 8-beat motif (`arr.motif(...)`), so `fragment → diminish → shift` operated on one clean cycle.

**How to apply.** When you need fragment/retrograde/augment/diminish, author the source as a single-cycle motif (an `Arrangement.motif`, or a bare cell), transform it, THEN tile/shift the result — don't reach for these ops on `generators.*` output that already looped across the section. Per-note ops (transpose/shift) have no such constraint.

## Generators degrade gracefully on OPTIONAL pads, raise on load-bearing ones

`reggae_one_drop` and `metal_gallop` hard-referenced `kit.hat_open` / `kit.crash`, which raise on the wrong-sound case. That crashed the *real* sun-zone-done build: Ableton's Hot Rod Kit ships three closed hats and no dedicated open-hat chain, so `kit.hat_open` raised even though the open-hat "lift" is just a once-every-4-bars accent. The synthetic GM-default snapshot hid it (GM has note 46), so the test suite stayed green while the real `--reset` build died.

**How to apply.** Classify each pad in a generator as load-bearing vs. flourish. Flourish pads → `try_pitch_of` + `if pad is not None:`. Add a degradation test with a `Kit.from_dict({kick,snare,hat_closed})` (captured-but-incomplete) asserting the generator builds and simply omits the missing flourish. This is the kit analogue of "the GM-default snapshot is not the real kit" — verify against an incomplete captured kit, not just GM defaults.

## When a capability ships, audit the planning + intent artifacts — stale intent misguides tools

The harmony axis + the sun-zone-done 184-bar re-author shipped, but the song's annotations still described the old 80-bar arc — and `genre-alternation-intent.md` told `/mix-review` *"genres never overlap → never flag cross-genre masking."* That instruction would have suppressed masking analysis **exactly at the new fusion climax** (the integration) — the one place fusion-vs-mud is the critical question. Separately, `docs/VISION.md` and `song-authoring-conventions.md` read ~2 arcs stale (no harmony axis, no performance layer, no analysis pipeline). The green test suite caught none of it — docs and annotations aren't exercised by tests.

**How to apply.** When a capability lands, sweep the WHY/intent layer, not just the code + its tests. Highest risk: intent docs that FEED read-side tools (`/mix-review`, the conformance lenses) — stale intent there produces confidently-wrong guidance. Treat "we shipped X but forgot to update the docs/intent for X" as the same class of bug as "we forgot X."

## Detect a running process with the framework's probe or `pgrep -x` — never `ps | grep name`

This session, `ps aux | grep -ic "Ableton Live.app/Contents/MacOS"` returned 2 and I told the user Live was running; the install preflight correctly reported `is_running: false`. The user caught the contradiction. The hand-rolled check was wrong, not the framework — which already had the answer.

**How to apply.** For Live-state gates in install/push workflows, read `cli preflight`'s `live.is_running` (it's authoritative and already there). For ad-hoc shell checks, `pgrep -x` matches the exact process name and doesn't self-match; if you must `grep`, filter `grep -v grep` or match on the absolute binary path with `pgrep -fl`. Don't trust a `ps | grep -c` count.

## When the render is blocked, verify compositional changes on the render-free signals — they validate, not just describe

This session, harmonizing sun-zone-done's integration (a looped Phrygian riff → a Dorian→Phrygian→fuse arc) raised the integration lead's resolve-by-step from 19%→39% in the melody lens — a measurable sign the line+harmony got MORE coherent, with no audio. The corollary that kept it honest: when a new hook (the hybrid) dropped resolve 39%→15%, the fix was to brighten the HARMONY to anchor the line (back to 21%), NOT to blandify the hook to chase the number — tune the harmony to the line, not the line to the lens. The lens is a ruler, not the verdict; the ear still rules last.

**How to apply.** When audio is unavailable, drive compose changes through build → lint (`ok=True`, no stasis) → melody lens deltas → shape tests, and read the lens numbers as evidence the change landed. Never treat a lens number as a target to optimize (that blandifies); treat a regression in it as a question to diagnose. Always label the result render-gated until the ear confirms.

## A file-mutating tool that errors mid-run is not a clean no-op — verify, then prefer a deterministic script

This session the `/backlog` skill crashed mid-write and left the backlog with one item DELETED-but-not-reinserted (data loss) plus four half-moved. Caught by re-reading the file (grep each target id's section + status) instead of trusting the error as a no-op, then repaired forward with a small parse-sections/move-by-id script. That same script shape then did the merged-item true-up, the ship-on-merge status flips, and (a sibling form) the helper-hoist across four song build.py files — each verified by a no-dups/no-leaks grep. Deterministic-script-for-bulk-edits became the session default once the skill proved fragile.

## A backlog sweep parallelizes when you cluster by file-area and VERIFY-against-current-code before each fix

This session, seven clusters fixed ~13 items with zero cross-agent file corruption. Verify-first earned its place immediately: it caught that `sync/push.py` had been split (a cited line was gone), that one item was already-fixed-and-stale, that an item's own brief was *backwards* (an "stdlib-only reversal" was actually dependency *adoption*), and that one item was blocked-by-design — turning would-be stale work into accurate close/defer recommendations. The one test that went red was a cluster correctly refusing to weaken a test outside its lane (the contract had legitimately changed); the orchestrator reconciled it to the stronger corrected assertion.

**How to apply.** Scout the backlog inline to build the work-list and partition by file-area (disjoint = no same-file races); spawn one agent per cluster with a verify→fix→narrow-test brief and the collision rules above; have each return per-item verdicts (`fixed`/`already-fixed`/`deferred` + evidence). Then consolidate centrally: full suite, ONE cumulative Critic (per `feedback_critic_cadence_for_small_chunks`), then reconcile backlog statuses + change-log with a deterministic flip-by-id script. Expect the Stop gates to fire mid-workflow (they don't see in-flight background work) — keep the turn open until the tree settles, or declare a scoped waiver and satisfy the gates for real on completion.

## A distribution artifact the product needs at install time must be TRACKED — check .gitignore before trusting it

INS-7V2D C1 made the plugin launch its bundled MCP server with `uv run --frozen`, whose entire version-coupling guarantee is a committed `uv.lock`. The lock generated + verified perfectly locally — but `.gitignore` excluded `uv.lock` ("ambient, not a tracked lock"), so a real `/plugin install` would ship without it and `--frozen` would fail. The Critic caught it; I had "verified" the mechanism without ever checking the artifact would leave my disk. (Same rule surfaced a stale, pre-workspace `hallucinote_mcp/uv.lock` hiding under the same ignore — workspaces use ONE root lock.)

**How to apply.** For any "X ships with the product and the product reads X at install/run time," before claiming done: (1) `git ls-files --error-unmatch X` (or `git check-ignore X`), (2) confirm a *fresh-clone / CI* path exercises it, not just a local run, and (3) if a contract test asserts `X.exists()`, remember it's a false-green until X is committed. Local generation + local launch is necessary but never sufficient evidence that a distribution artifact is real.

## A Claude Code plugin's hook/manifest format: verify against the installed plugin cache, not a docs/research agent's guess

INS-7V2D C2 needed a SessionStart pre-warm hook. The `claude-code-guide` agent returned an exec-form `{"type":"command","command":"bash","args":["${CLAUDE_PLUGIN_ROOT}/..."]}` shape. The installed prawduct plugin's own `hooks/hooks.json` showed the real format this CC runs: **shell-form** — a single `command` string with the path inline (`"command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/banner.py\""`), no `args` key. Following the agent's guess would have shipped a hook that never ran.

**How to apply.** (1) For any format the *harness* parses (hooks, manifest keys, settings shapes), prefer a working in-cache example over prose docs or an agent answer — the cache is version-matched, docs/agents may not be. (2) `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` are exported to plugin hook commands; the pre-warm DATA-env pattern is the uv analog of the docs' npm "diff the manifest, rebuild on change" example. (3) Treat "an agent is confident about an environment-specific format" as a prompt to find ground truth, not as the answer — the confidence is uncorrelated with the CC version you're targeting.

## A plugin MCP server's STARTUP timeout is `MCP_TIMEOUT`, not the per-server `timeout` field

INS-7V2D shipped a "generous timeout" mitigation for the bundled server's cold `uv sync`
(~70 MiB numpy/scipy/librosa), but put `"timeout": 60000` in `plugin.json`'s per-server field.
The connection log proved it never applied to startup: `Starting connection with timeout of
30000ms` … `Connection timeout triggered after 30004ms` — the default `MCP_TIMEOUT`, not the
60000 config. The follow-up raises `MCP_TIMEOUT` (floor 180000) via settings `env`
(`hallucinote-mcp set-startup-timeout`).

**How to apply.** (1) For an MCP server whose first launch builds/installs anything heavy,
budget the STARTUP timeout via `MCP_TIMEOUT` in settings `env` — not the per-server `timeout`
(that's tool-exec) and not a SessionStart pre-warm hook (it races the spawn). (2) A
plugin-provided server's startup behavior is end-user-distributable only through the install
flow writing the user's settings — the manifest can't. (3) When a cold start "silently drops
the server's tools" (CC#60224), read the connection log under
`~/Library/Caches/claude-cli-nodejs/<proj>/mcp-logs-*/` — it states the exact timeout value
in force, which tells you immediately whether the config you set is the one being applied.

## Severity-tier surfacing channels at the source, not by location

SYN-9F2L's "params_dialed lands OR warns" shipped the warn into `PushPlan.notes` via `plan.warn()`. But `notes` was already overloaded: the same channel carried diagnostic noise ("no tempo_map rows; nothing to push", "device not linked yet; rerun after apply"). `push_execute` — the only operator-visible surface on the execute path — never drained `notes` at all, so the warn was silently discarded: the exact silent-drop the chunk was filed to kill, alive on the primary push path. The per-chunk Critic (deferred to cumulative for a small chunk) couldn't see it because each side was unit-tested in isolation — the planner's warn was asserted in `plan.notes`, the executor's warnings were tested for cue deferrals — and the gap was the *dataflow between them*. Only the cumulative review, reading producer and consumer together, caught it.

The first fix attempt drained ALL `plan.notes` into warnings and immediately failed a test with 8 "nothing to push" warnings — the failure pointed straight at the overloading. The Critic's own suggestion ("drain devices-phase notes") would have leaked the "not linked yet" noise the same way. The root fix added a third tier — `PushPlan.alert()` (operator-actionable, drained to the report's `warnings`, exit stays 0) — between `notes` (diagnostic, never surfaced) and `errors` (halt). The unwritable-param warning moved to `alert()`; the executor drains alerts from every phase (deduped, including the same-pass convergence re-plan), severity-scoped not phase-scoped.

**How to apply.** (1) Three tiers, by audience+consequence: **halt** (the run can't proceed — `errors`), **alert** (the run proceeds but the operator authored something that was skipped and must know — `alerts`/`warnings`), **note** (diagnostic, for logs/debugging only — never surfaced). Give the producer a named method per tier; don't make the consumer guess from a flat list. (2) A consumer-side filter keyed on *location* (phase name, module) is a smell — it breaks the moment another site emits the same severity, and it surfaces co-located noise. Tag severity where the message is created. (3) When a chunk's correctness spans a producer AND a consumer (planner→executor, emitter→reporter), unit-testing each side isn't enough — write one test that exercises the *dataflow* end-to-end. That's the test that would have caught this; the cumulative Critic was the backstop that did.

## A realtime / long-playback MCP action needs a read-timeout policy entry — applied at the layer EVERY recv route shares, not just one

ENV-9P4T chunk 01's `perform_batch` plays the transport over the union span of all changed arcs in record (minutes at mix scale) and returns each arc's `automation_state` — the ONLY verification a write-only surface has. The FIRST fix added `("ableton_automation","perform_batch"): None` to `server.py`'s `_READ_TIMEOUTS` — and a Critic pass declared it resolved. But that table is consulted ONLY by the server's agent-forward route; the feature's PRIMARY consumer, `push_cli execute`, dispatches via `client.send(req)` with no `read_timeout`, hitting the 15s `client.send` default and talking to the Remote Script directly — bypassing the server table. A union span > 15s (a 16-bar fade ≈ 32s) → `socket.timeout` → classed `connection_lost` → halt, verification discarded while Live keeps recording. The same blocker, "resolved," still live on the route that matters. The dev smoke driver hard-coded a 180s CLIENT timeout — empirical proof the client layer is the one that bites — which masked it. The real fix moved the policy INTO `client.send` (`read_timeout_for(tool, action)` + a `_UNSET` sentinel so an unspecified `read_timeout` auto-resolves from the policy), making `client.send` the single source both routes share; `server.py` re-exports the names. Now `push_cli`'s `send_fn = client.send` gets the right window for free.

**How to apply.** (1) Put a per-(tool,action) policy at the lowest shared chokepoint (here `client.send`, the one socket-recv both routes funnel through), not at one caller — and have it auto-resolve when the caller doesn't specify, so a future caller can't forget. (2) When you "fix" a layer-crossing timeout/verification bug, trace EVERY consumer to the recv call: count the routes (`grep` the dispatch sites), don't assume the one you're looking at is the only one. A green Critic on the wrong layer is worse than no fix — it stops the search. (3) A test/dev harness's hard-coded override is a RED FLAG, not a convenience: it means the real default is wrong for that action; delete the override or the prod path stays broken behind it. (4) The regression test must exercise the route that bites: assert `client.send` (the push route) auto-resolves the action to the right timeout, not just that the policy function returns it. (5) "Wall-clock is content-proportional" is the trigger to check the read-timeout policy, same reflex as checking the gesture-restore `finally`.

## A green change-log/PR gate is not a pushed gate — re-push after any commit before merging

ENV-9P4T (#161): I pushed the feature branch at `25e5b76`, then the `check-change-log-entry` gate (correctly) blocked me to ADD a change-log entry, which I committed as `b7e9c29` — and never re-pushed. `gh pr merge --squash` squashed `origin/feature@25e5b76`, silently dropping the change-log entry from develop. The local gate had gone green (the commit existed locally), so nothing flagged it. This is the exact REL-6C3W failure mode (a feature merged with no change-log entry, invisible to the release flow) reached through a back door — the gate that exists to prevent it was satisfied by an unpushed commit. Caught post-merge by grepping develop's change-log; repaired by adding the entry directly to develop with `status=merged`.

**How to apply.** (1) Immediately before `gh pr merge`, assert `git rev-parse HEAD == git rev-parse @{u}` (local == pushed) — or just `git push` unconditionally; it's a no-op when synced. (2) Any gate that re-blocks you to write a file (change-log, evidence, a fix) creates a NEW commit AFTER your push — treat "the gate made me commit" as "I must re-push." (3) Prefer landing the change-log entry BEFORE the first push, so the gate→commit→merge order can't strand it. (4) The deeper gap: the PR gates check local git state, not origin; until they check `@{u}`, the human/agent owns the local-vs-pushed reconciliation.

## Multi-write Live handlers resolve everything before writing anything

RTE-1K9T chunk 01/02: `set_output_routing` / `set_input_routing` wrote `track.output_routing_type = matched_type` and THEN resolved the optional `channel_display_name`. An unknown channel raised after the type reroute had already applied — the MCP response was an error, but the session's output was now silently pointing at the new bus. The identical ordering was latent in the device-layer `set_input_routing_handler` this work extracted shared helpers from (so "no pre-existing exception" pulled it into scope). The Critic flagged it (warning, all reviewers); fixed by a shared `resolve_routing_write` that returns `(matched_type, matched_channel)` and raises on any bad input BEFORE the caller touches Live, so both writes happen only after both resolve.

**How to apply.** (1) Shape multi-write handlers as resolve-all → validate-all → write-all; never interleave a write between two validations. (2) The tell is a `setattr`/assignment to a Live object that appears textually before a later `raise` path in the same handler. (3) Test it directly: feed a valid first input + an invalid second and assert the first object is UNTOUCHED (not just that the response is an error) — a response-only assertion passes even when the session half-mutated. (4) This is the Live-write analogue of transaction atomicity; the DB mutators get it for free via the single-transaction `_emit`, but raw LOM writes don't — the handler owns the ordering.

## The schema canary checks column PRESENCE, not column DEFINITION

RTE-1K9T chunk 03 added CHECK-constrained columns (`output_routing_kind`, `monitoring_state`) via both declarations. A migration comment claimed "CHECKs MUST match schema.sql verbatim or the schema canary fails" — false, and the Critic caught it (Goal 4 coherence). The CHECKs happened to match, so no behavior defect, but the comment promised an enforcement guarantee the code doesn't deliver — which would breed false confidence in a future editor. (Precedent columns `intended_rt60_s`, `energy` carry CHECKs through `_ADDED_COLUMNS` too, so the gap pre-dates this chunk; it was just never written down.)

**How to apply.** (1) When adding a typed/CHECK'd/FK'd column via `_ADDED_COLUMNS`, diff the clause against the schema.sql CREATE TABLE line by eye — the canary won't. (2) Don't write comments that assert an enforcement the code doesn't perform; state what's actually guaranteed ("the canary verifies presence; CHECK parity is hand-maintained"). (3) A genuinely robust fix (compare normalized definitions from `sqlite_master.sql`) is whitespace/quoting-fragile and false-positive-prone — worth it only if definition drift actually bites; until then the hand-maintained convention + an honest comment is the proportional call.

## A build-plan "match the existing X" instruction can cite a precedent that doesn't exist — read the sibling before mirroring it

RTE-1K9T chunk 04 said "fingerprint-gate so unchanged routing never re-emits (match the existing mix/send gating)." Reading the siblings showed there IS no mix/send fingerprint gating — `plan_push_mix` and `plan_push_devices` re-emit idempotent `set_property`/`set_parameter` calls on every push; the ONLY fingerprint-gated phase is `performed_automation`, which gates because it has a real wall-clock cost (the transport plays each changed span in realtime). A routing set has no such cost, and a pure-data planner can't read Live's routing state to gate against it anyway (planners read the DB only). So the right move was to mirror what mix/devices ACTUALLY do (unconditional idempotent re-emit; "re-push is a no-op" at the effect level), recorded as design decision D7 — not to invent a fingerprint mechanism no sibling has.

**How to apply.** (1) Treat "match the existing X" as a claim to verify, not a spec to execute — `grep`/read X first. (2) When the plan's premise is false, don't silently follow it AND don't silently drop it: record a design decision (here D7) stating what the precedent actually does and what you did instead, and correct the plan text so the next reader isn't misled. (3) The tell that a plan instruction is a remembered-not-checked claim: it names a mechanism ("fingerprint gating") and attributes it to a sibling without a file:line — the attribution is the thing to verify.

## Open an existing song DB through `init_db` (migrate-on-open) — bare `connect()` reads a stale schema and crashes

A 0.9.0 song DB (swell) crashed `push_cli execute` at `plan_push_routing` reading `t["output_routing_kind"]` — a column RTE-1K9T added in 0.9.5 that the DB never gained, because `push_cli`/`pull_cli`/`compat.check_song` all opened with bare `connect()`. `run_build` (and thus `build.py`) already open every existing song via `init_db`, which is why a rebuild "fixed" it — but a pure push/pull/check against an un-rebuilt DB had no migration trigger. `init_db` is idempotent and non-destructive on existing DBs (IF-NOT-EXISTS schema + additive ALTER pass; `_rebuild_disposable_tables` only drops a re-derivable cache), so migrate-on-open is safe and makes the tool self-heal across schema-adding upgrades.

**How to apply.** (1) When you open a persistent song DB for app/read/sync use, use `init_db(path)`, not `connect(path)` — `connect` is the low-level primitive `init_db` builds on, for code that has *already* created/migrated the DB (init_db's own internal open) or genuinely must not mutate. (2) The one principled exception is a best-effort, side-effect-free read that must not ALTER the schema (e.g. the MCP `server.py` render-provenance seq read, which reads only pre-bump `songs`/`events`) — keep it bare with a comment saying why. (3) Watch for tests that reach through a CLI/module namespace for `connect` (`compat.connect`) — that's an accidental re-export dependency; import from `hallucinote.db` instead. (4) `IndexError: No item with that key` from a `SELECT *` row access ALWAYS means "this column isn't in the result set" — usually a schema/migration mismatch, not a logic bug.

## Build-plan chunk headings must be `### Chunk <id>:` (h3 + colon), not `## Chunk X —` (h2 + em-dash)

SNP-MIX-CLUSTER's plan used `## Chunk C — MIX-3S7P close-out`. `verify-chunk-refs` errored with `chunk 'C — MIX-3S7P close-out' not found in build-plan` (exit 0 — advisory, doesn't gate the PR). I first chased it as a text-divergence between the Status line and the heading and made them byte-identical — it STILL failed. The Critic's verify-resolutions pass named the real cause: `lib/buildplan_refs.py` `_chunk_section_lines` anchors only on `### Chunk <id>:` (h3 + colon), and `_current_chunk_id_from_status` extracts a bare id from a `Chunk X: name` Status line. Rewriting all three headings to `### Chunk A:` / `### Chunk B:` / `### Chunk C:` and the Status lines to the `Chunk X:` form made it pass (`ok: chunk C — 0 file ref(s) verified`).

**How to apply.** (1) Author build-plan chunk headings as `### Chunk <id>: <name>` (h3, colon after the id) and Status checkboxes as `- [ ] Chunk <id>: <name>` from the start — not `## Chunk X — …`. (2) When a verifier complains despite text that looks right, stop tuning the text and check what the verifier actually keys on (heading LEVEL, a delimiter char) — read the resolver, don't guess. (3) `verify-chunk-refs` is exit-0 advisory, so a wrong heading form silently gives the plan zero chunk-ref coverage — it won't block, it just stops protecting you.

## A sampler/drum part's note mapping is only verifiable by rendering it

`examples/b-natural`'s `11 Latin Perc` rendered as digital silence (-180 dB) while all ten other stems had audio. The part was authored against a Drum Rack's pad layout (C1 = MIDI 36); its instrument was an Instrument Rack wrapping an **Impulse**, whose eight slots are C3-G3 in Live's display — MIDI **60-67**. Every gate in the system was green: the notes were in the DB (129 of them), the notes were in Live, `verify-arrangement` passed on all 34 placements, `compat check` was 38/38 native, and the push reported `OK — all 14 phases completed`. The defect was found by rendering and listing per-stem RMS.

**How to apply.** (1) After the first push of any song with a sampler/drum-device part, render once and print per-stem RMS before doing any mix work — a stem at -180 dB is a mapping bug, not a quiet part. (2) Probe the actual pad layout (`ableton_device(action='get_device_chains')` exposes `in_note` per DrumChain) rather than assuming GM; `Kit.from_dict` with probed values documents what you measured. (3) An Impulse exposes no drum chains at all, so a chain walk returns nothing and tells you nothing — that silence in the probe is itself the signal to check the device class. (4) Never carry a pad constant across device kinds: "the first pad" is 36 on a Drum Rack and 60 on an Impulse.

## `skipped (idempotent)` is two different outcomes wearing one word

b-natural's first push reported `OK — all 14 phases completed` with both `envelopes` and `arrangement` showing `skipped (idempotent)`. They meant opposite things. `envelopes` skipped correctly: all 17 arcs had been routed through `performed_automation`, which recorded them in one realtime pass — the warning block enumerated every arc by name. `arrangement` skipped because its per-track probe had failed for all 11 tracks (Live's default scaffold tracks were still present and shifting indices), so nothing was placed on the timeline at all. The phase table rendered both as `[ok]`.

**How to apply.** (1) Treat the warning block as part of the exit criteria, not as decoration. (2) For each skipped phase, ask which of the two it is: work-done-elsewhere or precondition-failed. (3) `arrangement`, `envelopes`, `performed_automation` and `devices` are the four that report success on zero work — check the thing the brief names is actually present, rather than trusting the count. (4) Run the default-scaffold cleanup before concluding a probe failure is real; leftover default tracks were the cause here.

## A declared-vs-measured gap has two possible culprits — name which

b-natural's melody lens raised three declared-vs-measured questions, and all three resolved differently. `contour_intent="arch"` was declared out of habit and the line genuinely climbed to a late apex — the *declaration* moved. The chorus had drifted off its motif to 27% cell coverage, which meant a listener would hear a nice tune rather than the same tune resolved — the *music* was rewritten. `repetition_appetite` still read "moderate" afterwards and was left that way, because the claim being made was motivic ECONOMY, which the recurrence lens asserts separately (1/1 motifs recurring, 100% coverage) — the metric was measuring literal repetition, which a line that varies its cell every return should score low on.

**How to apply.** (1) Write which side moved, and why, next to the declaration — the reasoning is the artifact, the value is not. (2) A declaration that changes to match a measurement is only honest if the measurement described the intent better than the declaration did; say so. (3) When one lens's metric and another lens's metric disagree about the same musical claim, name which lens owns the claim rather than optimizing both. (4) Two different lines under one layer name need two profiles; a single profile flattens a real intent and makes the lens question the arc the song is.

## A correct automation arc is not evidence of an audible result

Two consecutive sessions misdiagnosed the same silent failure. Session one blamed
a latched `back_to_arranger` override; session two (me) blamed short automation
arcs not landing. Both were wrong, and both were reached by inspecting mechanism
— `automation_state` read 1 (playing), and parking the playhead mid-sweep read
back the exact authored value 0.387. The arc was perfect. The device it drove
could not do what was asked: `Mod Phase 0.0°` ran both channels' LFOs in
lockstep, so a wet flanger stayed bit-exact mono. Only a per-stem `L−R`
measurement on rendered audio separates "the automation didn't land" from "it
landed on a parameter that cannot express the intent". (2026-08-10, STR-4C8N)

**How to apply.** (1) Before diagnosing WHY a gesture didn't happen, render and measure the stem — `automation_state`, a parameter read-back and a green push all describe the mechanism, not the sound. (2) A lens that verifies the arc is not verifying the intent; ask which one you actually need. (3) When two sessions running reach two different wrong causes, the shared mistake is usually the missing measurement, not the reasoning.

## A "no effect" verdict indicts the probe as much as the device

Device-parameter verification probed spectral centroid alone. A flanger is a comb
filter and notches roughly symmetrically, so it barely moves the centroid however
wet it gets — producing `no audible timbre shift (2244→2219 Hz, 1% < 12%)`
against automation that provably landed. The fix is a second probe (stereo
correlation), not a looser threshold. The regression test that matters pins the
opposite direction: identical before/after windows must STILL read not-realized,
because a fix for false positives that becomes a rubber stamp is worse than the
bug. (2026-08-10, STR-4C8N A2)

**How to apply.** (1) Ask what the device physically does to the signal before trusting a probe's verdict — a comb filter moves the image, not the brightness. (2) Fix a false negative by ADDING a probe, never by loosening a threshold. (3) Pair every such fix with a test asserting the opposite direction still fails, or the fix is a rubber stamp. (4) Check the fixture models the real mechanism: simulating width with injected noise also changes the spectrum, so it tests something else.

## A criterion built from a symptom COUNT can fail by being satisfied

A2's criterion said "the three Dry/Wet findings stop being reported as
not-realized", written from the finding count on the assumption all were false.
Each arc had three change points; the beat-288 move was `0.38 → 0.42`, a 4 %
change that is genuinely inaudible, so "not realized" there was correct. Meeting
the criterion as written would have required making the probe lie. Correct the
criterion in the plan and say so — never quietly pass, and never loosen the code
to satisfy a wrong spec. (2026-08-10, STR-4C8N A2)

**How to apply.** (1) Expand a count into its individual symptoms before calling a partial pass a failure. (2) If satisfying the criterion would require the tool to report something untrue, the criterion is wrong — correct it in the plan and say so. (3) Never tune a threshold until a count reaches zero; that is how a rubber stamp gets built and called a fix.
