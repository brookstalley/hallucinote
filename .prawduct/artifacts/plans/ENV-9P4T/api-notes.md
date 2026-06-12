# ENV-9P4T — API notes & probe captures

Captures the foreign-API (Ableton Live) findings and the wire-shape design
decisions for the performed-automation-at-mix-scale work. Live-probe captures
are appended as they run; probes that could not run this session (Live bridge
version-mismatched + a 2nd agent holds a song) are listed as **DEFERRED** with
the exact recipe, and mirrored into `.prawduct/operator-verification.md`.

## Chunk 01 — single-pass batched recording

### Decision: replace the single-arc `perform` action with `perform_batch`

The shipped `ableton_automation(action='perform')` records ONE arc per call
(one transport pass per arc). Chunk 01 records all changed perform-routed arcs
in ONE transport pass. The plan offered "extend `perform` or add
`perform_batch`"; chosen: **a new `perform_batch` action that fully supersedes
`perform`, and the single-arc `perform` action + handler are removed.**

- **Why supersede, not coexist:** the planner (`plan_push_performed_automation`)
  is the *only code* consumer of the `perform` action (verified by grep). The
  remaining references were docs — `guides/gaps.md` and
  `skills/ableton-push/SKILL.md` (both updated to `perform_batch`). A 1-arc
  batch is the degenerate case of `perform_batch`, so keeping single-arc
  `perform` would be dead-on-the-planner-path code with a parallel test burden
  — the *no-back-compat-to-throwaway* norm says remove it.
- **Mechanism preserved, not rewritten:** the proven gesture lifecycle
  (save → arm → seek → `begin_gesture` → play → ramp → `end_gesture` → stop →
  restore, beat-space interp, `re_enable_automation` set-wide, async
  `record_mode` settle-poll) is generalized from 1 gesture to N **windowed**
  gestures. The N=1 batch is byte-for-byte the old event sequence — the
  `test_..._exact_gesture_sequence` test pins that the proven path survives.
- **Per-parameter windowing (the new work):** each arc's `begin_gesture` opens
  when the playhead enters its span and `end_gesture` closes at its span exit,
  inside one shared pass over the UNION span `[min(start), max(end)]`. Arcs
  active at the union start open before `start_playing` (matching the single-arc
  order); later arcs open mid-ramp. So a short arc never stamps a flat value
  across the whole song.
- **Per-arc correlation:** each wire arc carries an opaque `arc_id` (the planner
  stamps the envelope id) the handler echoes back per-arc. `apply_push_results`
  gates each arc's performed-state on ITS own `automation_state` — one
  unverified arc never blocks the others, and fingerprint-gating composes
  (only changed arcs enter the batch).
