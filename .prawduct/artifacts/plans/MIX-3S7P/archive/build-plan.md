---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# MIX-3S7P — Build Plan

Companion to `design.md` (read it first — esp. §0 "already shipped", §2 decision record,
§4 verification split). Item: atmospheric intro+break get wider image + wetter Plate,
snapping to baseline at verse/chorus (mix, M/M, HIGH).

## Requirements Confidence: **High** (with one user-deferred fork)

- **Problem (one sentence):** Intro (dawn cloud) + break (eureka suspension) should have a
  little more space (wider pan, wetter Plate) that snaps back to baseline at verse/chorus.
- **Success (one sentence):** The intro+break clip-local pan/send envelopes exist in the
  DB inside their host clips, push to Live without a warn-and-skip, and the *send* lift is
  objectively realized in the render — with pan width + the "nothing cheesy" amount handed
  to the human ear.
- **Out of scope (one sentence):** Re-authoring the already-shipped + test-locked
  atmosphere lanes; building the song-spanning DubDelay dynamic send (user-deferred to
  post-v1); fixing the per-(track,return)-per-section model gap.

**Why High, not Medium:** the host-clip strategy is decided + shipped + test-locked
(design §0/§2); the foreign-API mechanics are confirmed firsthand (design §2 facts 1–5);
the only unknowns are *by-ear amounts*, which are correctly PENDING-by-ear under the
unattended-Live constraint rather than confidence gaps. **What keeps it from being a free
"done":** the genuinely-open song-spanning DubDelay send (design §3.1) is a creative fork
the user deferred ("static send for v1") — carried as a PENDING user decision, not built.

**Posture:** This item is a VERIFY + RECORD item, not a build-the-feature item. The first
chunk proves the path end-to-end *as it already exists*; later chunks add the missing
verification gate and surface the by-ear amounts. No chunk re-authors shipped work
(NO-BACK-COMPAT-TO-THROWAWAY / GREAT-ART-NOT-SOFTWARE — don't manufacture a chunk to
re-do solved, test-locked work).

**Foreign API:** ableton-live-mcp (push + render + analysis). Mechanics confirmed
firsthand in design §2; each chunk that touches Live re-confirms via `verify-api` step 0.

---

## Chunk 1 — Thin end-to-end slice: prove the shipped lanes resolve onto their host clips (plan-level)

