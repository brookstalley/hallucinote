# Backlog sweep 2026-09-09 — incidental findings

Produced by the requirements+design sweep that advanced 54 S/M items to `stage: ready`.
Each finding is either captured in a named issue body (cited) or listed here because it
has no issue home yet. Kept because an issue body can be rewritten; this record of what
the code actually said on this date cannot be re-derived cheaply.


Collected while advancing S/M items to requirements+design (2026-09-09).
Each is verified against the tree unless marked UNVERIFIED.

**Read this as a dated record, not as current status.** It merged 2026-09-10, after 252
commits of release work landed alongside it, and the code facts below were true on
2026-09-09. The status claims inside it that have since resolved, so nobody acts on a
stale one:

- **Finding 17 (#498) says "NOT DONE".** It is done — the arm-after-locate fix shipped and
  #498 is closed. What survives is the *verification*: the operator box is still unticked in
  `.prawduct/operator-verification.md` under RELBLK-V19. The four-link causal chain the
  finding records is why that box is worth running, and is the part that cannot be re-derived.
- **Finding 8 (#322, #324)** — both closed since.
- **Finding 13 (#487)** — the numbers drifted again, exactly as the finding predicts:
  `ruff check --select I001,UP --statistics .` read 290 I001 / 245 UP on 2026-09-10 against
  the 250/216 filed here. The finding's point is that the counts do not stay put; treat every
  number in it as a reading with a date on it, and re-measure.

Everything else below is a code fact or a design argument, not a status, and is left as
written.

## Small doc corrections (safe, mechanical — need a branch decision)

1. `.prawduct/artifacts/nonfunctional-requirements.md:57` — says `testpaths` covers
   "`tests/`, `hallucinote_mcp/tests/` and `songs/`". Actual (`pyproject.toml:225`):
   `["tests", "hallucinote_mcp/tests", "examples"]`. Stale since the framework/songs split.
   VERIFIED. Folded into #488 R2a, but the doc itself is still wrong.

2. Dangling public pointers to the PRIVATE songs repo — three tracked files tell a public-repo
   user to read `songs/sun-zone-done/build.py`, which does not exist for them:
   - `src/hallucinote/tools/melody_lens.py:156`
   - `src/hallucinote/tools/recurrence_lens.py:140`
   - `src/hallucinote/tools/templates/song/build.py.tmpl:153`
   VERIFIED by grep. Agent reported 6 locations total incl. `recurrence/lens.py:27`,
   `recurrence/match.py:13,50` — those cite it in prose; re-check before editing.
   Folded into #232 R3. Candidate replacement: `examples/punk-fate/build.py:1143`.

3. `.prawduct/artifacts/declared-constraint-substrate.md` — two stale load-bearing anchors:
   cites `arrangement.py:457` for `vary` (actual `:478`) and `:321` for
   `section_melody_inputs` (actual `:342`). Both are anchors #239's acceptance points at.
   UNVERIFIED by me (agent-reported).

## Real defects found while designing (each captured in an issue body, listed here so the
## code-level facts are not lost if the issue text is later rewritten)

4. FALSE CONTRACT IN SCHEMA — `db/schema.sql:137-142` documents `clips.reverse` as
   "materialized at push as Live's clip reverse". `docs/research/audio-first-class/
   lom-audio-clip-surface.md:32-33` records "No `reversed` property — confirmed absent".
   Latent only because push refuses all audio clips today; #284 makes it live.
   Captured as #237 chunk A. Agent argues it should land WITH #284, not after.

5. TWO FATAL FROZEN BINDINGS blocking #309's dev_reload:
   - `wire.encode_message` isinstance check (`wire.py:330-334`) would TypeError on the
     reload's own success reply.
   - `LiveBusyError` identity drift (`dispatch.py:38` vs `dispatcher.py:522`) turns every
     busy refusal into "the action is broken".
   Captured in #309's body.

6. `#220`'s filed acceptance cited the WRONG COMMIT — `97816e1` is the FIX (snapshot has 3
   Shifters); the phantom state is its parent `02be0ec` (`build.py:512` names a Shifter,
   snapshot has 0). Also `examples/angle-of-the-light` no longer exists in the tree (retired
   ~`3e6e65c`), so the acceptance case must ship as a committed fixture. Corrected in #220.

7. `#488`'s two filed premises were BOTH FALSE: `hypothesis` is not unused
   (`pyproject.toml:44` + 7 importing modules); the sync executor is 14 phases, not 13
   (`sync-boundary-contract.md` § The 14 phases). VERIFIED both. Item survives on a real
   Test Strategy gap. Corrected in #488.

8. `#322`'s filed "Scope-out: single-flight admission control already mitigated" was FALSE.
   Corrected in #322. Also #324 carries `superseded_by: #322`; its fence work is now in scope.

## Orphaning risk (time-sensitive)

9. The constraint shim that `declared-constraint-substrate.md` is written against exists ONLY
   on the unmerged songs-repo branch `compose/missing` (`672ee01`) — `git ls-tree HEAD
   songs/missing/` shows no `_constraint.py`. The artifact's own §3 rev-coupling alert warns
   about exactly this. Bears on the #239 promote-or-hold decision.

## Re-sizings (these items have left the S/M goal scope but are specified)

- #230 mcp composite locate-and-play: M -> L
- #322 mcp run_on_main timeout: M -> L
- #237 clip reverse: M -> S
- #250 arrangement pull view state: M -> S
- #246 arrangement honest boundaries: impact S -> M

## Added from infra/tooling cluster (agent 5)

10. LATENT SCOPING DIFFERENCE — `tools/song_context.py:197` omits the `song_id` scope that
    `Q.tracks_by_name` carries. One of #486's 17 raw-SQL read sites is a correctness
    difference, not only style. #486's `impact:S` may be understated.

11. `queries.py:86` `get_device_parent_chain` docstring says it exists so the envelope
    planner avoids "a raw SQL JOIN inside the planner" — and `sync/pull/envelopes.py:214`
    and `:475` contain exactly that JOIN. Strongest single piece of evidence for #486.

12. STALE IN-CODE CLAIM — `hallucinote_mcp/.../server_side/analysis.py:703-706` says
    `init_workspace`'s `**/analysis/` "contradicts" the root `.gitignore` and is "the
    owner's to settle". It does not contradict: the two govern different trees, and
    `docs/song-authoring-conventions.md:59-64` already states that split as the rule.
    Correcting the comment folded into #455's design (no behaviour change).

13. #487 BLAST-RADIUS NUMBERS DRIFT. Re-measured 2026-09-09 at ruff 0.15.20:
    I001 250 (filed: 248 sweep / 249 comment), UP 216 (filed: 210), 284 files (filed: 283),
    E 1085 all E501 zero autofixable. Recommendation survives; numbers do not stay put.
    SEQUENCING COST the original missed: 33 of 284 files are under `_FINGERPRINT_PATHS`,
    so the mechanical commit flips the MCP fingerprint and forces a Remote Script re-vendor.

14. #459: CI IS SHIPPED (`.github/workflows/ci.yml`, `48d3b1b`, PR #212). Platform question
    closed; only the matrix legs are open. Item retitled to the narrower question.

## Owner-gated egress (do not act without explicit approval)

15. #489 R5 (briefing staleness probe has no opt-out) re-verified live against plugin
    3.4.1-dev.2: `plugin/lib/briefing.py:196` still substring-tests package names against
    architecture.md; no upstream issue covers it. Recomposed product-free payload is in
    #489's body, ready for `backlog file-upstream` preview + `--approve sha256:<digest>`.
16. #489 R7 is ALREADY UPSTREAM: `brookstalley/prawduct#724`, OPEN, same verify-resolutions
    yield problem from a 136-review dataset. Recommend a COMMENT carrying this repo's
    84-review dataset + counter-caveat, NOT a second issue.

## LIVE DATA-CORRUPTION BUG — verified end to end (#498)

17. CAPTURE STARTS AT THE LOCATE, NOT AT PLAY. Chain, all four links verified by me:
    (a) `prev_beat` ($f2) resets to -1 on the Arm RISING EDGE —
        `hallucinote_mcp/src/hallucinote_mcp/m4l/HallucinoteAnalyzer.amxd.spec.md:180-184`
        (a deliberate workaround so start_at_beat=0 crosses on a repeated render).
    (b) detector is `($f2 < $i3) && ($f1 >= $i3) && ($i4 == 1)`; with $f2=-1 and
        start_at_beat=0 the first clause is UNCONDITIONALLY TRUE.
    (c) so it fires on the first current_song_time change after arming, wherever the
        transport is.
    (d) `hallucinote_mcp/src/hallucinote_mcp/handlers/render.py` arms at :554, locates at
        :591 (moves current_song_time), plays at :594.
    => sfrecord~ starts at the LOCATE, capturing ~0.5s / 1.1 beats of pre-roll wall clock.
    Only bites when the locate actually changes the value — explains two good renders and
    one bad one on the same set minutes apart.
    COMPOUNDED by render.py:583 `seek_to = max(0.0, start_at_beat - pre_roll_beats)` which
    silently removes the pre-roll at start_at_beat=0.
    IMPACT: every per-section number in an affected report is a beat wrong.
    FIX: three-line reorder (arm AFTER locate) + call-order test. Python only, no patch edit.
    COST: render.py is fingerprint-bearing -> forces re-vendor + Live quit/reopen.
    NOT DONE — needs its own branch; user decision pending.

18. `db_seq` EQUALITY DOES NOT MEAN "SAME MIX". On the punk-fate pair the master moved
    6.68 LUFS at an unchanged `master_fader_db` (a Live-side master-chain change the DB
    never saw) while all four stems matched to within 0.02 dB. Anything treating db_seq as
    a mix-identity token (A/B tooling, calibration, replay guards) needs a per-surface
    audio check on top. #227's admission gate is designed to catch it.

19. `spectral_rolloff_hz` is BIN-QUANTIZED at sample_rate/_N_FFT = 23.4375 Hz
    (`timbre.py:37`, `:185-195`), so its re-capture jitter reads exactly 0.000 and its
    current 100 Hz floor is ~4 bins. A floor below one bin is meaningless. In #227 R3.

20. #240 CAUSE REVISED: the recorded "sequential disarm" attribution is almost certainly
    wrong. With no prev_beat reset in play mid-render, each instance's stop-cross resolves
    in its own [deferlow] slot and each sfrecord~ closes at its own vector boundary — a
    per-surface, load-dependent, buffer-independent ramp matching the recorded
    ~20ms/surface, ~170ms-across-nine magnitude. Explains why the master is shortest in one
    render and longest in another, which the disarm story could not.
    CHEAP PRE-FLIGHT PROBE (minutes, de-risks the L): run one render with the disarm loop's
    `_INTER_MUTATION_YIELD_S` set to 0. Spread unchanged => dispatch-ramp confirmed, patch
    edit justified. Spread collapses => original disarm attribution right, #240 shrinks to
    a small Python change.
