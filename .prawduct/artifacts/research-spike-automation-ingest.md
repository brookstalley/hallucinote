# Research Spike — Automation Ingest, Master-Track Control & the Control-Surface API Surface

**Status:** **PROPOSED** (not yet executed). Scoping artifact — defines the questions,
hypotheses, and probe method. Findings feed requirements; no code is designed against
undefined terms here (discovery precedes requirements per the build cycle).
**Date:** 2026-06-12
**Branch context:** raised from the `feature/perform-handler-hardening` work (ENV-8K2R/ENV-2T9K).

---

## ✅ CONSOLIDATED FINDINGS — design-ready (READ FIRST; 2026-06-12)

*The ⚡ blocks below are the chronological probe evidence (with raw measurements); §1–§8 are the
original plan. This section is the authoritative synthesis for design + build. All Live probing
was done; "Stop probing" called 2026-06-12 after the synthesis.*

### The architecture — one spine, four interchangeable sources

Capture mechanisms are **data SOURCES**; the LLM never sees raw data. Full detail in the
**SYNTHESIS ⚡ block** below. In brief:

- **L0 Capture** (interchangeable, chosen by cost/coverage/fidelity) → normalize to breakpoints-in-beats.
- **L1 Mechanical reconciler (NO LLM):** normalize → compare to DB authored envelopes → classify
  {MATCH·DRIFT·MISSING·UNEXPECTED·OVERRIDDEN} → bucket by **track × arrangement-section**.
  Two modes: **VERIFY** (capture vs DB → delta) and **INGEST** (capture → DB via mutators).
- **L2 Summary → LLM:** scales with the *delta*, not the data; musical coordinates, never raw events.
- **Moat:** the DB is the reference frame → capture becomes *reconciliation* → thousands of events
  collapse to a handful of deltas. The MixReport pattern for control data.
- **Seed exists:** `sync/pull/envelopes.py`'s sample→step-detect→curve-merge is the L1 kernel.

### The four capture mechanisms (READ side)

| Mechanism | Reach | Fidelity | In-session? | Needs in-RS code? | Cost | Status |
|---|---|---|---|---|---|---|
| `events_in_range` | **session-clip + same-track ONLY** | lossless (breakpoints + curve) | yes | no (probe verbs) | cheap | ✅ reads confirmed |
| **scrub-read** | anything the engine renders (arr/master/track) | value-exact per sample; resolution = your grid | yes | no (`set`/`get`); in-RS loop = perf only | N round-trips, or 1 in-RS | ✅ proven + characterized |
| **passive telemetry** | whatever gets played | atomic `(time,value)` at engine change-points | yes (rides playback) | **YES** (listeners need a callable) | ~free during a render pass | ◐ designed, unbuilt |
| `.als` XML | everything incl. master/arrangement | lossless (true breakpoints + curve KINDS) | **NO (Live closed)** | no (offline file) | offline parse | ◐ viable (hodel33), unbuilt |

### Write reach (mirror of read — anchors the writing discussion)

- **session-clip, same-track:** `insert_step` (stepped, current) → `create_event` (CURVED, the upgrade).
- **arrangement / master / return / group:** `perform_batch` (gesture recording, ~2.5 Hz, lossy)
  **OR** `.als` XML (lossless, cold). No envelope object exists for these → no third option in-LOM.

### ❌ Dead ends & corrections (things we learned are NOT true / NOT good ideas)

1. **"No breakpoint-enumeration API exists"** (asserted 6/11) — **FALSE.** `events_in_range`
   enumerates losslessly (session clips). Corrected by direct probe.
2. **Event API (`create_event`/`events_in_range`) as an INGEST path** — **FALSE.** Reach is
   session-clip + same-track ONLY; arrangement, master, return, cross-track all raise
   `RuntimeError: Not a session clip or parameter belongs to another track`. It is a session-clip
   *fidelity upgrade*, not an ingest mechanism.
3. **A realtime listener "capture-session" as the INGEST mechanism** — **dropped.** scrub-read does
   in-session ingest with NO shim. Listeners survive only for PASSIVE TELEMETRY (verification) — a
   different job.
4. **Polling `parameter.value` over MCP to sample during playback** — **bad.** Non-atomic
   serialized round-trips → value/time slop (measured: value 0.80 read while position read 0.79).
   Use scrub-read (stopped, atomic) or in-RS capture.
5. **Sending raw captured events to the LLM** — **bad** (thousands of events). MUST pass through
   the L1 mechanical reconciler → delta summary only.
6. **Diffing captured vs *idealized-authored* DB curve** — **bad.** Performed automation is a
   ~2.5 Hz staircase, so it ALWAYS false-flags as DRIFT. Diff vs **expected-rendered** (DB through
   the known fidelity model).
7. **debugpy / attach-to-process into Live's interpreter** — **dead end** (microsoft/debugpy#887).
   The working interactive path is a socket-REPL Remote Script — which Hallucinote already IS.
8. **"Attach to Live's interpreter via project X unlocks new capability"** — **FALSE.** Same
   interpreter, same LOM limits; AbletonOSC / ableton-js / ableton-liveapi-tools hit identical
   walls. A parallel bridge grants no new automation capability.
9. **"Push has a secret master-automation WRITE API"** — **FALSE.** Push records via
   `begin_gesture`/`end_gesture` exactly like `perform_batch`. Master-write parity already existed;
   the real master gap was READ/ingest (now closed by scrub-read) — see ❓ master DEVICE loading.

### Confirmed vs open

- **CONFIRMED:** event-API existence + full reach map; `events_in_range` read; scrub-read (async
  settle, sub-beat resolution, value-exact); `perform_batch` master write; `.als` XML viability.
