# Quickstart — your first song in ~10 minutes

This is the guided version of the README's "Try it" section: one path, one
guaranteed result. By the end you'll have built the example song into Ableton
Live and heard it play, then composed a brand-new song from a single prompt.

**Before you start**, finish the one-time setup in the [README](../README.md):
install the package, run `/ableton-mcp-install`, select **Hallucinote** as a
Control Surface in Live's Preferences, and verify the bridge. This quickstart
assumes that's done.

> Everything below is said to **Claude Code** in plain language. The agent
> turns your words into the skills (`/song-new`, `/ableton-push`, …) and MCP
> calls under the hood — you don't type the slash-commands yourself unless you
> want to. The exact phrasings here are examples; paraphrase freely.

---

## 1. Open Live and Claude Code

1. Open **Ableton Live** with an **empty set**. (Hallucinote should already be
   selected as a Control Surface from setup — Preferences → Link, Tempo & MIDI.)
2. In a terminal, `cd` into the Hallucinote repo and run:

   ```bash
   claude
   ```

## 2. Build the example song

`songs/falling-walking/` is the canary song — a D-minor electronic piece the
project uses to gate every push. It's the safest first thing to build. Say:

> **"Load falling-walking into Live."**

Claude builds `songs/falling-walking/falling-walking-<branch>.db` from that
song's `build.py`, then pushes it into Live through ten ordered phases:

```
tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues
```

**What you should see:** Live fills with named tracks (drums, bass, …), return
tracks (reverbs/delays), clips in the Session view, and device chains on each
track. **Press play in Live** — you should hear the song.

If the push errors before finishing, check the
[README troubleshooting section](../README.md#troubleshooting) — the most common
cause is the Control Surface slot not being assigned, or Live and the Remote
Script being out of sync after a `git pull`.

## 3. Compose a new song from a prompt

Now the fun part. Describe a song — genre, length, structure, parts, and a
slug (the folder/file name). For example:

> **"Let's make a 2-minute punk rock song that condenses the chord progressions
> of Beethoven's 5th into those 2 minutes. Four parts: drums, bass, lead guitar,
> and vocals on a staccato synth. Call it punk-fate."**

Claude will:

1. Scaffold `songs/punk-fate/` (`/song-new punk-fate`) — `build.py`, a snapshot,
   tests, and intent/decision folders.
2. Pick instrument **chains** per track (instrument + effects + send levels).
3. Write note-generating code in `build.py` using the generator library.
4. Build the song's DB and **push it into Live**, with sound design baked in.

A finished song arrives finished — the device chains, feel, and mix moves are
part of being done, not a follow-up to-do list. **Press play.**

## 4. Iterate by talking

Don't like something? Say so:

> **"The bridge feels flat — lift the lead an octave there."**
> **"Raise the verse ghost snares."**
> **"Put a giant gated reverb on the chorus drums."**

Claude edits `build.py` (or the DB) and re-pushes. Re-runs are **idempotent** —
pushing again converges Live to the DB without piling up duplicates.

## 5. Pull manual edits back (optional)

If you tweak faders, mutes, or sends directly in Live and want to keep them:

> **"Pull my Ableton edits back into the DB."**

`/ableton-pull` diffs Live against the DB and folds the changes in through the
standard mutator path.

---

## Where to go next

- **[`docs/skills.md`](skills.md)** — the full menu of things you can ask for.
- **[`docs/song-authoring-conventions.md`](song-authoring-conventions.md)** —
  how `build.py` works, when you want to read or hand-edit it.
- **[`docs/collaboration.md`](collaboration.md)** — share a song with someone
  on a different machine.
- **[`docs/faq.md`](faq.md)** — short answers to common questions.
- **[`docs/VISION.md`](VISION.md)** — why Hallucinote works the way it does.
