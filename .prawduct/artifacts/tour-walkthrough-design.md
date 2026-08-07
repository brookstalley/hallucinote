---
artifact: design
version: 1
---

# Design — the demo song and the end-to-end tour

The public-readiness pass deliberately left one thing undone: the repo's prose is
strong and its **evidence is absent**. One placeholder hero SVG, no audio, no
screenshots. Every differentiating claim — *"a finished session arrives finished"*,
*"microtiming is authorship"*, *"the agent has an ear"* — is asserted, never shown.
For a music tool, the unanswered question is the loudest one: **what does it sound
like?**

This design covers the fix: **one reproducible demo song**, and **one worked-example
document** built from real artifacts captured while that song was authored.

## What we are building

1. **`examples/<slug>/`** — a demo song, in this repo, that a reader can clone and
   rebuild. Stock Live devices only. 60–90 seconds.
2. **`docs/tour.md`** — "Making a song, start to finish." Ten beats, one artifact
   per beat, ~300 lines, a ten-minute read.
3. **Capture tooling** — so the artifacts are *generated from real sessions*, not
   hand-staged, and can be regenerated when behavior changes.
4. **README evidence graft** — real hero, audio near the top, a link to the tour.
   The README gets *shorter* in prose, richer in artifacts. It does not restate the
   tour.

## The concision rule (this is the whole design)

**One spine song, one artifact per stage.** A mechanical cap, not a judgment call.
Each lifecycle stage earns exactly one piece of evidence, chosen for the thing only
it can show, and **links** to the existing deep doc rather than restating it.

**Evidence budget — hard cap:** 4 screenshots · 1 hero video · 3 audio clips.

**The cap counts *items*; two kinds of item ship as two files each**, both for the same
reason — GitHub renders no inline player, so every piece of media needs a still to
stand in for it (see *Capture tooling* item 4):

- the **hero** is one item = `hero.mp4` + the poster PNG that links to it;
- each **audio clip** is one item = `<name>.mp3` + its `showwavespic` waveform PNG.

So the budget permits **at most 12 media files** — 4 screenshots + 2 + (3 × 2) — and
neither the poster nor any waveform counts against the four screenshots. Everything
else is text or code. C1's "the cap is met exactly" and D1's asset test are both
written against those numbers; without this paragraph they have no unambiguous target,
and the likely outcome is a test relaxed to permit arbitrary extras — exactly what the
byte cap exists to prevent.
Everything else is text or code. Every screenshot is a maintenance liability, so
they are spent only where text cannot carry the point: off-grid MIDI, the full
arrangement, the session filling in, meters during playback.

## The tour outline

| # | Beat | The one artifact | What only this can show |
|---|---|---|---|
| 0 | The result, first | 60–90 s audio + hero poster → video | Lead with the song; everything after is "how" |
| 1 | Ideation → intent | Transcript excerpt: the brief, and Claude *proposing* key / central tension back | It does not auto-decide — propose-and-react |
| 2 | Scaffold + chains | Song directory tree + one instrument-chain listing | A song is a directory; sound design ships as authorship |
| 3 | Harmony & form | `build.py` excerpt — progression + section list | Harmony is a modeled substrate parts compose *against* |
| 4 | Rhythm & feel | `build.py` feel excerpt + clip-editor screenshot of off-grid notes | Microtiming is authorship — invisible in prose, obvious in a screenshot |
| 5 | Melody | Real `hallucinote melody` lens output | Symbolic analysis against a *declared* profile, not a universal score |
| 6 | Arrangement | Arrangement-model code + Arrangement-view screenshot | The whole form at a glance |
| 7 | Materialize | Real 14-phase push output + Session-view screenshot | It actually lands |
| 8 | Production & mix | MixReport excerpt + the producer-question `/mix-review` returned | The agent has an ear, and frames it as a question |
| 9 | **Iterate** | One change → the diff → **before/after audio A/B** | The money shot: the entire value proposition in one beat |
| 10 | Bake, commit, fork | `git log` / the song diff | Forkable and reproducible, not a binary |