- **OPEN (probe/build):** `create_event` CURVED-WRITE round-trip (harness-blocked — needs in-RS
  `EnvelopeEvent` construction); passive listener resolution + leak-safe lifecycle; `.als` XML
  schema specifics (clip + arrangement + master envelopes); L1 tolerance / coverage / normalization
  design; **WRITE side: master DEVICE loading — DISPUTED (2026-06-12), re-probe queued.** DEV-2M9K
  shipped a "forever-manual" verdict on the premise that `song.view.selected_track = master`
  *silently refuses* (master "has no selectable session/arranger slot"), and since
  `browser.load_item` targets only the current selection, master loads were gated everywhere
  (handler / render / push all detect-only). **Counter-evidence:** the Push 2 manual ("press
  Master to *select the Main track*" + Add Device targets "the *currently selected track*") and
  the decompiled `Push2/track_list.py` (selects master via a GENERIC `_track_provider.selected_item
  = track` — master is a normal mixable; the ONLY master guard is against mute/solo, NOT
  selection) both indicate master is a normally-selectable track. **Decisive re-probe (do when
  Live is up):** `set song.view.selected_track = {$path song.master_track}` + read-back. If it
  STICKS → DEV-2M9K's premise is wrong → `selected_track = master; browser.load_item(item)` should
  load onto master → master device loading is POSSIBLE and "forever-manual" must be retracted. If
  it genuinely refuses on 12.4 (track_list.py is from Live 10.1 — a version delta is possible) →
  DEV-2M9K stands and `.als` XML write is the only path. Either way, RESOLVE before trusting the
  writing-side recommendation above. (cc SYN-2M9P.)
>
> **✅ RESOLVED — DEV-2M9K REFUTED; master device load+delete WORKS (2026-06-12, live-proven).**
> Full lifecycle on the open **Live 12.4.2** set: `set song.view.selected_track = {$path song.master_track}`
> → read-back `selected_track.name == "Main"` (**the setter STICKS**; old≠new object — NOT the
> silent no-op DEV-2M9K claimed) → `application.browser.load_item(<audio_effects child "Align
> Delay">)` → `master_track.devices` grew `[] → ["Align Delay"]` → `master_track.delete_device(0)`
> → back to `[]`. **Mechanism: `select master → browser.load_item` (identical to every other
> track).** DEV-2M9K's premise ("`selected_track` silently refuses master; no LOM path to load on
> master") is **FALSE on this build** (could be a pre-12.4.x regression since fixed — the original
> test's Live version is unknown). **Blast radius — revisit every surface built on the false
> premise:** `handlers/device.py` (refuses master loads early), `analyzer/setup.py` (master
> analyzer "detect-only" — but it's a MaxDevice and we just loaded a MaxDevice onto master, so
> auto-load should work), `render` setup, `sync/push/devices.py` (master "configure-only").
> **"forever-manual" is RETRACTED.** Minor caveat: proven with one device that happens to be M4L
> (Align Delay); a native-device load (e.g. EQ Eight) is worth one corroborating check, though
> `load_item` is device-type-agnostic. Also resolves the master-WRITE-side recommendation: master
> device authoring is now POSSIBLE in-session, not XML-only. Filed to backlog.

---

> **⚡ Interim live-probe results (2026-06-12, scratch set, Live 12.4.x).** The gating probe
> (Lane 3.1) was run early because the operator had Live up. **Decisive outcome — the
> envelope-event API's reach is now settled, not open:**
> - **The undocumented event API EXISTS and READS.** On the `Envelope` class:
>   `create_event(EnvelopeEvent)`, `events_in_range(t0,t1) -> EnvelopeEventVector`,
>   `delete_events_in_range(t0,t1)`, plus the known `insert_step` / `value_at_time`. `.parameter`
>   is readable. `events_in_range(0,8)` on a one-step envelope returned real `EnvelopeEvent`
>   objects — **lossless breakpoint enumeration is real, not just a symbol.** This corrects
>   the 2026-06-11 claim that "no breakpoint-enumeration API exists."
> - **But it does NOT reach the targets that matter for ingest.** `create_automation_envelope`
>   for master volume on a track's clip → `RuntimeError: Not a session clip or parameter belongs
>   to another track.` The `Envelope` object is only obtainable via a **session clip, for a
>   parameter on that same track.** Master/return have no session clips; cross-track is refused.
> - **Therefore (B) is a *fidelity upgrade*, not the ingest answer.** It can make our existing
>   session-clip read lossless (`events_in_range` replaces `value_at_time` sampling) and our
>   write curved (`create_event` replaces stepped `insert_step`) — a real quality win. But
>   **ingest of master/arrangement automation falls to (C) `.als` XML and/or (A) playback
>   sampling**, because those targets have no `Envelope` to enumerate.
> - **Reach map COMPLETE (2026-06-12):** arrangement clips are **also refused** (same
>   `RuntimeError`, even for the clip's own-track volume). So the `Envelope` object exists for
>   **session clips + same-track params ONLY** — never arrangement, master, return, or
>   cross-track. Since "a song that already has automation" means **arrangement** automation,
>   **the event API does not address ingest at all.**
> - **Harness gap (blocks 3.2):** `create_event` needs an `EnvelopeEvent` *instance* arg, which
>   `ableton_probe`'s `$path` grammar can't construct, and returned `EnvelopeEvent`s have no path
>   to `describe` — so the curved-WRITE probe and EnvelopeEvent shape introspection need a
>   grammar extension or a REPL/handler shim.
>
> **Net effect on the plan:** Lane 3 is **answered** — the event API is a *session-clip
> read/write fidelity upgrade* (lossless `events_in_range` read + curved `create_event` write),
> **NOT** an ingest mechanism. The ingest headline (Lane 1) is therefore **C (`.als` XML) for
> cold/lossless + A (playback sampling) for in-session/lossy** — those are the only two that
> reach arrangement/master. B is reclassified from "candidate ingest path" to "quality lane for
> the automation we already author on session clips.

> **⚡ Interim live-probe results — Lanes A & B (2026-06-12).** Ran after "A and B both."
> - **(A) The "Push way" mechanism is CONFIRMED.** Authored a 2-step session-clip volume
>   envelope (0.30 over beats 0–4, 0.80 over 4–8), fired it, polled the track's
>   `mixer_device.volume`: **`automation_state` flipped 0→1** on play (the engine is driving the
>   param — exactly Push's "automated" signal), and **`value` tracked the full curve** — 0.30 at
>   `playing_position`≈2.89, 0.80 at ≈6.27, vs static 0.85 when stopped. Generalizes to
>   **master/arrangement** (the engine renders all automation into `parameter.value` identically),
>   which is why A reaches what B can't.
> - **(A) ARCHITECTURE FINDING → confirmed by operator (2026-06-12).** The agent-side polls were
>   **non-atomic serialized MCP round-trips**: sample #1 read `value`=0.80 while `playing_position`
>   read 0.79, because the two were read at *different* playhead instants. Operator's call:
>   **push the sampling loop INTO the Remote Script's Python** so cadence is deterministic and not
>   MCP-timing-bound. **This is correct and is the design for Lane 4 (capture-session):**
>   - Best form: **`add_value_listener`** on each target param; in the callback, capture
>     `(current_song_time, value)` **atomically on Live's main thread**. Fires on every
>     engine-driven change → captures the actual rendered change-points (closest to the true
>     breakpoints), not a fixed grid. Literally Push's display mechanism.
>   - Alt form: a **self-rescheduling `schedule_message` task** reading `(time, value)` each tick
>     → deterministic grid; **same primitive Lane 5 needs for the perform WRITE** — so read-capture
>     and write-perform converge on one in-RS scheduled-task machinery.
>   - Plumbing: the MCP call arms listeners → plays the span → accumulates on the main thread →
>     stops/unregisters → returns the whole buffer in ONE response (the `threading.Event` +
>     worker-blocks-on-main pattern `dispatch.py:105` already uses, widened to a playback window).
>   - **Honest ceiling:** in-RS removes the MCP variable, but fidelity is then bounded by the RS
>     tick (~60 Hz / engine buffer) and Live's own gesture thinning (lom-rec doc). Deterministic
>     and far higher-fidelity than MCP polling — but whether it's *lossless* vs the authored
>     breakpoints is an empirical probe, and still below (C) `.als` XML for true lossless ingest.
> - **(B) Read VALIDATED; curved-write BLOCKED on harness.** `events_in_range` reads events
>   losslessly. `create_event` couldn't be probed — it needs an `EnvelopeEvent` *instance*
>   (`EnvelopeEvent(ControlCoefficients|Vector)`, RS-only, no public signature) that the `$path`
>   grammar can't construct. **Unblock = run code that imports the class inside the RS** (a
>   throwaway shim, or B's real handler change). Both need a **full Live quit+reopen** (Control-
>   Surface module cache). Recommendation: **B + the Lane-4 capture-session are ONE in-RS build**
>   (a new branch, plan + Critic) — they share the in-RS-code + Live-reload cost, and a single
>   reload can validate listener resolution (A) *and* `create_event` round-trip (B) together.

> **⚡ Reframe — non-realtime one-shot "dump events X→Y" (operator, 2026-06-12).** Operator:
> *"create a 'dump all events from time X to Y' script, run it in Live's context, then read the
> resulting file/buffer — we don't need truly realtime."* This is sharper than the realtime
> capture-session and **removes the shim/Live-reload need on the READ side**, split by target:
> - **Session-clip automation → already solved, NO shim, NO realtime, NO playback.** A one-shot
>   "dump X→Y" is exactly `events_in_range(X,Y)` (lossless) — and it runs through the EXISTING
>   `ableton_probe` verbs today. (`ableton_automation read_envelope` also reads these, via
>   `value_at_time` sampling — but `events_in_range` is the lossless upgrade, = Lane 3/B read.)
> - **Arrangement / master automation → there are NO events to dump** (no `Envelope` object; reach
>   wall). The one-shot, non-realtime substitute is **SCRUB-AND-READ**: step `current_song_time`
>   across [X,Y] with the transport STOPPED and record `parameter.value` at each step.
>   Deterministic, file-dumpable, prototypable via the existing probe (`set current_song_time` +
>   `get …value`) — **no shim**. **Hinges on ONE untested question: does Live apply automation to
>   `parameter.value` when the playhead is moved while STOPPED?** If yes → the operator's dump
>   approach reaches the hard targets non-realtime. If no → fall back to a single non-interactive
>   playback pass (still one-shot, transport-moving) or (C) `.als` XML.
> - **DECISIVE PROBE — DONE, SCRUB-READ CONFIRMED (2026-06-12).** Laid a known master-volume
>   ramp (0.85→0.40 over beats 0–4) via `perform_batch` (`automation_state`→1), stopped, then set
>   `current_song_time` and read `master…volume.value` at each settled position:
>   **beat 0 → 0.850 · beat 2 → 0.714 · beat 4 → 0.460** (monotonic, tracks the ramp).
>   **Setting `current_song_time` while STOPPED moves the playhead and `parameter.value` updates
>   to the automation value at that position — for MASTER arrangement automation, which has no
>   `Envelope` object.** So the operator's non-realtime "dump X→Y" reaches arrangement/master via
>   **scrub-and-read**, at **arbitrary resolution** (scrub as finely as you like — NOT bound by
>   perform's ~2.5 Hz), **no `Envelope`, no realtime, no RS shim** (works through existing
>   `set`/`get`).
>   - **Async-settle detail:** `set current_song_time` applies ~asynchronously — the immediate
>     `set` read-back is STALE (showed `new=0.0` while the prior value was the real `old`; the
>     next-call read showed the settled position). A scrub loop MUST let the seek settle (a tick)
>     before reading. (Confirmed by `set=4`→stale-0, then `set=2` reporting `old=4.0`.)
>   - **Fidelity caveat:** scrub-read samples the *rendered* value at your scrub grid — a SAMPLED
>     reconstruction (like `value_at_time`), not the original authored breakpoints/curve-type. For
>     ingesting an existing **user-drawn** curve this faithfully captures the drawn shape at
>     whatever resolution you scrub; for true-lossless (actual breakpoints + curve kind), (C)
>     `.als` XML still wins. (My test ramp was perform-recorded, hence already coarse — the
>     0.714@beat-2 vs ideal-linear 0.625 gap is perform fidelity + the volume taper, NOT a
>     tracking error.)
>   - **In-RS loop = optimization, not a requirement.** Via MCP, N samples = N `set`+`get`
>     round-trips (slow for dense dumps). The operator's "run a script in Live's context" is the
>     right optimization: an in-RS scrub loop reads the whole buffer on the main thread and
>     returns in ONE call. But it's a *perf* upgrade — the capability already works through the
>     probe today.
> - **Net (read side, in-session, NO shim required):** ingest of an existing song's automation is
>   now mechanically solved in-session = **`events_in_range` (session-clip-hosted, lossless) ∪
>   scrub-read (arrangement/master, sampled, arbitrary resolution)**. (C) `.als` XML remains the
>   out-of-band lossless option. The realtime capture-session shim (earlier block) is **no longer
>   needed for ingest** — scrub-read replaces it. Only B's `create_event` curved-WRITE still needs
>   in-RS code.

> **⚡ Dense scrub-read pass — RESOLUTION characterized (2026-06-12, option "a").** Sampled the
> same master ramp at a finer grid (transport stopped): **beat 0 → 0.850 · 1.0 → 0.806 · 1.25 →
> 0.714 · 2.0 → 0.714 · 3.0 → 0.552 · 4.0 → 0.460.** Conclusions for the resolution policy:
> 1. **Scrub-read is value-EXACT per point.** It returns the literal rendered `parameter.value`;
>    there is no scrub-introduced error. The ONLY fidelity knob is grid resolution.
> 2. **Sub-beat resolution discriminates.** 1.0 (0.806) vs 1.25 (0.714) are distinct → ≤0.25-beat
>    works; finer is available (limited only by sample count, not by Live).
> 3. **It faithfully exposes the STORED curve.** The 1.25≡2.0 plateau is scrub-read reporting
>    perform's ~2.5 Hz STAIRCASE (a real artifact of how that automation was *written*), not a
>    scrub limit. For a **user-drawn** smooth curve (the real ingest target), fine scrubbing
>    recovers the drawn shape.
> 4. **Cost = round-trips.** 6 points ≈ 10 MCP calls with settle. Whole-song × many params is
>    impractical per-sample over MCP → the in-RS dump loop is the production form (this *quantifies*
>    why the operator's "run a script in Live's context" is right — not a capability gap, a
>    throughput one).
> 5. **Resolution policy:** since per-point is exact, the policy is purely grid choice. An
>    **adaptive** grid (coarse, then refine where the value changes — exactly the existing
>    `value_at_time` step-detector in `sync/pull/envelopes.py`) minimizes samples. Scrub-read
>    imposes NO fidelity ceiling, only a sample-count/runtime tradeoff.
> 6. **v1 verdict:** scrub-read SUFFICES for in-session ingest of automation *values* at a chosen
>    resolution. (C) `.als` XML is needed ONLY to preserve original breakpoint *times* + *curve
>    kinds* losslessly — a fidelity upgrade, NOT a v1 blocker.

> **⚡ New capability — PASSIVE automation telemetry during playback (operator, 2026-06-12).**
> Operator: the workflow *already* plays the song over and over; passively capture what we can
> during those passes (**buffered in-RS, transmitted at pass-end**) to (i) **sanity-check** that
> automation fired as authored and (ii) **map** where automation is active. This RESURRECTS Lane
> 4's listener/capture-session with a DISTINCT PURPOSE — observation/verification, NOT ingest
> (scrub-read ∪ `events_in_range` own ingest). The two are complementary, not redundant.
> - **Mechanism, two tiers:** `add_automation_state_listener` = cheap **MAP** (which params'
>   automation engages, and when — 0→1→2 transitions, no values); `add_value_listener` = rich
>   **SANITY-CHECK** (atomic `(song_time, value)` at every engine-emitted change, captured on the
>   main thread → the highest-fidelity in-session capture, essentially free during a pass).
> - **Shape:** buffer locally on the main thread, drain in ONE response at pass-end → no per-event
>   round-trips, no MCP-timing slop (timestamps captured atomically at listener-fire, not by
>   polling).
> - **Killer integration:** rides the playback already happening — and specifically can ride the
>   SAME pass as `ableton_render` / `ableton_analysis` (`research-spike-audio-analysis.md`). It is
>   the **control-rate sibling** of the M4L audio telemetry: the analyzer streams audio features
>   over OSC during the render pass; the Remote Script captures automation value/state during that
>   same pass; the two are cross-referenceable (e.g. "the cutoff move at bar 33 ↔ the spectral
>   shift the analyzer saw").
> - **Verification framing:** Hallucinote KNOWS what it pushed (DB envelopes); passive capture
>   observes what the engine RENDERED. Diff = **automation verification** — the control-rate analog
>   of the MixReport's intent-vs-measurement. Strongest on the **EXPECTED(DB)-vs-ACTUAL(rendered)
>   delta**: catches push failures, manual overrides (`automation_state=2`), drift, and automation
>   present in Live but absent from the DB (ingested / hand-edited songs).
> - **Cost / honesty:** this is the ONE thing that genuinely needs the **in-RS shim + Live reload**
>   (listeners take a Python *callable*; the probe can't register one). Now JUSTIFIED by ongoing
>   value, not a one-shot. **Coverage = only what you play** (biased toward replayed/early
>   sections). Captures *rendered* values (post-everything) — exactly right for "what does the
>   audience hear" verification, NOT for lossless breakpoint preservation.
> - **Boundary vs scrub-read (so we don't build overlap):** passive = cheap, broad, continuous
>   **SENTINEL** that flags "something here changed / didn't change as expected"; scrub-read /
>   `events_in_range` = precise on-demand **PROBE** of a specific span. Passive flags; active reads
>   precisely. A natural pipeline: passive flags an anomaly → scrub-read confirms it exactly.
> - **Design Qs (→ requirements before code):** watch-list scope (all params vs a declared list —
>   reuse the analyzer's track/param enumeration); listener lifecycle + leak-safe teardown; drain
>   trigger (transport-stop detection vs explicit MCP drain); buffer cap; the integration point
>   with the render pass.

> **⚡ SYNTHESIS — the unifying architecture (operator + agent, 2026-06-12).** Operator: passive
> capture yields thousands of events; **raw events must NOT reach the LLM** — we need a purely
> MECHANICAL "diff from DB" layer, and the LLM sees only a summary of *what changed, where, on
> which tracks*. This is not a listener detail — it generalizes across ALL four mechanisms and is
> THE architecture. **Capture mechanisms are interchangeable data SOURCES behind one mechanical
> reconciliation layer; the LLM only ever sees an intent-keyed delta summary.**
>
> **Three layers:**
> - **L0 — Capture** (interchangeable; a cost/coverage/fidelity tradeoff invisible above):
>   `events_in_range` (session-clip lossless) · scrub-read (arrangement/master, on-demand,
>   sampled) · passive listener telemetry (continuous, rides the render pass) · `.als` XML (cold
>   lossless). All normalize to a common form (per target → breakpoints in beats; sampled sources
>   pass through step-detection first).
> - **L1 — Mechanical reconciler (NO LLM):** normalize → compare to the DB's authored envelopes →
>   CLASSIFY each target {MATCH · DRIFT · MISSING · UNEXPECTED · OVERRIDDEN (`automation_state=2`)}
>   → BUCKET by **track × arrangement-section** (via the DB's section map) → emit a compact
>   structured report.
> - **L2 — Summary to the LLM:** scales with the **PROBLEM (the delta), not the data volume.** A
>   healthy push → near-zero tokens ("N targets match"). Surfaces only divergence, in MUSICAL
>   coordinates ("Track 3 cutoff, chorus 2 — drifted"), never raw beats/events.
>
> **Why it works (the moat):** the diff is only possible because Hallucinote KNOWS what it pushed
> (the DB). Generic DAW capture has nothing to diff against → must summarize all activity.
> Hallucinote has the score → capture becomes **reconciliation**, and reconciliation collapses
> thousands of events into a handful of deltas. Same "knowing the score collapses inference into
> measurement" as the audio layer — **this is the MixReport pattern for CONTROL data.**
>
> **Invariant (already how the codebase works):** high-volume data NEVER enters LLM context —
> notes are authored as code (`compose-part`), audio is reduced to a MixReport, automation is
> reduced to this summary. The LLM reads intent-keyed findings, not raw streams.
>
> **Two modes of L1 (same L0 sources):**
> - **VERIFY:** capture vs DB → delta summary → LLM (the sanity-check / map).
> - **INGEST:** capture → normalized envelopes → DB via mutators (events fall out) → LLM sees
>   "ingested N envelopes across M tracks," not breakpoints. (An imported song has no DB reference
>   yet → ingest is reduce-and-write, not diff.)
>
> **Already half-built:** `sync/pull/envelopes.py` does `value_at_time` sampling + step-transition
> detection + a curve-preservation MERGE (match captured bp ↔ DB bp by time within tolerance,
> inherit `curve_kind`). **That merge IS the seed of the L1 reconciler** — generalize it into
> classify-and-bucket.
>
> **Hard parts (→ requirements before code):**
> - **TOLERANCE must model KNOWN fidelity.** Else performed automation ALWAYS false-flags as DRIFT
>   — we measured the ~2.5 Hz staircase, so "rendered ≠ idealized-authored" is the NORM for
>   performed arcs. Diff against **expected-rendered** (DB curve through the known
>   capture/perform-fidelity model), not idealized-authored — or use a deliberately coarse band.
> - **COVERAGE.** Passive capture only sees played spans. The reconciler must record which
>   time-ranges were covered and report MISSING only WITHIN them — else unplayed sections
>   false-alarm as "didn't fire."
> - **NORMALIZATION.** Sampled sources (scrub, passive) need step-detection to become breakpoints;
>   `events_in_range` / XML are already breakpoints. Converge to one form before L1.

**Driving asks (user, 2026-06-12):**
1. *Read automation "the way Push devices do"* — we have **no good way to ingest a song that
   already has automation**. (Priority 1.)
2. *Master-track devices & automation* — "Push can do that, why can't we?" (Priority 1.)
3. *Thorough spike across all capabilities* — don't stop at 1 & 2.

**Prior art already on disk (don't re-derive):**
- `docs/research/audio-first-class/lom-recording-automation.md` — TOPIC B is the
  load-bearing reference: binary-docstring-confirmed facts about the 12.4.1 LOM automation
  surface. Several conclusions below are lifted from it (marked **[CONFIRMED — lom-rec doc]**).
- `.prawduct/artifacts/plans/ENV-9P4T/api-notes.md` — the perform-path probe notes.
- The current read path: `src/hallucinote/sync/pull/envelopes.py` (709 LOC) — `value_at_time`
  sampling + step-transition detection + curve-preservation merge.

---

## TL;DR

1. **"Read like Push" is one of THREE candidate ingest mechanisms, and it's the lossiest.**
   The spike's center is a **bake-off** between:
   - **(A) Playback value-sampling** — the literal "Push way": register `add_value_listener`,
     play the transport, sample `parameter.value` as the engine renders. Captures *everything
     the engine plays* including master/arrangement; **lossy** (sample-rate-limited, requires
     real-time playback); reconstructs breakpoints by change-detection.
   - **(B) The undocumented envelope-event API** — `AutomationEnvelope.events_in_range` /
     `create_event` / `EnvelopeEvent(ControlCoefficients|Vector)`. **Lossless** breakpoint
     read *and* curved write. **[CONFIRMED present — lom-rec doc]** but gated to session
     clips; whether it reaches arrangement/master is the single highest-value open probe.
   - **(C) `.als` XML round-trip** — parse the gzipped project file offline (Live closed).
     **Lossless** for *everything* including master/arrangement. Prior art:
     hodel33/ableton-project-processor. **[CONFIRMED viable — lom-rec doc]**.
2. **The Push premise needs a correction.** For *writing* master automation, **Push does
   exactly what our perform path does** — `begin_gesture`/`end_gesture` on encoder touch while
   armed. **[CONFIRMED — lom-rec doc: "Push's encoders call exactly this on touch/release."]**
   Push has no secret envelope-write API. What Push *does* that we don't is **read/display live
   values via listeners** (mechanism A's read side) — and Push never *ingests*, so it dodges
   the problem entirely. So: master *automation write* parity ≈ already achieved (perform path);
   the real gaps are **ingest** (A/B/C) and **live value observation** (listeners).
3. **There may be a lossless write upgrade hiding here too.** We write envelopes today via
   `Envelope.insert_step` only → curves are recorded as hints but applied as `hold`. The
   envelope-event API (B) with `EnvelopeEvent(ControlCoefficients)` may let us write **true
   curved segments**, fixing the stepped-only limitation for session-clip automation.
4. **Recommended sequencing:** offline lanes first (free, no Live) → the one critical Live
   probe (does the envelope-event API reach arrangement?) → then the bake-off decides the
   ingest architecture. Time-box **~3–5 focused days**; most of day 1 is offline.
5. **Probe harness:** prefer `ableton_probe`'s existing `call(+then)` grammar; fall back to a
   *temporary* unconstrained REPL only for the self-rescheduling-chain probe (Lane 5) if the
   grammar can't express it. No new production surface created during the spike.

---

## 1. The reframe — three ingest mechanisms, compared

The user's instinct ("read like Push") is mechanism **A**. The on-disk research already
surfaces **B** and **C** as potentially *lossless* — which A can never be. The spike must
compare all three head-to-head before we commit an ingest architecture.

| Dimension | (A) Playback value-sampling | (B) Envelope-event API | (C) `.als` XML round-trip |
|---|---|---|---|
| **Fidelity** | Lossy (sample-rate ceiling; thinning) | **Lossless** (real breakpoints + curves) | **Lossless** (verbatim FloatEvents) |
| **Reaches master / arrangement?** | **Yes** — engine plays it all | **NO — session+same-track only** (probed 2026-06-12: master refused) | **Yes** — `MasterTrack > AutomationEnvelopes` |
| **Requires Live open?** | Yes (real-time playback) | Yes (RS API) | **No** — Live must be *closed* |
| **Requires transport pass?** | Yes (N× = song length) | No | No |
| **Captures curve shape?** | No (samples values) | **Yes** (`ControlCoefficients`) | **Yes** (event curve data) |
| **In-session (live) vs out-of-band?** | In-session | In-session | Out-of-band (file) |
| **Maturity / prior art** | Push display; our own `value_at_time` cousin | Undocumented, unproven reach | hodel33/ableton-project-processor (in the wild) |
| **Main risk** | Fidelity ceiling; long passes; listener→worker plumbing | Reach gate may exclude arrangement (then useless for ingest) | File-format drift across Live versions; Live-closed constraint |

**Read this table as the spike's spine.** Each row is a measurable question. The bake-off
answers: *which mechanism (or combination) becomes the ingest path?* A likely outcome is a
**hybrid** — C for cold ingest of an existing project file, B for in-session lossless
read/write where it reaches, A as the universal fallback that always works because the engine
always plays.

---

## 2. The Push premise, corrected

> "Push devices can do master devices/automation. Why can't we?"

Decompose "do":

- **Control master *device parameters* + mixer live** — Push sets `master.mixer_device.volume`,
  walks `master.devices[n].parameters`. **We already do this** (perform path supports
  `mixer_volume`/`mixer_pan`/`device_parameter` on master; the snapshot reads master device
  params). No gap.
- **Write master *arrangement automation*** — Push records it via `begin_gesture` →
  encoder-touch value writes → `end_gesture` while `session_automation_record + record_mode`
  are armed. **[CONFIRMED — lom-rec doc.]** **This is identical to our `perform_batch` path.**
  No secret API. So our master-write parity is *already* essentially there — what ENV-8K2R/2T9K
  are hardening *is* the Push-equivalent mechanism. The honest finding to confirm in the spike:
  **we are not behind Push on master automation *write*; we're at parity, modulo fidelity.**
- **Read/display the master's live values** — Push uses `add_value_listener` +
  `add_automation_state_listener` to update its screen as the engine plays. **We do zero
  listener work.** *This* is a real gap — but it's an *observation/UX* gap, not a write gap.
- **Ingest existing master automation as data** — Push **never does this**; it's a controller,
  not an importer. So "the Push way" gives us mechanism A's *read* but not an ingest answer.

**Net:** the spike should explicitly retire the "Push can, we can't" framing for *writing*
master automation (parity confirmed), and redirect the energy to (a) **ingest** and (b) **live
value observation**, which is where the actual daylight is.

---

## 3. Spike lanes

Each lane: **Question → Hypothesis → Method/probes → Offline or Live → Done-when.**
Probes numbered to merge into a build-plan chunk later (mirrors the lom-rec doc's probe list).

### Lane 1 — Ingest existing automation: the three-mechanism bake-off  *(P1, the headline)*

- **Question.** Given a `.als` (or open set) that already contains automation — clip envelopes,
  arrangement automation, master/return mixer automation — how do we faithfully ingest it into
  the Hallucinote DB (through the mutator path, events falling out) so a song authored elsewhere
  becomes editable/re-pushable?
- **Hypothesis.** No single mechanism wins on all axes; the answer is a hybrid keyed on
  *source* (cold file vs open session) and *fidelity need*. C is the strongest cold-ingest
  candidate; B is the strongest in-session candidate *if* it reaches arrangement; A is the
  always-available fallback.
- **Probes.**
  - **1.1 (offline)** — Mine hodel33/ableton-project-processor: confirm the XML paths for clip
    envelopes (not just mixer), the curve/coefficient encoding, and round-trip integrity. Build
    a throwaway parser over one real `.als` with known automation; diff extracted breakpoints
    against what we authored.
  - **1.2 (Live, critical)** — see Lane 3 probe 3.1 (does `events_in_range` reach arrangement).
    The bake-off can't conclude without it.
  - **1.3 (Live)** — Playback-sampling spike: register `add_value_listener` on a known automated
    master-volume param, play 8 bars, capture the sampled curve; compare reconstructed
    breakpoints to ground truth (from 1.1's XML extract of the same set). Quantify the fidelity
    gap and the wall-clock cost.
  - **1.4** — Decide the ingest contract: what shape lands in the DB, how curve data maps to our
    `curve_kind`, how arrangement-time vs clip-local time is normalized (the existing pull path
    already does this translation — reuse it).
- **Done-when.** A written recommendation: the ingest mechanism (or hybrid + routing rule), the
  fidelity each delivers measured against ground truth, and the DB contract sketch.

### Lane 2 — Master-track devices & automation: audit + close the *real* gap  *(P1)*

- **Question.** Concretely, what can Push do with the master track that Hallucinote can't —
  device params, mixer, automation read, automation write — and which gaps are real?
- **Hypothesis (from §2).** Write parity already exists (perform path). The gaps are *read/
  ingest* of master automation (Lane 1) and *live value observation* (Lane 4). Device-param
  read/write on master already works.
- **Probes.**
  - **2.1 (offline)** — Capability matrix: enumerate what the perform path + snapshot + pull
    already cover for `master_track` vs what Push's decompiled `Push2` components touch.
  - **2.2 (Live)** — Confirm perform-path master write actually lands automation
    (`automation_state` 0→1) at mix scale, and that read-back via the Lane 1 winner recovers it.
- **Done-when.** A crisp gap list for master, each tagged real/not-real with the closing
  mechanism. Explicitly states the "Push parity for write = already done" finding (or refutes it).

### Lane 3 — Lossless envelope read **and** curved write via the undocumented event API  *(P1)*

- **Question.** Do `AutomationEnvelope.events_in_range` / `delete_events_in_range` /
  `create_event` + `EnvelopeEvent(ControlCoefficients|Vector)` work, and **how far do they
  reach** — session clips only, or arrangement/take-lane/master too?
- **Hypothesis.** They work on session clips (lets us replace `value_at_time` sampling with true
  breakpoint enumeration *and* replace `insert_step` with curved writes — fixing the stepped-only
  limitation). Reach beyond session clips is the make-or-break unknown.
- **Probes.**
  - **3.1 (Live) — PARTIALLY DONE 2026-06-12.** ✅ API exists; ✅ `events_in_range` reads back
    real `EnvelopeEvent`s; ✅ **reach gate found**: session-clip + same-track only, master/return
    refused (`RuntimeError: Not a session clip or parameter belongs to another track`).
    **Still to probe:** (a) does it reach an **arrangement clip** on a regular track (needs an
    arrangement clip present)? (b) `create_event` round-trip with `ControlCoefficients` to prove
    curved write — **blocked on harness**: needs a way to construct an `EnvelopeEvent` instance
    (probe `$path` grammar can't; use a REPL or a tiny handler shim that imports the class).
    (c) introspect `EnvelopeEvent` fields (time/value/coefficients) — also needs the shim, since
    returned events have no LOM path to `describe`.
  - **3.2 (Live)** — If 3.1 reaches session clips only: prototype swapping the *write* path from
    `insert_step` to `create_event` curved segments; verify curves survive round-trip (kills the
    "curves recorded as hold" limitation for session-hosted automation).
- **Done-when.** A reach map (which target kinds the event API serves) + a go/no-go on adopting
  it for (i) lossless read, (ii) curved write. If it reaches arrangement, **this likely becomes
  the ingest answer and demotes A/C** — flag that loudly.

### Lane 4 — Live value & automation-state listeners (the Push display mechanism)  *(P2)*

- **Question.** Can we adopt `add_value_listener` / `add_automation_state_listener`, and what do
  they buy us beyond ingest?
- **Hypothesis.** Listeners are an *observation* upgrade, not a new write path. Three concrete
  wins: (a) **event-driven settle-verify** replacing the ENV-8K2R timeout-polling
  (`_wait_for_song_flag_on_worker`) — directly de-fragilizes the branch we're on; (b) **live
  manual-edit observation** as an alternative to snapshot-diff pull; (c) the **capture-session**
  primitive Lane 1-A needs.
- **Architecture question (the real work).** Listeners fire on Live's main thread; our MCP model
  is synchronous request/response (worker marshals to main, blocks). Adopting listeners needs a
  **stateful "capture session"**: register listeners → play → accumulate on main thread → stop →
  return buffer, signalling the blocked worker via a `threading.Event` (the pattern
  `dispatch.py:105` already uses). Map this design; it's reusable across A, settle-verify, and
  live-edit observation.
- **Probes.**
  - **4.1 (offline)** — Read the decompiled `Push2` / `pushbase` components for the canonical
    listener register/unregister lifecycle (leak-safety: listeners must be torn down).
  - **4.2 (Live)** — Register a value listener on a param, drive a change, confirm callback
    fires on the main thread and the worker can harvest it.
- **Done-when.** A design note for the capture-session primitive + a recommendation on whether
  to retrofit ENV-8K2R's settle-verify to be event-driven.

### Lane 5 — `schedule_message` cadence: retire the ENV-2T9K tempo hack  *(P2)*

- **Question.** Is the ~2.5 Hz perform ceiling a Live limit or an artifact of the worker
  `run_on_main` + `time.sleep(0.1)` loop? Can a self-rescheduling main-thread
  `schedule_message` chain write denser breakpoints at normal tempo?
- **Hypothesis.** The 2.5 Hz is loop-design, not engine. *However* — the lom-rec doc says "RS
  timers tick ~60 Hz max (100 ms realistic)" and "Live thins/smooths recorded gestures," which
  is **counter-evidence** the cadence may be genuinely capped. This lane must honestly resolve
  the tension, not assume the optimistic read. (ENV-2T9K's plan already records that "adaptive
  tick density was probe-invalidated" — so treat this as *re-opening a probed-closed question
  with a new mechanism*, and respect the prior negative result.)
- **Probes.**
  - **5.1 (Live)** — A self-rescheduling `schedule_message(1, next)` ramp; measure effective
    write rate and `.als`-dumped FloatEvent count per beat vs the current loop. Compare against
    ENV-2T9K's tempo-reduction baseline.
- **Done-when.** A measured answer: either "schedule_message beats 2.5 Hz → ENV-2T9K is
  removable" or "the cap is real, tempo-reduction stays, and here's the FloatEvent evidence."
  Either way the suspected ceiling becomes a measured one.

### Lane 6 — Device & parameter fidelity  *(P3)*

- **Question.** Two smaller capability gaps the original research surfaced: `str_for_value` and
  the `_Generic/Devices.py` bank mapping.
- **Probes.**
  - **6.1 (Live)** — `str_for_value` / `value_items` for faithful enum + display-string readback
    (e.g. "6.50 kHz", Amp `Type` enums) — better than raw float in snapshot/pull/verification.
  - **6.2 (offline)** — `_Generic/Devices.py` bank mapping: how Push groups the "best 8 params
    per page." Relevant to *device representation* — which params are the meaningful ones to
    surface/automate, vs the full flat list. Decide if Hallucinote should know this grouping.
- **Done-when.** Go/no-go on adopting `str_for_value` in the read path; a note on whether bank
  grouping is worth ingesting.

### Lane 7 — Adjacent capability: scripted audio + take-lane recording  *(stretch)*

- **Question.** TOPIC A of the lom-rec doc (clip-slot `fire(record_length=…)`,
  `trigger_session_record`, take lanes, `duplicate_clip_to_arrangement` as a comping substitute)
  is an adjacent capability the user's "across all capabilities" ask invites. In scope only if
  Lanes 1–6 land early.
- **Done-when (if reached).** A one-paragraph verdict on whether scripted recording/comping is
  worth a follow-up spike, citing TOPIC A's confirmed surface.

---

## 4. Prior art to mine (all offline — do these first, no Live needed)

- **hodel33/ableton-project-processor** — the `.als` XML round-trip reference (Lane 1.1, 3-XML).
- **leolabs/ableton-js**, **Ziforge/ableton-liveapi-tools** — socket-bridge Remote Scripts; same
  interpreter we already inhabit (confirms no new *capability*, but worth reading their
  listener/threading patterns for Lane 4).
- **ideoforms/pylive + AbletonOSC** — OSC-mediated read; AbletonOSC issues **#112** (envelope
  modification) and **#205** (master/return) are *still open* per the lom-rec doc — i.e. the
  community has NOT solved in-session arrangement/master envelope I/O. Calibrates expectations:
  if it were easy via the documented API, AbletonOSC would have it.
- **Decompiled `Push2` / `pushbase` / `_Generic/Devices.py`** (gluon Live 12 mirror + local
  install) — the authoritative listener-lifecycle + bank-mapping source (Lanes 4.1, 6.2).
- **`docs/research/audio-first-class/lom-recording-automation.md`** — re-read TOPIC B in full;
  it's the spine. Binary-extraction helpers were in `/tmp/lomdig/` (regenerable).

---

## 5. Probe harness

- **Default:** express probes through `ableton_probe`'s existing `describe/get/set/call(+then)`
  grammar — no new surface, stays inside governance.
- **Fallback:** a *temporary, spike-only* unconstrained `exec` REPL **only** for Lane 5's
  self-rescheduling chain if `call(+then)` can't express a recurring main-thread task. Must be
  removed before any findings ship; never becomes a production surface.
- **`.als` dump** is the ground-truth oracle for *written* shape (FloatEvent count, curve data) —
  used across Lanes 1, 3, 5. The lom-rec doc already maps the XML paths.
- **Offline binary/XML probes** (Lanes 1.1, 4.1, 6.2, and parts of 3) need **no Live** — run them
  first to de-risk before any operator-gated reconnect.

---

## 6. Prioritization & sequencing

```
Day 1 (offline, no Live):     Lane 1.1 (.als parser spike) · Lane 3 XML-path study ·
                              Lane 4.1 + 6.2 (decompiled source) · Lane 2.1 (capability matrix)
Day 2 (one Live reconnect):   Lane 3.1 (CRITICAL — does the event API reach arrangement?) ·
                              Lane 1.3 (playback-sampling fidelity) · Lane 2.2 · Lane 4.2
Day 3 (analysis):             Bake-off decision (Lane 1) · master gap verdict (Lane 2) ·
                              event-API go/no-go (Lane 3)
Day 4 (second Live pass):     Lane 5 (schedule_message cadence) · Lane 6.1 (str_for_value) ·
                              Lane 3.2 (curved-write prototype if 3.1 green)
Day 5 (writeup):              Findings doc + requirements hand-off; Lane 7 only if time remains
```

**Critical path:** Lane 3.1 gates everything. If the event API reaches arrangement/master, it
likely *becomes* the ingest answer and reshapes Lanes 1 & 2. Run it as early as the first Live
reconnect allows.

**Batch the Live work** into ~2 operator-gated `/mcp` reconnects (per the project's MCP-reconnect
norm + the ENV-8K2R precedent of batching Live smoke) — don't reconnect per probe.

---

## 7. Risks & honest gaps

- **Lane 3 reach may disappoint.** If the event API is hard-gated to session clips, it doesn't
  help ingest of arrangement/master automation at all — then C (XML) carries cold ingest and A
  (sampling) carries in-session, and the event API is "only" a session-clip read/write upgrade.
  Still valuable, but reframes the headline. *Don't pre-commit the architecture to B.*
- **Cadence lane fights a prior negative.** ENV-2T9K's plan says adaptive tick density was
  *probe-invalidated* and the lom-rec doc cites a ~60 Hz RS timer cap + engine-side gesture
  thinning. Lane 5 must respect that evidence — the new mechanism (self-rescheduling chain) is a
  genuinely different lever, but if it also caps out, the honest result is "tempo-reduction
  stays." Budget for a negative result.
- **`.als` XML is version-fragile and Live-must-be-closed.** A schema that drifts across Live
  releases is ongoing maintenance; the closed-set constraint makes it out-of-band (can't run
  mid-session). Fits cold ingest, not live sync.
- **Listener plumbing is real architecture, not a free win.** Main-thread callbacks → worker
  harvesting → teardown/leak-safety is a new stateful surface (the capture session). Scope it as
  design, not a drop-in.
- **Undocumented API = no stability contract.** `events_in_range`/`create_event` are absent from
  M4L docs and could change without notice. Adopting B means owning that risk (mitigate: feature-
  detect at runtime, fall back to A).
- **This is a spike, not a build.** Output is *findings + requirements*, not shipped code. The
  throwaway parser/REPL are probes, deleted after. New domain terms surfaced here
  (ingest, envelope-event, capture-session, …) get written as requirements **before** any
  implementation designs against them (tripwire #1).

---

## 8. What "done" looks like for the spike

A findings document (sibling to this one, or an update in place) that delivers:

1. **Ingest recommendation** — the mechanism/hybrid for "ingest a song that already has
   automation," with fidelity measured against `.als` ground truth, and a DB-contract sketch.
2. **Master verdict** — the real gap list, with "write parity already achieved (or not)" stated
   plainly.
3. **Event-API reach map + go/no-go** for lossless read and curved write.
4. **Listener design note** — the capture-session primitive + whether to retrofit ENV-8K2R
   settle-verify.
5. **Cadence answer** — measured, with FloatEvent evidence; ENV-2T9K removable or not.
6. **Device-fidelity calls** — `str_for_value` adopt/skip; bank-mapping worth-it/not.
7. A prioritized **follow-up backlog** (each item routed through `/prawduct:backlog` at an
   appropriate `stage:`), so the spike converts cleanly into planned work.
