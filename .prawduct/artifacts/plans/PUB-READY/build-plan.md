---
artifact: build-plan
version: 1
plan_id: PUB-READY
last_validated: 2026-08-06
---

# Build Plan — Public-Repo Readiness (PUB-READY)

**Critic mode:** cumulative-final

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
Pre-work suite: 4614 passed, 2 skipped; ruff, mypy, `uv lock --check` all clean.

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

**Scope correction made during the build.** The plan originally said untrack
`incoming-bugs/` wholesale. Investigation found ~130 references across shipped source
comments, tests and plans citing `incoming-bugs/archives/` as provenance, so untracking
it would dangle every one. Only the raw drop-zone (`incoming-bugs/*.md`) is ignored;
`archives/` stays tracked. This meets the owner's stated goal — no internal triage
inbox in the public repo — at zero coherence cost.

**Defect found and fixed en route:** 11 refs in shipped source and tests still named
pre-archive paths and had silently gone stale when those files were archived.

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

### Chunk C6: housekeeping  [status: partial — size compaction deferred]

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

- [x] C1 — README version coherence
- [x] C2 — privacy scrub
- [x] C3 — untrack the incoming-bugs drop-zone
- [x] C4 — community health files
- [x] C5 — strategy artifacts
- [~] C6 — housekeeping (size compaction deferred with reasoning)

## Done when

All chunks resolved, full no-path `python -m pytest` green, ruff + mypy + `uv lock
--check` clean, `/prawduct:critic cumulative` run with zero unresolved blocking
findings.

**Verification at commit 7b14fa8:** 4614 passed, 2 skipped; ruff, mypy and
`uv lock --check` all clean.
