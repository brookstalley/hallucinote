---
artifact: build-plan
version: 2
scope: tour
depends_on:
  - artifact: tour-walkthrough-design
  - artifact: project-root-contract
  - artifact: onboarding-and-teaching-model
governed_by:
  # No `## Direction` section in any artifact governs documentation or media
  # tooling — the repo's only one (plans/BAK-7D2V/design.md) covers mix-bake
  # durability. The entries below are the artifacts whose prose binds this work
  # even without a Direction section; each records a disposition.
  - artifact: project-root-contract
    dispositions:
      - "songs live in a workspace repo outside the framework repo → exception (the `examples/` bounded exception, already written into the contract on this branch and scoped to docs + CI)"
      - "workspace identified by a `hallucinote.toml` marker discovered by walking up → conforms (examples/ carries its own marker; no resolution-code change)"
  - artifact: onboarding-and-teaching-model
    dispositions:
      - "onboarding paths send users to a workspace of their own → conforms (the tour is watch-it-done; quickstart keeps the do-it-yourself role and still routes to `init-workspace`)"
  - artifact: project-preferences
    dispositions:
      - "structural doc/preference tests live in `tests/preferences/test_*.py` → conforms"
      - "every new preference gets an enforcement mechanism (Linter | Test | Critic) → conforms (the media budget and snippet-freshness rules each get a test; see D1)"
      - "numbers that drift are not restated in prose; point at the canonical source → conforms (the tour quotes no test counts)"
last_validated: 2026-08-06
---

## Requirements Confidence

**Level:** Medium

**Why:** The design is thorough, owner-authored and specific about what each beat must
show, and the ordering constraint (tooling before authoring) is correct and load-bearing.
Three things are genuinely unsettled, and two of them are the owner's to settle, not
mine to infer.

**Open assumptions / unknowns:**

- [ASSUMPTION: the demo song's musical brief — genre, tempo, the specific "chorus that
  needs to lift", the "kick/bass collision", and which feel change is worth A/B-ing in
  beat 9 — is the owner's creative call and is NOT made in this plan | HIGH impact |
  user decides at B1]  The design shapes the song around what each beat must *demonstrate*;
  it does not choose the music. Per the propose-and-react discipline this is a creative
  lock-in, so B1 opens by proposing and reading the reaction rather than auto-deciding.
- ~~[ASSUMPTION: GitHub renders an inline `<video>` from a relative repo path | MED impact |
  resolved by probe, not by me]~~ **RESOLVED at A3, 2026-08-06 — it does not, and the
  reason is stronger than the assumption's framing:** GitHub's sanitizer removes the
  `<video>` element itself, so an absolute CDN `src` does not rescue it either. The hero
  is a poster still linking to the mp4. Evidence table in the design artifact; the same
  verdict replaced this chunk's `showwaves` video with a `showwavespic` still.
- [ASSUMPTION: total committed media ≤ 12 MB | MED impact | user can override] The design
  caps evidence by *count* (4 screenshots · 1 hero video · 3 audio clips) but not by
  *bytes*, and this is a public repo whose history is permanent — a decision to rewrite
  history was explicitly considered and closed (PRC-6N2X). A byte cap is the missing half
  of the count cap; D1 makes it a test rather than a hope.

**What would raise confidence:** B1's opening proposal, answered. Nothing else needs a
decision before A1 starts — Phase A is fully specified.

## Status

- [x] Chunk A1: Transcript renderer with a redaction gate
- [x] Chunk A2: Deterministic Ableton screenshot capture
- [x] Chunk A3: Media encode — audio clips, waveform stills, hero post, and the GitHub-video probe
- [x] Chunk A4: One lifecycle diagram, light/dark aware
- [x] Chunk B1: The `examples/` workspace and the demo song
- [x] Chunk C1: Capture the evidence from the finished set
- [x] Chunk D1: `docs/tour.md`, the README graft, and the freshness tests
Context: **COMPLETE (2026-08-11, `feat/tour-evidence` off v1.8.2).** All chunks
shipped. B1's second take is `examples/punk-fate/` — authored end-to-end from a
sparse prompt in one live session (2026-08-11, the same session the hero was shot
from), landed with its decisions, annotations, attempt ledger, analysis reports
and shape tests (commit 4fabff3). C1+D1 (commit abe99d7): the evidence set under
`docs/assets/` (all tool-produced from that session's real renders and frames,
plus one fresh off-grid MIDI capture), `docs/tour.md` (ten beats), the README
graft, and `tests/preferences/test_tour_freshness.py` (manifest item cap + 12 MB
byte cap + verbatim snippets + mix numbers recomputed from committed reports;
adversarially verified). Cumulative Critic rev-20260811T144456Z: 0 blocking.

