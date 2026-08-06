---
artifact: build-plan
version: 1
plan_id: PUB-READY
# Binds this plan to the `scope=pub-ready` change-log entries so the release
# can regenerate the Status section below. Discovery is by this declaration,
# not by filename or directory — without it the scope resolves to no plan and
# regen-views withholds the view.
scope: pub-ready
last_validated: 2026-08-06
---

# Build Plan — Public-Repo Readiness (PUB-READY)


## Confidence check

**What problem are we solving?** The repo is being made public carrying
version-inconsistent README prose, a private sibling project's local path and file
inventory, 15 personal filesystem paths, no security or conduct policy, two *required*
strategy artifacts absent, a tracked internal bug inbox, and stale governance state.

**What does success look like?** A visitor sees consistent versioning, zero personal
paths or private-project pointers, standard community-health files, and
contributor-facing architecture + API documentation. The four session advisories are
cleared or consciously dispositioned.

**What is out of scope?** The hero image and demo-song walkthrough (owner deferred it to
a dedicated pass with a new demo song showing the full create → push → arrange flow);
any product code change beyond repointing stale doc references; and the backlog →
GitHub Issues migration, which is a separate decision with its own cost.

**Requirements confidence: High.** Every item was enumerated and explicitly authorized.
One judgment call the owner resolved directly: `.prawduct/` stays tracked (it is
deliberately public — the README links `authorship-model.md`), while the raw
`incoming-bugs/` inbox does not.

## Baseline

Branch `chore/public-readiness` off `develop` @ v1.7.1 (develop == main, clean tree).
Pre-work gates all green (suite, ruff, mypy, `uv lock --check`); counts live in
the evidence store.

### Chunk C1: README version coherence  [status: done]

Drop the "It's early" / "approaching 1.0" framing contradicting the shipped v1.7.1.
Known Issues section left untouched — it is the page's most trust-building content.

### Chunk C2: privacy scrub  [status: done]

Remove the reference disclosing a private sibling project's local path and file
inventory; anonymize its name across the archived design doc (its repo URL was already
deliberately redacted, so the design reasoning survives without the pointer). Replace
15 hardcoded `/Users/<name>/...` paths across 6 files with repo-relative or placeholder
forms.

**Acceptance:** `git ls-files | xargs grep brookstalley` returns only legitimate GitHub
org references and the author email in plugin manifests.

### Chunk C3: untrack the incoming-bugs drop-zone  [status: done]

Triage the 3 pending reports into the backlog FIRST — they were real unfiled
requirements — then gitignore the inbox.

**Two passes, and an owner decision between them.** The chunk first narrowed to
ignoring only the raw drop-zone, keeping `incoming-bugs/archives/` tracked because ~130
references across shipped source comments, tests and plans cited it as provenance. The
Critic (rev-20260806T200317Z, R-2) correctly held that this untracked *zero* files and
that publishing 64 internal reports was the owner's call, not the chunk's.

**Owner decision, 2026-08-06: untrack the whole tree and repoint the refs.** Executed:
108 references across 24 files repointed to a non-file provenance form — the **backlog
id** where one exists (50 of 64 reports map to one), and the report's own title restated
inline for the remaining 14, so the record is self-contained rather than pointing at
something no reader can open. Four more used an elided (`…`) path form that a
whole-name match missed. `incoming-bugs/` is now fully gitignored; all 64 files remain
on disk locally.

`project-preferences.md`'s triage norm was rewritten to match: for these files
specifically the backlog id is the citable provenance, inverting the usual
link-don't-summarize rule — because a link nobody can follow is worse than a restatement.

**Defect found and fixed en route:** refs in shipped source and tests had silently gone
stale when reports were archived, including one whose filename wraps across two source
lines and so was invisible to a whole-path grep.

**Filed:** SYN-6R2D (fold a Live clip hand-edit back into `build.py`), PSH-7T4C (push
halts on a disabled chain-mixer param capture itself wrote), REC-3W8N (recurrence lens
blind to a composed `transpose ∘ onset-diminish` recall). Each verified against the
code before filing.

### Chunk C4: community health files  [status: done]

`SECURITY.md` and `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).

SECURITY.md discloses rather than implies the trust model. Its load-bearing statement:
a song's `build.py` is executable Python, so building someone else's song runs their
code — that is the feature, not a hole to sandbox away, and reports to that effect are
working-as-designed. What *is* in scope is a path from song **data** files to execution
without anyone running `build.py`.

### Chunk C5: strategy artifacts  [status: done]

`architecture.md` and `api-contract.md` authored for real — both were required by
recorded structural characteristics (`multi_process_distributed`,
`exposes_programmatic_interface`) and absent.

`data-model.md` and `security-model.md` are brief but genuine, because a "(not
relevant)" stub would have been false for this product. `operational-spec.md` records
honestly that nothing is operated; `nonfunctional-requirements.md` and
`observability-strategy.md` record the few constraints that do bind (the agent-host
call timeout, the no-blocking-the-event-loop rule, no-telemetry-by-decision).

`api-contract.md` records the three decisions the framework tracks: versioning
(fingerprint, not semver, with reasoning), the error model (errors teach — the consumer
is an LLM, so an error is the next turn's input), and deprecation (no shims to unshipped
consumers; aliases for one major version on the song-authoring API, with a dated
revisit trigger).

### Chunk C6: housekeeping  [status: done]

Done: `prawduct-hook update-gitignore`; deleted the AUD-2D6T plan (all 4 chunks
complete, shipped v1.7.1); repointed `active_build_plan`, which still named the deleted
plan and was the root of the stale-plan advisory.

**Deferred, with reasoning:** compacting `project-state.yaml` (43KB) and
`learnings.md` (49KB). Neither is compactable without destroying records. `learnings.md`
is 70 rules averaging 695 bytes — already the "rule in brief" form the advisory asks
for; only 9 entries carry movable narrative, worth ~7KB against a 40KB threshold.
`project-state.yaml` is discovery and decision record, and the advisory's specific
suggestions (trim completed-chunk deliverables, trim test history) do not map onto its
actual contents. `change-log.md` (190KB, 79 entries) is cited by backlog `closed-by:`
refs, so trimming to "last ~10" would dangle them. These are internal-hygiene concerns
orthogonal to public readiness; doing them properly is its own work cycle.

## Status

- [ ] Chunk C1: README version coherence
- [ ] Chunk C2: privacy scrub
- [ ] Chunk C3: untrack the incoming-bugs drop-zone
- [ ] Chunk C4: community health files
- [ ] Chunk C5: strategy artifacts
- [ ] Chunk C6: housekeeping

## Done when

All chunks resolved, full no-path `python -m pytest` green, ruff + mypy + `uv lock
--check` clean, `/prawduct:critic cumulative` run with zero unresolved blocking
findings.

Verification is recorded in the evidence store (`prawduct-hook test-status`), not
copied into this prose, where it would drift.