The first chunk validates the *whole architecture* (DB intent → planner host-clip
resolution) without needing Live, closing the one objective gap the existing song tests
leave open: they pin DB breakpoint shape but NOT that the planner resolves each lane onto
a host clip (vs the silent warn-and-skip, design §2 fact #3). This is the cheapest proof
the clip-local strategy actually works through the push planner.

- **Type:** code (song-side test in `hallucinote-songs`)
- **Foreign API:** ableton-live-mcp (planner only — no live instance; the planner is pure
  Python over the DB, so `verify-api` here = read the planner source, not probe Live)
- **Critic mode:** inference (chunk)
- **Done when:**
  0. **verify-api** — read `src/hallucinote/sync/push/envelopes.py`
     (`plan_push_envelopes`, `_emit_send_envelope`, `_emit_mixer_envelope`,
     `_resolve_and_translate_to_session_clip`) + `sync/geometry.py`
     (`_resolve_envelope_session_clip`) + `sync/push/_core.py` (the `PushPlan`
     dataclass) to confirm the exact ToolCall shape (`tool="ableton_automation"`,
     `args.action="write_envelope"`, `target_kind in {send_level, mixer_pan}`,
     `key="envelope:<id>"`) AND the plan result shape. **Confirmed firsthand
     (`_core.py:42–50`): `PushPlan` has `.calls` (list[ToolCall]) and `.notes`
     (list[str]) ONLY — there is NO `.warnings` attribute.** `plan.warn(msg)`
     appends to `plan.notes`; the "no coverage" skip message contains the literal
     substring `"no arrangement clip on track {…} covers beat range"`
     (`envelopes.py:460–471`) and the "not linked" skip contains `"not linked; skipping"`
     (`envelopes.py:477–480`). Assert against `plan.notes`, NOT `plan.warnings`. No Live
     instance needed — the planner is pure Python over the DB. Capture the confirmed
     shape (and the `.notes`-not-`.warnings` correction) in a comment in the new test.
  1. New song-side test (in `hallucinote-songs/songs/sun-zone-done/tests/`,
     e.g. `test_atmosphere_pushes_clip_local`) builds the song, stands up the
     session + links (see step 2), runs `plan_push_envelopes(conn, song_id=built,
     session_id=session)` against the song DB, and asserts that **all 6 intro+break
     atmosphere envelopes (4 `send_level` + 2 `mixer_pan`)** each produce a `write_envelope`
     ToolCall and that NONE of them appears in `plan.notes` as a "no arrangement clip …
     covers beat range" skip. The 6 envelopes, keyed by `(target_kind, track, return)`
     identity (confirmed firsthand against the test windows dict,
     `test_sun_zone_done_build.py:280–285`), are:
     - `("send_level", "04 Organ", Plate)` — intro organ wet-send ramp
     - `("mixer_pan", "04 Organ", None)` — intro organ pan (−0.30)
     - `("send_level", "01 Drums", Plate)` — intro drums wet-send ramp
     - `("send_level", "05 Lead", Plate)` — break lead wet-send
     - `("send_level", "06 Steel", Plate)` — break steel wet-send
     - `("mixer_pan", "06 Steel", None)` — break steel pan (0.34)

     **Assert by identity, NOT by bare count.** A `len(calls) == 6` assertion would PASS
     even if a pan envelope silently warned-and-skipped and some unrelated lane filled the
     count. The test must confirm each of the 6 identities above emitted a `write_envelope`
     call AND did not appear as a "no coverage" skip in `plan.notes`. **The 2 `mixer_pan`
     envelopes route via the host clip independently of the `send_level` on the same track**
     (`_resolve_and_translate_to_session_clip` is called per-envelope), so a pan lane CAN
     warn-and-skip even when the send on its track resolves — they must be checked
     separately. Pan is half the user's explicit ask ("play with pan"); a bare count is
     exactly the silent-failure mode this chunk exists to catch (W1). A warn-and-skip on any
     of the 6 lanes FAILS the test.
  2. **The test MUST stand up a SESSION + Ableton links itself — the existing song tests do
     NOT provide a session+links fixture, so there is nothing to "reuse."** Confirmed
     firsthand: the song's `built` fixture (`test_sun_zone_done_build.py:122–125`) is just
     `build_module.build(reset=True)`; `build()` creates the song DB only — grep of
     `build.py` shows NO `create_ableton_session`, NO `set_ableton_link`/`link_db_to_ableton`,
     and `captured_session.json` is a static mixer snapshot read for baseline values
     (`build.py:73`), NOT a session/link projection. But `plan_push_envelopes(conn, *,
     song_id, session_id)` REQUIRES a `session_id`, and `_resolve_and_translate_to_session_clip`
     warns-and-skips unless (a) an `arrangement_clip` placement on the host track covers the
     range AND (b) the covering session clip has a `get_ableton_link` row in that session
     (`envelopes.py:459–481`). So a test that ran against the unlinked built DB would have
     **every** atmosphere lane skip for the WRONG reason ("not linked") — making the property
     under test (coverage resolves → no "no coverage" skip) unobservable, and risking a false
     pass.
     - **Follow the FRAMEWORK fixture precedent, not a song fixture:**
       `hallucinote/tests/unit/sync/test_push_envelopes.py` stands up the full chain at the
       DB level with no live Live — `create_ableton_session` (:37), `link_db_to_ableton` for
       track/clip/return (:47–49, :73–74, :94–95), `add_arrangement_clip` (:65–68) — and its
       `test_mixer_volume_emits_via_session_clip` (:358), `test_mixer_pan_emits_via_session_clip`
       (:385), and `test_device_parameter_skipped_when_no_arrangement_clip_covers` (:337) prove
       BOTH the emit path and the warn-skip path are DB-testable. Apply that pattern to the
       real **built** song DB.
     - **Concretely, after `built`:** create a session
       (`M.create_ableton_session(conn, song_id=built, name=...)`), then link the host clips,
       their tracks, and the Plate return so the coverage path can resolve. The host clips are
       the per-section clips that already cover the windows the existing DB-shape test pins
       (intro `[0,64)` on Organ/Drums; break `[480,544)` on Lead/Steel — see
       `test_atmosphere_envelopes_are_clip_local:280–285,294`). Link the arrangement_clip
       placements' clips (`link_db_to_ableton(..., db_kind="clip", ...)`), the four host tracks
       (`db_kind="track"`: 04 Organ, 01 Drums, 05 Lead, 06 Steel), and the Plate return
       (`db_kind="return"`) — the `send_level` emitter needs the return link too. After linking,
       the ONLY skip reason that can still fire is "no coverage" — which is exactly the property
       the test asserts is absent.
     - **If the build itself does create a session/links** (re-verify at build time — the
       briefing says re-read code, never trust a summary): the test reuses the build's session
       and only adds whatever links are missing. The test must NOT assume; it must read what
       `built` produced and link only the gap.
  3. Existing song test `test_atmosphere_envelopes_are_clip_local` still passes (regression
     — the DB-shape lock is the contract; do not weaken it). **Scope guard (N1):** that lock
     pins **13** envelopes — the 6 intro+break atmosphere PLUS 4 outro DubDelay throws + 3
     outro Room lifts (windows dict, `test_sun_zone_done_build.py:279–293`). MIX-3S7P is
     intro+break ONLY. The new plan-level test asserts the **6 intro+break** identities
     explicitly; it must NOT use a `set(...)`-equality against the full 13 (that would either
     require linking the outro host clips this item doesn't touch, or fail spuriously). Assert
     membership of the 6, not equality with the whole envelope set.
  4. Full song-side suite passes (`pytest songs/sun-zone-done/tests/` in `hallucinote-songs`).
  5. /critic run and blocking findings resolved.
  6. Committed (in `hallucinote-songs`) and chunk marked [x] in Status.

- **Note on the "not linked" vs "no coverage" distinction (per the learnings rule
  "Detection that replaces a user question must enumerate every state"):** the planner
  warns-and-skips for TWO distinct reasons, both confirmed firsthand in `envelopes.py`:
  "no arrangement clip on track {…} covers beat range" (:460–471) AND "{…} not linked;
  skipping" (:477–480). The test is asserting the *coverage* path resolves, so it MUST
  establish the links first (step 2) — otherwise every lane skips for "not linked" and the
  test proves nothing about the clip-local strategy. The assertion should match the
  "no arrangement clip … covers beat range" substring specifically, so a "not linked"
  misconfiguration in the fixture fails LOUDLY (the test setup is broken) rather than
  masquerading as a coverage pass/fail.

---

## Chunk 2 — Render-level objective verification + surface the by-ear amounts (Live UP)

Push the song to Live, render, and run the analysis lens to objectively confirm the
**send** (reverb wetness) lift is realized, then surface the measured numbers and flag the
unmeasurable amounts for the human ear. This is where the unattended-Live constraint bites:
the send is objectively verifiable; pan width and the aesthetic are not.

- **Type:** code (verification harness / measurement run; may add a small song-side
  render-check helper if one doesn't exist — reuse the existing `/mix-review` /
  `ableton_analysis` path first)
- **Foreign API:** ableton-live-mcp (push → render → analysis — real Live)
- **Critic mode:** inference (chunk)
- **Done when:**
  0. **verify-api + ENTRY GATE (render-pipeline health — this is a GATING step, not a
     footnote).** "Live UP" ≠ "render pipeline healthy": `sun-zone-done.md:99` records that
     the multi-stem capture went stale and a full Live reopen is the current gate. Before any
     objective assertion, this step MUST:
     - (a) Read `src/hallucinote/audio/automation.py` (`verify_envelope_realization`,
       `_verify_level`, `_POST_FADER_KINDS`) + `audio/reverb.py` (`measure_return_rt60`) to
       confirm the metric shapes, and confirm `mixer_pan` comes back `measurable=False`
       (design §1 / §4); confirm the `ableton_render(action='render')` capture path +
       `ableton_analysis` MixReport shape (envelope-realization + reverb sections).
     - (b) **Produce a FRESH multi-stem capture for the song and confirm it is non-stale AND
       correctly keyed.** Run a render and confirm the captures dir contains a capture per
       expected surface (the host tracks 04 Organ / 01 Drums / 05 Lead / 06 Steel and the
       Plate return), keyed by the structurally-stable capture SURFACE ID (`track:N` /
       `return:N`), NOT a stale or empty map. Per the learning "DB-UUID → capture-surface-ID
       lifts must key by surface ID": a capture keyed wrong reads as "no change → not realized"
       and an empty-map render reads as a false PASS via the no-op path — so a healthy,
       correctly-keyed, non-empty capture set is a NAMED PRECONDITION, not assumed.
     - **GATE OUTCOME:** if a fresh, correctly-keyed multi-stem capture CANNOT be produced
       (pipeline stale / Live reopen required / capture map empty or mis-keyed), Chunk 2 is
       **BLOCKED-pending-render**. Record that explicitly (per Principle 5), do NOT push +
       assert against a stale/partial capture, and treat **Chunk 1 (plan-level) as the
       verification floor** — it does not depend on a live render. Do NOT mark Chunk 2 [x] on
       a blocked gate; mark it BLOCKED with the reason and proceed to Chunk 3 (which records
       the by-ear amounts as PENDING-next-clean-render).
     - Capture the confirmed metric shapes + the gate outcome (HEALTHY or BLOCKED-with-reason)
       in the harness/notes.
  1. **Only if step 0's gate is HEALTHY** (else Chunk 2 is BLOCKED — skip to step 4 and
     record the block): push the song to the live session, render the intro window [0,64)
     and the break window [480,544) (or full song if windowing is cheaper to drive), run
     `ableton_analysis` on the captures dir.
  2. **Objective assertion (must pass IF the gate is HEALTHY):** the Plate-send envelopes on
     intro organ, intro drums, break lead, break steel each read `realized=True` via
     `_verify_level` (return RMS up in the declared direction ≥1.5 dB), AND the Plate return
     RT60 is present/of the declared character via `measure_return_rt60`. Record the measured
     dB deltas + RT60. **Confirm the analysis read non-empty, correctly-keyed captures
     (step 0b)** — a `realized=False`/`measurable` field read off an empty or mis-keyed map is
     a false signal, not a real "not realized." If the captures are empty/mis-keyed, this is a
     BLOCKED gate (step 0), not a failing assertion.
  3. **PENDING BY-EAR — surface, do NOT resolve (Live unattended):**
     - **Pan width** (intro organ −0.30, break steel 0.34): `mixer_pan` is post-fader →
       `measurable=False`. Record that the pan envelopes are present + pushed, and that
       audible width is **unmeasured this run**. Do NOT change the pan amounts.
     - **Aesthetic "nothing cheesy / a little more space"**: no objective metric. Surface
       the realized send dB + RT60 numbers and the conservative authored amounts so a human
       can judge on listen-back. Do NOT pick a final amount.
     - **Boundary snap feel** (does verse1 arrive musically-dry after the wash, or does the
       snap read abrupt): by-ear.
  4. Write the measured numbers + the three by-ear flags into the song's render-gated notes
     (the existing `decisions/08` "Open / render-gated" block or the song md verification
     section) — LINK to the decision record, don't restate the strategy.
  5. /critic run and blocking findings resolved.
  6. Committed and chunk marked [x] (HEALTHY gate) OR [BLOCKED] with reason (failed gate) in
     Status.

- **Render-pipeline-blocked path (formalized as the step-0 GATE above, not a footnote):** if
  step 0(b) cannot produce a fresh, correctly-keyed multi-stem capture, the objective render
  assertion is UNVERIFIABLE this run. Per Principle 5, record explicitly: "render-level
  verification BLOCKED on render-pipeline reset / mis-keyed-or-empty capture; DB + plan-level
  verification (Chunk 1) pass; send realization + all by-ear amounts PENDING next clean
  render" rather than faking a green render or reading a false `realized` off an empty map.
  Chunk 1 (plan-level) is the verification floor and does not depend on a live render.

---

## Chunk 3 — Record the host-clip decision under Prawduct governance + reconcile the backlog (doc-only)

Capture the host-clip strategy decision in the Prawduct artifact home (this is the item's
deliverable per design §0), and reconcile the open threads in the backlog so the
user-deferred DubDelay send and the model gap are tracked, not lost.

- **Type:** doc-only
- **Critic mode:** inference (final — last chunk; full review of the decision-record prose
  + cross-check that nothing in the design was silently dropped)
- **Done when:**
  1. The host-clip decision-record (`design.md` §2) is confirmed complete: chosen strategy
     (b) clip-local, alternatives (a) monolith / (c) auto-partition with rationale, the
     two-coexisting-patterns contrast table, trade-offs (single timeline per identity,
     hard boundary snap). LINK to the song's `decisions/08` §5 (do not duplicate it).
  2. Backlog reconciled (`.prawduct/backlog.md`): MIX-3S7P's *atmosphere* scope marked
     done/verified-pending-render; the **song-spanning DubDelay dynamic send** carried as a
     PENDING user decision (creative fork the user deferred — "static send for v1"); the
     **per-(track,return)-per-section model gap** recorded as a separate framework item
     (DISCOVERED-FROM-FRICTION, not built now); the **planner auto-partition** (W10-F /
     `envelopes.py` line 469) linked as the candidate general answer for the DubDelay case.
  3. The three by-ear amounts (pan width, aesthetic, boundary snap) are recorded as
     PENDING-by-ear in the song's render-gated notes (carried from Chunk 2).
  4. No canonical model-doc edit is made (design §5 — none needed; recorded as PROPOSED if
     auto-partition is ever built).
  5. /critic final run and blocking findings resolved; learnings cross-check + backlog
     reconciliation pass.
  6. Committed and chunk marked [x] in Status.

---

## Verification strategy (summary)

Three layers, mapped to the design §4 objective/by-ear split:

1. **DB-level (no Live, already locked):** `test_atmosphere_envelopes_are_clip_local`
   pins breakpoint ranges inside host clips. Regression gate — never weakened.
2. **Plan-level (no Live, NEW — Chunk 1):** with a test-created session + the host
   clips/tracks/Plate-return linked (framework `test_push_envelopes.py` fixture pattern —
   the song tests have NO such fixture), `plan_push_envelopes` produces a `write_envelope`
   ToolCall for each of the **6 intro+break envelopes (4 send_level + 2 mixer_pan)**, asserted
   by `(target_kind, track, return)` identity (NOT a bare count), with NONE appearing as a
   "no arrangement clip … covers beat range" skip in `plan.notes`. Closes the silent-failure
   gap (design §2 fact #3) the DB-shape test can't see — including the 2 pan lanes ("play
   with pan") that can skip independently of the sends on their tracks.
3. **Render-level (Live UP — Chunk 2):** ENTRY-GATED on a fresh, correctly-keyed multi-stem
   capture (step 0b). If HEALTHY: push → render → `ableton_analysis`; the **send** lift is
   objectively realized (`_verify_level` ≥1.5 dB + RT60 present). If the gate fails (stale
   pipeline / empty-or-mis-keyed capture), Chunk 2 is BLOCKED-pending-clean-render and Chunk 1
   is the verification floor — never faked, never read off an empty map.

**Governance checkpoints:** after Chunk 1 (architecture validation — does the planner
actually host the lanes?) and before completion (Chunk 3 final — decision recorded, by-ear
amounts surfaced not guessed, backlog reconciled).

## PENDING by-ear calls (Live unattended — surfaced, NOT guessed)

1. **Pan width** — intro organ pan (−0.30) + break steel pan (0.34): `mixer_pan` is
   post-fader → `measurable=False` (`automation.py`). Audible image width is irreducibly
   by-ear; surface "present + pushed, width unmeasured," hand the amount to the human.
2. **"Nothing cheesy / a little more space" aesthetic** — Plate-send wetness amounts
   (intro organ 0.06→0.92, intro drums 0.08→0.55, break lead 0.42, break steel 0.40): the
   *direction/realization* is objectively measurable; the *tasteful amount* is not. Surface
   the measured send dB + RT60 + the conservative authored values; do not pick a final
   number.
3. **Boundary-snap feel** — whether the hard send/pan snap at the section boundary reads as
   a musically-dry verse1 arrival after the wash, or as abrupt: by-ear.

## Files the plan touches (collision analysis)

- `hallucinote-songs/songs/sun-zone-done/tests/test_atmosphere_pushes_clip_local.py` (NEW,
  Chunk 1) — song-side plan-level test in the **private songs repo**.
- `hallucinote-songs/songs/sun-zone-done/decisions/08-back-half-reinvention.md` and/or
  `sun-zone-done.md` render-gated notes (Chunk 2 — append measured numbers + by-ear flags).
- `.prawduct/artifacts/plans/MIX-3S7P/design.md` (decision record — already written) +
  `.prawduct/backlog.md` (Chunk 3 reconciliation), in the **framework repo** (cwd).
- **No edits** to `src/hallucinote/sync/push/envelopes.py`, `mix.py`, `audio/automation.py`,
  `reverb.py`, or `db/mutations/devices.py` — they are read-only verify-api references; the
  shipped mechanism is correct as-is. **No edits** to `hallucinote-2` (stale clone) or
  `hallucinote/songs/` (empty by design).

## Status

- [x] Chunk 1 — plan-level host-clip resolution test (test-created session + links; all 6
      intro+break envelopes emit, asserted by identity, no "no coverage" skip).
      DONE: `hallucinote-songs` `feature/mix-3s7p-atmosphere-verify` commit 4c01cb8 —
      `songs/sun-zone-done/tests/test_atmosphere_pushes_clip_local.py` (3 tests; full
      sun-zone-done suite 39 passed). Non-vacuity proved: dropping a host-clip link makes
      the break lanes warn-and-skip.
- [BLOCKED] Chunk 2 — render-level send verification (ENTRY-GATED on fresh correctly-keyed
      capture) + surface by-ear amounts. **BLOCKED-pending-render:** Live up but UNATTENDED;
      the multi-stem capture pipeline is the gate (stale; a full Live reopen required per
      `sun-zone-done.md` Verification status). Per Honest Confidence, no render was forced and
      no `realized` flag was read off a stale/empty capture. The 3 by-ear amounts were
      surfaced (NOT guessed) into `decisions/08` "MIX-3S7P verification" — songs commit
      7030c4f. Chunk 1 (plan-level) is the verification floor.
- [x] Chunk 3 — record decision under governance + reconcile backlog (doc-only, final).
      DONE: design §2 decision-record confirmed complete; `.prawduct/backlog.md` reconciled
      (MIX-3S7P → done-verified-pending-render; DubDelay carried as PENDING user fork; new
      MIX-7K2D for the per-(track,return)-per-section model gap; ENV-3M7K linked as the
      auto-partition candidate). Framework branch commit recorded below.

**Context:** MIX-3S7P VERIFY+RECORD complete. Chunk 1 (plan-level) + the pre-existing DB-shape
lock are the verification floor and pass; Chunk 2 (render-level) is BLOCKED-pending a fresh,
correctly-keyed multi-stem capture (Live unattended) — recorded, not faked. Chunk 3 recorded
the host-clip decision under governance and reconciled the backlog. Genuinely open: the
song-spanning DubDelay dynamic send (user-deferred to post-v1 — PENDING user fork, NOT a
chunk; ENV-3M7K is the candidate mechanism) and the 3 by-ear amounts (pan width + aesthetic +
boundary snap — surfaced in `decisions/08`, never guessed). Next: a clean render to close
Chunk 2's objective send/RT60 assertion.

**PENDING user decision (NOT a chunk):** build the song-spanning dynamic DubDelay send now
(monolithic-host or planner auto-partition), or keep the static Lead DubDelay send for v1?
The user signalled "static send for v1" — do not fork without a re-lock.

---

## Review resolution (REVISE → addressed)

The independent reviewer returned REVISE on one BLOCKING finding (B1) and two WARNINGs
(W1, W2). All three are resolved in the spec (requirements strengthened, not weakened); each
load-bearing claim was re-verified firsthand against the actual repos/source.

- **B1 (BLOCKING) — false fixture premise in Chunk 1 step 2.** Re-verified firsthand: the
  song's `built` fixture (`test_sun_zone_done_build.py:122–125`) is just `build(reset=True)`;
  `build.py` creates NO `create_ableton_session` / `link_db_to_ableton`, and
  `captured_session.json` is a static mixer snapshot (`build.py:73`), so there is no
  session+links fixture to "reuse." Chunk 1 step 2 is rewritten to (i) drop the false claim,
  (ii) reference the FRAMEWORK precedent `hallucinote/tests/unit/sync/test_push_envelopes.py`
  (`create_ableton_session` :37, `link_db_to_ableton` track/clip/return :47–95,
  `add_arrangement_clip` :65; emit/skip tests :337/:358/:385), and (iii) require the new test
  to itself create a session and link the 4 host clips + their tracks + the Plate return so
  the only skip reason that can fire is "no coverage" — the property under test. The "not
  linked vs no coverage" note was tightened to match the "no arrangement clip … covers beat
  range" substring so a broken fixture fails loudly rather than masquerading.
- **W1 — "4 lanes" undercount.** Corrected throughout to **6 intro+break envelopes
  (4 `send_level` + 2 `mixer_pan`)**, enumerated by `(target_kind, track, return)` identity
  (verified against the windows dict `:280–285`), with an explicit requirement to assert by
  identity NOT by bare count and to check the 2 pan lanes separately (they route via the host
  clip independently of the send on the same track — pan is half the user's "play with pan"
  ask). Fixed in Chunk 1 step 1, the verification summary, design §4, and Status.
- **W2 — Chunk 2 render assertion likely unverifiable; gate it.** Chunk 2 step 0 is rewritten
  as an explicit ENTRY GATE: confirm the metric shapes AND that a fresh, non-stale,
  correctly-keyed (`track:N`/`return:N`, per the DB-UUID→surface-ID learning) multi-stem
  capture is producible BEFORE any objective assertion. If not, Chunk 2 is BLOCKED-pending-
  render and Chunk 1 (plan-level) is the verification floor. Steps 1–2 are now conditioned on
  a HEALTHY gate and guard against reading a false `realized` off an empty/mis-keyed map; the
  former tail-footnote fallback is folded into the gate.
- **Bonus correction surfaced during verification (not flagged by the reviewer):** the
  build-plan said the test should assert against `plan.warnings`, but `PushPlan` (`_core.py:42–50`)
  has only `.calls` and `.notes` — `plan.warn()` appends to `.notes`. Asserting `.warnings`
  would raise `AttributeError`. Corrected in Chunk 1 step 0/step 1 and design §4.
- **N1 (NOTE) — full-13 set guard added.** Chunk 1 step 3 now states the existing DB-shape
  lock pins 13 envelopes (6 intro+break + 4 outro DubDelay + 3 outro Room) and requires the
  new plan-level test to assert MEMBERSHIP of the 6 intro+break identities, NOT `set(...)`
  equality with the whole envelope set (which would drag in outro host clips this item
  doesn't touch).
- **N2 / N5** were "confirm, no change needed" — the user-deferred DubDelay fork stays a
  PENDING user decision (not forked), and the canonical deltas stay recorded-not-applied. No
  change.