**Chapter 2 extended the deliverable past this plan (`feat/tour-chapter2`).** The
same song went back into the studio for three re-cuts — feel, dirt/tone, and the
lead-instrument swap — so `docs/tour.md` gained a second chapter (beats 11–16)
and the song gained `decisions/08`–`11`, `measurements/`, and two attempt-ledger
entries. No chunk here covers it: the work matched none of A1–D1, which is why
the cumulative review could grade no chunk. Two governing changes it required,
both recorded rather than absorbed: the item cap in `tour-walkthrough-design.md`
§The concision rule is now **amended to account per editing session** (chapter 2
spends 2 screenshots · 1 audio item; 16 files, 7.0 MB of the unchanged 12 MB
byte cap) — owner-vetoable; and the tour's evidence-freshness locks grew to cover
chapter 2's figures, its heading structure, and the premise behind its published
true-peak number. A subsequent docs pass corrected five stale claims the chapter
left in the surrounding docs. Cumulative Critic rev-20260811T215052Z: 3 blocking,
all resolved on-branch.

**Two recorded deviations, deliberate and owner-rooted:** (1) the demo song is
115.2 s against B1's "60–90 s" acceptance line — the owner's own prompt asked
for 2 minutes, and the owner's directive outranks the plan's guideline; (2) the
hero *video* does not exist — no screen recording was taken, and the design
itself defers the demo video until the walkthrough is seamless
(`demo-video-design.md`), so the hero item ships as the committed still. Both
also recorded in the change-log entry and the C1/D1 commit message.

DOC-8V3Q was already closed by the v1.8.2 hero (#319, shipped); D1's close step
was a no-op. The B1 stale-fact list resolved as: pyproject comment (already
fixed pre-session, then refreshed), `project-root-contract.md` (generic wording
already true once punk-fate landed), #321/TMP-4J6Q (staleness comment filed
2026-08-11). The pre-split `project-preferences.md` layout rot (#320/DOC-4Q2X,
deferred until after B1) was rewritten at the Critic-disposition pass.

Every Phase-A chunk had its stated mechanism falsified by its own verify-api probe,
which is worth knowing before trusting a later chunk's stated mechanism:

- **A3's probe reshaped the design.** GitHub's sanitizer drops the `<video>` element
  outright — absolute `src` included — so the hero is a poster still linking to the
  mp4, and C1 captures accordingly. That verdict also killed this chunk's own
  `showwaves` video (it existed to make audio skimmable *inline*; nothing is inline),
  replaced by a `showwavespic` still. Evidence table in the design.
- **A2's mechanism did not exist.** Live publishes zero accessibility windows, and its
  own AppleScript dictionary blocks 120 s before failing, so no AppleScript path yields
  a window id. `CGWindowListCopyWindowInfo` via `ctypes` does, with no new dependency.
  **A2's live capture is blocked on Screen Recording permission**, which only the
  operator can grant — the five checks are queued in `operator-verification.md`.
- **A4** is verified in all four theme combinations, including both OS/GitHub theme
  mismatches; its GitHub-page render is queued for the operator.

Phase B is owner-gated (needs Live and real creative work), dominates the schedule, and
opens with a musical proposal rather than a decision; A, C and D are each well under a
day. Closes DOC-8V3Q (the placeholder hero) at D1. The pre-split `songs/` layout rot in
`project-preferences.md` is deferred to DOC-4Q2X, to be fixed once after B1 creates
`examples/` rather than twice.

## Scaffolding

### Project Initialization

None — this work lands inside the existing repo and adds no runtime dependency. The
capture tools are stdlib-only Python driving external binaries already present on the
authoring machine: `ffmpeg` 8.0.1 at `/opt/homebrew/bin/ffmpeg` and `screencapture` at
`/usr/sbin/screencapture` (both verified 2026-08-06), plus `git`, which A1 shells out to
for `rev-parse --show-toplevel` and which degrades to a no-op fallback when absent.

### Dependencies

