# Quickstart — your first song in ~10 minutes

This is the guided version of the README's install section: one path, one
result. By the end you'll have composed a song from a single prompt and heard
it play in Ableton Live.

**Before you start**, finish the one-time setup in the
[README](../README.md#install): install **uv** (the plugin launches its bundled
environment with it) and the **plugin** (from GitHub: `/plugin marketplace add
brookstalley/hallucinote` then `/plugin install hallucinote@hallucinote` — or, for
framework dev, `claude --plugin-dir /path/to/hallucinote`). The plugin brings the
skills, the MCP server, **and** the engine — there's no separate engine install.
Then run `/hallucinote:ableton-mcp-install` and select **Hallucinote** as a Control
Surface in Live's Preferences. This quickstart assumes that's done.

> Hallucinote has two halves: the **plugin** (the `/hallucinote:*` skills + the
> MCP server, installed into Claude Code) and your **songs**, which live in
> their own git repo — a *song workspace* with a `hallucinote.toml` marker at
> its root. You compose in the songs repo; the plugin's skills work from there.

> Everything below is said to **Claude Code** in plain language. The agent turns
> your words into skills (`/hallucinote:song-new`, `/hallucinote:ableton-push`, …)
> and MCP calls under the hood — you don't type the slash-commands yourself
> unless you want to. The phrasings here are examples; paraphrase freely.

---

## 1. Open Live and Claude Code in your songs workspace

1. Open **Ableton Live** with an **empty set**. (Hallucinote should already be
   selected as a Control Surface from setup — Preferences → Link, Tempo & MIDI.)
2. In a terminal, `cd` into your **song workspace** — a repo with a
   `hallucinote.toml` marker at its root. Don't have one yet? Make an empty
   folder, `cd` into it, and run `hallucinote init-workspace` — it writes the
   marker, a `.gitignore` for the regenerable build artifacts (DB, captures,
   analysis), and `git init`s for you. (Or clone your existing songs repo.) The
   marker is just:

   ```toml
   # hallucinote.toml
   [workspace]
   layout     = "monorepo"
   songs_root = "songs"
   ```

   Then start Claude Code from the workspace:

   ```bash
   claude
   ```

   > New to all this? Run `/hallucinote:getting-started` instead — it detects a
   > missing workspace and offers to create one before you make your first song.

## 2. Compose a song from a prompt

Describe a song — genre, length, structure, parts, and a slug (the folder/file
name). For example:

> **"Let's make a 2-minute punk rock song that condenses the chord progressions
> of Beethoven's 5th into those 2 minutes. Four parts: drums, bass, lead guitar,
> and vocals on a staccato synth. Call it punk-fate."**

Claude will:

1. Come back **once** (`/hallucinote:song-brief`) with proposals for whatever the
   prompt left open and load-bearing — here, the key Beethoven's progressions get
   condensed into and how the 2 minutes are budgeted across the four parts. Each
   comes with reasoning and a recommendation, so *"yep"* is a complete answer.
   The result is written down as the song's brief.
2. Scaffold `songs/punk-fate/` (`/hallucinote:song-new punk-fate`) — `build.py`,
   a snapshot, tests, and intent/decision folders — using the brief's values.
3. Pick instrument **chains** per track (instrument + effects + send levels).
4. Write note-generating code in `build.py` using the generator library.
5. Build the song's DB and **push it into Live** through fourteen ordered
   phases — with sound design baked in:

   ```
   tempo → meter → tracks → returns → scenes → clips → mix → devices → routing → device sidechain → envelopes → performed automation → arrangement → cues
   ```

**What you should see:** Live fills with named tracks (drums, bass, …), return
tracks (reverbs/delays), clips in the Session view, and device chains on each
track. A finished song arrives finished — the chains, feel, and mix moves are
part of being done, not a follow-up to-do list. **Press play in Live** — you
should hear it.

If the push errors before finishing, check the
[README troubleshooting section](../README.md#troubleshooting) — the most common
cause is the Control Surface slot not being assigned, or Live and the Remote
Script being out of sync after an engine update.

> **Already have songs in this workspace?** Just name one — *"Load falling-walking
> into Live."* Claude builds `songs/falling-walking/falling-walking-<branch>.db`
> from that song's `build.py` and pushes it.

## 3. Iterate by talking

Don't like something? Say so:

> **"The bridge feels flat — lift the lead an octave there."**
> **"Raise the verse ghost snares."**
> **"Put a giant gated reverb on the chorus drums."**

Claude edits `build.py` (or the DB) and re-pushes. Re-runs are **idempotent** —
pushing again converges Live to the DB without piling up duplicates.

## 4. Pull manual edits back (optional)

If you tweak faders, mutes, or sends directly in Live and want to keep them:

> **"Pull my Ableton edits back into the DB."**

`/hallucinote:ableton-pull` diffs Live against the DB and folds the changes in
through the standard mutator path.

---

## Where to go next

- **[`docs/skills.md`](skills.md)** — the full menu of things you can ask for.
- **[`docs/song-authoring-conventions.md`](song-authoring-conventions.md)** —
  how `build.py` works, when you want to read or hand-edit it.
- **[`docs/collaboration.md`](collaboration.md)** — share a song with someone
  on a different machine (a song is a git repo).
- **[`docs/faq.md`](faq.md)** — short answers to common questions.
- **[`docs/VISION.md`](VISION.md)** — why Hallucinote works the way it does.
