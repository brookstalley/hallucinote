# MICROTUNE — verify-api findings (Chunk 1, step 0)

**Status: CLOSED (2026-06-19).** The None/12-TET branch + read path + version drift were
confirmed live on 2026-06-16; the **loaded-tuning shapes are now confirmed too** — probed off
a real loaded tuning (Wendy Carlos gamma) on 2026-06-19. The shapes turned out **simpler than
feared** (a flat `list[float]`, not the typed-as-"dictionary" guess), and `read.py`'s
extraction is closed against them. See "Loaded-tuning shapes — CONFIRMED" below.

## Loaded-tuning shapes — CONFIRMED (2026-06-19, Wendy Carlos gamma)

Probed via `ableton_probe(action='get'/'describe', path='song.tuning_system…',
allow_version_mismatch=true)` with the tuning loaded in Live's Tuning section. `TuningSystem`
properties (the captured values are verbatim in `tests/unit/tuning/fixtures.py::GAMMA_LOADED_RAW`):

| LOM field | type | value (gamma) | → `TuningData` |
|---|---|---|---|
| `name` | `str` | `"Wendy Carlos gamma"` | `name` |
| `note_tunings` | **`list[float]`** | `[0.0, 35.0977…, …, 666.857…]` (20 entries) | `step_cents` = `note_tunings[1:] + [period]` |
| `number_of_notes_in_pseudo_octave` | `int` | `20` | `step_count` (== `len(note_tunings)`) |
| `pseudo_octave_in_cents` | `float` | `701.9550…` | `period_cents` |
| `reference_pitch` | `ReferencePitch` | `{octave:3, index_in_octave:0, frequency:440.0}` | `reference_note` = `(3+2)*12+0` = **60** |
| `lowest_note` / `highest_note` | `PitchClassAndOctave` | `{octave, index_in_octave}` | **unused** (range, not blob) |

**The key shape facts (each closes a prior unknown):**

1. **`note_tunings` is a flat `list[float]`, not a dict.** Degree-indexed `0..n-1` within ONE
   pseudo-octave (length == `number_of_notes_in_pseudo_octave`), **NOT** keyed by MIDI note and
   **NOT** 128-long. Index 0 is the unison (`0.0` cents); the **period is excluded** (it's the
   separate `pseudo_octave_in_cents` scalar). So `step_cents` = drop `note_tunings[0]`, append
   the period as the final degree (the Scala convention `TuningData` stores). `read.py` asserts
   `note_tunings[0] ≈ 0` and `declared count == len` so a misread fails loud.
2. **`reference_pitch` is a STANDARD 12-key MIDI anchor** (`ReferencePitch`: `octave`,
   `index_in_octave` 0–11, `frequency`). `reference_note = (octave+2)*12 + index_in_octave` —
   Ableton's C3=60 numbering, the same convention the ASCL `REFERENCE_PITCH octave index freq`
   directive uses (cross-checked against the shipped gamma `.ascl`'s `REFERENCE_PITCH 3 0 440.0`).
   This off-by-12 matters for *correctness*, not just register: 12 is not a multiple of
   `step_count`, so a wrong octave base would corrupt the degree mapping (`% step_count`). The
   blob deliberately drops the 440 Hz `frequency` (decision 4 — interval structure, not anchor).
3. **`lowest_note` / `highest_note` (`PitchClassAndOctave`) are NOT 12-key** — their
   `index_in_octave` can exceed 11 (gamma's highest = `{octave:5, index_in_octave:18}`), so they
   express the playable range in the tuning's **own pseudo-octave degree** coordinates. Not
   needed for the blob; not read by `read.py`.
4. **The probe path grammar reaches nested scalars** — `song.tuning_system.reference_pitch.octave`
   and `.index_in_octave` both `get` cleanly, so the `/tuning-pull` skill probes them directly
   (no `describe` needed).

**Drift-warn (Chunk 3) is now verified-by-shape too:** `tuning_notice._read_loaded_tuning`
probes `song.tuning_system.name` (str) + `.pseudo_octave_in_cents` (float) and the top-level
`{type:"TuningSystem"}` discriminator — all three confirmed above. Chunk 3's "scalars unverified"
honest-confidence caveat is resolved; the remaining name+period-only compare is a deliberate
scope choice, not an unverified one.

---

## Original probe context (2026-06-16) — the PARTIAL state, retained for history

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

## PENDING (2026-06-16) — RESOLVED 2026-06-19

> This was the sole Medium→High gap as of the 2026-06-16 partial probe: the loaded-tuning
> shapes (typed only as "dictionary" in the Cycling '74 ref). It is now **CLOSED** — see
> "Loaded-tuning shapes — CONFIRMED" at the top. The guess that `note_tunings` might be
> "keyed by MIDI note" was wrong: it's a flat degree-indexed `list[float]`. `read.py`'s
> extraction is closed against the real shapes (no stub remains).

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