**No new packaged dependency.** The external binaries are invoked as subprocesses, not
imported, and are needed only to *produce* the committed assets — never to consume
them. That asymmetry is deliberate: a reader cloning the repo gets the media as
committed files and needs neither binary, and CI needs neither either. The tools
therefore live in `tools/` (author-side, like the existing `tools/scenario_eval.py`),
not in `src/hallucinote/`.

As shipped, the full set is wider than "ffmpeg and screencapture": `ffmpeg` **and
`ffprobe`** (A3 — every post-encode check re-measures the file it just wrote),
`screencapture` **and `sips`** (A2 — `sips` does the downscale and reads the width
back; being macOS-native it costs nothing a macOS-only tool was not already paying),
plus `open` for raising Live and `ps` for naming the app that needs Screen Recording
permission. A2 additionally calls **CoreGraphics through `ctypes`** — a system
framework, not a package — because Live publishes no accessible window to ask.
Each tool checks for its binaries up front and names the missing one.

### Build & Test Configuration

Unchanged. New tests go under `tests/unit/tools/` (the existing home for
`tools/`-adjacent tests) except the structural doc tests, which go under
`tests/preferences/` per `project-preferences.md`. Finish every chunk with a **no-path**
`python -m pytest` — `testpaths` is `["tests", "hallucinote_mcp/tests"]`
(`pyproject.toml`), and a path-scoped run silently skips the half you did not name.

### Scaffold Verification

`tools/tour_transcript.py --help` runs and the no-path suite stays green.

### Verification Strategy

Each Phase-A tool is verified by running it against **real** input and eyeballing the
output, not only by unit tests: A1 against an actual session JSONL under
`~/.claude/projects/`, A2 against a running Ableton Live window, A3 against a real
render's capture directory. That is the point of the phase — the tools exist so the
evidence is generated rather than staged, and a tool that passes tests against fixtures
but produces unusable output against reality has failed its purpose.

Phase D's freshness tests are themselves verified adversarially: deliberately edit a
quoted snippet in `build.py` and confirm the test goes red, then revert. A green test
that does not actually check the rule is worse than no test.

## Project Structure

```
tools/
├── tour_transcript.py       # A1  session JSONL → redacted markdown excerpt
├── capture_live_shot.py     # A2  deterministic Ableton window screenshot
└── make_demo_media.py       # A3  audio clips + waveform stills; hero mp4 + poster
examples/
├── hallucinote.toml         # B1  layout="monorepo", songs_root="."
└── <slug>/                  # B1  the demo song (build.py, snapshot, decisions/…)
docs/
├── tour.md                  # D1  the worked example
├── assets/lifecycle.svg     # A4  the one lifecycle diagram, theme-proof
└── assets/                  # C1  the committed evidence (replaces hero.svg)
tests/
├── unit/tools/              # A1-A3 tool tests
└── preferences/             # D1  freshness + budget tests
```

### Module Boundaries

The three tools share nothing and import nothing from each other — each is a standalone
script with a `main()`. They do not import `hallucinote`: they operate on files
(transcripts, WAVs, window ids), not on the engine's model, and coupling them to it
would make the doc pipeline fail whenever the engine moves. The one exception is A3
reading a render's capture directory, which it *locates* by path convention
(`songs/<slug>/captures/<ts>/`) but which couples it to the manifest's **schema**, not
merely its layout: it reads `master.filename` and the three trust flags. That is a real
consumer relationship, registered in `boundary-patterns.md` → *Capture Manifest*, and it
is why A3 gates `schema_version` the way the in-`src` loader does. The supported-version
set is duplicated rather than imported (the no-engine-import rule above), so a test
asserts the duplicate equals the engine's — otherwise it drifts silently.

**Sibling duplication between the three is accepted, and this is the decision, not an
oversight.** The paragraph above argues only against importing the *engine*; it never
addressed the tools duplicating each other, and they do: a run-and-check subprocess
wrapper, a binary-presence check, an exited-0-but-wrote-nothing guard, and the
`argparse → try → print → return 1` skeleton each exist two or three times.

The cost of extracting them is not the extraction — it is the invocation contract.
Every tool is documented and used as `python tools/<tool>.py`, which puts `tools/` on
`sys.path` rather than the repo root, so a shared `tools/_toolshed.py` import fails
unless every call site becomes `python -m tools.<tool>` (or each tool grows a
`sys.path` shim). That change would touch three tools' docstrings, this plan, the
operator-verification entries, and the tour that quotes the commands — to deduplicate
roughly forty lines.

