# Skills reference

Hallucinote's capabilities are exposed as **Claude Code skills** — slash-commands
the agent invokes on your behalf. You rarely type these directly; you describe
what you want and the agent picks the right one. This page is the menu, so you
know what's possible.

Hallucinote ships as a **plugin**, so skills are namespaced — invoke one
explicitly by typing `/hallucinote:<name>` in Claude Code, or just ask in plain
language (*"build a reverb bus"* → `/hallucinote:return-new`). (Working inside
the framework checkout itself? Load it with `claude --plugin-dir .` — the names
are the same.)

> This list is maintained by hand; the source of truth is each skill's
> `description` in `skills/<name>/SKILL.md`. If something here disagrees
> with a skill's own description, the skill wins — please open a PR.

## Start here

| Skill | What it does |
|---|---|
| `/hallucinote:getting-started` | Orientation for a new user — checks your install (uv, the MCP bridge, the Remote Script, the Max for Live analyzer), says plainly what works with and without Max for Live, and **proposes** the next step (install if needed, then a new or existing song). Run it first, or whenever you're unsure "what now?". |
| `/hallucinote:song-workflow` | The song-creation **lifecycle map** — the phases, the skill that runs each, each stage's [definition of done](song-workflow.md#stage-exit-criteria), and the three checkpoints (`/song-brief`, `/compose-review`, `/mix-review`) that are easy to skip. Read first for any song work; links to [`docs/song-workflow.md`](song-workflow.md) for the full depth and the research behind each tool. |

## Setup

| Skill | What it does |
|---|---|
| `/hallucinote:ableton-mcp-install` | Install the Ableton Remote Script into Live's User Library (the one thing the plugin can't do for you — the MCP **server** itself comes from the plugin). Run once at setup, or after a Python/Ableton update. |
| `/hallucinote:ableton-mcp-uninstall` | Cleanly remove the Remote Script and the `hallucinote-mcp` entry. |

## Compose & author

| Skill | What it does |
|---|---|
| `/hallucinote:song-brief` | **The elicitation stage — runs before `/song-new`.** Sweeps the load-bearing dimensions a starting prompt left open (harmony, tempo, production stance, named narrative turns, meter, the section time budget, and the mechanism behind every named gesture), marking each **DECIDED / UNDECIDED / NOT-APPLICABLE**, and closes the undecided ones in **one consolidated turn of informed proposals** — never a questionnaire, and silent when nothing applicable is open. Writes `annotations/01-the-brief.md`, which supplies the tempo/meter/section values `/song-new` needs as arguments. |
| `/hallucinote:song-new` | Scaffold a new song: `songs/<slug>/` with `build.py`, snapshot, tests, and intent/decision folders — on the brief's values, not values invented to satisfy the command line. |
| `/hallucinote:song-pick-instruments` | Pick instrument **chains** per track (instrument + post-FX + send levels) from Live's browser, respecting a portability mode. The chain is authorship, not a mix-time to-do. |
| `/hallucinote:compose-part` | Compose a part to a finished, audible state via the author-as-code loop: write/extend note-generating code in `build.py`, build, and scoped-push the changed clips. Use to write or rewrite drums, bass, a lead line, or a section's comp. |
| `/hallucinote:track-new-with-instrument` | Create a MIDI track and load an instrument on it in one step. |
| `/hallucinote:return-new` | Create a return track, load an effect, and optionally initialize sends — *"build a new reverb/delay/chorus bus."* |
| `/hallucinote:clip-humanize` | Apply per-note velocity jitter to a clip for a looser feel. |

## Materialize & sync (push / pull)

| Skill | What it does |
|---|---|
| `/hallucinote:ableton-push` | Push the DB into Live through fourteen ordered phases (tempo → meter → tracks → returns → scenes → clips → mix → devices → routing → device-sidechain → envelopes → performed-automation → arrangement → cues). Materializes a song from scratch or converges an existing set. |
| `/hallucinote:ableton-pull` | Pull manual Live edits (faders, mutes, sends, notes) back into the DB through the mutator path. |
| `/hallucinote:tuning-pull` | Capture the alternate tuning loaded in Live onto a song (rare — non-12-TET songs only). Reads `song.tuning_system`, caches a re-draggable `.ascl`, records it on the song. See `docs/alternate-tunings.md`. |
| `/hallucinote:song-snapshot` | Refresh a song's `captured_session.json` against the open set — the single durable mix bake: instrument params, sends, device chains, sidechain sources. (Not for clips/notes/automation — those are build.py-owned; use `/ableton-pull` to stage them.) |

## Mix

| Skill | What it does |
|---|---|
| `/hallucinote:mix-sidechain` | Set up sidechain compression on a target track from a source track (capability-probed across native + third-party dynamics devices). |

## Review

| Skill | What it does |
|---|---|
| `/hallucinote:compose-review` | Compose-stage guided evaluation — reads the composition (sections, density, energy arc) and the symbolic melody/recurrence lenses *against* declared intent: *"you wanted the chorus to lift — does it?"* Use before the mix stage, or when you ask *"is the chorus landing?"* / *"what's missing?"* |
| `/hallucinote:mix-review` | Holistic, intent-aware mix review — reads the whole MixReport (masking, loudness, reverb, per-part timing/feel, cross-rhythm) per section and interprets it *against* declared intent. Use after an analysis pass or when you ask *"how's the mix?"* **Uses Max for Live (Live Suite, or the M4L add-on); without it, `/compose-review` is the symbolic alternative.** |

## Understand a song

| Skill | What it does |
|---|---|
| `/hallucinote:song-context` | Query a song's composer intent + decision rationale (markdown-primary, FTS5-indexed) before non-trivial composition work. |
| `/hallucinote:decisions` | Query a song's compose-time audit log for prior LLM prompts and decision rationale. Complementary to `/hallucinote:song-context`. |
| `/hallucinote:song-attempts` | Query a song's attempt ledger — what was tried on a part/section and how it turned out (including reverted dead ends) — *before* re-trying something. The compositional/mix sibling of `/song-context`. |

## Contributing & project health

These are for working on Hallucinote itself, not on a song.

| Skill | What it does |
|---|---|
| `/prawduct:critic` | Independent Critic review — quality governance for code changes. |
| `/prawduct:pr` | PR lifecycle — create, update, merge, or check status with an independent reviewer. |
| `/prawduct:janitor` | Periodic codebase maintenance — health check across VCS hygiene, code quality, docs, tests, dependencies. |
| `/prawduct:learnings` | Look up project learnings and preferences relevant to your current task. |
| `/prawduct:doctor` | Repo health-check, repair, and maintenance for an onboarded Prawduct repo. |

---

See the [Quickstart](quickstart.md) to put the composing and push/pull skills to
work, or [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the governance skills.