- **Cost model:** wall-clock estimate is the UNION-span integral
  (`_estimate_span_seconds(union_start, union_end)`), not the per-arc sum — one
  continuous pass. The operator-facing overwrite warning moves from `notes`
  (diagnostic, unseen) to **`alert()`** (CLR-A's operator-actionable channel),
  naming every span the pass will record/overwrite (Visible Costs).

### Explicit descope (not a silent drop)

The single-arc action exposed optional `span_start_beats` / `span_end_beats`
(record a span wider than the breakpoints — pre-roll). **The planner never used
them** (it always recorded `[first_bp, last_bp]`), so `perform_batch` derives
each arc's span from its breakpoints and does **not** expose per-arc explicit
span in v1. Re-add if a pre-roll need arises.

### Partial-batch failure stance (v1)

A per-arc runtime error mid-pass (a gesture/value write raising) aborts the
whole pass; the `finally` closes every open gesture and disarms the set (safe),
and no fingerprints are recorded, so all arcs retry next push (safe but
pessimistic — a good arc recorded earlier in the pass is discarded). Granular
per-arc error isolation is a possible later refinement, out of Chunk 01 scope.

### Live probes (verify-api — Chunk 01 step 0) — CONFIRMED 2026-06-11

Ran on a scratch set (Live default: 4 tracks, returns A-Reverb/B-Delay,
120 BPM, 4/4) once the bridge was healed (`/ableton-mcp-install` re-vendored
the Remote Script to `725742c1`, Live restarted, `/mcp` reconnected — clean
calls without `allow_version_mismatch` confirm the handshake). The earlier
blocker (server `c0b443e0` vs Remote Script `b0c3c347`) is gone.

**No `.als` dump was needed.** The recipe called for an `.als` because
arrangement automation has no LOM *envelope* read surface — but two surfaces
that ARE live-readable settle the keystone: each arc's returned
`updates_written` (value-writes only fire while a gesture is open) and
`DeviceParameter.value` traced by `seek` (post-record `re_enable_automation`
leaves the lanes active, so a stopped read at beat B reflects the recorded
value at B). The decisive discovery: **outside a gesture-recorded region the
parameter reverts to its MANUAL value, not the interp-clamped edge** — so a
read before a span distinguishes "windowed (empty here → manual)" from
"flat-stamped (0.2 written here)", which I had feared was `.als`-only.

**Probe 1 — two gesture windows in ONE pass (keystone).** `perform_batch`
`[master_vol [0,64] 0.85→0.4, return1_vol [16,48] 0.2→0.8]`:

| arc | automation_state | span | updates_written | writes/beat |
|---|---|---|---|---|
| master_vol | **1** | [0, 64] | 81 | 1.27 |
| return1_vol | **1** | [16, 48] | 41 | 1.28 |

`union_span_beats [0,64]`, `wall_clock_s 34.32`, `arc_count 2`. Seek-and-read
trace (expected in parens):

| beat | master | return | reads |
|---|---|---|---|
| 8 (pre-span) | 0.798 (0.794) | **0.850 = manual** (a flat-stamp would read 0.2) |
| 32 (mid-span) | 0.625 (0.625) | **0.499 (0.500)** — control: reads DO reflect the return ramp |
| 56 (post-span) | 0.460 (0.456) | 0.789 (≈0.8 held; gesture ended at 48) |

→ **Per-parameter windowing holds in Live.** The return arc wrote nothing
before beat 16 (manual 0.85 read, not 0.2) and `updates_written = 41` ≈ its
32-beat span (a non-windowed return open across the 64-beat union would show
~81, like master) — bounding BOTH edges, including the [48,64] trailing side
the value-read can't isolate. Both arcs recorded in ONE pass; `wall_clock`
≈ the union-span integral (64 beats @120 = 32 s + ~2.3 s settle), NOT the
48 s per-arc sum → single-pass cost model confirmed.

**Probe 2 — achieved breakpoint density.** Falls out of the same pass: the
master arc attempted 81 writes / 64 beats and the return 41 / 32 beats =
**~2.5 Hz each** (32 s and 16 s wall-clock at 120 BPM), within the ENV-7G4K
~2.5–3 Hz single-arc baseline. The per-beat write rate is *identical* under
2-param batching (1.27 ≈ 1.28), so **batching does not starve the main
thread**. This is the handler's *attempted* rate; the seek-read trace
reconstructs both ramps to <0.5% error at the sampled beats, so Live's
*retained* density is adequate. The exact retained breakpoint count
(post-Live-thinning) is the only thing an `.als` would still add — a Chunk 03
fidelity-baseline detail, substitutable with a fine seek-read sweep, and **not
a gate requirement**.

**Probe 3 — safe batch ceiling.** Not stressed (N=2 recorded cleanly with no
misbehavior). The bounded-batch fallback (max M arcs/pass) was the contingency
if many simultaneous open gestures misbehaved; N=2 gives no signal that a
ceiling is needed. A higher-N stress pass remains available if Chunk 02's
10+-track use case ever shows contention — tracked as a non-blocking note.

## Chunk 02 — plain/audio-track perform targets (implementation design)

**Code survey corrected two discovery assumptions.** The discovery framed this
as "almost entirely `_route_for_host_kind` + an authoring choice." Reading the
code found: (1) the perform addressing (`_arc_addressing`, perform.py:116-157)
is **already kind-agnostic** for non-master tracks — it addresses any track via
`track_index`, so the "minimal addressing touch" is **unneeded**; (2) there is a
**second contract surface** the survey missed — the `create_envelope` **mutator**
(`db/mutations/devices.py:846`) **refuses audio hosts** for the host-kind-routed
kinds, so an audio mixer envelope can't even be created. Both surfaces partition
the same way ("single source of truth", classify's docstring), so both change.

**The change (3 source files):**
1. **`classify_envelope_route`** (envelopes.py) gains a `song_id` kwarg and, for
   the track-hosted kinds (`mixer_volume`/`mixer_pan`/`send_level`/
   `device_parameter`) on **midi+audio** hosts, does **infer-from-span** via the
   existing `_resolve_envelope_session_clip` + `_envelope_beat_range`:
   - **covered** by a single session clip → per-clip route: `session_clip`
     (midi) / `refused_audio` (audio — its session-audio-clip push is CLP-AUD2);
   - **uncovered** (no single clip spans it, incl. the song-spanning case) →
     `perform` (continuous arrangement ride).
   - master/group keep `perform` with **no** inference (no session clips to
     ride); no-breakpoint envelopes fall back to the coarse host-kind route.
   Applied uniformly across the 4 host-kind-routed kinds (memory: design
   uniformly), reusing `_route_for_host_kind` as the covered/coarse map.
2. **`create_envelope` mutator** admits `audio` (perform now gives it a route);
   the dead audio-refusal branch in `_envelope_track_kind_refusal` is removed
   (no back-compat to throwaway); comments updated.
3. **`perform.py:282`** threads `song_id` into the classify call.

**Supersession (not silently dropped):** the session-clip resolver's
"no-covering-clip → skip with *(c) partition the envelope by hand … v1.1 scope*"
teaching (`_resolve_and_translate_to_session_clip`, the D1 message) is the very
deferred capability this chunk delivers. Uncovered envelopes now route to
`perform` **before** reaching that emitter, so its no-cover branch becomes an
internal-invariant guard (classify already guaranteed coverage), and the v1.1
teaching is removed (memory: don't keep pre-bumped version labels for shipped
scope). `_warn_non_session_route`'s `refused_audio` teaching is retargeted to
CLP-AUD2 + points at the perform route for continuous rides.

**Test-contract flips (changed requirement, not weakened):** uncovered →
skip-with-warn becomes uncovered → perform. Rewritten with named reasons:
`test_push_envelopes.py` — `test_mixer_volume_skipped_when_no_arrangement_clip`,
`_skipped_when_envelope_exceeds_placement`, send/device `_skipped_when_no_
arrangement_clip_covers`, both `test_d1_teaching_message_*`, and the partition
test (signature + infer assertions); `test_mutations.py` —
`test_create_envelope_mixer_volume_refuses_audio_target` and
`_send_level_refuses_audio_target` flip to **succeed**. New: audio continuous
ride → perform; audio per-clip (covered) → refused_audio/CLP-AUD2; within-clip
midi → session_clip (preserved). Within-clip session-clip path is unchanged.