**What is not accepted is the copies silently diverging**, which already happened and
produced a real defect: A1 removes a stale output on refusal and A2/A3 did not, so a
failed re-shoot left the previous asset in place looking fresh. They are now aligned.
The rule going forward: a change to any of these four shared behaviours is applied to
every tool that has it in the same commit, or the duplication has stopped paying for
itself and the invocation change becomes the cheaper option.

## Build Chunks

### Chunk A1: Transcript renderer with a redaction gate

- **Description:** The walking skeleton — real session JSONL in, publishable markdown
  out, with redaction as a hard gate rather than a review catch. This is the tool that
  makes beats 1 and 8 of the tour genuinely un-fabricated, and it is first because the
  genuine session transcript happens exactly once (design §Sequencing).

  **Redaction is the reason this chunk is not trivial.** A session transcript carries
  absolute `/Users/<name>/…` paths, hook output, MCP server names, and the contents of
  memory files injected as `<system-reminder>` blocks. The public-readiness release that
  just shipped (v1.7.2) spent a whole cluster scrubbing exactly that class of exposure
  out of the tracked tree; a renderer that pipes it back into `docs/` reopens it. So the
  renderer **fails closed**: it emits nothing until every block has passed the filter,
  and an unrecognized record `type` is a refusal, not a silent skip.

  *(As shipped, the gate keys on what actually leaks rather than on the marker: an
  account segment — including its dash-encoded form in Claude Code's own directory
  names — and an unpaired reminder tag. A bare `/Users/` token and the bare word
  "system-reminder" in authored prose are deliberately allowed, since gating on those
  refuses any session that discusses its own harness. Tool names, MCP ones included,
  ship on purpose; choosing which session to render is therefore an editorial act.)*

  Concretely the filter drops `isSidechain` records (subagent chatter), `isMeta` records,
  every `thinking` block, all `system`/`attachment`/`file-history-snapshot` record types,
  and any block whose text matches the home-path or system-reminder patterns; it rewrites
  surviving absolute paths to repo-relative. Tool calls render as one-liners
  (`name` + `input.description`), never full inputs — a `Bash` command line is exactly
  where a stray absolute path hides.

  *(A stale `project-preferences.md` linting row — "None configured", untrue since ruff +
  mypy shipped as live CI gates in INF-2C4X — was corrected in the plan commit rather than
  here, because this plan's `governed_by` block cites that file as authority and must not
  cite a stale one.)*

- **Depends on:** none
- **Foreign API:** claude-code-transcript-jsonl
- **Artifacts consumed:** `tour-walkthrough-design.md` §Capture tooling item 1
- **Deliverables:** new `tools/tour_transcript.py`, new `tests/unit/tools/test_tour_transcript.py`, new `tests/unit/tools/fixtures/transcript_sample.jsonl` (a hand-built fixture carrying each record type **and** each leak class, so the redaction assertions have something to bite)
- **Tests:** unit — each record type routes correctly; each leak class (home path, system-reminder body, sidechain record, thinking block, hook output) is absent from the rendered output; an unknown record `type` raises rather than silently skipping; tool-call one-liners never include full `input`
- **Acceptance criteria:** run against a real session JSONL under `~/.claude/projects/` and the output contains a usable prompt→response excerpt with **zero** `/Users/` occurrences and no `<system-reminder>` content; `grep -c '/Users/' <output>` returns 0
- **Done when:**
  0. verify-api — the record and content-block shapes were probed against a real session
     on 2026-08-06 (`type` ∈ user/assistant/system/attachment/file-history-snapshot/
     custom-title/mode/last-prompt; `message.content` is `str` or a list of
     `text`/`thinking`/`tool_use`/`tool_result` blocks; `isSidechain`/`isMeta` present on
     user and assistant records). Re-probe and record any drift before writing handlers;
     build fixtures only after.
  1. Acceptance criteria met and tests pass (no-path `python -m pytest`)
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk A2: Deterministic Ableton screenshot capture

- **Description:** Raise Live, `screencapture -o -l <windowID>` grabs that window only,
  then downscale to a fixed width. Determinism is the whole value: a
  re-shoot after a Live UI change must be a one-liner, not a manual re-composition, or
  the four screenshots the design budgets become four permanent maintenance liabilities.
  macOS-only, which is sufficient and stated in the tool's docstring.

  *(The verify-api probe falsified the stated mechanism. Live publishes **no**
  accessibility windows — `count of windows` is 0 — and its own AppleScript dictionary
  times out rather than answering `id of window 1`, so no AppleScript path yields a
  window id. The window server's `CGWindowListCopyWindowInfo`, reached through `ctypes`
  and parsed via `plistlib`, does — with no new dependency. The design records both dead
  ends so neither is re-tried.)*
