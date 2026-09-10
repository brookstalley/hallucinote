---
artifact: build-plan
version: 2
scope: RELBLK-0910
branch: fix/release-blockers-0910
depends_on:
  - artifact: api-contract
  - artifact: sync-boundary-contract
  - artifact: boundary-patterns
governed_by:
  - artifact: api-contract
    dispositions:
      - "Refuse-and-teach over silent wrong behavior, at every boundary → conforms (all three chunks ARE this norm applied: 01 stops a wrong-device write and stops calling a failed restore success, 03 replaces silent sidechain-source loss with a named warning)"
      - "Errors teach — structured recovery information, never a bare string → conforms (01's shortfall exit names what was captured vs restored and that the journal is retained; 03's warning names track and device)"
      - "The MCP surface is versioned by content fingerprint, never a hand-maintained number → conforms (02 touches server.py, which is NOT a fingerprint path, and bumps no number by hand; the release's re-vendor comes from other work)"
      - "No compatibility shims for consumers that cannot exist; one-major-version aliases → conforms (JOURNAL_VERSION goes 1→2 and a version-1 journal is REFUSED with a teaching error rather than read through a shim — the journal is an internal recovery file with no external consumer, and guessing its missing positions is the defect)"
      - "Mutator signatures are keyword-only after conn, and every mutator accepts actor/reason → conforms (01 keeps writing links through M.link_db_to_ableton with actor and reason unchanged; only the index VALUE it passes changes)"
      - "Timing transforms stay in the engine and off the MCP surface → inapplicable because no chunk touches timing"
      - "The MCP tool surface stays inside the band where tool-selection accuracy holds → conforms (02 retypes one existing parameter; no tool or action is added)"
      - "These interfaces stay internally scoped → inapplicable because no chunk changes what is published"
partition: >
  delegated — three chunks, disjoint file ownership by construction, one
  coordinator-created worktree each. 01 owns `sync/chain_rebuild.py` +
  its test; 02 owns the MCP probe surface; 03 owns the capture/push
  sidechain-warning path. No file is named by two chunks. The coordinator
  integrates on `fix/release-blockers-0910` and owns the combined suite,
  the Critic and every state update.
last_validated: 2026-09-10
---

## Requirements Confidence

**Level:** High

**Why:** All three defects are established by direct operator evidence against
Live 12.4.5 on 2026-09-10 (`.prawduct/operator-verification.md` § #291, and
`incoming-bugs/archives/2026-09-10-sidechain-authoring-blockers.md`), and every
mechanism was re-verified in the tree at `bb4bd3d` before this plan was written
rather than taken from the issue text. Each chunk's defect is code-visible and
unconditional; none depends on data or environment to reproduce.

The release context is what makes two of them urgent rather than merely open:
this release ships #533's fix, which converts chain-rebuild's restore from
"every write refused" to "every write lands". Chunk 01 is the difference
between that being a fix and being a regression in blast radius.

**Open assumptions / unknowns:**

- [ASSUMPTION: a positional survivor-mapping is the right way to re-derive
  physical indices | HIGH impact | owner can override] Recorded as a decision
  below with its alternative. The alternative (identity matching on class +
  name) is *worse* here for a reason this song demonstrates: `alien` now carries
  three Compressors on one track, so class+name is ambiguous exactly where it
  would be relied on. Positional mapping asserts class equality at each pairing,
  so it degrades to a loud alert rather than a wrong write.
