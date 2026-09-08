# Learnings

Accumulated wisdom from building this product. Each entry below is the **rule in brief** —
the When-X-do-Y-because-Z statement. Where a rule has an incident + how-to-apply
narrative, it lives in [learnings-detail.md](learnings-detail.md) under the **same heading**,
in the same order (a rule with no narrative has no detail counterpart). Add new rules here;
put any narrative there.

<!-- prawduct:descent-obligation — the statement below is the HOME of the
     descent rule; `/prawduct:learnings` points here rather than restating
     it. Reword the prose freely; keep this marker, above the first rule. -->

**Reading a rule is not applying it.** The failure mode of a learnings file is not absence, it is assent: a rule arrives at the right moment, is read, is agreed with, and changes nothing, because nothing made you recognize the case in hand as an instance of it. So for any rule you read here, name the decision you are about to make and say what the rule changes about it — or say that it does not apply, which is also an answer.

## Newly enabling a capability doesn't update the guards that predated it — grep for stale exclusions

**When a change makes a previously-impossible thing possible (DEV-6M2K made master device chains pushable; the earlier premise that Live can't load onto the master was refuted), the exclusions/guards/skips written under the old invariant don't auto-update — they silently become bugs. The push probe's master-exclusion ("master has no pushable devices, reached via ableton_session not a track index") was a correct invariant that became the analyzer-aware-reconciliation gap once master devices were real. After enabling a capability, grep for every guard keyed on the old "can't" (skips, `if kind != 'master'`, detect-only carve-outs, "still-open piece" comments) and audit whether it's now stale.**

## Threading a new param means making the test doubles faithful — not weakening tests

**When you add a parameter to a function that tests stub out (a `send_fn`, a monkeypatched planner, any injected callable), the stubs break with `TypeError: unexpected keyword argument`. The fix is to EXTEND each double to mirror the real signature (`def send(req, *, read_timeout=None)`, `**kwargs`) — that makes the double MORE faithful to the thing it imitates, the opposite of test corruption. Reach for it before reaching for a conditional that skips the new arg.**

## A collision/ordering guarantee needs a test per visit-order, and a single pass can't encode "this class always wins"

**When the rule is "class A always beats class B on a shared resource" (a recorded lane beats a re-record; an existing binding beats a new one), a single forward pass that claims-as-it-goes only enforces it when A happens to be visited first — the guarantee silently becomes order-dependent. Encode "A wins" as a PRE-PASS that claims all of A before B is processed, and test BOTH visit orders, not just the favorable one.**

## A "trivial" fix can key off a value another layer's policy depends on — trace the consumer first

**Before applying a literal one-line fix, check whether the field it changes is read by a DIFFERENT layer's decision. ENV-8K2R #2 ("write interp(span_end) before end_gesture") was a clean endpoint fix for normal arcs — but unconditionally bumping `updates_written` from 0 to 1 would have defeated `record_perform_result`'s stale-lane gate (which treats updates_written==0 as "degenerate sub-tick window, don't trust automation_state, re-perform"). Reconciled by pinning the final value ONLY when the gesture actually ramped (`updates_written > 0`): fixes the normal-arc endpoint, preserves the degenerate-window safety. The backlog's literal instruction was right for the case it described and wrong two layers away.**

## Install/setup skills do filesystem mutations in tested Python, never hand-authored shell

**A skill that copies, deletes, or edits files on the user's machine must call a tested, atomic Python helper (via a CLI subcommand), not hand-author `rsync`/`rm`/JSON-edit shell in the SKILL.md. The shell boundary is a footgun, and skill shell is untestable and non-atomic.**

## A permission to collaborate must restate precedence in the same breath

**When you add a norm or skill instruction that *permits* more proposing / stopping / collaborating, state the precedence guard ("but if the user directed it, or said they'll handle the rest, execute and hand back") in the same place. A bare "you may propose here" leaks into directed work as friction.**

## Pattern sweeps are tree-wide or they don't count

**When changing a convention (a kind, name, or shape used across many surfaces), audit every reference with a tree-wide grep before declaring the sweep done. Partial sweeps create self-contradicting docs that ship.**

## Inverting a black-box formatter: validate a monotonic proxy, don't enumerate formats

**When you must invert an opaque value→string formatter that has no string→value API, don't special-case each output format. Parse a numeric proxy, VALIDATE it's monotonic over the domain by sampling, then bisect — and refuse when it isn't. One monotonicity check subsumes every "weird format" guard and auto-handles formats you haven't seen.**

## When a doc or duplicated contract IS the deliverable, lock it with a drift/parity test

**A discoverable doc index or a value duplicated across surfaces only stays true if a test exercises it. When the deliverable IS documentation or a mirrored contract, the test is its teeth: a drift guard (doc ↔ source, both directions) or a parity lock (every duplicate emits the identical thing).**

## DSP with a detection front-end: calibrate against real cases, don't assert from intuition

**For any analyzer whose input is *detected* (onset detection, pitch tracking, beat tracking) rather than given, run real/representative cases through the actual pipeline and read the numbers BEFORE writing test assertions. The detection stage has latency and failure modes that abstract reasoning misses, and a fixture chosen for convenience can hide them.**

## A staleness/version signature must be content-derived, never hand-bumped

**When you surface a "version" or "signature" so a consumer can tell whether loaded code is stale, derive it from the content (hash the source), not a hand-maintained string. Forgetting to bump a manual version is the exact failure mode the signature exists to catch — a manual bump and the stale-reload it's meant to detect are indistinguishable.**

## DB-UUID → capture-surface-ID lifts must key by surface ID, and be tested with distinct IDs

**When an analysis handler lifts DB rows into something the capture/analysis layer consumes, key the result by the capture SURFACE ID (`track:N` via `track_id_for_surface(track_index)`), never the DB UUID (`row['id']`). Test with UUIDs deliberately distinct from the index so a wrong-key no-op fails loudly.**

## Sync planner discipline

**When emitting a `ToolCall` for an MCP tool that has no `ALIASES_TODAY` entry, verify the actual MCP signature against the planner's args before considering the planner complete.**

## Round-trip pull's default-detection rests on the external system's default — probe it or narrow scope

**When an idempotent pull writes a NULLABLE column by diffing against the live system, "NULL ≡ the system's default" is the rule that stops every NULL churning into an explicit default on the first pull — but it only works if you actually KNOW the default. For an open / hardware-bound domain whose default you haven't live-probed, don't assume one: narrow the pull to the default-INDEPENDENT case so the unverified premise can't churn the store.**

## A new authorable event kind must be registered in the tombstone-protection map

**When you add a mutator/event kind that a NON-build actor (`sync` from pull, `llm` from an edit) can emit on a build-ownable row, register it in `build.py`'s `_LATEST_ACTOR_EVENTS[<row_kind>]` — otherwise a build-owned row carrying only that edit is silently CASCADE-deleted on the next `build_session` tombstone sweep.**

## Detection that replaces a user question must enumerate every state

**When you refactor "ask the user X" into "detect X programmatically," the detector must enumerate every state the user would have known to mention — including the ones that look the same from outside.**

## Freezing a shared interface? Census every consumer against authoritative sources first

**Before freezing a shared interface (wire shape, address grammar, schema key, protocol), enumerate ALL its consumers/features against authoritative sources — the code and the platform API — not from memory or an assumed count. The census's job is to find any consumer needing a capability the frozen interface can't express. This session a design assumed "5 node features"; a two-front audit (codebase coverage + LOM surface) found ~3 already-shipped were missed (the routing family was collapsed; device-sidechain-source omitted) AND surfaced two findings that changed the frozen wire (a `drum_pad` terminal; addresses-as-values). Freezing on an incomplete census bakes in a gap that forces a re-flip later — when the user asks "is there a 6th/7th hiding?", that IS the census, do it. Reinforces *Validate Before Propagating* + *Structural Awareness*.**

## Never use `is` for Live API object identity

**When a handler creates a Live API object and then needs to find its index or reference, NEVER scan for `obj is new_obj` against `song.X` / `track.X` — Live re-wraps API objects on every property access. The scan returns False even for the same underlying Live object, and the handler silently fails or returns a result missing a field.**

## Live API: trust the side effect, not the getter readback

**When writing a Live property (especially anything bound to transport — `current_song_time`, anything that affects the audio thread), do NOT verify success by reading the same property back in the same callback. Verify by inspecting the actual side effect (e.g., `song.cue_points` after a `set_or_delete_cue` toggle).**

## An honest read-back of the wrong property is the hardest bug to see

**When a write is supposed to change a BEHAVIOUR, verify the behaviour, not the property you wrote. A property that reads back exactly what you set proves the write landed — never that it governs what you wanted.** Ask at design time what property the behaviour actually reads, and prefer a check on the realized effect, which holds even when the mechanism is wrong.

## A field that is 1 whenever ANY prior state exists cannot verify THIS pass

**Before trusting an external system's verification flag, ask what it reads true for. If it answers about the target's STATE rather than about your OPERATION, it is asymmetric — honest on a virgin target, unconditionally affirmative on one you have touched before — so it verifies the first run and nothing after. Verify with a count the operation itself owns, and state the verdict rather than leaving a reader to derive it from two fields that can disagree.**

## Unit fakes that mirror an *assumed* Live API give false confidence

**Test fakes for Live's Remote Script API must simulate the real API's quirks — not the API's documented or assumed shape. Without an integration smoke test against a real Live process, the unit suite gives a green light to handlers that crash empirically.**

## A recorded "can't" is a dated claim — re-verify (platform OR code) before designing around it

**When a user (or your own reasoning) challenges a recorded limitation, VERIFY it against the live system before defending from the artifact. Two flavors of the same trap:**
- **External platform/LOM verdict** ("X is not supported / forever-manual") — RE-PROBE the platform directly; capability verdicts are VERSION-SENSITIVE (a finding true on an older build can be silently fixed by an update), and the stale "can't" propagates into code, skills, and workarounds as a false premise.
- **Internal stale comment/docstring** asserting a limitation of OUR OWN code — verify against the actual code path, because code outgrows its comments. This session: "Python can't call MCP tools directly" (a docstring in `capture.py`/`capture_cli.py`) was FALSE — the engine already calls Live via `hallucinote_mcp.client.send` (`push_cli`/`pull_cli execute` drive it with no agent), and the false belief had shaped an entire agent-orchestrated capture design (nearly led to building a "new bridge" that already existed).

**Corollary:** treat probe-confirmable platform/API facts as must-verify, not recall. We live-probed `DeviceParameter.default_value` and found it exists but *raises* on some quantized params — a nuance pure reasoning would have missed. (Reinforces *Verify, don't guess*.)

**Corollary (read-SHAPE, not just settability): when a foreign-API field's shape is only documented loosely — or not at all — STUB LOUD (raise) until a real probe pins it; do NOT guess the shape to "unblock."** MICROTUNE (verify-api, 2026-06-19): the Cycling '74 ref typed Live's `TuningSystem.note_tunings` as "dictionary"; we refused to guess and shipped `read.py`'s extraction as a `raise`-ing stub with a fixture test pinning the held contract. When a real tuning (Wendy Carlos gamma) was finally loadable, the probe showed the shape was BOTH simpler AND *different* from the doc — a flat `list[float]` (degree-indexed, unison at `[0]`, period excluded), and `reference_pitch` a standard 12-key anchor, not a dict. A guessed dict-shape would have passed its own unit tests (the fake encodes the guess — see the NODE-ADDR test-trap learning below) while being silently wrong about pitch. The loud stub cost one extra session of waiting for Live; the wrong guess would have cost a corrupted tuning shipped green. Stubbing-loud-until-probed is the cheap insurance.

## A shipped "can't" is a dated snapshot — re-probe a challenged capability verdict before defending it

**When a recorded capability verdict ("can't / not supported / impossible") is challenged and the platform is live, RE-PROBE before citing the artifact — it is a dated snapshot of one build, not a law, and the re-probe costs minutes against a false premise that can span many surfaces. Capability claims must record the build they were verified against; a build-less verdict is untrustable on a later one.**

## Link, don't summarize

**When an artifact needs to reference a fact that lives in another artifact, file, or code path, link to the source — don't restate the fact in this artifact's prose.**

## Human-authoring boundaries split the chunk

**When a chunk's deliverables cross a Claude-cannot-author boundary (binary Max for Live `.amxd`, Logic Pro patch, image asset, anything that requires a visual/proprietary editor), restructure the chunk into two passes BEFORE building. Claude lands a written contract + the driver code + the verification math; the human authors the binary; Claude resumes for verification + Critic.**

## Live parameters are float / int / enum only — strings need an out-of-band channel

**When designing an M4L device's exposed parameters, never assume a "string parameter" can exist as a Live parameter. Live's Remote Script API and automation system only carry float, int, and enum values. `live.text` exposes a string *as a UI element*, but not as something the Remote Script can `set_parameter` against — its parameter type field literally won't accept "Symbol/String".**

## Live's Remote Script API surfaces parameters by short name, not long name

**When writing or driving an M4L device parameter from the Python side (`ableton_device.set_parameter`, `get_parameters`), the parameter address must be the `parameter_shortname` value from the Max patch, NOT the `parameter_longname`. The Remote Script API's `Parameter.name` attribute reads from `parameter_shortname` if set; the long name only appears in Live's UI parameter list for humans.**

## sfrecord~ control API: bare integers (1 / 0), not `record N`

**When driving Max's `sfrecord~` from a patch, use the documented bare-integer left-inlet API: `1` (integer) starts recording, `0` (integer) stops AND finalizes the WAV header in one operation. There is no `close` message, no `stop` message, and no `record 0` stop variant — those are not part of sfrecord~'s API and are either silently ignored or rejected with "doesn't understand". The `record <N>` message is a SEPARATE API for fixed-duration recording (`record 100` = "record for 100 ms then auto-stop"); using `record 1` as if it meant "start recording" produces a 1-millisecond capture, not an indefinite one.**

## M4L Int parameter range capped at 256 — use Float + Unit Style Int

**Live encodes Int-typed `live.numbox` parameter automation as a single byte (0-255), so an Int-typed Live parameter's range can hold at most 256 distinct values. Setting `Range: 11000 11400` on an Int-typed `live.numbox` silently clamps to `11000 11255` in Max's Inspector — the cap is not surfaced as an error, just a quiet snap. Per Max's documentation: "By convention, the Live application uses floating point numbers for its calculations; the native integer representation is limited to 256 values, with a default range of 0-255. When working with Live UI objects whose integer values will exceed this range, the Type attribute should be set to Float, and the Unit Style attribute should be set to Int." Float type removes the 256-step cap; Unit Style = Int renders the float as a whole number in the UI.**

## M4L device source belongs in `Presets/Audio Effects/Max Audio Effect/`, not Remote Scripts

**When installing an M4L `.amxd` into Live, copy it to `<User Library>/Presets/Audio Effects/Max Audio Effect/` and nowhere else. If the same `.amxd` is also present anywhere else under `<User Library>` (e.g., inside the Remote Script's vendored package directory), Live's browser indexes BOTH copies and shows the device twice with the same display name. Users can then accidentally drag a stale copy onto a track and waste hours wondering why their Max edits don't show up — Max's editor saves to the file the device was loaded from, but the running instance is whichever file Live happened to load when the device was dragged from the browser.**

## M4L `[value]` doesn't emit on write — use `[i]` / `[f]` for cold-inlet storage

**Max for Live's `[value]` object in current Max versions stores writes silently — its outlet only emits when banged, not on receive. This breaks any chain that feeds `[value]` and expects downstream consumers to react (cold inlets of `[expr]`, `[gate]` control inputs, `[print]` boxes, etc.). Use `[i]` (int) or `[f]` (float) instead — both emit on every write.** The trade-off is losing named-shared-variable semantics across patchers; for local-only use within a single patcher that doesn't matter.

## M4L `[value <name>]` is GLOBAL-by-name across all device instances — never use for per-instance state

**`[value <name>]` in M4L's bundled Max is a GLOBAL SHARED VARIABLE keyed by `<name>` across the entire Live session. Every `[value foo]` box in every device instance reads/writes the SAME underlying global. Storing per-instance state in `[value <name>]` causes silent cross-instance clobbering: the LAST writer wins; all OTHER instances see that last write when they bang their local `[value]` box. Fix: feed the value DIRECTLY to its consumer at receipt time (no intermediate storage), or use `[zl reg]` / `[coll]` / a `[message]` box scoped to the patcher.**

## M4L `live.toggle` outlet emits int (0/1) directly — no `[== on]` shim needed

**In current Max versions, `[live.toggle]`'s outlet emits int 0 (off) or int 1 (on) directly when its bound Live parameter changes. NOT the symbol "off"/"on". Adding a `[== on]` symbol-to-int converter shim between live.toggle and downstream INVERTS the value, because `[== on]` coerces the symbol arg `on` to int 0 — so `0==0→1` and `1==0→0`. Wire `[live.toggle]` outlet DIRECTLY to downstream `[i]` storage or trigger chains.**

## M4L `live.observer` needs runtime `property <name>` message; outputs bare value

**`[live.observer @property current_song_time]` as a single box with the property as an @attribute silently fails to fire in current Max versions. The `@property` attribute isn't honored at load. Also: when configured correctly, `live.observer` outputs ONLY the value (a bare float/int), not `<property_name> <value>` as some Max documentation suggests — so `[route <prop>]` downstream filters everything out.**

## M4L patcher editor and Live runtime fight over udpreceive — close the editor before testing

**When a Max for Live patcher is open in Max's patcher editor (the window that opens when you click Live's "Edit" button on a device), Max-editor and Live-runtime each have an instance of the patcher. They compete for the `udpreceive` socket binding. Symptoms: multiple "binding to port N" then "bind unsuccessful" console messages; OSC messages reach SOMETHING but unpredictably; `live.observer` may silently not fire; saving the patch doesn't reliably propagate changes to the running instance.**

## M4L device identity is in `device.name`, not `device.class_display_name`

**Every M4L audio-effect device in Live has `device.class_display_name = "Max Audio Effect"` — that's the device CLASS, not the specific .amxd identity. The .amxd filename (sans extension) lives in `device.name`. Code that detects "is this analyzer/device a HallucinoteAnalyzer instance?" by comparing against `class_display_name` will be permanently False for every real M4L device, with no error — just silent always-add behavior. The correct check is `device.name == "<.amxd filename>"` (with `class_display_name == "Max Audio Effect"` as a secondary anchor proving it's an M4L device, not a similarly-named user preset).**

## M4L devices installed under User Library require `preset_query`, not `kind=`, in `ableton_device(action='load')`

**When the device-load handler is given just `kind='<DeviceName>'`, it walks ONLY the built-in `_BROWSER_LOAD_ROOTS = (instruments, audio_effects, midi_effects, drums)` — it does NOT walk `user_library`, `plugins`, `samples`, or `packs`. M4L devices installed via the project's own install skill (e.g. HallucinoteAnalyzer.amxd → `User Library/Presets/Audio Effects/Max Audio Effect/`) live under `user_library` and are therefore invisible to `kind=`-based lookup. The fix is to pass `preset_query={'root': 'user_library', 'pattern': '<DeviceName>', 'path_prefix': [<exact install path segments>]}` instead. `kind` must STILL be passed (it's required by the handler signature) but `preset_query` takes precedence and selects the actual item.**

