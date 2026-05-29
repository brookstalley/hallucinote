# Wave 0 — Canary songs

**Purpose.** Stress-test the v1 stack with shapes that exercise the corners falling-walking doesn't. Each canary is built by a fresh-context agent following the documented workflow (README + skills) as a moderately sophisticated user would. The agents **surface friction; they do not fix it.**

Each canary has:

- `<slug>.md` — the brief: one paragraph on shape + a list of system corners it targets.
- `<slug>-runbook.md` — the agent's running log of every friction, dead-end, recovery, and unanswered question.

After all three runbooks land, `triage.md` consolidates findings and maps each to a downstream wave/chunk or backlog entry (`W0-C`).

## The three canaries

1. **`solo-piano-ambient`** — Minimal-track, long-envelope, no-drums shape. Exercises envelope authoring without trip-hop's groove crutch.
2. **`full-band-rock`** — Many-track audio+MIDI mix with third-party plugins. Exercises Wave 13 (cross-machine portability) directly.
3. **`odd-meter-experimental`** — 7/8 + polyrhythm + multiple simultaneous tempos via the 1/64 grid. Exercises VISION's "reach music Ableton wasn't built for" claim.

## Reading the runbooks

Each entry in a runbook records:

- **What I tried** — concrete step, with the command or skill invoked.
- **What happened** — observed behavior including error text.
- **What was missing or confusing** — the friction itself: a doc gap, a tool that didn't exist, an unhelpful error, a chicken-and-egg with snapshots, etc.
- **What I did instead (if anything)** — improvisation logged so triage can decide whether the improvisation should become a real feature.

Successful steps are noted briefly; failures and friction get the air.
