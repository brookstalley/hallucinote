# Developing Hallucinote on the machine you make music on

> **Maintainer note.** Read this only if you hack on Hallucinote itself *and*
> make music with it on the same machine. If you just installed the plugin to
> make music, none of this applies.

You both **develop** Hallucinote (the framework/plugin/MCP server, this repo) and
**use** it to write music (the `../hallucinote-songs` repo) on one machine. Those two
roles want incompatible things from the same Live instance, and getting it wrong
costs Live-restart cycles (it did on 2026-06-13). This is the recommendation.

## The one constraint you can't engineer away

Ableton Live loads **exactly one** Hallucinote Remote Script at startup, on one OSC
port, behind a **strict version handshake** (`server_version == remote_script_version`,
both a content fingerprint of the wire-shape files). Consequences:

- At any instant, only **one** server fingerprint can drive Live.
- The vendored Remote Script in Live's User Library is a **process-global singleton**
  — it can match only one server fingerprint at a time.
- Live **caches Control Surface modules at startup**, so re-vendoring while Live is
  open does nothing until a full quit + reopen.

Therefore **crossing the dev↔music boundary always costs a re-vendor + full Live
restart.** No topology removes this. Optimize everything *else*: make each activity
churn-free internally, and make the boundary crossing a single deliberate action.

## Three coupling axes (don't conflate them)

1. **MCP server / plugin** — which `hallucinote_mcp` Claude Code launches
   (marketplace plugin `main`, vs `--plugin-dir <repo>` `develop`). The active one
   shadows the other (same plugin name).
2. **Remote Script vendor** — the copy in Live's User Library; must fingerprint-match
   the running server (axis 1). This is the singleton above.
3. **Python engine** (`hallucinote`, imported by every `songs/*/build.py`) — now ships
   in the plugin's uv env (no separate install). Under `--plugin-dir` it's **editable
   from your checkout**, so in-flight generator edits change song builds live; the
   marketplace plugin runs the engine frozen from its lock.

Axes 1+2 are the handshake. Axis 3 is independent — decide it deliberately too.

## Recommendation: two worktrees, always `--plugin-dir`, no marketplace on this machine

Your instinct ("just use `--plugin-dir ../hallucinote` for songs too, drop the
marketplace install") is right. Do it via **two git worktrees** rather than
branch-switching one checkout:

```
../hallucinote            # your working tree on develop/feature  → DEV sessions
../hallucinote-stable     # git worktree pinned to main, never edited → MUSIC sessions
```

- **Dev session:** `claude --plugin-dir ../hallucinote` (develop).
- **Music session:** `claude --plugin-dir ../hallucinote-stable` (a clean `main`).

Create the stable worktree once:

```bash
git -C ../hallucinote worktree add ../hallucinote-stable main
```

Why this beats "marketplace for music + `--plugin-dir` for dev":

- **No shadow ambiguity.** Two same-named plugins fight; the marketplace silently
  shadows `--plugin-dir`. With worktrees there's only ever one plugin — the one you
  launched. (This is exactly what cost restart cycles: the server was `46bd`/develop
  while we *thought* the marketplace might be serving it.)
- **No autoUpdate surprise.** The marketplace's `autoUpdate` can move `main` under a
  song session mid-flight. A pinned worktree never moves until you `git pull` it.
- **"Which server is running" is unambiguous** — it's the `--plugin-dir` you typed.
- **No in-place `git checkout` dance.** Uncommitted dev edits can't block a music
  session; each worktree holds its own branch.

The marketplace install still matters for *real consumers* — it's just the wrong tool
on the *developer's* machine, where it's the source of the coexistence pain.

**Engine axis (3):** for music sessions, point `../hallucinote-songs` at the **stable
worktree's** engine (or a pinned release), so dev edits to generators don't silently
change song builds. For dev sessions, editable is correct.

## The unavoidable boundary crossing — make it one command

Switching activities still = re-vendor the Remote Script to the target worktree's
fingerprint + restart Live. That sequence should be a single supported action, not an
ad-hoc dance. A `dev-mode`/switch skill that (a) confirms which worktree's server is
active, (b) re-vendors the matching Remote Script, (c) prints the "quit + reopen Live,
then `/mcp`" steps + the current fingerprints — is the right tool, **but its design
depends on the topology choice above**, so it's filed for sign-off, not built blind
(backlog: the install cluster, alongside INS-3W8P).

## What makes any topology safe regardless: INS-3W8P

The foundational correctness fix (shipped with this doc): `/ableton-mcp-install` now
resolves the **running server's** identity (via the `ableton://server/info` resource)
and vendors / fingerprints against *that* copy — never whatever the install shell's
`sys.path` resolves first. `preflight` reports `server.confirmed` +
`coexistence_divergence`; `install-remote-script` takes `--from-package-root` +
`--require-server-version` and **refuses to vendor a divergent copy without mutating**.
So even if you keep a coexistence setup, the install can no longer silently produce a
handshake mismatch — and the runtime handshake remains the ultimate net.