## M4L `[peakamp~]` is self-clocked via a reporting-interval arg, not banged

**Max's `[peakamp~]` object does NOT reliably emit on bang to its left inlet in M4L's bundled Max runtime, despite some documentation suggesting it should. The canonical control surface is its constructor argument (an int in milliseconds): `[peakamp~ <interval>]` auto-emits the peak + resets every `<interval>` ms. With no constructor arg, the object may default to a state where it doesn't emit at all.**

## M4L `[average~]` has one inlet, not two — window-size message shares the signal inlet

**`[average~]` exposes a single inlet that multiplexes the audio signal (entered via `~` connection) with control messages (entered via non-`~` connection). The window size in samples is set by sending an int message to that SAME inlet — there is no separate right inlet for window configuration despite what some Max object references imply. Max disambiguates by message type: `~` carries signal flow; non-`~` carries control messages, and the two coexist in the same inlet without colliding.**

## M4L `[expr]` function vocabulary is narrow — no conditionals, no min/max; use `[clip <floor> <ceiling>]` upstream for log-of-zero protection

**Max's `[expr]` object in M4L's bundled runtime has a NARROW function vocabulary: `abs, ceil, floor, int, float, exp, log, log10, fact, ln, pow, sqrt, rand, random` + the trig family. It does NOT have `if(cond, then, else)` (returns `function if not found`), does NOT have `max(a, b)` or `min(a, b)` (also `function max not found`), and the C-style ternary `? :` is unreliable. Some Max documentation lists `max()` as an `[expr]` function but it's empirically absent in M4L's bundled Max — do not trust the docs over the runtime. For "compute `log10(x)` but produce a sentinel when x is zero" conversions, clamp the input UPSTREAM with `[clip <floor> <ceiling>]` (a Max control-rate object, space-separated args, single inlet/outlet) and keep the expr as plain arithmetic.**