## Doc boundaries — three jobs, no drift

- **`docs/quickstart.md`** — *do it yourself*, minimal path, ten minutes.
- **`docs/tour.md`** — *watch it done*, with evidence.
- **`docs/song-workflow.md`** — the map and the *why*, with the research behind it.

The tour absorbs the README's "See it" role. It links; it never restates. Drift
between the three is the standing risk, and link-don't-summarize is the control.

## Where the demo song lives

`examples/<slug>/`, with an `examples/hallucinote.toml` marker
(`layout = "monorepo"`, `songs_root = "."`). **No code change is needed** — marker
discovery (precedence step 3 of the root contract's resolution rules) finds it, and
per-branch DB naming probes the containing repo's branch as usual.

**With one caveat verified against the resolver, not assumed:** `find_workspace()` walks
up from `CLAUDE_PROJECT_DIR` / cwd / an explicit `start=` — *not* from the song
directory. Since `examples/hallucinote.toml` is a descendant of the repo root, a session
rooted at the repo root never sees it and silently falls back to the legacy
`songs/<slug>`. The marker resolves when the cwd is inside `examples/` or when the start
directory is named explicitly, which is what a CI build must do. See
[`project-root-contract.md`](project-root-contract.md) → *Bounded exception*.

**This departs from the framework⇄songs split** the root contract established, where
songs live in a separate workspace repo. The departure is deliberate and owner-chosen,
bought for two things a separate demo repo cannot give: the demo sits in the repo the
reader has already landed on — no second destination between the walkthrough and the
song it documents — and CI can build it as a real integration test.

It is recorded as a **bounded exception** in
[`project-root-contract.md`](project-root-contract.md) → *"Bounded exception — the
example workspace"*, scoped to documentation and CI. The split still holds for
authored work, and the onboarding paths continue to send users to a workspace of
their own. Amending the contract to match instead would have silently retracted a
norm that still binds everywhere else.

## Capture tooling

Ordered by value. Items 1–2 are what make this repeatable rather than a one-time
hand-staging exercise.

1. **`tools/tour_transcript.py` — session transcript → markdown.** Claude Code writes
   structured JSONL to `~/.claude/projects/<slug>/*.jsonl` with typed `user` /
   `assistant` records, tool calls and timestamps (verified against a real session).
   The renderer extracts a prompt, selected assistant text, and tool-call one-liners.
   This gives **real, un-fabricated agent output with zero hand-typing**, and lets the
   doc be regenerated after a behavior change. Hand-written fake transcripts are the
   first thing a skeptical reader catches; this removes the temptation.
2. **`tools/capture_live_shot.py` — deterministic Ableton screenshots.** Raise Live →
   `screencapture -o -l <windowID>` (that window only) → downscale to a fixed width.
   Deterministic framing makes a re-shoot after a UI change a one-liner rather than a
   manual re-composition. macOS-only, which is sufficient.

   **The window id does not come from AppleScript, because for Live there is none to
   get.** Probed against a real running Live on 2026-08-06: `count of windows` of
   process "Live" is **0** and its `AXWindows` attribute is empty — Live draws its
   interface on a custom surface, so it publishes no accessibility windows — and
   Live's own dictionary never answers `id of window 1`: it blocks for 120 seconds
   and then fails with an AppleEvent timeout (`-1712`), measured twice. The id comes
   instead from the window server itself,
   `CGWindowListCopyWindowInfo` reached through `ctypes` and serialised via
   `CFPropertyListCreateData` into something `plistlib` parses. That keeps the
   no-new-dependency rule intact: no PyObjC, no compiled helper. Live is raised with
   `open -a` (~0.1 s) rather than `osascript … activate` (~2 s on the same AppleEvent
   channel that hangs elsewhere).

   **It needs Screen Recording permission, granted to the terminal's host
   application** — and its absence does not announce itself: `screencapture` reports
   *"could not create image from window"*, which reads like a bad window id, and
   window names silently come back empty. The tool therefore preflights
   `CGPreflightScreenCaptureAccess` and names both the host app and the settings pane
   before it raises anything.
3. **`tools/make_demo_media.py` — audio and image encode.** From a render's capture
   directory (per-track + master WAVs already exist): master → mp3 (~1 MB/min), the
   A/B pair → two clips, and a waveform **still** per clip via ffmpeg `showwavespic`,
   so the audio is skimmable rather than an unlabelled download link.

   **A waveform *still*, not the `showwaves` video originally specified.** That was
   written to make audio "embeddable and skimmable rather than a download link", and
   item 4's probe removed the premise: GitHub renders no inline player, so a waveform
   video is a download link too — one that costs megabytes and a click to show a
   scrolling line. A `showwavespic` PNG *does* render inline, shows the whole
   arrangement's dynamics at a glance, and is ~8 KB. Each clip therefore ships as an
   inline waveform image linking to its mp3.
4. **Hero capture + post.** A two-window take (Claude Code left, Live filling in
   right) → ffmpeg crop → 4× speed → mp4 + poster PNG.

   **Probed 2026-08-06; the hero is a poster still linking out, not an inline
   player.** GitHub's markdown sanitizer **drops the `<video>` element entirely** —
   not merely its relative `src`. Rendering the four candidate forms through both
   `POST /markdown` (`mode=gfm`, repo context) and
   `GET /repos/{owner}/{repo}/contents/{path}` with `Accept: application/vnd.github.html`
   gave the same result on both:

   | Form | Rendered as |
   |---|---|
   | `<video src="relative.mp4">` | *nothing* — an empty `<p>` |
   | `<video><source src="…"></video>` with `poster` | *nothing* — element removed |
   | `<video src="https://raw.githubusercontent.com/…">` | *nothing* — absolute src does not help |
   | `![clip](clip.mp4)` | `<img src="clip.mp4">` — a **broken image**, worse than no hero |
   | `[![poster](poster.png)](clip.mp4)` | `<a href="clip.mp4"><img src="poster.png">` ✅ |

   So the fallback is the only form, and it is what C1 captures: a poster PNG
   wrapped in a link to the committed mp4. The mp4 still ships and still counts
   against the media budget — a reader gets one click, not zero.

   **The rejected alternative, so it is not re-litigated:** GitHub *does* play video
   uploaded through its web UI to `github.com/user-attachments/assets/…`. That route
   is rejected on design grounds rather than rendering grounds — such an asset lives
   outside the repo, so it cannot be produced by a tool, cannot be re-shot by a
   re-run, is invisible to the committed-media budget test, and vanishes from a
   clone. Every one of those is a property this design is buying deliberately.
5. **Docs-freshness test.** Extend the `markdown_refs` idea: assert every code snippet
   quoted in `tour.md` still appears verbatim in the demo song's `build.py`, and that
   quoted MixReport numbers match the committed report JSON. A worked example that
   rots is worse than none; this is what keeps it honest, structurally.
6. **One SVG lifecycle diagram** — prompt → artifacts → Live → analysis → back.
   Light/dark aware. One diagram, not five.

## Sequencing, and the ordering constraint that matters

**The tooling must exist before the demo song is authored.** The genuine session
transcript happens once. Build the renderer afterwards and you are re-staging a fake —
precisely what item 1 exists to prevent.

- **A — Tooling.** Items 1, 2, 3, 6. No Live required.
- **B — Author the demo song.** *The expensive phase; needs Live and real creative
  work.* Shaped so each beat has something to show: a chorus that needs to lift
  (melody lens), a kick/bass collision (mix-review), a feel change worth A/B-ing
  (beat 9). Capture as you go.
- **C — Screenshots and media** from the finished set.
- **D — Write `docs/tour.md`**, graft evidence into the README, add the freshness test.

Phase B dominates the schedule; A, C and D are each well under a day.

## The risk worth naming

**The demo song *is* the product claim.** A mediocre one actively hurts — *"this is
what it makes?"* is worse than showing nothing. Its quality, not the document's, is
what this pass is actually betting on. Stock-devices-only costs some polish, and
reader-reproducibility is worth that trade.