- **Depends on:** none (independent of A1)
- **Foreign API:** macos-screencapture-applescript
- **Artifacts consumed:** `tour-walkthrough-design.md` §Capture tooling item 2
- **Deliverables:** new `tools/capture_live_shot.py`, new `tests/unit/tools/test_capture_live_shot.py`
- **Tests:** unit — window-id resolution and the argv the tool would invoke, with the
  subprocess boundary faked (the fake built after the verify-api probe, never before);
  a missing/ambiguous Live window is a clear error, not a capture of the wrong window
- **Acceptance criteria:** with Live running, one invocation produces a correctly-framed,
  fixed-width PNG of the Live window; two consecutive runs on an unchanged set produce
  images of identical dimensions
- **Visual change:** yes — framing and legibility of a captured screenshot are exactly
  what a test cannot speak to
- **Done when:**
  0. verify-api — probe `screencapture -l` and the AppleScript window-id path against a
     real running Live; capture the actual invocation and output shape
  1. Acceptance criteria met and tests pass
  2. Operator-verification entry appended to `.prawduct/operator-verification.md`
  3. `/prawduct:critic` run and blocking findings resolved
  4. Committed and chunk marked `[x]` in Status

### Chunk A3: Media encode — audio clips, waveform stills, hero post, and the GitHub-video probe

