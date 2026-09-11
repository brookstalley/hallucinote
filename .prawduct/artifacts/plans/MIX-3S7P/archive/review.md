---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# MIX-3S7P — Independent Spec Review (adversarial)

**Reviewer role:** independent adversarial spec-reviewer. I did not write this design.
**Verdict:** **REVISE** (one BLOCKING defect; two WARNINGs; several NOTEs).

I verified the design's load-bearing claims *firsthand against the actual repos and
source*, not from the design's or research's prose (per LINK-DON'T-SUMMARIZE corollary:
"re-read code, never trust prior summarizations of code").

---

## What holds up (verified true — credit where due)

The design's central, scope-defining claim — *"most of MIX-3S7P is already shipped +
test-locked"* — is **TRUE**, confirmed firsthand:

- `hallucinote-songs/songs/sun-zone-done/build.py` `_ATMOSPHERE` (line 1542) +
  `_author_atmosphere_envelopes` (1554) + `_hold`/`_ramp` (1566/1572) exist and author
  exactly the intro+break clip-local pan/send lanes the item asks for. The `end - 4.0`
  guard (1569/1578) is real.
- `tests/test_sun_zone_done_build.py::test_atmosphere_envelopes_are_clip_local` (line 243)
  exists and asserts every non-Amp, non-Rhythm-Gtr envelope's range sits **strictly inside**
  its host-clip window (`wlo <= lo and hi < whi`, line 299) → the boundary snap-back is
  locked. The send-peak floor (`max(vals) >= 0.30`, line 303) is real.
- `decisions/08-back-half-reinvention.md` §5 (lines 119–127) names the clip-local
  host-clip strategy and the `(track, kind, return, parameter)` identity collision-avoidance.
- `sun-zone-done.md` Deferred note (the song-spanning DubDelay still-open line) and the
  `## Open / render-gated` block both exist as cited.
- The framework foreign-API surface is real and matches the facts: `plan_push_envelopes`,
  `_resolve_and_translate_to_session_clip`, `_emit_send_envelope`, `_emit_mixer_envelope`
  (`sync/push/envelopes.py`), `_resolve_envelope_session_clip` (`sync/geometry.py`),
  `_POST_FADER_KINDS = {"mixer_volume","mixer_pan"}` with `measurable=False`
  (`audio/automation.py:61,135`), `measure_return_rt60` (`audio/reverb.py:112`).
- The warn-and-skip path is genuinely **two distinct states** — "no clip covers range"
  (`envelopes.py:459`) and "session clip not linked" (`:476`) — exactly as the plan's
  Chunk 1 note warns, and as the project learning "Detection that replaces a user question
  must enumerate every state" demands. That note is correct and well-grounded.

The VERIFY+RECORD posture (don't re-author shipped, test-locked work to manufacture a
chunk) is the right call and is consistent with NO-BACK-COMPAT-TO-THROWAWAY /
GREAT-ART-NOT-SOFTWARE. The ruler-not-stamp boundary (§1) is correctly drawn: `_hold`/`_ramp`
scaffold geometry from plan-derived bounds; the *amounts* live in the hand-authored
`_ATMOSPHERE` table; no "atmosphere generator" exists or is proposed. Both-sides is
satisfied by an existing dimension (authoring = mutators + build; lens = automation.py +
reverb.py) — correctly, no new axis is invented. By-ear calls (pan width post-fader,
the "nothing cheesy" aesthetic, boundary-snap feel) are flagged PENDING, not guessed,
under the unattended-Live constraint. Requirements Confidence: High is defensible given
the unknowns are by-ear amounts, not "what to build."

---

## BLOCKING

### B1 — Chunk 1 step 2 rests on a FALSE premise about the existing song-test fixture; as written it sends the builder into a dead end.