## Splitting a monolith into a package: the facade contract is every name, private ones included

**When a module grows past ~3kLOC and you split it into a per-domain package, the re-export `__init__.py` is a contract: it must surface EVERY name the old module exposed — public AND private. Before moving anything, grep the whole tree for every name imported from the module (`from x import _helper`, `x.SOME_CONST`, `x._priv`); that list is the contract. The existing test suite is the correctness oracle — a behavior-preserving split adds zero tests and changes zero test files; if a test breaks it's a missing re-export or a circular import, never a reason to touch the test.**

## Pulling enforcement earlier shadows a downstream guard — migrate its tests, keep a bypass backstop

**When you move a validation to an earlier layer (schema CHECK → mutator write-boundary guard), the earlier layer now fires FIRST, so every test that asserted the downstream error is testing a path that no longer runs. Flip those tests to the new (earlier, more specific) error, AND add a raw-bypass test that still exercises the now-shadowed layer — otherwise its coverage silently rots.**

## Variation ops are tiling-safe only on single-cycle motifs

**The motivic variation ops split by input shape: per-note ops (`transpose`, `shift`) are safe on the pre-tiled multi-cycle note lists the generators emit, but `fragment` / `retrograde` / `augment` / `diminish` assume the list is ONE motif cycle. Apply the latter to a single-cycle motif you authored or registered, never to a generator's already-looped output.**

