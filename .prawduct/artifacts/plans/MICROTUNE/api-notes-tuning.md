# MICROTUNE — verify-api findings (Chunk 1, step 0)

**Status: PARTIAL.** The None/12-TET branch + read path + version drift are confirmed live;
the **loaded-tuning dict shapes remain PENDING** (could not load a tuning — see below).

## Probe context (2026-06-16)

- Live was running and **occupied by another agent's song** (12-TET). Only **read-only**
  probes were run; nothing in Live was mutated, and **no tuning was loaded** (loading is
  Set-global and saved in the Set → it would clobber the active song).
- Probes used `ableton_probe` with `allow_version_mismatch=true` (justified: read-only, and
  re-vendoring to reconcile the drift was explicitly off the table this session).

## Confirmed

1. **`song.tuning_system` on a 12-TET Set → `{"type": "NoneType", "value": null}`.**
   Grounds `read.py`'s `tuning_system is None → 12-TET no-op` branch in a live reading
   (matches the requirements doc's "fresh Set reads None").
2. **Read path is reachable** through the running server (the probe returned `ok: true`).

## Version drift observed — and why it does NOT block MICROTUNE

> MCP server `0.1.0+c487d2b32ba7`; Remote Script `0.1.0+dc62195e594a`.

This is the exact mismatch the build plan flagged as a "blocking precondition." **Reframed
by the live probe:** the bypass warning scopes the corruption risk to *mutating calls*
("This bypass CAN RESULT IN DATA CORRUPTION on mutating calls"). **MICROTUNE performs zero
Live mutations** — it only *reads* `song.tuning_system` (verify-api + push-time drift
re-read), then writes files + DB rows locally. So `allow_version_mismatch=true` on the
read-only probes is safe, and the mismatch is **not** a true blocker for this feature.
The real gate is simply **having a tuning loaded in a Set we can read** — a Live-availability
constraint, not a version one. (Fold this back into the build plan's precondition framing.)

## PENDING — the sole Medium→High gap

The dict shapes of a **loaded** tuning are still unknown (typed only as "dictionary" in the
Cycling '74 ref):

- `note_tunings` — relative note tunings in cents (shape? keyed by MIDI note? a flat array?)
- `reference_pitch`
- `lowest_note` / `highest_note`
- `pseudo_octave_in_cents` (the period — scalar, should be straightforward)

**To close it:** load a tuning in a readable Set (EDO, a JI/ratio tuning, and a non-octave
e.g. Bohlen-Pierce), then probe `song.tuning_system` with
`ableton_probe(action='get'/'describe', path='song.tuning_system', allow_version_mismatch=true)`
and walk each field. Record the actual shapes here before locking `read.py`'s extraction.

**Until then:** `read.py`'s loaded-tuning *extraction* is the ONLY piece held — it ships as a
clearly-marked stub with a fixture-based test. The `.ascl` writer, mapper, cache, DB column,
and mutator/query consume the *derived* blob (`{name, step_count, period_cents,
reference_note, step_cents}`), whose shape we decided — they're independent of the LOM dict
shape and can be built now.

## `.ascl` writer format (researched 2026-06-16 — the write side, CONFIRMED)

Sources (cross-checked ≥2): Scala `.scl` spec (huygens-fokker.org/scala/scl_format.html) ·
Ableton ASCL spec (help.ableton.com — "ASCL Specification", as of Live 12.1) ·
surge-synthesizer/tuning-library parser + its Ableton-shipped `.ascl` fixtures.

The writer (`tuning/ascl.py`) emits, in order:

1. `!`-comment lines (filename + a "reconstructed by Hallucinote" provenance note).
2. **Description** line (first non-comment line) = the tuning name.
3. **Note-count** line (second non-comment line) = `step_count`.
4. **`step_count` pitch lines**, each cents (a value with `.` is cents; `/` or bare int is a
   ratio — we emit cents uniformly, 6 dp). The implicit `1/1`/0-cent unison is **not** listed;
   the **last** pitch line is the period (`period_cents`, never assumed 1200 — non-octave OK).
5. `! @ABL` directives **after** the pitch list; file is UTF-8.

Deliberately **omitted**, both optional: `@ABL NOTE_NAMES` (LOM exposes no note names) and
`@ABL REFERENCE_PITCH octave index freq_Hz` (our blob has no reference *frequency* — only a
MIDI anchor). When `REFERENCE_PITCH` is absent Live auto-assigns one; the result reproduces
the tuning's **interval structure** faithfully, with the absolute pitch anchor left to Live —
the accepted reconstruction limitation. (`@ABL NOTE_RANGE_BY_INDEX` requires `REFERENCE_PITCH`,
so it's out too.) Adding a `reference_hz` blob field + `REFERENCE_PITCH` is a future additive
step once the LOM `reference_pitch` dict shape is captured (same verify-api gate as above).

**Round-trip proof without Live:** `tests/unit/tuning/fixtures.py::parse_scl` is a test-only
spec-faithful Scala reader (the package ships no parser); the writer's cents re-read to
`step_cents` on EDO / JI / non-octave fixtures. Live round-trip (success-criterion #3,
re-drag → `note_tunings` matches) stays deferred to the same loaded-tuning gate.

**Structural parity against a real Ableton file (2026-06-16).** `tests/unit/tuning/data/
wendy_carlos_gamma.ascl` is copied verbatim from Live 12 Suite's Core Library
(`Tunings/EDO/Wendy Carlos gamma.ascl`) — a genuine, Ableton-authored, **non-octave** tuning
(20 equal divisions of the 3/2 perfect fifth; period ≈ 701.955 cents, NOT 1200). It confirms
the researched format end-to-end: count line = 20 pitch lines (implicit unison unlisted),
the period written as the ratio `3/2` on the last pitch line, and `@ABL NOTE_NAMES /
REFERENCE_PITCH 3 0 440.0 / NOTE_RANGE_BY_INDEX / LINK` after the pitch list — exactly the
directive shapes the research predicted. `test_ascl_parity.py` proves our writer round-trips
this real tuning's cents and stays Ableton-compatible while honestly omitting the
REFERENCE_PITCH / NOTE_NAMES / NOTE_RANGE we can't derive from the blob. (This is a *write*-side
parity check — it does NOT close the read-side loaded-tuning stub, which still needs a tuning
loaded in a readable Live Set to capture the LOM `tuning_system` dict shapes.)
