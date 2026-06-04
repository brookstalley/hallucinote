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

## Setup

| Skill | What it does |
|---|---|
| `/hallucinote:ableton-mcp-install` | Install the Ableton Remote Script into Live's User Library (the one thing the plugin can't do for you — the MCP **server** itself comes from the plugin). Run once at setup, or after a Python/Ableton update. |
| `/hallucinote:ableton-mcp-uninstall` | Cleanly remove the Remote Script and the `hallucinote-mcp` entry. |

## Compose & author

| Skill | What it does |
|---|---|
| `/hallucinote:song-new` | Scaffold a new song: `songs/<slug>/` with `build.py`, snapshot, tests, and intent/decision folders. The start of every song. |
| `/hallucinote:song-pick-instruments` | Pick instrument **chains** per track (instrument + post-FX + send levels) from Live's browser, respecting a portability mode. The chain is authorship, not a mix-time to-do. |
| `/hallucinote:compose-part` | Compose a part to a finished, audible state via the author-as-code loop: write/extend note-generating code in `build.py`, build, and scoped-push the changed clips. Use to write or rewrite drums, bass, a lead line, or a section's comp. |
| `/hallucinote:track-new-with-instrument` | Create a MIDI track and load an instrument on it in one step. |
| `/hallucinote:return-new` | Create a return track, load an effect, and optionally initialize sends — *"build a new reverb/delay/chorus bus."* |
| `/hallucinote:clip-humanize` | Apply per-note velocity jitter to a clip for a looser feel. |

## Materialize & sync (push / pull)

| Skill | What it does |
|---|---|
| `/hallucinote:ableton-push` | Push the DB into Live through ten ordered phases (tempo → … → cues). Materializes a song from scratch or converges an existing set. |
| `/hallucinote:ableton-pull` | Pull manual Live edits (faders, mutes, sends, notes) back into the DB through the mutator path. |
| `/hallucinote:song-snapshot` | Refresh a song's `captured_session.json` against the open set — instrument params, sends, device chains. (Not for clips/notes/automation.) |
| `/hallucinote:snapshot-bake-recent-changes` | Bake mid-session device-parameter tweaks back into the DB so they survive the next push. Lighter than a full snapshot. |

## Mix

| Skill | What it does |
|---|---|
| `/hallucinote:mix-review` | Holistic, intent-aware mix review for a song — reads the whole MixReport (masking, loudness, reverb, per-part timing/feel, cross-rhythm) per section and interprets it *against* declared intent. Use after an analysis pass or when you ask *"how's the mix?"* |
| `/hallucinote:mix-sidechain` | Set up sidechain compression on a target track from a source track (capability-probed across native + third-party dynamics devices). |

## Understand a song

| Skill | What it does |
|---|---|
| `/hallucinote:song-context` | Query a song's composer intent + decision rationale (markdown-primary, FTS5-indexed) before non-trivial composition work. |
| `/hallucinote:decisions` | Query a song's compose-time audit log for prior LLM prompts and decision rationale. Complementary to `/hallucinote:song-context`. |

## Contributing & project health

These are for working on Hallucinote itself, not on a song.

| Skill | What it does |
|---|---|
| `/critic` | Independent Critic review — quality governance for code changes. |
| `/pr` | PR lifecycle — create, update, merge, or check status with an independent reviewer. |
| `/janitor` | Periodic codebase maintenance — health check across VCS hygiene, code quality, docs, tests, dependencies. |
| `/learnings` | Look up project learnings and preferences relevant to your current task. |
| `/prawduct-doctor` | Product-repo setup, health check, and repair. |

---

See the [Quickstart](quickstart.md) to put the composing and push/pull skills to
work, or [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the governance skills.