## Generators degrade gracefully on OPTIONAL pads, raise on load-bearing ones

**A drum generator must call `kit.try_pitch_of(...)` (returns None on absence/wrong-sound) for FLOURISH pads — open-hat lifts, crash accents, fills — and skip them when the kit lacks them; reserve the raising `kit.pitch_of` / `kit.<pad>` accessors for LOAD-BEARING pads (kick, snare, closed-hat) whose absence really does mean the pattern is broken. A caller that genuinely requires a flourish pad asserts it up front with `kit.assert_has(...)`.**

## When a capability ships, audit the planning + intent artifacts — stale intent misguides tools

**A new capability (a generator, an axis, an analysis) outpaces the docs and the per-song INTENT artifacts that describe it. When/after shipping, sweep the planning + intent layer (vision, conventions, per-song annotations, intent docs) — stale intent doesn't just read wrong, it can actively MISGUIDE the read-side tools that consume it.**

## Detect a running process with the framework's probe or `pgrep -x` — never `ps | grep name`

**To check whether Ableton Live (or any process) is running, use the framework's own detector (`hallucinote_mcp.install_paths` / `python -m hallucinote_mcp.cli preflight` → `live.is_running`) or `pgrep -x "Live"`. Never `ps aux | grep -c "<name>"` — the grep process's own command line contains `<name>`, so `ps` lists it and the count includes the grep itself (and the shell wrapper), producing a false positive.**

## When the render is blocked, verify compositional changes on the render-free signals — they validate, not just describe

**Audio review (the ear) is the authority for composition, but when the render pipeline is down you are NOT blind: the harmony lint (`theory.lint`, ok/stasis + cross-mode questions), the symbolic melody lens (`tools/melody_lens.py` — NCT share, resolve-by-step, contour, ambitus), and the per-song shape tests together form a real proxy for whether a change COHERED. Use their deltas to validate a change, then mark the result render-gated-to-confirm.**

## The toolkit removes bookkeeping — its absence is never a limit on the art

**When a generator/helper/envelope-kind/device for what the music needs doesn't exist, hand-author it (notes/breakpoints/chains are plain lists) or build the capability — never scope the request down to the toolkit, and never silently substitute a lesser effect. The toolkit removes bookkeeping; it never caps what's authorable. See `docs/song-authoring-conventions.md` -> "The toolkit reduces work — it never limits what you can author".**

## A file-mutating tool that errors mid-run is not a clean no-op — verify, then prefer a deterministic script

**When a file-mutating skill or tool errors mid-run (e.g. the forked `/backlog` skill dying on an API socket error), VERIFY the file's actual state before retrying or proceeding — a crash can leave a partial mutation with real data loss, not a rollback. For bulk structural edits (backlog section-moves, mass reindents, multi-item status flips) prefer a deterministic, idempotent script you can re-verify (parse → transform by id → assert no dupes/leaks) over an LLM-driven multi-edit that can die halfway.**

## A backlog sweep parallelizes when you cluster by file-area and VERIFY-against-current-code before each fix

**To clear a wide tier of independent backlog items at once, run them as file-disjoint clusters in ONE workflow (one agent per area), and make every cluster re-verify the item against the *current* code before editing — backlog file:line refs drift, items get fixed out-of-band, and brief framings can be stale or backwards. Collision rules make the shared tree safe: each agent edits only its area, CREATES new test files (never appends to a shared one), exactly ONE cluster owns `@given`/`@settings` edits, and none touch backlog/change-log/build-plan (the orchestrator reconciles those centrally).**

## A distribution artifact the product needs at install time must be TRACKED — check .gitignore before trusting it