- **Description:** From a render's capture directory (per-track and master WAVs already
  exist there): master → mp3, the A/B pair → two time-bounded clips, and a waveform
  still per clip so the audio is skimmable rather than an unlabelled download link. Plus
  hero post-production: crop, speed up, and emit an mp4 with its poster PNG.

  **The probe gates the design, so it runs first.** The design flags as unverified
  whether GitHub renders `<video>` from a relative repo path; the known-safe fallback is
  a poster image linking out. Resolve it by pushing a scratch asset to a branch and
  looking at the rendered page — not by recalling how GitHub behaved. The answer decides
  whether the hero is a video or a still, which decides what C1 captures, so guessing
  here costs a re-shoot.

  *(Probe result, 2026-08-06: `<video>` is stripped by GitHub's sanitizer outright —
  relative and absolute `src` alike — so the hero is a poster PNG linking to the mp4.
  The verdict and its evidence table are in the design artifact. It also removed the
  rationale for the `showwaves` **video** originally specified here: that existed to
  make audio skimmable *inline*, and nothing plays inline, so a `showwavespic` **still**
  replaces it — it renders inline, shows the whole arrangement's dynamics, and costs
  ~8 KB against a video's megabytes. The design records the substitution.)*
- **Depends on:** none (independent of A1, A2)
- **Foreign API:** ffmpeg
- **Artifacts consumed:** `tour-walkthrough-design.md` §Capture tooling items 3-4
- **Deliverables:** new `tools/make_demo_media.py`, new `tests/unit/tools/test_make_demo_media.py`, the probe verdict recorded in `.prawduct/artifacts/tour-walkthrough-design.md`
- **Tests:** unit — clip-boundary arithmetic and the ffmpeg argv for each output kind,
  subprocess faked; a capture directory missing its master WAV errors clearly rather than
  emitting a zero-length file
- **Acceptance criteria:** run against a real capture directory and produce a playable
  mp3 plus an inline waveform PNG for the full master and for two A/B clips, each clip's
  measured duration matching its requested bounds within 0.05 s; and a hero mp4 + poster
  PNG whose dimensions and duration match the requested crop and speed-up
- **Done when:**
  0. verify-api — confirm the waveform filter chain against the installed ffmpeg 8.0.1;
     **and** probe GitHub's inline-`<video>` rendering from a relative repo path, recording
     the verdict and the chosen hero form in the design artifact
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk A4: One lifecycle diagram, light/dark aware

- **Description:** A single hand-authored SVG — prompt → artifacts → Live → analysis →
  back. One diagram, not five, per the design's concision rule. Theme-aware via
  `prefers-color-scheme` so it reads on both GitHub themes; no external font or asset
  reference, since GitHub's sanitizer strips them and a diagram that renders locally but
  not on the repo page is worse than none.
- **Depends on:** none
- **Artifacts consumed:** `tour-walkthrough-design.md` §Capture tooling item 6
- **Deliverables:** new `docs/assets/lifecycle.svg`
- **Tests:** none directly — D1's asset-existence test covers it. Declared rather than
  omitted: an SVG's correctness is whether it reads, which is A4's operator check.
- **Acceptance criteria:** renders correctly on GitHub in both light and dark themes,
  with no external references
- **Type:** doc-only
- **Visual change:** yes
- **Done when:**
  1. Acceptance criteria met (checked on a pushed branch page, both themes)
  2. Operator-verification entry appended
  3. Committed and chunk marked `[x]` in Status

### Chunk B1: The `examples/` workspace and the demo song

- **Description:** **The expensive phase, owner-gated — it needs Live and real creative
  work, and it is what the whole pass is betting on.** The design names the risk
  precisely: the demo song *is* the product claim, and a mediocre one actively hurts.

  Creates `examples/hallucinote.toml` (`layout = "monorepo"`, `songs_root = "."`) and
  the demo song under it. Stock Live devices only, 60-90 seconds, so a reader can rebuild
  it. The bounded exception permitting this one in-repo workspace is already written into
  `.prawduct/artifacts/project-root-contract.md` on this branch and lands with the
  directory it describes.

  **This chunk opens with a proposal, not a decision.** Key, tempo, the central tension,
  what the chorus does — these are creative lock-ins the owner has not directed, and the
  song must additionally be *shaped so each beat has something to show*: a chorus that
  needs to lift (beat 5, melody lens), a kick/bass collision (beat 8, mix-review), and a
  feel change worth A/B-ing (beat 9, the money shot). Propose the shape, read the
  reaction, then drive the standard song workflow end-to-end. Capture as you go — the
  transcript is generated once.

  **Verify before authoring, not after:** the design asserts `examples/` needs no code
  change because marker discovery walks up from the song directory (root-contract
  precedence step 3). Confirm that against the resolver with a real DB-path resolution
  from inside `examples/<slug>/` before composing a note.
- **Status note (2026-08-07): the first take shipped and was then RETIRED.**
  `examples/angle-of-the-light` was built end to end, pushed, rendered and
  measured — and its real output was the six framework defects it surfaced by
  being rebuilt from scratch, not its audio. It is archived outside the repo; its
  ADRs remain in this branch's history. **The Deliverables below therefore name
  files that are not currently in the tree** — they describe what the NEXT take
  re-creates, and only `examples/hallucinote.toml` survives today.

  The next take is re-authored from a sparse prompt through discovery and
  elicitation, so it will be a *different song* — that is intended, not a
  regression. See `tour-walkthrough-design.md` → *A walkthrough, not a recipe*.
  Do not paste the first take's brief back in: the brief is what the elicitation
  pass must PRODUCE, and skipping it is the defect the next take exists to close.

  **Three places still describe the retired song in the present tense, and the
  next take must fix them — recorded here so a deferral does not become a drop:**
  `pyproject.toml`'s `testpaths` comment (it explains the song's tests, which no
  longer exist; `examples/` currently collects nothing, which is correct but
  undescribed), `project-root-contract.md`'s bounded-exception paragraph, and
  backlog item `TMP-4J6Q`, which quotes `examples/angle-of-the-light/build.py`
  by line number. None is wrong about intent; all three are stale about fact.

- **Depends on:** Chunk A1 (the transcript renderer must exist before the session that
  produces the transcript), A2, A3
- **Artifacts consumed:** `tour-walkthrough-design.md` §Where the demo song lives + §Sequencing, `project-root-contract.md` §Bounded exception, `song-conventions.md`
- **Deliverables:** new `examples/hallucinote.toml`, new `examples/angle-of-the-light/build.py`, new `examples/angle-of-the-light/captured_session.json`, new `examples/angle-of-the-light/tests/test_angle_of_the_light_build.py`, new `examples/angle-of-the-light/annotations/01-the-brief.md`, new `examples/angle-of-the-light/annotations/02-capture-log.md`, new `examples/angle-of-the-light/decisions/01-the-tritone-transfiguration.md`, new `examples/angle-of-the-light/decisions/02-the-time-budget.md`, new `examples/angle-of-the-light/decisions/03-the-microtiming-arc.md`, new `examples/angle-of-the-light/decisions/04-signal-chains.md`, new `examples/angle-of-the-light/decisions/05-the-master-ceiling.md`, new `examples/angle-of-the-light/decisions/06-the-octave-drop.md`, a rendered session transcript retained for D1
- **Tests:** the song's own build is the test — `build.py` runs headless to a DB with no
  Live present, which is what makes the CI-buildable claim real rather than asserted