Chunk 1 step 2 says: *"confirm how the existing song tests stand up a session+links
fixture (the build's `captured_session.json` path) and reuse it."* **There is no such
fixture in the song tests.** Verified firsthand:

- The `built` fixture (`test_sun_zone_done_build.py:122`) is just `build_module.build(reset=True)`.
- `build()` creates the song DB only. Grep of `build.py` shows **no** `create_ableton_session`,
  **no** `set_ableton_link`, **no** session_id — `captured_session.json` is a *snapshot*
  read for static mixer values (`build.py:73`), not a session/link projection.
- `test_atmosphere_envelopes_are_clip_local` runs against `init_db(...)` with no session and
  asserts only DB breakpoint shape — it never calls `plan_push_envelopes`.

But `plan_push_envelopes(conn, *, song_id, session_id)` **requires a `session_id`**, and
`_resolve_and_translate_to_session_clip` warns-and-skips unless (a) an `arrangement_clip`
placement covers the range AND (b) the host clip has a `get_ableton_link` row in that
session (`envelopes.py:473–481`). The song build creates the arrangement_clips but creates
**neither a session nor any ableton_links**. So a song-side test that "reuses the existing
fixture" would feed an unlinked DB → **every** atmosphere lane warns-and-skips for the
"not linked" reason → the test either fails for the wrong reason or (worse) a sloppy
assertion gives a false PASS on the coverage question. The plan's own Chunk 1 note already
worries about exactly this confusion but then points the builder at a fixture that doesn't
exist to resolve it.

**The grounding the plan should have cited instead exists in the FRAMEWORK repo, not the
song repo:** `hallucinote/tests/unit/sync/test_push_envelopes.py` is the precedent. It
stands up the full chain at the DB level with no live Live — `create_ableton_session`
(:37), `set_ableton_link` for track/clip/return (:48,:74,:95), `add_arrangement_clip`
(:65) — and has `test_mixer_volume_emits_via_session_clip` (:358),
`test_device_parameter_track_emits_via_session_clip` (:250), and
`test_device_parameter_skipped_when_no_arrangement_clip_covers` (:337) proving BOTH the
emit and the warn-skip paths are DB-testable. **Chunk 1 is feasible — but only via this
framework fixture pattern, applied to the real built song DB (create a session, link the
4 host clips + their tracks + the Plate return, then assert).** The plan must say so.

**Fix:** Rewrite Chunk 1 step 2 to (i) drop the false claim that the song tests have a
session+links fixture; (ii) reference `tests/unit/sync/test_push_envelopes.py` as the
fixture pattern to follow; (iii) make the test EXPLICITLY create the session and link the
host clips/tracks/Plate-return before calling `plan_push_envelopes`, so the only remaining
skip reason that can fire is "no coverage" — which is the property under test. Without
this, the chunk's verifiable signal ("no warn-and-skip") is unobservable as written:
a builder following step 2 literally cannot stand up the precondition. This is the
"unobservable acceptance criterion / dead instruction" class — BLOCKING per the gate.

---

## WARNINGS

### W1 — "4 atmosphere lanes" undercounts the 6 intro+break ENVELOPES; the assertion target is ambiguous and could silently miss the 2 pan envelopes.

`_ATMOSPHERE` has 4 *table rows* but produces **6 envelopes** for intro+break: intro organ
**send + pan** (2), intro drums **send** (1), break lead **send** (1), break steel
**send + pan** (2). The test windows dict confirms exactly these 6 keys
(`test_sun_zone_done_build.py:280–285`). The build-plan repeatedly says "the 4 intro+break
atmosphere lanes" (Chunk 1 step 1; §"Plan-level"; design §0.2). The parenthetical does
enumerate all 6, but a builder who reads "4 lanes" and asserts "4 `write_envelope`
ToolCalls" would **pass while the 2 pan envelopes warn-and-skip** — and the pan side is the
half the user explicitly asked for ("play with pan"). That is the exact silent-failure mode
this chunk exists to catch, re-introduced by sloppy counting.

**Fix:** State the count as "6 intro+break atmosphere envelopes (4 send_level + 2 mixer_pan)"
and require the assertion to check each of the 6 by `(target_kind, track, return)` identity,
not a bare count. (Note: `mixer_pan` envelopes route via the host clip too, so they CAN
warn-and-skip independently of the send on the same track — they must be asserted
separately.)

### W2 — Chunk 2's objective render assertion is likely UNVERIFIABLE this run, and the plan's fallback, while honest, makes Chunk 2 nearly empty of objective signal — the governance weight then rests almost entirely on Chunk 1.

The plan's own Chunk 2 fallback note and `sun-zone-done.md:99` both say the render pipeline
is stale (multi-stem capture went stale; a full Live reopen is the current gate). The item
brief says Live is "UP but UNATTENDED," but UP ≠ render-pipeline-healthy. If the render is
blocked, Chunk 2's only *objective* deliverable (send-lift realized via `_verify_level` +
RT60) cannot run, and everything else in Chunk 2 is by-ear-surfacing (correctly deferred).
That is honest (Principle 5) — but it means a reviewer should not treat Chunk 2 as carrying
real verification weight unless the render actually succeeds. The plan should make the
**Chunk 2 entry gate explicit**: step 0 (verify-api) must FIRST confirm the render pipeline
produces a fresh multi-stem capture for the song; if it does not, Chunk 2 is BLOCKED-pending-
render and Chunk 1 (plan-level) is the verification floor. The plan implies this in its tail
note but doesn't make it a gating step — so a builder could push, get a stale/partial
capture, and read a false `realized` (the DB-UUID-keyed silent-no-op learning is a live
risk here: a capture keyed wrong reads as "no change → not realized," or an empty-map no-op
reads as pass). Make the freshness/keying check a named precondition, not a footnote.

