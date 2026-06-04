# MIX-3S7P — Design

**Item (mix, M/M, HIGH):** *"play with pan and reverb a bit more, especially in intro
and break. Nothing cheesy — just a little more space. Then snap back to the baseline at
verse/chorus."* Intent: atmospheric sections (intro = dawn polyrhythm cloud; break =
ethereal eureka suspension) get a wider image + wetter Plate tail, returning to baseline
at verse1 + integration.

**Stage:** DESIGN ONLY. No production code, no canonical-doc edits. Proposed deltas are
recorded here as deltas.

---

## 0. Headline — most of this item is ALREADY SHIPPED (honest scope)

This design must open with the truth, not re-derive a solved problem. The item's
"WHY DEFERRED" framing (pan/send envelopes can't span tacet gaps; host-clip strategy
undecided) is **stale**. The work was authored in the canonical private songs repo as
part of the back-half reinvention (`decisions/08`, dated 2026-06-01) and is committed
clean. Verified firsthand (not from a prior summary) by reading:

- **Decision record** — `hallucinote-songs/songs/sun-zone-done/decisions/08-back-half-reinvention.md`
  §5 "Mix: clipping headroom + per-section 'space'" (lines 119–127) names the chosen
  host-clip strategy explicitly.
- **Authoring** — `hallucinote-songs/songs/sun-zone-done/build.py`: `_ATMOSPHERE` table
  (line 1542) + `_author_atmosphere_envelopes()` (line 1554), wired at build line 1892.
- **Test (the lock)** — `hallucinote-songs/songs/sun-zone-done/tests/test_sun_zone_done_build.py`
  `test_atmosphere_envelopes_are_clip_local` (line 243) pins the full clip-local set and
  asserts each range sits entirely inside its host clip → snaps back at the boundary.
- **Song md Deferred note** — `sun-zone-done.md` lines 103–104 records both the shipped
  atmosphere and the one genuinely-open thread.

