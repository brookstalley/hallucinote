# FAQ

Short answers with links to the canonical docs. For install/connection
problems, the [README troubleshooting section](../README.md#troubleshooting) is
the authority — this FAQ points there rather than duplicating it.

## What is Hallucinote, and who is it for?

An LLM-native music composition and production environment: you describe musical
intent in plain language and Claude composes a song against a SQLite source of
truth, then pushes it into Ableton Live through an in-repo MCP server. It's for
technically-comfortable musicians and producers who are happy running a CLI.
See [`docs/VISION.md`](VISION.md) for the why.

## Do I need to know Python?

No — for using it. You talk to Claude Code in plain language; the agent writes
the `build.py` code for you. You'll get more control if you can *read* Python
(to inspect or hand-edit a part), but it isn't required. To *contribute* to
Hallucinote itself, yes — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Does it work on Windows?

Yes — macOS and Windows, with **Ableton Live 12**. On Windows, if `python` opens
the Microsoft Store, use `py -3` everywhere. See [README → Requirements and
Install](../README.md#requirements).

## Can I mix the song inside Hallucinote?

Hallucinote authors the mix as part of composing — instrument **chains**, device
settings, sends, and per-part feel ship with the song (sound design is
authorship, not a post-hoc to-do). You then push to Live and do hands-on mixing
there; pull your tweaks back with `/hallucinote:ableton-pull` to keep them. Detailed mix
*review* (masking, loudness, reverb, timing) is available via `/hallucinote:mix-review`,
which uses Max for Live (Live Suite, or the M4L add-on); `/hallucinote:compose-review`
reviews the composition against intent on any edition.

## A push overwrote my manual Live tweaks. How do I keep them?

The DB is the source of truth, so a fresh push converges Live to the DB. Before
re-pushing, fold your manual edits back into the DB:

- Faders / mutes / sends / notes → `/hallucinote:ableton-pull`.
- Device-parameter knob tweaks (and the full mix layout — params, sends, chains,
  sidechain) → `/hallucinote:song-snapshot`, the single durable mix bake. It writes
  the git-tracked `captured_session.json`, so the next `build.py` reproduces them
  (a DB-only bake would revert on rebuild).

See the [Quickstart](quickstart.md#4-pull-manual-edits-back-optional).

## Can I share a song if my collaborator doesn't have the same plugins?

Mostly yes. A song is a directory you commit to git. On push, the compat check
probes the collaborator's installed plugins and refuses-and-confirms if a
third-party plugin is missing, generating a `REQUIREMENTS.md` of what to install.
Native Live devices and catalog-ID drift are handled automatically; bundling
sample packs is out of scope. The three portability cases are spelled out in
[`docs/collaboration.md`](collaboration.md).

## Can I compose in a non-12 tuning (microtonal / 19-EDO / Bohlen-Pierce)?

Yes — a niche path built so 12-TET songs never pay for it. You think in
scale-degree indices, a mapper converts each to a MIDI integer the **unchanged**
generators consume, and Live's loaded tuning reinterprets the pitches at playback.
Push can't load the tuning for you (the LOM tuning surface is read-only), so it
instructs you to drag the cached `.ascl` in and warns if the wrong one is loaded.
Full story + current limitations: [`docs/alternate-tunings.md`](alternate-tunings.md).

## Where do the notes, automation, and arrangement actually live?

In the song's `build.py` and the SQLite DB it materializes — **not** in Live.
(Live's API can't read clip notes back, among other gaps, so the DB is the
authoritative score.) Manual *mixer* state in Live can round-trip via pull; clip
notes, automation, and arrangement are authored in `build.py`. See
[`docs/song-authoring-conventions.md`](song-authoring-conventions.md).

## It re-built the whole song — did it duplicate everything?

No. Push is **idempotent**: re-running converges Live to the DB's state instead
of stacking duplicates. Iterate freely — change something, push again.

## Live won't connect, or I get a "version mismatch."

See [README troubleshooting](../README.md#troubleshooting). The two most common
fixes: assign **Hallucinote** to a Control Surface slot in Live's Preferences,
and after a `git pull` that touched `hallucinote_mcp/`, rerun
`/hallucinote:ableton-mcp-install` then fully **quit and reopen Live** (a `/mcp` reconnect
isn't enough — Live caches Control Surface modules at startup).
`python -m hallucinote_mcp.cli preflight` diagnoses install state.

## How does Hallucinote find my song? It looked in the wrong place.

From a song slug, it looks — in order — at `$HALLUCINOTE_SONGS_ROOT`, then the
`hallucinote.toml` workspace marker **above** your session directory, then the
workspace that actually **holds that song** among the ones nested below your
session directory or sitting **beside** it (the usual framework-repo +
songs-repo pair). Only if nothing holds the song does a lone nested workspace
win, so a new song still scaffolds where you'd expect.

It never guesses between two real candidates: if two workspaces both hold the
slug, it says so and names them instead of picking one.

If your songs live somewhere that search can't see — a songs repo more than one
directory sideways, or several candidates — say so once:

```sh
export HALLUCINOTE_SONGS_ROOT=/path/to/your-songs/songs   # the dir holding the song dirs
```

That beats everything else, and every "couldn't resolve" message points at it.
The other reliable fix is simply to start Claude Code **inside** your songs
workspace (the folder with `hallucinote.toml`); `--plugin-dir` can still point
at the framework repo from there.

## Can I edit `build.py` by hand?

Yes. It's plain Python against the generator library, and the build is a
state-converger (running it brings the DB to match the code). The conventions —
generators, feel, kits, meter, repeated sections — are in
[`docs/song-authoring-conventions.md`](song-authoring-conventions.md).

## What can I ask Claude to do? Is there a command list?

See [`docs/skills.md`](skills.md) for the full menu. You don't have to type the
slash-commands — describe what you want and the agent picks the right skill.