- **Acceptance criteria:** the song builds from a clean checkout with no Live running;
  it pushes to Live and plays; it is 60-90 s and uses only stock devices; each of the ten
  tour beats has something real to point at
- **Visual change:** yes — it is a piece of music
- **Done when:**
  0. verify-api — resolve a DB path from inside `examples/<slug>/` and confirm marker
     discovery finds `examples/hallucinote.toml` with no resolution-code change
  1. The musical shape proposed and the owner's reaction incorporated
  2. Acceptance criteria met; no-path suite green
  3. Operator-verification entry appended (it plays, in Live)
  4. `/prawduct:critic` run and blocking findings resolved
  5. Committed and chunk marked `[x]` in Status

### Chunk C1: Capture the evidence from the finished set

- **Amendment — four artifacts CANNOT wait for this chunk.** Recovered here
  because it was written into the retired song's capture log and would otherwise
  have died with it. C1 keeps its role as the curation and budget-enforcement
  pass, and still spends the cap exactly once — but some of its raw material has
  to be acquired *during* composition, because these four stop being true the
  moment the song is finished:

  | Beat | Artifact | Why it cannot wait |
  |---|---|---|
  | 7 Materialize | the session view *filling in* | a finished set is full; "filling in" is a state, not a view |
  | 6 Arrangement | the arrangement *growing* | the whole-form shot works at the end; the *becoming* does not |
  | 8 Production & mix | the mix **before** the fix | once fixed, the evidence of the problem is gone |
  | 9 Iterate | the A/B pair | the "before" is by definition a discarded state; render it while it exists |

  Two standing rules follow, and they belong to B1 as much as to C1: **screenshot
  before fixing anything interesting — the bug is the evidence**, and **never
  stage a shot** — if an artifact would have to be manufactured to look right, it
  does not go in the tour. The premise of the document is that all of it happened.

- **Description:** Spend the evidence budget, exactly once, against the finished song:
  4 screenshots (off-grid MIDI in the clip editor, the arrangement, the session filling
  in, meters during playback), 3 audio clips (the full song, and the beat-9 A/B pair),
  and the hero in whichever form A3's probe determined. Every asset is produced by the
  A2/A3 tools rather than by hand, so a re-shoot is a re-run.