- [ASSUMPTION: the `_PARAM_EPSILON` tolerance model (#534) stays out of scope |
  MED impact | owner can override] Verified not to bite the restore path, which
  writes only Live-read, grid-resident values. If Chunk 01's verify starts
  failing on values it just wrote, that assumption is wrong and #534 has become
  load-bearing — which is the tripwire, not a surprise.
- Live cannot be driven from this session. Every chunk lands with unit coverage
  against fakes plus an `operator-verification.md` entry; the fakes cannot prove
  the Live-side behaviour and this plan does not claim they do. This is the
  standing limit recorded in `learnings.md` (the 2026-05-17 fakes mirrored what
  we *thought* Live exposed and the unit suite never saw the divergence), and it
  is the whole reason #291's witness box exists.

**What would raise confidence:** Re-running #291's witness box (blocked behind
Chunk 01) and its sidechain box (runnable now that `alien` carries seven
sidechain compressors) against a single-writer `alien`. Both are queued in
`operator-verification.md`; neither can run from this session.

## Status

- [x] Chunk 01: chain-rebuild addresses the post-rebuild chain, and a shortfall cannot exit 0 (#532 Symptom A + #538)
- [x] Chunk 02: `probe set`'s value schema is an explicit union over every JSON type (#537)
- [x] Chunk 03: an unreadable sidechain source warns instead of vanishing (#536)

Context: Built 2026-09-10 on `fix/release-blockers-0910`, cut from
`origin/develop` @ `bb4bd3d`. All three chunks were built by coordinator-created
worktree delegates against disjoint file sets, merged here with no conflicts, and
their worktrees reaped. #532 Symptom B was **descoped as already fixed** before
dispatch — see Decisions. Suite green; `.prawduct/change-log.md` carries the
`RELBLK-0910` entry.

**Three review rounds, and the integration run is what earned them.** Two defects
reached the tree that no delegate could have seen, because each lives in the seam
between a chunk and a file no chunk owned: a second hardcoded dedicated-branch
list in `test_push_execute.py` (the combined suite caught it), and the link
rebind writing a DB position where every consumer reads a physical index — #532's
own defect one layer out, found by the first cumulative review and reachable
through the recovery this work recommends. A third, the shortfall journal blocking
`push execute --only devices`, was found by reading the call site at integration.

Worth carrying forward: round 1 was wasted on a dispatch-mismatch because two
documentation commits landed inside the review interval, and rounds 2→3 existed
because resolving findings introduced new judgeable surface. Reviewing after the
integration fixes rather than before would have cost one round instead of three.

Remaining, and not blocking the release: the `chain_rebuild.py` sidechain warning
(the same silence on the most destructive surface — it deletes and reloads the
device), #526's re-scope, and naming the sidechain-enable hints MCP-side so the
drift guard can compare imports instead of source. Six Live checks are queued in
`operator-verification.md`; #291's witness box is unblocked.

## Decisions taken

### #532 Symptom B is descoped — the defect it describes is already fixed

Symptom B claims `ableton_device(action='load')` on a rendered track leaves the
new device after the `HallucinoteAnalyzer` tap, so the stem under-measures while
the master does not. **The harm is not reachable.** `render_handler`
(`hallucinote_mcp/.../handlers/render.py:401`, the `start` path) calls
`ensure_analyzers_loaded` at `:465`, which for every surface calls
`_reposition_action` (`analyzer/setup.py:516`) and, when the analyzer is present
but not last, deletes and re-adds it so it lands terminal *before* any capture.
That self-heal shipped 2026-06-13 in `39487be` (SNP-8R4K chunk 3), three months
before the report, and its own comment describes this exact case: *"a device
loaded after a prior render lands past the analyzer … leaving the tap mid-chain
→ silent under-measurement. We self-heal that here at render start."*

The reporter observed the post-load chain order and inferred a consequence the
sweep prevents; the workaround they recorded (delete the analyzer, load, let
`ableton_render` re-add it at the chain end) is precisely what the sweep does
unattended.

Two residues, neither release-gating, both to be recorded on #532 rather than
built here:

- The `load` response stays silent about the transient non-terminal state. Per
  *Errors teach* that is worth a note eventually, but nothing measures in the
  window between the load and the next render, because the measurement *is* the
  render and it heals first.
- #532's acceptance criterion — "`find_authored_after_analyzer` returns `[]`
  after any sequence of `load` calls" — tests the wrong instant. It is false
  immediately post-load and true at every moment that matters (capture time).
  The criterion should be restated against capture time or dropped.

Consequence for the release: **#532 needs no MCP change**, so its cross-package
re-vendor argument and its open "where does the predicate live" question both
dissolve. (That question was already answered in-tree regardless:
`analyzer_identity.py`'s module docstring records the ratified shape — the
dependency direction is MCP→engine, the MCP side defines its own
`ANALYZER_DEVICE_NAME`, and `tests/unit/test_analyzer_identity.py` is the
drift-guard that keeps R1 true.)

### Chunk 01 re-derives physical indices positionally, asserting class at each pairing

`rebuild_chain` excludes the analyzer from the *logical* model in three places
(`:315`, `:426`, `:840`) while the restore addresses devices *physically* by the
index captured before the delete (`:316` → `:701`). Post-rebuild the analyzer
sits at the head rather than the tail, so every restore lands one slot off.

The fix re-reads the chain after the rebuild and pairs the *k*-th unauthored-device-skipping
survivor with the *k*-th journal entry, asserting class equality at each pairing
and alerting on mismatch. Rejected: identity matching on class + name — `alien`
now carries three same-class Compressors on one track, so the discriminator is
ambiguous exactly where it would be load-bearing, and #537 is open precisely
because renaming them is impossible. Positional mapping is also what the rebuild
actually does (it reloads in ascending DB `position` order), so the mapping
mirrors the mechanism instead of guessing at it.

An unauthored device that is **not** the analyzer refuses, naming it, in the same
shape as the existing not-loadable refusal: only the analyzer has a render path
that justifies tolerating it.

### Chunk 01's exit contract: any shortfall is non-zero, and the journal survives it

`main()` returns 0 unconditionally (`:1534`) on the stated ground that "an alert
is operator-actionable but not a failure". That reading is sound for one refused
parameter and false for all of them — and the verify cannot catch the difference,
because it is scoped to `written` (`:932`) and `continue`s on an empty set, so a
wholly-failed restore verifies vacuously against zero comparisons. The journal,
which the module's own docstring calls "the only way back", is then unlinked on
that clean path (`:1211`).

Contract: a run that captured N writable parameters and restored M < N exits
non-zero and retains the journal; an empty `written` against a non-empty writable
capture fails verification rather than passing on nothing. Per *Errors teach* the
exit names N, M and the retained journal path.

### Chunk 02 widens the schema without narrowing the value domain

The union is explicit over **every** JSON type — string, number, boolean, object,
array, null — not the scalar-only union the issue originally filed. A scalar union
would make a `dict` value schema-invalid and take out `probe set`'s LOM-object
assignment path (`handlers/probe.py:419` resolves `{"$path": …}` markers into live
LOM objects). The point is explicitness, not narrowing: the set of values
`probe set` accepts after this change is the set it accepts today. #508's
server-side `coerce_wire_value` stays exactly as it is — #508 rejected typing *as
a substitute for* coercion, not typing *alongside* it.

### A requirement surfaced at integration: a retained journal has two meanings

Chunk 01's #538 half introduced a state the module did not previously have, and
nothing in the plan anticipated what it collides with. **A shortfall journal and
a mid-flight journal are not the same object, and `push execute` treats them
identically.**

`push_cli._refuse_on_stranded_rebuild` (`push_cli.py:833`) runs unconditionally
in `push execute`, before any phase and regardless of `--only`. Its reasoning is
that a journal means a rebuild "gutted a chain and did not finish", so the DB's
device links describe a chain Live no longer has. That is true of a journal left
at `journaled` / `demolished` / `rebuilt`. It is **false** of a shortfall journal:
`_rebind_links` has already run, the chain is in the DB's order, and the verify
passed for everything that landed — only some captured values are missing.

The collision is concrete and self-inflicted: the shortfall alert tells the
operator to run `push execute --only devices` to re-apply what did not land, and
that command is refused by the journal the shortfall just retained. A fix whose
own recommended recovery is blocked by the fix is not finished.

**Requirement.** The journal's state is readable, and the refusal acts on it:
a mid-flight journal refuses the push (unchanged); a shortfall journal warns,
names itself, and lets the push proceed. Retention itself is not up for
negotiation — #538 asks for it by name, and the journal is the only record of
the values that did not land.

The mechanism was already there and unused: the journal persists a `phase` at
every step (`journaled` → `demolished` → `rebuilt` → `restored` → `verified`,
each written to disk), so classifying costs a read rather than a new format.

**Also mine at integration, from Chunk 01's report:** `push_cli`'s reconcile
caller ignored `result.ok`, so `push execute --reconcile-chains` still exited 0
on a shortfall — #538's contract honored by one of its two callers is not
honored. And the refusal message's claim about stale links is wrong for the
shortfall case, which is the misleading half of the same defect.

### Chunk 02 flips no fingerprint — #537's stated re-vendor cost was wrong

Found at integration, and it corrects the reasoning that put this chunk in
scope. #537's body says *"`actions/probe.py` and `handlers/probe.py` are hashed
into the version-handshake fingerprint, so this **forces a re-vendor**"*, and the
plan inherited that. The fix as built touches **neither** file: `ParamSpec` has
no schema hook, so the change lands in `server.py`, and `_FINGERPRINT_PATHS`
(`hallucinote_mcp/src/hallucinote_mcp/__init__.py:46`) is exactly `wire.py`,
`schema.py`, `dispatcher.py`, `actions`, `handlers`, `remote_script` — `server.py`
is not in it.

So this chunk forces no re-vendor on its own. What it needs to take effect is an
**MCP server restart** — the schema is emitted by the locally running
`hallucinote-mcp` process, not by the copy vendored into Live's User Library, and
the Remote Script is the far side of the wire rather than the thing that
generates the schema.

The release's re-vendor verdict is unchanged, because other work since `v1.8.6`
*does* touch `actions/` and `handlers/` — 19 such files. The correction matters to
the release note's per-item instruction, not to the consumer-facing verdict: a
reader should not be told to re-vendor *for this item*.

### `ableton_index` holds the index Live answers to, never the DB's ordinal

Recorded here as well as in `boundary-patterns.md` § Ableton Projection, because
this is the decision the whole of Chunk 01 turns on and it had been living in a
private docstring.

For `db_kind="device"` an `ableton_links` row holds the **physical**
`device_index` — what `plan_push_devices` hands `set_parameter` — and not the
device's DB `position`. The two are equal only while every unauthored device sits
after the authored ones, which for the `HallucinoteAnalyzer` means while the tap
is terminal. A rebuild breaks that for as long as the tap survives at the head:
position *q* answers to index *q+1*.

Writing the position there is how authored values reached the neighbouring device
through `push execute --only devices` — the same wrong-device class as #532, one
layer out, through the recovery this work's own alert recommends. A producer
holding only positions must read the live chain and map (`_logical_chain`); it may
not assume the two numbers agree.

*Why it is written at the boundary rather than left to the producer:* the defect
arrived through exactly this ambiguity — "index" read as "ordinal" — inside a
function called `link_db_to_ableton`, with nothing at the boundary saying which
number it meant. The review found it; the record is what stops it returning.

### The release's two governance gaps, dispositioned (owner rulings, 2026-09-10)

Both were surfaced as release decisions and both were ruled by the owner while
this plan's chunks were being built.

**The operator-verification gate stays unarmed for this release.** The ruling and
what it does and does not mean are recorded at the top of
`.prawduct/operator-verification.md`, which is where a reader of that file's exit
code will actually look. Arming it was left open for a later release, so the
absent key is a per-release decision rather than settled policy.

**The six planless release-pending scopes were five mis-readings and one correct
one.** The owner chose to retro-record the code-bearing scopes and explicitly
accept the rest; working the list turned up that most of it needed no record at
all:

- `BUGSWEEP-0910` — **the plan existed all along.**
  `.prawduct/artifacts/build-plan-open-bugs.md` is the complete plan for exactly
  that work (B1–B12, #291 as B8, #322 as B9, cumulative Critic closed), but its
  frontmatter said `scope: open-bug-sweep` while the change-log entry says
  `scope=BUGSWEEP-0910`, and nothing else in the change log used the former — an
  orphaned tag, so the gate could not pair them. Retagged to `BUGSWEEP-0910` and
  archived as completed, which is what its all-ticked Status had earned. No
  document was written; one tag was corrected.
- `CHAIN-RESTORE-STR` — genuinely planless, and **correctly so.** It is a
  one-branch, one-branch-of-one-function bugfix (`_param_write_kwargs`'s
  continuous branch sending a float at a `str` wire field). By the size heuristic
  in `/prawduct:methodology building` that is *small* work, whose governance is
  "understand + build + verify + update affected artifacts" — a build plan is not
  among them. Its change-log entry is unusually thorough and carries everything a
  plan would have. Writing a retrospective plan here would have manufactured an
  artifact the methodology never asked for.
- `docs-hygiene`, `governance-file-sizes`, `advisory-clearing`,
  `effort-s-burndown` — docs and chore scopes, same reasoning as
  `CHAIN-RESTORE-STR` and more so. Accepted as shipping planless, on the record.

So `check-releasability`'s warning is sound as a prompt and wrong as a verdict:
"no plan describes this" is a defect only when the work was big enough to need
one. Five of the six warnings were the gate asking a question that had a good
answer.

## Chunks

### Chunk 01: chain-rebuild addresses the post-rebuild chain, and a shortfall cannot exit 0

- **Description:** Two defects on one path, shipped together because the second is
  how you can tell the first is actually fixed. #532 Symptom A is a physical-vs-logical
  index confusion; #538 is the reporting and exit contract that let it run green.
  Without #538, re-running #291's witness box after fixing #532 produces an exit 0
  that means nothing.
- **Depends on:** none
- **Owns:** `src/hallucinote/sync/chain_rebuild.py`,
  `tests/unit/sync/test_chain_rebuild.py`
- **Artifacts consumed:** `api-contract.md` § Direction (refuse-and-teach;
  errors teach), `.prawduct/operator-verification.md` § #291 (the measured
  failure, including the two lost gain cuts)
- **Deliverables:** the restore and the verify address devices by an index
  re-derived from a post-rebuild chain read rather than by `entry["device_index"]`;
  an unauthored non-analyzer device refuses by name; the exit contract above; the
  journal retained on any shortfall.
- **Tests:** the fake `send_fn` must be able to hold an unauthored device — today
  it builds its chain from the DB rows, so the scenario is *unrepresentable*
  rather than merely untested, and that is why this shipped. Then: a journal
  physical index that differs from the post-rebuild physical index still restores
  to the right device; a surviving analyzer at the head restores every captured
  parameter; no alert reports a class change that did not occur; a fake refusing
  every `set_parameter` produces both a non-zero exit and a failed verify (the
  scenario that ran green for the module's entire life); the journal still exists
  after a shortfall exit; an unauthored non-analyzer device refuses before any
  delete.
- **Done when:** the tests above pass, `operator-verification.md` § #291's
  witness box records that it is now unblocked, and the coordinator's combined
  suite is green.

### Chunk 02: `probe set`'s value schema is an explicit union over every JSON type

- **Description:** `ParamSpec(name="value", type="any")`
  (`actions/probe.py:96`) serializes to `anyOf: [{}, null]`. An empty `{}` gives
  the calling client no type to serialize a string against, so a string is emitted
  bare and dies in the client's own JSON parse before a request is ever sent —
  reproduced 6/6. Device renaming therefore has no working path, which is
  load-bearing because `replay_capture` keys devices by `display_name` and `alien`
  now carries three indistinguishable Compressors on one track.
- **Depends on:** none
- **Owns:** `hallucinote_mcp/src/hallucinote_mcp/actions/probe.py`, and
  `hallucinote_mcp/src/hallucinote_mcp/handlers/probe.py` only if the typing
  genuinely requires it, plus the probe action/handler unit tests
- **Artifacts consumed:** `api-contract.md` § Direction (the fingerprint norm —
  this path is hashed, so the re-vendor is forced by the fingerprint and no
  version number is touched by hand)
- **Deliverables:** an explicit `anyOf` over string, number, boolean, object,
  array and null, with whatever `ParamSpec` change that requires; the emitted
  schema carries no empty `{}` branch.
- **Tests:** a string value (with and without spaces) is schema-valid and reaches
  `setattr`; a `{"$path": …}` **dict** value stays schema-valid and still resolves
  to a live LOM object — this is the regression the scalar-only union would have
  caused; numeric, boolean and null keep working, so #508's coercion tests stay
  green; the emitted schema for `probe set`'s `value` has no empty-schema branch.
- **Done when:** the tests above pass and the fingerprint change is noted for the
  release's re-vendor line (the coordinator writes that, not the delegate).

### Chunk 03: an unreadable sidechain source warns instead of vanishing

- **Description:** `Multiband Dynamics` exposes the canonical `S/C On` parameter
  but no input routing, so its source can be armed and never pointed anywhere —
  and a source the user sets by hand in Live's UI is silently lost on the next
  `build.py` rebuild. Not a routing fix: the Live-side limit is real and is not
  ours to make. The loss stops being silent. `capture.py:1894` records routing
  only when `has_input_routing` is truthy, which is where the silence is.
- **Depends on:** none
- **Owns:** `src/hallucinote/capture.py`, `src/hallucinote/sync/push/devices.py`,
  `src/hallucinote/sync/push/plan.py`, and their unit tests
- **Artifacts consumed:** `api-contract.md` § Direction (refuse-and-teach: skip
  with a warning, never write the wrong value), #362's shipped
  snapshot-silence-as-no-opinion contract
- **Deliverables:** wherever `S/C On == 1` meets `has_input_routing == false`, a
  named warning from `/song-snapshot`'s capture and from push's
  `device_sidechain` phase, each naming track and device and saying the source
  will not survive a rebuild. Consider recording the condition in the snapshot so
  the warning survives into a session that did not run the capture — decide it
  explicitly either way.
- **Tests:** that state produces the named warning from both surfaces; a device
  with a readable routing surface produces **no** warning, so the Compressor path
  #374 already covers gains no new noise; a regression test pins the predicate and
  the message.
- **Done when:** the tests above pass and the `alien` Multiband Dynamics case is
  quiet no longer.

## Verification Strategy

The coordinator owns all integration verification. Each delegate runs only the
narrowest run covering its own change — normally the one or two test files its
diff touches — per `project-preferences.md`'s ratified `Delegate verification`
row. Never the full suite: several whole-suite runs contending on one box each
report a different total, none complete, all exiting 0, and a green nobody can
attribute to a known set of tests is not evidence.

At integration the coordinator merges each branch onto
`fix/release-blockers-0910`, runs the combined suite once, records evidence, then
runs `/prawduct:critic cumulative`. Live-side behaviour is verified by the
operator, not here: Chunk 01 unblocks #291's witness box and Chunk 03 adds its own
`operator-verification.md` entry.

**Critic mode:** cumulative — one review spanning all three chunks at
integration. The diff is three small, independent, single-purpose changes well
under the 12-judgeable-file roster threshold, so per-chunk reviews would buy
three rounds of the same reviewer attention over a third of the context each.