**Repo topology (load-bearing — see research.md §"Repo topology"):** the framework repo
(cwd, `hallucinote`) has an **empty `songs/` by design** (split, PR #133). The song lives
in the private **`hallucinote-songs`** repo. **`hallucinote-2` is a stale pre-split clone
— ignore it.** Any song-side change goes to `hallucinote-songs`; the engine side stays in
`hallucinote`. Per LINK-DON'T-SUMMARIZE, this design references the song artifacts rather
than re-stating their content.

The VERIFIABLE SIGNAL the item names — *"a decision-record naming the host-clip strategy
+ sun-zone-done authoring per-section pan/send for intro+break that returns to baseline
(verifiable by the breakpoints in the DB)"* — **already exists and is test-locked.** So
the deliverable of THIS item is not "build the atmosphere lanes." It is:

1. **A Prawduct design decision-record** (this file §2) that captures the host-clip
   strategy decision, its alternatives, and the ruler-not-stamp boundary — so the decision
   lives where Prawduct governance reads it, not only in the song's `decisions/08`.
2. **An objective render-gated verification** of the shipped lanes (build-plan Chunk 1–2),
   with the irreducibly by-ear amounts FLAGGED as PENDING by-ear (Live is unattended).
3. **A scoped decision on the one genuinely-open thread** — the song-spanning dynamic
   DubDelay send (§3) — which is the *only* case the clip-local trick does not solve.

This is the GREAT-ART-NOT-SOFTWARE / NO-BACK-COMPAT-TO-THROWAWAY posture applied to
planning: don't re-author shipped, test-locked work to manufacture a chunk. Verify it,
record the decision under governance, and surface the real open edges.

---

## 1. Both-sides shape

The item touches the **mix dimension** (pan + reverb-send automation). Both sides of the
dimension already exist in the framework and are exercised here — this item adds neither
a new authoring primitive nor a new lens; it *uses* both:

### Authoring surface (declares INTENT)

- **DB mutators** `create_envelope` + `replace_breakpoints`
  (`src/hallucinote/db/mutations/devices.py`) — author `send_level` and `mixer_pan`
  envelopes as pure DB breakpoints. No Live instance needed to author; only push+render
  verifies. `create_envelope` is **find-or-create keyed by identity**
  `(song, target_kind, target_track_id, target_send_return_id, parameter_path)`.
- **Song build** declares the *musical intent* — which sections get more space, which
  tracks carry it, the shape (hold vs ramp) — in `_ATMOSPHERE` and
  `_author_atmosphere_envelopes`. The build is the composer's hand; the helpers
  (`_hold`, `_ramp`) are RULERS (they scaffold the breakpoint geometry from the
  section's plan-derived bounds) — they never choose *which* sections, *which* tracks,
  or *how much* space. That choice is the `_ATMOSPHERE` table, authored by hand.

### Measurement lens (MEASURES, never a verdict the composer didn't ask for)

- **`src/hallucinote/audio/automation.py`** `verify_envelope_realization` —
  windows each value-changing breakpoint and reports realized-vs-declared. Confirmed
  firsthand (lines 59–61, 135–151):
  - `send_level` → **measurable** on the return surface (RMS moves in the declared
    direction, ±1.5 dB threshold, `_verify_level`).
  - `mixer_pan` / `mixer_volume` → **post-fader → `measurable=False`** with a teaching
    note. It refuses a false "not realized" verdict (Honest Confidence). **This is the
    structural reason pan width is irreducibly by-ear** (§4).
- **`src/hallucinote/audio/reverb.py`** `measure_return_rt60` — measures the Plate
  return's RT60 from its own ring-out (multi-source-robust), a second objective signal
  that the reverb tail is present and of the declared character.

These are info/coaching lenses: they report what the render did, against what the build
declared. They never emit "your mix is too dry" unbidden. The composer asked "is the
elevated send realized?" → the lens answers that and only that.

### Ruler-not-stamp boundary (explicit)

- A **ruler** here: `_hold` / `_ramp` (geometry scaffolds from section bounds), the
  beat-range host-clip **resolver** (`_resolve_envelope_session_clip`, measures coverage),
  and the two analyzer lenses (measure realized vs declared).
- A **stamp would be**: a helper that *decides* "intro should be 0.92 wet and −0.30 pan
  because that's a nice cloud." That decision lives in the hand-authored `_ATMOSPHERE`
  table and in the by-ear tuning loop — never in a helper. There is **no** "atmosphere
  generator" and this item must not add one. "A little more space, nothing cheesy" is a
  musical judgment; the toolkit measures and hosts it, the composer (human, by ear)
  decides the amount.

---

## 2. DECISION RECORD — host-clip strategy for mixer/send envelopes

**Decision:** For the per-section atmosphere lanes (intro + break pan/send), use
**clip-local session-clip-routed envelopes** — option (b) — NOT a monolithic mixer-host
clip. Each lane's breakpoint range sits entirely inside the per-section organ/lead/steel
clip that already hosts it; the push resolver hosts it there by beat-range coverage and
nowhere else, so the mix **auto-snaps to baseline at the section boundary** (the host clip
ends there, the envelope simply stops existing, the track reverts to its static snapshot
send/pan). This decision is ALREADY MADE and shipped in the song's `decisions/08` §5; this
record captures it under Prawduct governance and the contrast with the Amp-Type precedent.

### Foreign-API facts grounding the decision (verify-api — read source, Live 12.4 LOM)

Confirmed firsthand by reading `sync/push/envelopes.py`, `sync/geometry.py`,
`audio/automation.py`, `db/mutations/devices.py` (full notes in research.md §"verify-api"):

1. `mixer_pan` / `mixer_volume` / `send_level` / `device_parameter` envelopes are accepted
   by Live 12.4 LOM **only on SESSION CLIPS**, routed via a session clip on the target
   track, then `duplicate_to_arrangement` snapshot-copies into the arrangement
   (`envelopes.py` docstring lines 58–65; emitters `_emit_mixer_envelope` line 600,
   `_emit_send_envelope` line 659).
2. The host clip is resolved by **BEAT-RANGE COVERAGE, not by name**
   (`_resolve_envelope_session_clip`, `geometry.py` line 231): the placement whose
   `[start_beats, start_beats + source_clip.length_beats]` covers `[env_min, env_max]`.
   **This is the mechanism that makes the clip-local strategy work** — and it is the
   inverse of the Amp-Type problem.
3. A miss is **warn-and-skip, NON-FATAL** (`envelopes.py` lines 459–472). A too-wide range
   that overruns its host clip degrades to "lane silently doesn't push," surfaced only as
   a warn → **the verification plan must assert no atmosphere lane warns** (a DB shape test
   alone won't catch it; the plan must run `plan_push_envelopes` and assert a
   `write_envelope` ToolCall per lane).
4. Coverage uses the SOURCE clip's `length_beats`; a trimmed placement won't *sound*
   breakpoints past the trim (`geometry.py` 244–251). The author guards this by ending
   every clip-local range at `end - 4.0` beats (`_hold`/`_ramp`, `build.py` 1566–1579).
5. Track-kind gate: only `kind='midi'` tracks host these (master/audio/group refused at
   both mutator and planner). Organ/Drums/Lead/Steel are MIDI → satisfied.

### Alternatives considered

| Option | Mechanism | Verdict | Rationale |
|---|---|---|---|
| **(a) Monolithic mixer-host clip per automated track** (mirror the Amp-Type 736-beat Rhythm Gtr clip) | One song-spanning session clip per atmosphere track, bookended to baseline outside the section | **Rejected** for the atmosphere lanes | The Amp-Type monolith exists because the rhythm gtr's amp character must persist song-wide and the gtr is **voiced in every section** (never tacet) — so a host clip must span the whole arc. The atmosphere lanes are the **opposite** case: they are section-scoped *by intent*, and the per-section clip is a perfect, already-existing host. Adding a monolith would force authoring baseline-bookend breakpoints everywhere the section is silent — bookkeeping the clip-local route gets for free, and it would re-introduce the "what hosts the gap" problem the monolith was invented to dodge. The tacet gap is **not a problem to solve — it is exactly where the envelope is supposed to end.** |
| **(b) Per-section clip-local session-clip-routed envelope segments** | Each lane's breakpoint range fits inside its per-section host clip; resolver hosts by coverage; snaps to baseline at the boundary automatically | **CHOSEN** | Sidesteps the gap entirely. No monolith, no manual baseline bookends, automatic boundary snap. Matches the LOM resolver's beat-coverage semantics exactly. Already shipped + test-locked. |
| **(c) A cleaner mechanism** (e.g. auto-partition a song-spanning envelope into per-section sub-envelopes at push time) | Planner splits one wide envelope into per-host-clip pieces | **Out of scope / deferred** | The planner's warn already names this as "Auto-partition is v1.1 scope (W10-F follow-up)" (`envelopes.py` line 469). It's the right general answer for the *song-spanning dynamic send* (§3), not for the section-scoped atmosphere lanes — those already have a natural host per section, so partitioning would add planner complexity for zero gain here. |

### The two coexisting host-clip patterns (the decision's real content is the contrast)

| Lane | Host strategy | Why this strategy |
|---|---|---|
| **Amp Type** (genre flip) | **monolithic** 736-beat gtr clip | character must persist song-wide; gtr never tacet — needs a song-spanning host |
| **intro/break atmosphere** pan+send | **clip-local** per-section clips | section-scoped *by intent*; auto-snaps to baseline at the boundary; tacet gap is the intended end |
| **break-drift gtr** pan/vol/reverb | **monolithic gtr clip** (bookended to center/baseline) | the gtr IS the source, plays every section, so its lanes ride the existing monolith |

**Trade-offs accepted:**
- **One clip-local timeline per `(track, kind, return, param)` identity.** A track cannot
  be wet via the *same* return in *two different* sections with *different* amounts —
  that would need an envelope-model change (`build.py` comment line 1541;
  `decisions/08` lines 124–127). The author dodged this by allocating identities so they
  don't collide (organ+drums → intro Plate; lead+steel → break Plate; outro extra reverb
  rides the **Room** return — a free identity). This is a **known limitation**, recorded
  in §3.3 below; NOT a bug to fix in this item.
- **Boundary snap is hard, not crossfaded.** Because the host clip ends at the section
  boundary, the mix reverts to the static snapshot send/pan at the boundary edge. For an
  atmospheric *wash that should decay past the boundary* (a reverb tail bleeding into
  verse1), the Plate's own RT60 tail provides the natural decay — the *send* snaps but the
  *reverb tail already in flight* rings out naturally. This is acceptable and intended
  (the dawn cloud's send snaps off; its tail rings into a dry, present verse1). Flag for
  the by-ear pass whether the snap reads as abrupt (§4).

---

## 3. What is genuinely OPEN (the only un-shipped work)

### 3.1 — Song-spanning dynamic DubDelay send (the original tacet-gap case) — STILL DEFERRED

`sun-zone-done.md` line 104: *"A song-spanning dynamic send (dry-reggae / wet-metal
DubDelay across the whole arc) still needs a host-clip strategy (it crosses the
metal-chorus gaps where the source track is tacet) — tracked in MIX-3S7P. The Lead
DubDelay stays a static send for v1."*

This is the **one case the clip-local trick does NOT solve**, because the gesture must
persist *across* sections where the source track is tacet — exactly the shape the item's
"WHY DEFERRED" described. Candidate solutions if/when built:
- **(a) Monolithic host** — a song-spanning host clip on a track that is never tacet
  (e.g. the rhythm gtr monolith already exists; a DubDelay send lane could ride it,
  mirroring the break-drift pattern), OR a dedicated silent host clip spanning the arc.
- **(c) Auto-partition** — the planner's named v1.1 follow-up (`envelopes.py` line 469):
  split the song-spanning envelope into per-host-clip sub-envelopes. The right *general*
  answer, but a planner change in the framework repo.

**This is explicitly punted to post-v1.** The design's recommendation: **do NOT build it
in this item without a user lock.** It is a creative + scope decision ("does the song want
a dry→wet DubDelay arc, or is the static Lead send the v1 intent?") — a high-stakes
creative fork the user has signalled they're deferring ("stays a static send for v1").
Per the precedence rule, the user directed v1 to keep the static send; do not fork that.
The build-plan carries it as a **PENDING user decision**, not a chunk.

### 3.2 — Exact amounts (PENDING by-ear, Live unattended)

All atmosphere/space amounts are first-pass, render-gated (`decisions/08` §"Open /
render-gated" lines 143–149). The DB carries conservative values authored by hand
(`_ATMOSPHERE`, `build.py` 1547–1550): intro organ Plate ramps 0.06→0.92 / pan −0.30;
intro drums Plate 0.08→0.55; break lead Plate 0.42; break steel Plate 0.40 / pan 0.34.
The skank levels were already bumped once from a render that read them inaudible
(`build.py` 1776–1777) — concrete evidence the by-ear loop is live and the amounts are
**not yet final**.

Live is UP but UNATTENDED this run. Per the constraint: **measure objectively, do not
guess the final number.** See §4 for the split of what's measurable vs irreducibly by-ear.

### 3.3 — Model gap (record, do not fix here)

Per-`(track, kind, return, param)` single-timeline identity → a track can't be wet via the
same return in two different sections with different amounts (`build.py` line 1541). Not
blocking the current authoring (identities were allocated to avoid collision). **Flag as a
known limitation; out of scope for MIX-3S7P.** If a future section needs the same track
wet via the same return twice, that's a separate envelope-model item — DISCOVERED-FROM-
FRICTION, not a speculative axis to build now.

---

## 4. Verification strategy — objective vs irreducibly by-ear

Live is UP but UNATTENDED. The split is structural (grounded in §1's lens facts), not a
matter of effort:

### Objective (resolve this run, no human ear)

- **DB-level (no Live):** build the song; assert the intro+break atmosphere envelopes
  exist with breakpoints in the expected beat ranges, on MIDI tracks, ranges entirely
  inside their host clips. This is the item's stated verifiable signal — and it is
  **already test-locked** by `test_atmosphere_envelopes_are_clip_local`. The build-plan
  re-runs that test as the regression gate; it does not re-author.
- **Plan-level (no Live):** run `plan_push_envelopes` against the song DB (with a
  test-created session + the host clips/tracks/Plate-return LINKED — the song tests have
  no session+links fixture; follow the framework precedent `tests/unit/sync/test_push_envelopes.py`)
  and assert **each of the 6 intro+break envelopes (4 `send_level` + 2 `mixer_pan`)**
  produces a `write_envelope` ToolCall (NOT a warn-and-skip), keyed by
  `(target_kind, track, return)` identity — NOT a bare count. The 2 `mixer_pan` lanes
  (intro organ, break steel) route via the host clip independently of their track's send and
  can skip on their own, so they must be asserted separately (pan is half the user's ask). A
  "no arrangement clip … covers beat range" skip in `plan.notes` (the planner has `.calls` +
  `.notes`, NO `.warnings`) is the silent-failure mode (fact #3) and MUST fail the check. The
  current song tests pin DB shape but NOT the plan resolution — this is the gap the
  build-plan closes.
- **Render-level (Live UP):** push → render → `ableton_analysis`. The Plate **send**
  wetness lift in intro+break IS objectively measurable two ways:
  - `automation.py` `_verify_level`: return RMS moves up in the declared direction by
    ≥1.5 dB across each send breakpoint (`measurable=True`).
  - `reverb.py` `measure_return_rt60`: the Plate return's RT60 tail is present and matches
    the declared reverb character.
  Assert the elevated send is realized.

### PENDING by-ear (CANNOT resolve unattended — FLAG, do not guess)

- **Pan WIDTH.** `mixer_pan` is **post-fader → `measurable=False`** in the analyzer
  (`automation.py` lines 61, 135–151, confirmed firsthand). The analyzer can confirm the
  pan envelope is *present in the DB* and *pushed*, but its *audible image width* is NOT
  objectively measurable by the current lens. **Irreducibly by-ear.** Do not tune the
  exact pan amount this run.
- **The aesthetic — "nothing cheesy / a little more space."** Whether the realized amounts
  read as tasteful space (vs gimmicky width / drowning reverb) is a subjective musical
  judgment with no objective metric. **Irreducibly by-ear.**
- **Boundary snap feel.** Whether the hard send/pan snap at the section boundary reads as
  musical (a dry, present verse1 arriving after the wash) or abrupt — by-ear.

The build-plan flags these three as PENDING by-ear: render, surface the measured send
numbers + a note that pan width and the aesthetic are unmeasured, and **hand the amount
back to the human ear.** Do not write a final pan/wetness number this run.

---

## 5. PROPOSED deltas to canonical docs (record only — apply later under Critic governance)

Per the stage constraint, these are PROPOSED, not applied:

- **`hallucinote-songs/songs/sun-zone-done/sun-zone-done.md` `## Deferred` (line 104):**
  no change yet. The DubDelay song-spanning send line is the honest open item; leave it
  until §3.1 is built (which is itself pending a user lock). When built, move it from
  Deferred into the authored list.
- **No framework canonical *model* doc needs a change for the shipped atmosphere lanes.**
  The clip-local routing is an existing, documented capability of `sync/push/envelopes.py`
  — not a new mechanism, so no new model-doc axis. (BOTH-SIDES is already satisfied:
  authoring = mutators + build; lens = `automation.py` + `reverb.py`.)
- **Candidate framework delta IF §3.1 is built via auto-partition:** the planner's
  warn at `envelopes.py` line 469 names auto-partition as "v1.1 scope (W10-F follow-up)."
  Building it would touch the envelope planner and belongs in its **own item** (a
  framework-engine change), not MIX-3S7P's song-side scope. Recorded here as the link, not
  pursued.
- **This design itself** is the Prawduct-governance home of the host-clip decision
  (§2), complementing the song-local `decisions/08` §5. Per LINK-DON'T-SUMMARIZE it
  references that record rather than duplicating it.