**When a feature depends on a generated file shipping with the product (a lockfile, a vendored manifest, a committed snapshot), verify the file is actually git-tracked before treating it as the guarantee — a broad `.gitignore` rule (`uv.lock`, `*.lock`, `dist/`) can silently make it local-only, so the feature "works on my machine" and breaks on every real install/clone. `git ls-files --error-unmatch <file>` is the one-line check; generating + locally running the artifact proves nothing about whether it ships.**

## A Claude Code plugin's hook/manifest format: verify against the installed plugin cache, not a docs/research agent's guess

**When authoring a plugin artifact whose format is interpreted by the running Claude Code version (a `hooks/hooks.json`, a `plugin.json` field, an MCP-server env block), confirm the exact shape against a *known-working installed plugin in the cache* (`~/.claude/plugins/cache/.../hooks/hooks.json`) — that is ground truth for THIS CC version. A docs/WebSearch/`claude-code-guide` agent can confidently return a plausible-but-wrong shape, and a wrong hook silently never fires (no error), which is the worst failure mode to debug.**

## A plugin MCP server's STARTUP timeout is `MCP_TIMEOUT`, not the per-server `timeout` field

**Claude Code applies a `mcpServers` entry's `"timeout"` field to TOOL EXECUTION, not the
startup/connection handshake. The startup window is governed by the `MCP_TIMEOUT` env var
(milliseconds, default 30000). A plugin manifest cannot set `MCP_TIMEOUT`; the only channel
that reaches a plugin-provided MCP server's spawn is `env` in `~/.claude/settings.json` (or a
trusted project `.claude/settings.json`), which Claude Code injects into spawned subprocesses.
A SessionStart hook CANNOT cover a slow startup either — SessionStart hooks RACE the MCP spawn
and cannot block it. So for a server with a heavy first-run build, the load-bearing fix is a
generous `MCP_TIMEOUT`; a pre-warm hook is best-effort, not the mitigation.**

## Severity-tier surfacing channels at the source, not by location

**When one channel carries both operator-facing signal and internal diagnostics, you can neither surface it wholesale (leaks noise) nor ignore it (drops signal). Split it by severity AT THE SOURCE — give the producer a distinct method per audience — instead of filtering by phase/location at the consumer.**

## A realtime / long-playback MCP action needs a read-timeout policy entry — applied at the layer EVERY recv route shares, not just one

**Any MCP action that holds its wire response open for realtime work (transport playback, a long load, a render) MUST get a read-timeout policy entry — otherwise the default socket timeout fires mid-operation, is classed as a connection error, and discards the action's OWN result. And the policy must live where ALL recv routes consult it: there are TWO independent socket-recv paths to the Remote Script (`server.handle_tool_call`'s agent-forward AND `push_cli`'s direct `client.send`), so a policy entry on one route leaves the other on the bare default. The action's internal wall-clock deadline does not protect the wire; the wire has its own clock, on every route.**

## A green change-log/PR gate is not a pushed gate — re-push after any commit before merging

**`check-change-log-entry` (and the other PR gates) evaluate LOCAL commits, but `gh pr merge` squashes ORIGIN. If you commit anything — especially the change-log entry the gate just forced you to add — AFTER your last `git push` and before `gh pr merge`, re-push first. A gate that passed locally does NOT mean the commit reached the branch the merge will squash.**

## Multi-write Live handlers resolve everything before writing anything

**When an MCP handler performs more than one Live write derived from separate validations (a routing TYPE plus an optional CHANNEL, a load plus a link, etc.), resolve and validate ALL inputs before performing ANY write. A raise that lands mid-sequence leaves Live half-mutated while the agent receives an error response and reasonably assumes nothing changed — a silent state/response divergence.**

## The schema canary checks column PRESENCE, not column DEFINITION

**The dual-declaration convention (every additive column in both `schema.sql`'s CREATE TABLE and `connection.py`'s `_ADDED_COLUMNS` ALTER pass) is only half-guarded: `_check_schema_canary` compares column *names* (`PRAGMA table_info`), never the type/CHECK/FK *text*. A CHECK or FK that differs between the fresh-DB (schema.sql) path and the migrated-DB (ALTER) path ships SILENTLY — fresh and existing DBs then enforce different constraints. Keep the two clauses identical BY HAND; don't trust the canary to catch a drifted definition.**

## A build-plan "match the existing X" instruction can cite a precedent that doesn't exist — read the sibling before mirroring it

**This repo's chunk plans routinely say "mirror Y's pattern" / "match the existing X" (the cross-referencing is a feature — it keeps siblings consistent). But the plan's *characterization* of the cited code can be wrong. Before implementing "match the existing X," open X and confirm it does what the plan claims. Mirroring a misremembered precedent silently propagates the error; following it blindly drops the real requirement.**

## Open an existing song DB through `init_db` (migrate-on-open) — bare `connect()` reads a stale schema and crashes

**The additive-column migration (`_ensure_added_columns`) runs ONLY inside `init_db`. Bare `connect()` opens the DB as-is. So any code path that opens a song DB built by an *earlier* release with bare `connect()` reads it raw — and the first planner/query to touch a column a later schema bump added crashes with sqlite3's `IndexError: No item with that key` (sqlite3.Row's missing-column error). Open existing song DBs via `init_db`, never bare `connect()`.**

## Build-plan chunk headings must be `### Chunk <id>:` (h3 + colon), not `## Chunk X —` (h2 + em-dash)

**`prawduct-hook verify-chunk-refs` resolves the current chunk by anchoring on an h3 heading with a colon (`### Chunk A: …`); a heading authored as `## Chunk A — …` (h2 + em-dash) is invisible to it, so the verifier reports "chunk not found" even when the Status-line title byte-matches the heading. Making the Status line and heading text identical does NOT fix it — the heading LEVEL (`###`) and the `:` delimiter are what the resolver keys on. Write chunk headings as `### Chunk <id>: <name>` from the start.**

**Two consumers, and the stakes are gate-weakening, not cosmetic (2026-07-20).** `lib/critic_mode.py`'s `**Critic mode:**` reader folds onto the same `_chunk_section_lines` walk, so a wrong heading form silently disables per-chunk Critic-mode overrides too — both parsers fail by quietly doing nothing, which is why this went unnoticed from 2026-07-04 to 2026-07-20 despite the learning already existing. **The trap when you REPAIR headings mid-plan:** fixing them wakes the mode reader, and spent `- **Critic mode:** chunk` lines on already-built chunks immediately go live — `infer-critic-mode` starts returning `chunk|plan-override`, which would demote a `Type: cumulative-final` chunk to a Goals-1-3 pass and skip the run the PR gate needs. So after repairing headings: delete the mode pins from chunks that are already built and reviewed, and re-run `prawduct-hook infer-critic-mode` to confirm inference resumed. Also expect the repair to surface previously-invisible broken file refs — `verify-chunk-refs` had never actually run.