---

## NOTES (builder's call; not blocking)

### N1 — The "13-envelope" test lock is broader than this item's scope; make sure Chunk 1 doesn't accidentally re-assert outro lanes (or accidentally weaken the existing lock).
`test_atmosphere_envelopes_are_clip_local` pins **13** envelopes — the 6 intro+break
atmosphere + 4 outro DubDelay throws (#5) + 3 outro Room lifts (#D) (windows dict,
:279–293). MIX-3S7P is *only* intro+break. The new Chunk 1 plan-level test should scope to
the 6 intro+break envelopes and must **not** touch / weaken the existing 13-envelope DB-shape
lock (Chunk 1 step 3 correctly says "still passes — do not weaken it"; good). Just be alert
that the song carries more atmosphere than this item authored — don't let the plan-level
test's `set(...)` equality accidentally assert the full 13 against a session that only links
the intro+break host clips.

### N2 — §3.1 / the PENDING user fork (song-spanning DubDelay) is handled correctly.
The user signalled "static send for v1"; the plan carries the dynamic DubDelay arc as a
PENDING user decision, not a chunk, and does not fork directed work. This is the right
read of the precedence rule (CLAUDE.md "Precedence dominates this carve-out") and the
"permission to collaborate must restate precedence" learning. No change needed — flagged
only to confirm it was checked, not missed.

### N3 — Chunk 1's `verify-api` is correctly "read source," not "probe Live."
The planner is pure Python over the DB, so reading `envelopes.py`/`geometry.py` is the
right verify-api mode (preference order: read source first). The `Foreign API:` field is
present on both Live-touching chunks and a `verify-api` step appears as step 0 in each —
satisfies the Foreign-API rule; the Critic's Goal-2 check will find the literal token.

### N4 — First chunk IS a genuine thin vertical slice.
Chunk 1 threads DB intent → planner host-clip resolution → ToolCall emission without Live —
the full clip-local architecture, end to end, at the cheapest layer. It validates the path
before Chunk 2 widens it to a render. Good ordering; independently reviewable; the
governance checkpoint after Chunk 1 (architecture validation) is well-placed.

### N5 — Proposed canonical deltas (§5) are correctly recorded-not-applied.
No canonical model-doc edit is proposed for the shipped lanes (clip-local routing is an
existing documented capability — no new axis), and the only candidate framework delta
(auto-partition for the DubDelay case) is correctly punted to its own future item. The
DISCOVERED-FROM-FRICTION discipline (don't build the per-(track,return)-per-section model
change speculatively) is respected.

---

## Perspective summary

- **Product:** Faithful to the user's ask (intro+break space, snap back at verse/chorus);
  scope honestly bounded; the one open creative fork is correctly left to the user. The
  "play with pan" half is the one most at risk of silent loss — see W1.
- **Design / Both-sides:** Existing dimension, both sides present and used, no new
  primitive or lens invented. Sound.
- **Architecture / Foreign-API:** Mechanics verified firsthand; verify-api steps present.
  The one architectural gap is B1 — the plan-level test's precondition (session + links) is
  mis-grounded.
- **Skeptic:** The "already shipped" headline is the kind of claim that's usually too good
  to be true; I checked it hard and it holds. The defect is not in the headline — it's in
  the one place the plan describes NEW work (the plan-level test scaffolding), where it
  cites a fixture that doesn't exist.
- **Testing:** Tests-are-contracts respected (existing lock not weakened). The NEW test is
  buildable but only via the framework fixture pattern, not the (nonexistent) song fixture
  the plan names. Assertion must be identity-keyed (6 envelopes), not count-based.

**Revise trigger:** B1 alone (a Done-when instruction that cannot be followed as written,
making Chunk 1's verifiable signal unobservable) is sufficient to return REVISE. Fixing B1
and W1 is cheap (rewrite Chunk 1 step 2 + restate the count); the plan is otherwise strong.
