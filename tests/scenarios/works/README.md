# Musical-work eval harness — capability regression for the *output*

The persona scenario-eval (`../briefs/`, `tools/scenario_eval.py`) judges a
**transcript**: did the agent *behave*. This harness judges the other axis —
given an **abstract stylistic request** (a style + a few key characteristics,
one level up from a literal spec), does the system *produce the right song*, and
does it tell the truth about what it cannot produce?

It is the sibling module `tools/song_eval.py`, reusing the persona judge-result
schema verbatim (a work result is a persona result by shape).

## Two scoring surfaces

Every rubric line is prefixed with the surface it is scored against:

- **`framing:`** — read from the **conversation transcript**. Honest dimensional
  caveats, no confabulation, the round-trip invite, honest refusal.
- **`artifact:`** — read from the **produced song**. This surface is *tiered*,
  degrading gracefully with the capability cliff:
  1. **Supported dimensions** → the *existing* review surface. We build **no**
     new musical inference: `/compose-review` reads the composition (sections,
     density, register, the energy arc) from `build.py` + the arrangement —
     **no audio** — and the judge interprets *that report* against intent.
     When audio exists, `ableton_analysis(action='analyze')` → `/mix-review`
     adds the masking/loudness layer (optional).
  2. **The cliff** → once a request asks for something with no generator or
     helper, the analyzers go *blind* — they have no frame for what was produced.
  3. **Novel / emergent output** → the tool can still *produce* something (raw
     notes / clips / devices written directly). Evaluate the **actual produced
     song via a raw DB extract** and reason about it on its own terms. The judge
     prefers the analyzer report where it speaks to a line and falls back to the
     raw DB extract where the request outran the analyzers — `judge-prompt`
     takes both `--compose-review` and `--db-extract`.

     The extract is just text the judge reads, so the producer is open. Today:
     query the song's sqlite DB through `hallucinote.db.queries`
     (tracks / clips / notes / sections / devices). The natural increment — and
     the consistent home with how the agent reaches everything else — is to
     surface a song **structural dump as an MCP action/resource** alongside
     `ableton_analysis`, so the same extract is one tool call rather than a
     bespoke script. Deferred until the cliff briefs (#5 phase piece, #6 art
     song) actually need it; the thin slice (`lofi-study`) is a supported
     `deliver` case that compose-review reads on its own.

  Pushing to Live is optional throughout; a populated DB is enough to score.

## Capability cliffs are the point

Each brief carries `expected_capabilities` — per-dimension expected outcome:

| expectation | meaning |
|---|---|
| `deliver` | render the dimension fully |
| `caveat` | render, but name the thin dimension honestly (e.g. melody ◐) |
| `refuse` | honest "can't, here's why" (e.g. sung vocals ✗) |
| `known-gap` | we'd attempt it but the capability isn't built — a real failure the suite is meant to surface |

Keyed to `docs/capability-truth.md`. This makes the suite a **regression
tracker**: when melody or vocals mature, flip the affected expectation and the
same brief re-grades to a higher bar. Update `CAPABILITY_DIMENSIONS` in
`song_eval.py` and the capability table together.

## Brief schema

| Field | Notes |
|---|---|
| `id` | Lowercase slug; **must equal the filename stem**. |
| `request` | The abstract prompt the simulated user voices. |
| `response_character` | *How* they respond, not *what* — vocabulary, what they defer. |
| `axes` | `{specificity: loose/medium/precise, sophistication: simple/medium/complex/very-high}`. |
| `expected_capabilities` | `[{dimension, expectation, note}]` — backbone of the artifact rubric. |
| `rubric.must` / `must_not` | Each line starts `framing:` or `artifact:`. |
| `tags` | Optional. |

## Runner procedure (ad hoc, per work)

Run from repo root.

1. **Pick a brief**: `python -m tools.song_eval list` / `show <id>`.
2. **Voice the request**: `python -m tools.song_eval request-prompt <id>`. Spawn
   a **user subagent** with that prompt. It is *not* shown the rubric or the
   capability expectations — it must not lead the witness.
3. **Run the conversation + compose pass**: a second agent plays the Hallucinote
   agent. Seed the song's declared intent from
   `python -m tools.song_eval intent-doc <id>` (this is what `/compose-review`
   RECALLs), scaffold via `/song-new`, compose a first pass so `build.py`
   populates the DB. Capture the full transcript to a file. Push to Live only if
   you want the optional mix surface.
4. **Score the artifact** (tiered): run `/compose-review <slug>` and capture its
   output. For a request that outran the analyzers (a `known-gap` or novel
   result), also capture a **raw DB extract** of the produced song
   (tracks / clips / notes / sections / devices via `hallucinote.db.queries`) so
   the judge can evaluate what the analyzer can't read.
5. **Render the judge prompt**:
   `python -m tools.song_eval judge-prompt <id> --transcript t.txt --compose-review c.txt [--db-extract d.txt]`.
   Spawn a **judge subagent**; it returns a JSON result. (Omit both artifact
   flags only to record a no-compose run — every `artifact:` line then scores
   false by construction.)
6. **Record it**: write the JSON through `write_result` (validates + timestamps,
   names it `<id>-<UTC>.json` under `../results/`), or check a saved file with
   `python -m tools.song_eval validate-result <file>`.

## Status

Six works author the grid up to two deliberate capability cliffs:

| Brief | Axes | The point |
|---|---|---|
| `lofi-study` | loose / simple | In-capability `deliver` — the slice that proved the wiring. |
| `pop-hook` | loose / medium | The canonical move: deliver the bed, `caveat` melody, `refuse` vocals, invert into round-trip. |
| `synthwave-chase` | loose / complex | All `deliver`, **arc-stress** — the artifact must actually escalate density section to section. |
| `soul-ballad` | loose / complex | Vocal-centric → honest `refuse` + **round-trip redirect** as the centerpiece, bed delivered. |
| `reich-phase` | medium / very-high | `known-gap` — no phasing generator; the brief that **exercises the raw-DB artifact tier** (compose-review is blind to phase). |
| `art-song` | precise / very-high | **Layered refusal** — vocals + lyrics `refuse`, narrative-bearing melody `caveat`, through-composed bed delivered. |

Each is keyed to `docs/capability-truth.md`; when a dimension matures there, flip
the affected brief's expectation and re-run. The corpus test
(`tests/unit/tools/test_song_eval.py`) asserts the set is exact, every
expectation kind is exercised, and the grid is spanned — a missing cliff is a
failing test, not a quiet gap.