- **Depends on:** Chunk B1, A2, A3
- **Artifacts consumed:** `tour-walkthrough-design.md` §The concision rule (the hard cap)
- **Deliverables:** committed assets under `docs/assets/`, replacing the placeholder `docs/assets/hero.svg`
- **Tests:** none directly — D1 asserts existence and the byte budget
- **Acceptance criteria:** the cap is met exactly — 4 · 1 · 3 **items**, which is at most
  **12 files**, because the hero and each audio clip ship as a pair (media + the still
  that stands in for it, since nothing plays inline; see the design's *Evidence budget*).
  No more; every asset is
  git-tracked (`git ls-files --error-unmatch` per asset — a broad ignore rule silently
  swallowing a media directory is a known trap); total committed media ≤ 12 MB
- **Visual change:** yes
- **Done when:**
  1. Acceptance criteria met, including the tracked-ness check on every asset
  2. Operator-verification entry appended
  3. Committed and chunk marked `[x]` in Status

### Chunk D1: `docs/tour.md`, the README graft, and the freshness tests

- **Coordination note (2026-08-11, docs/release-readiness session):** the README this
  chunk grafts into was fully overhauled on `docs/release-readiness` (restructured
  sections, badges, `docs/assets/lifecycle.svg` embedded, known issues split out to
  `docs/known-issues.md`, new `docs/README.md` audience index) — base the graft on that
  branch's README, not the pre-overhaul one. Two parity tests will meet this chunk:
  `tests/unit/test_docs_index_parity.py` fails unless `docs/tour.md` gets a row in
  `docs/README.md`, and the lifecycle/pipeline doc-parity suite applies if the tour
  enumerates the push phases or the song lifecycle. Candidate raw evidence: the
  2026-08-11 punk-fate hero-session captures (prompt/brief and mix-review terminal
  frames, session + arrangement Live frames, a mid-push "filling in" frame — the state
  C1's amendment says is unrecoverable after the fact). The composed hero shipped as
  `docs/assets/hero.png`; the raw frames are preserved outside the repo on the owner's
  machine (`Desktop/hallucinote-hero-captures-20260811/`). Whether the tour uses them
  or a fresh capture is the owner's scope call.

- **Description:** Write the ten beats against the real artifacts, graft the evidence
  into the README (shorter in prose, richer in artifacts — it links to the tour, it does
  not restate it), and lock the whole thing with tests so it cannot rot quietly.

  **The freshness test's design is constrained by a known trap.** It must assert over
  content the test *controls* — the committed `docs/tour.md` and
  `examples/<slug>/build.py`, read by path — and never over ambient git or filesystem
  state. No mtime comparisons, no `git log` recency: CI checks PRs out **detached**, so
  an ambient-state assertion is green on `push:` and red on `pull_request:`, which this
  repo has already been burned by once.

  **It is deliberately one-directional, and that is a decision, not an oversight.**
  doc → source is asserted: every annotated snippet in `tour.md` must appear verbatim in
  the demo `build.py`. source → doc is **not** asserted, because the tour shows a curated
  subset of the song by design — the concision rule is the whole point — and a
  bidirectional lock would force every new line of `build.py` into the document. Recorded
  here so a future reviewer applying the repo's usual both-directions rule sees why this
  one departs from it.

  Closes DOC-8V3Q: the README's placeholder hero and its `<!-- HERO: … -->` comment both
  go away.
- **Depends on:** Chunks B1, C1, A1, A4
- **Artifacts consumed:** `tour-walkthrough-design.md` §The tour outline + §Doc boundaries
- **Deliverables:** new `docs/tour.md`, `README.md` evidence graft, new `tests/preferences/test_tour_freshness.py`
- **Tests:** doc→source snippet verbatim match; every asset path referenced by `tour.md`
  and `README.md` exists on disk; total committed media under `docs/assets/` ≤ 12 MB;
  `README.md` contains no `HERO:` placeholder comment
- **Acceptance criteria:** the tour reads end-to-end in ~10 minutes with one artifact per
  beat; the three doc roles stay distinct (quickstart = do-it-yourself, tour =
  watch-it-done, song-workflow = the map and the why) with links rather than restatement;
  the freshness test is verified adversarially — edit a quoted snippet, watch it go red,
  revert
- **Type:** cumulative-final
- **Visual change:** yes — the README is the repo's front page
- **Done when:**
  1. Acceptance criteria met and the no-path suite green
  2. Adversarial verification of the freshness test performed and its result stated
  3. Operator-verification entry appended
  4. Committed, then `/prawduct:critic cumulative` run and blocking findings resolved
  5. DOC-8V3Q closed via `/prawduct:backlog update status=shipped`
  6. Chunk marked `[x]` in Status

## Early Feedback Milestone

**Milestone chunk:** A1
**What the user can do:** run `tools/tour_transcript.py` against any of their own real
sessions and read a publishable, redacted markdown excerpt — the first tangible proof
that the tour's agent output will be genuine rather than staged.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic review passes. D1's
`cumulative` review makes the branch PR-ready.

**Note on the gate.** `active_build_plan` is repointed to this plan at A1 (PUB-READY
shipped in v1.7.2), so the stop-hook Critic gate arms normally for this work.

**Phase A's review cadence, as actually run.** A1 took three per-chunk rounds. A2, A3 and
A4 were then built back to back and covered by **one `cumulative` review spanning all
three**, rather than the per-chunk review each chunk's Done-when names. That is the
repo's recorded cadence preference — skip per-chunk review for small chunks and roll up —
and it is written here rather than left implicit, because an unticked Done-when step is
otherwise indistinguishable from a skipped one. The substitution is sound in this
direction only: `cumulative` covers all seven goals against `merge-base...HEAD`, a
strict superset of what three `chunk` reviews (goals 1-3, each against its own diff)
would have covered.

- After A1: confirm the redaction gate actually holds against a real transcript before
  three more tools and a song are built on the assumption that it does.
- After A3: the GitHub-video verdict is in — confirm the hero form before C1 spends the
  capture budget on the wrong asset.
- Before B1: the musical proposal is a genuine creative fork; the owner owns it.
- After D1 (cumulative): full-bundle review — the evidence budget, the doc boundaries,
  and whether the freshness tests really bite.