## In a git worktree, pin `pythonpath` in pytest config — a bare `pytest` silently tests the PRIMARY checkout

**This repo is installed editable via plain-path `.pth` files (`__editable__.hallucinote*.pth` → `<primary>/src` + `<primary>/hallucinote_mcp/src`). A `pytest` run in a worktree resolves `hallucinote`/`hallucinote_mcp` through those `.pth` entries → it imports the PRIMARY checkout's code, not the worktree's, and reports green against the wrong tree. The trap is silent for edits to EXISTING functions (a no-PYTHONPATH run passes against the old behavior); it only surfaces by accident when a test imports a brand-new symbol (ImportError). Every prawduct hook that shells `python -m pytest` (test-status, test-evidence, the Stop gate) hits this too. Fix structurally: add `pythonpath = ["src", "hallucinote_mcp/src"]` to the ROOT `[tool.pytest.ini_options]` and `pythonpath = ["src", "../src"]` to `hallucinote_mcp/pyproject.toml` (paths are relative to each config's rootdir; pytest front-inserts them so they win over the `.pth`). Then a bare `pytest` is correct-by-default in any worktree, and a no-op in the primary dir. Do NOT `pip install -e` inside the worktree — it repoints the SHARED editable install at the worktree and the live `--plugin-dir` MCP server would start serving worktree code, defeating the isolation. (NODE-ADDR build, 2026-06-15)**

## A handler-signature migration must grep `<handler>(` across ALL source — a wire/sync-scoped consumer census misses in-process callers

**When you change a handler's signature (e.g. NODE-ADDR flipped the device handlers from flat `track_index/device_index/device_path` to a single `node`), the consumers are NOT just the wire schema + the push/pull planners that *build wire args*. Code that calls the handler FUNCTION directly, in-process, also breaks — and a consumer census scoped to "the wire boundary" silently misses them. NODE-ADDR's Explore census mapped actions/handlers/push but missed: `analyzer/setup.py` (loads the analyzer + sets its Port/EmitPort params via `device_handlers.set_parameter_handler`/`load_handler`), `handlers/render.py` (arms analyzers the same way), and the pull planner that *emits* a `get_parameters` wire call. They surfaced only when the FULL suite ran (render/analyzer_setup test files failed with `TypeError: got an unexpected keyword argument 'track_index'`). Lesson: for any handler-signature change, `grep -rn '<handler_name>(' <all source>` (both packages) BEFORE declaring the migration scoped, and run the whole suite — not just the obviously-related test files — to flush out in-process callers. Bonus: a schema-arg-parity canary (a test asserting a planner's emitted args are all registered schema params, like `test_plan_pull_device_parameters_args_match_mcp_get_parameters_schema`) catches producer/schema drift instantly and is worth more than another happy-path unit test. (NODE-ADDR wire flip, 2026-06-15)**

## Load a device INTO a rack chain with `Chain.insert_device`, not `browser.load_item` — and a fake that models an unverified Live mechanism ships broken code GREEN

**Two coupled lessons from the NODE-ADDR chain-load bug (Live-verified 2026-06-15). (1) THE API: `browser.load_item` ONLY ever appends to the *track's main device chain* — setting `rack.view.selected_chain` AND/OR `song.view.select_device(appointed)` does NOT redirect it (verified on a real set: the device silently landed at the track top level, leaving a stray, twice). To load a device into a rack/drum chain at ANY depth, call `Chain.insert_device(<browser display name>, index=-1)` — it takes the same name `kind` already carries (multi-word like "EQ Eight" works), handles empty AND non-empty chains, and returns the new Device. When unsure how a Live operation works, `ableton_probe describe` the object and READ its methods before assuming a mechanism — that is exactly how `insert_device` surfaced after two wrong guesses (`selected_chain`, then `select_device`). (2) THE TEST TRAP — the more dangerous half: this shipped GREEN because the unit fake asserted `rack.view.selected_chain is chain` and then appended to the chain — baking in the assumption that Live honors `selected_chain`, which it doesn't. A fake that encodes how an EXTERNAL system RESPONDS, when that response is the behavior under test, proves nothing until the assumption is operator-verified; cite the operator-verification check in the fake, or treat the green as unproven. The runtime post-condition that FAILS LOUD on a no-op load ("did not append") is the backstop that actually caught it in Live — keep those guards. (NODE-ADDR chain-load fix, 2026-06-15)**

## Presence — even a change-listener — is NOT settability: probe the WRITE path with an actual `set` before classifying a feature buildable

**Across NODE-ADDR Chunks D/E/F, LOM probes turned 2 of 3 "buildable" feature chunks into hard walls — the trap was trusting *presence* (or the settability heuristic) over a real write. (1) A macro `DeviceParameter.name` HAS an `add_name_listener` (the probe-findings settability heuristic says "value-bearing primitive + listener ⇒ read/write"), yet `set …parameters[1].name='x'` raises `AttributeError: property of 'DeviceParameter' object has no setter` — macro custom NAMES are read-only (they ride the preset). The listener heuristic is a HINT, not proof; for anything load-bearing on a schema/handler decision, actually `ableton_probe(action='set', …)` it on a scratch set and read the result (settability "is itself a finding" — the probe tool's own words). (2) Chain key/velocity/chain-select ZONES aren't even present — a `Chain` describe (even on a chain-select selector rack) has no `key_range`/`velocity_range`/`chain_select_range`; the Zone editor is UI-only and `/song-snapshot` can't capture it either ⇒ `UNSUPPORTED_IN_LIVE`. (3) Conversely, macro VALUES needed no new code — they ARE `DeviceParameters` (parameters[1..8]) already authored by the existing `device_parameters` feature. Lesson: for a probe-gated feature chunk, probe the exact WRITE path (a real `set`/method call, not `describe` presence) BEFORE designing schema/handler — it routinely collapses a planned "flip stub→handler" into a one-cell matrix correction (names/zones → wall) or a no-op (values → already covered), saving a handler built against an API that doesn't exist. Use the `client.send` bridge directly (`Request('ableton_probe','set',{path,value})`) when the MCP tool layer is flaky — same transport push/pull use. (NODE-ADDR Chunks D/E/F, 2026-06-16)**

## A param's CAPTURE discriminator must be PROBED on the live witness, not assumed from its name/behavior

**DEV-4P7R (value_raw channel) almost shipped with the wrong discriminator. The bug class is a quantized, non-monotonic-display, non-[0,1]-range device param (Wavetable `LFO 1 S. Rate`: raw 8.0 → "1/2", range [0,21]). I planned to gate the capture/pull auto-emit on `is_quantized` — the natural-seeming signal for "stepped musical-division param." Probing the live witness (`ableton_probe get …parameters[76].is_quantized` on the running swell set) returned **False** — `is_quantized` is False on the very param the fix targets (Live reserves it for params that expose `value_items`; this one is continuous-with-a-step-display). The correct discriminator is structural and probe-confirmed: **raw range ≠ [0,1]** (for any such non-enum param the normalized channel is pushed AS raw and mis-dials, and the display may be non-monotonic, so the raw value is the only always-correct channel). Lesson: before choosing the predicate that routes a param down a capture/push channel, `ableton_probe get` the candidate attribute on the actual witness — a one-call check overturned an assumption that would have made the auto-emit silently never fire on the bug it fixes. Sibling of the NODE-ADDR "presence is not settability — probe the write path" lesson: here it's "the obvious attribute is not the discriminator — probe the read." (DEV-4P7R, 2026-06-17)**

## A bug report's proposed fixes may be PARTIALLY shipped by a later, unrelated feature — check each sub-fix against the code, not just the item's existence

**When picking a backlog bug whose report proposes multiple fixes (1/2/3), grep the CURRENT code against EACH proposed sub-fix before sizing — a later unrelated feature may have already shipped some of them. PSH-3H8M ("perform_batch hangs indefinitely") proposed watchdog + hard-ceiling + pre-perform-reset; ENV-2T9K's tempo-reduction work had since shipped the span-proportional wall-clock CEILING (so it no longer hangs FOREVER) and the reset already did stop+reseek — leaving only the FAST watchdog + the loop/punch clear as the real residual. Same session, RND-2R9K's functional half ("breaks relink") was already shipped by SYN-RENDER-RELINK, leaving only name hygiene. Twice in one session a `stage: ready` item was 60-80% done, and in BOTH the headline severity named the already-mitigated part. Read the code against each sub-claim, reframe the residual honestly, regroom impact — don't rebuild what shipped. Sibling of "ready items may already be shipped" (which is about the WHOLE item); this is the same trap one level down, at the sub-fix. (PSH-3H8M / RND-2R9K, 2026-06-21)**

## A Live-side change OUTSIDE `_FINGERPRINT_PATHS` ships silently — the handshake won't tell you to re-vendor

**When you change Remote-Script-executed code that is NOT under `_FINGERPRINT_PATHS` (`wire/schema/dispatcher/actions/handlers/remote_script`) — e.g. `analyzer/setup.py`, which runs Live-side via `runs_on_worker=True` + `run_on_main` — the server content fingerprint does NOT flip, so `/ableton-mcp-install` and the version handshake report `matched` even against a STALE vendored Remote Script that lacks your change. Do NOT trust the version match to signal that a re-vendor is needed: force it (relaunch dev-mode so running==disk → `/ableton-mcp-install` → reopen Live, which caches Control Surface modules at startup) and say so explicitly in the operator-verification entry, because the usual "fingerprint flips → re-vendor" reminder is silent here. (RND-2R9K, 2026-06-21)**

## Critic-clean is not PR-ready — Critic and the independent PR reviewer catch different bug classes

**When a chunk has passed Critic review, still run the independent PR reviewer before merge and treat both as required, not redundant — Critic evaluates whether the diff itself is correct in isolation, while the PR reviewer's broader lens catches unchanged-but-should-have-changed siblings and edge cases Critic reasoned were "hypothetical" but are actually reachable (the v0.9.0 empty-`display_name` substring bug Critic dismissed as unreachable, the dead `sys.path` shims in PR #133). Skipping either layer reliably lets through what the other would have caught. (Extracted from 2026-05-19 → 2026-06-03 reflections during the PRC-5W2N archive sweep, 2026-07-04)**

## An expensive restart/reload cycle only pays off if you batch every fix into it

**When the next verification step requires an expensive external restart (a Live relaunch, an MCP reconnect/re-vendor, a Max patcher reload), read through the code and identify EVERY fix you can find before triggering the restart, then land them all in one cycle — fix-one/restart/see-what's-next/repeat amortizes very poorly against that cost (batching saved 3 Live-restart cycles in one 2026-05-27 session; three independent sessions that day rediscovered the same rule). (Extracted from 2026-05-27 reflections during the PRC-5W2N archive sweep, 2026-07-04)**

## A structural gate that keeps getting carved around needs escalation, not another carve-out

**When the same broken hook/gate recurs across many PRs or sessions (the `check-operator-verification` ModuleNotFoundError across 6+ PRs; the gitflow base-detection bug that resolved `main` before `develop` biting three times), stop treating each hit as a one-off exception — escalate it to an actual upstream fix, because the accumulating carve-outs are evidence the gate is no longer a trustworthy safety net and every exception trains you to override it. (Extracted from 2026-05-20 → 2026-06-04 reflections during the PRC-5W2N archive sweep, 2026-07-04)**

## A test asserting ambient git state is green on `push:` and red on `pull_request:` — CI checks PRs out DETACHED

**`actions/checkout` checks a `pull_request` event out at the detached merge commit, so `git symbolic-ref --short HEAD` exits non-zero and any branch-name probe legitimately returns nothing; a `push:` run checks out a real branch ref and passes. A test that reads the AMBIENT checkout (`assert "branch" in provenance_metadata()`) therefore passes locally and on every develop push, and only goes red the first time it runs in PR context — this one hid from 2026-05-21 to 2026-07-20. Fix the TEST, not the probe: a best-effort probe dropping a key it genuinely cannot resolve is correct behavior, and "make CI report a branch" would mean inventing a placeholder. Build a throwaway repo (`git init -q` + `-c commit.gpgsign=false commit --allow-empty` + `checkout -b <name>`) and `chdir` into it, so the expected branch is a value the test CONTROLS — that is strictly stronger than asserting against the ambient tree, which only ever proved "the suite runs from some worktree". Same trap in tolerant disguise: `assert "git_sha" in meta or "branch" in meta` survives detached HEAD but still breaks outside a checkout. To verify a fix for this class, reproduce with `git worktree add --detach` and confirm the OLD test fails there first — a local attached checkout cannot tell you anything. (PR #213, 2026-07-20)**

## Guards sharing one unverified premise don't corroborate each other — honour the producer's trust flags

**When several checks all derive from the same source file, their agreement is not independent evidence: an incomplete Hallucinote render yields a SHORT BUT PERFECTLY VALID master WAV, so open clip bounds derive from the truncated length, the post-encode duration check compares against that same derived number, and the non-empty-file check passes — every guard agrees and they are wrong together, publishing a truncated take as the tour's central evidence. Adding another derived check cannot find this class; only reading what the PRODUCER already recorded can. The capture manifest carries `status`, `analyzer_not_terminal` and per-entry `terminal` for exactly this reason ("never measure-and-lie"), so any consumer — especially one whose output is published — must honour them and require an explicit `--allow-incomplete` to override, while treating ABSENCE of the fields as fine, since manifests predating them must stay readable. Generalises: before adding a fourth check derived from an input, ask whether the input's producer already told you not to trust it. (TOUR A3, Critic rev-20260807T011821Z R-13)**

## A comment asserting how an external tool fails is a test, not a comment

**When you write down how a subprocess behaves on a failure path AND build a guard on it, verify the claim — the guard is only as good as an assumption nobody checked. "ffmpeg writes a zero-length file on an out-of-range seek" was wrong: it exits 0, with EMPTY stderr, writing ~428 bytes of valid mp3 header, which sails straight through the file-is-non-empty check written to catch it. The fix was not a better threshold but a different KIND of check (re-measure the encoded duration), and the same shape recurs — a gate sharing its patterns with the mechanism it guards cannot catch that mechanism's blind spot (TOUR A1), and a traceback guard catching only the tool's own exception class misses FileNotFoundError, the likeliest failure at that step (A1, R-14). Pin the external behaviour in a test so a version bump that changes it goes red. (TOUR A3, 2026-08-06)**

## Verify a from-scratch reproduction, not a re-push onto matching state

When testing that something can be rebuilt, push into an EMPTY target, because a
push into state that already matches skips the work and reports OK. Hallucinote's
devices phase diff-reconciles, so every push onto an already-correct Live set had
been skipping the loads entirely; the first push into a fresh set exposed a
preset-shadowing bug and a stale-link permanent halt within minutes. Reading the
code finds neither — the code is correct in the state it usually runs in.
(2026-08-07, TOUR B1)

## A test you have not seen fail is not evidence — plant the failure

For any guard or scanner, verify RED by planting the thing it should catch, not
just GREEN on a clean tree. A repo-wide secret/path scan passed vacuously because
the constant it iterated was `(regex, description)` pairs and the loop called
`.search` on the tuple — it matched nothing, forever, while looking thorough. Also
verify the OVER-drop direction: a scan that flags legitimate fixtures gets deleted
rather than fixed. (2026-08-07, TOUR B1)

## Prose naming a mechanism reads as a decision — DESCRIBED-BUT-UNBUILT

A docstring or design note that says how something works is indistinguishable from
a record that it was built. `build.py` documented an outro pitch-drop as riding a
Shifter envelope; no Shifter and no envelope ever existed, the build ran clean and
the push reported OK. This is the only defect class with no symptoms. When a stage
cannot decide something, mark it explicitly OPEN — never hand it downstream in the
clothes of a decision. (2026-08-07, TOUR B1)

## A required CLI argument can forbid the stage that should supply it

Before concluding a missing step is a discipline problem, check whether the
tooling makes it impossible. Hallucinote never elicited musical requirements
partly because `/song-new`'s scaffold CLI takes tempo, meter and the section list
as REQUIRED arguments — the agent must invent them to run the command, and the
invented values become the song. Ordering forbade the stage; no amount of norm
would have fixed it. (2026-08-07, TOUR B1)

## Check whether a rule describes the tooling before obeying it

The PR skill says a develop-bound change-log entry stays statusless. Following it
made a chunk invisible to this repo's derived views, because only `status=shipped`
feeds them. When a written rule and the implementation disagree, the rule may be
describing a different repo's tooling — verify which, and record the departure
rather than silently matching either. (2026-08-07, TOUR B1)

## A sampler/drum part's note mapping is only verifiable by rendering it

**When a part's instrument is a sampler or drum device, verify its note mapping by RENDERING and checking per-stem RMS. No symbolic gate can see a note sent where nothing is mapped — the clip, the push and the arrangement all report success while the pad stays silent.**

## `skipped (idempotent)` is two different outcomes wearing one word

**When a push reports OK with a phase `skipped (idempotent)`, read the warning block before concluding anything. The same word covers both work-already-done-elsewhere and precondition-probe-failed, and only the warnings separate them.**

## A declared-vs-measured gap has two possible culprits — name which

**When a review lens reports declared-vs-measured drift, record explicitly whether the DECLARATION or the WORK was wrong. Tuning the declaration until the question disappears is gaming the lens, and it leaves no trace that anything was ever off.**

## A correct automation arc is not evidence of an audible result

**When a declared audible gesture "doesn't happen", measure the RENDERED AUDIO before diagnosing the mechanism. A verified-correct automation arc proves the arc and not the sound — the parameter can read back its exact authored value mid-sweep while the stem is bit-exact mono.**

## A "no effect" verdict indicts the probe as much as the device

**When a verification lens reports "no effect", check whether the PROBE can see the effect that device produces. The wrong probe manufactures false negatives that look like real defects — a comb filter changes the stereo picture, so a centroid-only check calls a working flanger unrealized.**

## A criterion built from a symptom COUNT can fail by being satisfied

**When an acceptance criterion is derived from a COUNT of symptoms, re-derive it per-symptom before treating a partial pass as failure. Some of the symptoms may be the tool being right, in which case the count was never the thing to hold.**

## Narrowing a norm right after review finds you violating it is the tell

**When review finds prose or code violating a norm and your first instinct is to narrow the NORM, stop — that is amending the rule to fit your own work, and "the corpus violates it" is evidence about the corpus. Record who actually decided each clause, ship the narrowing as PENDING OWNER VETO rather than as ratified, and let the owner rule. This norm was narrowed twice in one day; only the pending-veto record made the owner's later rejection possible at all.**

## A discriminating test must be run against the examples it is meant to separate

**When you write an operational test for a judgment call, apply it to your own banned AND permitted examples before shipping it. A test that sounds discriminating can invert: "would removing the negated half leave the subject undefined?" cleared "Ableton is the speaker, not the score" — the exact sentence its own row banned — because the remainder is perfectly well defined.**

## A rule restated in N carriers is a rule that will drift in N-1 of them

**When a rule needs recording in a plan, a change-log and its home artifact, restate it ONLY in the home and have the others point at it. Fixing one defective test wording here meant four hand-synced edits; a completed build plan is archived rather than deleted, so its stale copy outlives the source where someone still reads it.**

## An estimator that reports the FIRST threshold crossing is bimodal on multi-lobe material

**When a measurement is the interval between two threshold crossings, anchor BOTH scans on the feature you mean and scan back from it — never forward from a search window's edge. Forward-scanning let an earlier envelope lobe capture a kick's 90 % point, so a 1 % change in that lobe's height moved the reported rise by 28 ms and a uniform mix edit "changed" two sections of ten. A bimodal reading on real material looks exactly like a real difference.**
