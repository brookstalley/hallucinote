---
artifact: build-plan
version: 1
scope: CAPSPAN-491
branch: fix/capture-start-offset
depends_on:
  - artifact: architecture
  - artifact: api-contract
  - artifact: nonfunctional-requirements
governed_by:
  - artifact: project-preferences
    dispositions:
      - "reuse over new mechanism → the span check extends alignment.py, which already owns 'does the captured audio have the length it should', and lands in the report's existing `alignment` block; no new report section"
      - "one fact, one home → the beat→seconds integrator moves to a shared public function so BeatSampleMap and the span check cannot disagree about how long a declared span is"
partition: serial — Chunk 02 consumes the API Chunk 01 defines
last_validated: 2026-09-09
critic_mode: cumulative-final
---

# Build plan — CAPSPAN-491: a capture that does not span what it declares must say so

Backlog: #491. Incoming report:
`incoming-bugs/2026-09-08-render-capture-starts-one-beat-early.md`.

## Requirements Confidence

**Level:** High

**Why:** The defect and the discriminator were measured against three real captures
of `songs/alien` before any design was chosen (2026-09-09, `~/source/hallucinote-songs`),
not inferred from the report.

| capture | declared span | master audio | excess |
|---|---|---|---|
| `20260908T233753Z` (the reported one) | 515 beats = 249.19 s | 249.71 s | **+1.06 beats** |
| `20260909T041123Z` | 523 beats = 253.06 s | 253.06 s | −0.02 beats |
| `20260909T043509Z` | 523 beats = 253.06 s | 253.05 s | −0.04 beats |

At 124 BPM. The separation is ~20× the healthy spread, so the threshold is not a
tuning problem.

**Two facts the report did not have, both load-bearing:**

1. **The per-surface spread is normal and must not be flagged.** Within *every*
   capture, healthy ones included, the returns run up to +0.38 beats longer than
   the master — that is the #417 independent-`sfrecord~`-finalize tail spread,
   already corrected by `trim_to_common_length`. Only the **common (minimum)
   length** discriminates; a per-surface check would flag all three captures.
2. **Nothing noticed because `BeatSampleMap` is designed to absorb exactly this.**
   It maps the declared span onto whatever sample count it is handed and
   *rescales* — its own docstring says the rescale exists so "a global tempo
   offset between the DB `tempo_map` and what the render actually played can't
   shift boundaries". That is a good property against tempo mismatch and an
   indistinguishable one against a capture-length defect. The map is not the bug
   and is not changed; the excess is measured before the rescale hides it.

**Requirement discovered mid-build (Chunk 02), recorded here rather than coded silently.**
The check compares real audio against a duration integrated from the song's
**declared** tempo map, and `_collect_tempo_map` already documents that the render
may not have honored it: the push layer materializes only the bar-1 tempo (the
non-bar-1-tempo gap, `TMP-7B3X` / `TMP-4J6Q` / `TMP-5K1R`), so a song declaring
variable tempo renders at one tempo today. Against such a song the declared
duration and the rendered audio disagree for a reason that is **not** a capture
defect, and a span check that fired there would be measuring-and-lying — the
failure this codebase names by that phrase.

So the check answers only where it can: **when the declared tempo agrees with
what the render actually played**, which is the bar-1 row and nothing else.
Otherwise it declines and names the push gap as the reason.

**That gate is about the render, not the score, and the distinction is load-
bearing.** A first attempt asked whether the *declared* tempo was constant across
the captured span — which accepts a song declaring 90 bpm at bar 1 and 124 from
beat 8, rendered from beat 16: declared-constant at 124, actually played at 90
throughout, because `plan_push_tempo_map` sets Live's one global tempo from the
bar-1 row and warns-and-skips the rest. That would have compared real audio
against a duration nobody performed and reported the push gap as a broken
capture, in the one lens the mix-review skill tells the reader never to hedge.
The Critic caught it; the predicate now asks for the bar-1 bpm and requires the
declared tempo to agree with it **from beat 0 through the span's end**, not merely
across the span. That is stricter than strictly necessary — a departure restored
before the window begins would integrate correctly and is declined anyway — and
deliberately so: the error it forgoes is a false decline, the one it refuses to
risk is a false alarm.

**The refusal does not retire itself.** An earlier draft of this plan claimed it
was "self-healing — it stops applying the moment variable-tempo rendering lands";
the Critic caught that the code does not do it. The predicate reads the DECLARED
tempo, not what the renderer can honour, so after variable-tempo rendering ships
every variable-tempo song still declines and still blames a gap that is gone.
That is the shape `learnings.md` already records as *newly enabling a capability
doesn't update the guards that predated it*, so the obligation is written where
whoever lands that capability will meet it — the docstring says the guard must be
deleted, and the tracking item carries it — rather than asserted as automatic
here.

**Open assumptions / unknowns:**

- [ASSUMPTION: the excess is a HEAD offset, not a TAIL overrun | MED impact |
  NOT resolved in this plan] The report measured first-sound beats per stem and
  found every one late by the same ~1.1 beats, which is a head offset. A length
  check alone cannot tell the two apart, so the finding claims only what it
  measures — *the audio does not span what the manifest declares* — and never
  "the capture started early". Distinguishing them needs the authored-onset
  cross-correlation in Scope-out.
- [ASSUMPTION: `ring_out_beats=8` is not causal | LOW impact | left open] The bad
  capture is the only ring-8 one seen. n=1, and the report's own alternative
  (a stale transport start position, the #471 distinction) is at least as likely.
  Nothing in this plan depends on which is true.

## Scope boundary — what this plan does NOT do

- **It does not correct the offset.** Trimming by a measured lag, or cue-jumping
  before the pre-roll seek, both live in `hallucinote_mcp/.../handlers/render.py`,
  which is fingerprint-bearing — changing it forces a re-vendor of the Remote
  Script. Detection is separable, ships without a handshake change, and is what
  stops a wrong number being believed. Correction is its own decision.
- **It does not diagnose the Live-side root cause.** Why `sfrecord~` armed early
  stays open on #491.
- **It does not change `BeatSampleMap`.** See Requirements Confidence #2.
- **It does not move `SCHEMA_VERSION`.** `Finding.kind` is a free-form string with
  no enumeration to extend, and the `alignment` block gains a key. Both are
  additive; a reader of an older report sees the key absent, which is the same
  thing it means today. Bumping the version would make every existing report
  un-diffable (`compare.ensure_comparable` refuses across versions) for no
  consumer's benefit — the same reasoning `MixReport`'s docstring already records
  for AUD-PORTPATH.

## Status

- [x] Chunk 01: one integrator, and a capture-span measurement built on it
- [x] Chunk 02: the finding, the report block, and the regression that reproduces #491

---

### Chunk 01: one integrator, and a capture-span measurement built on it

**Spec.**

`section.py` already integrates beats→seconds across a tempo map, inside
`BeatSampleMap.__init__`, using `_partial_seconds`. The span check needs the same
number. **Expose it once rather than computing it twice** — two integrators that
disagree about how long 515 beats is would produce a finding that contradicts the
section windows in the same report.

- Add `declared_span_seconds(start_beat, stop_beat, tempo_segments) -> float | None`
  to `section.py`, public. Returns `None` when there is no usable tempo evidence —
  no segments, or none with `bpm > 0`, or a non-positive span.
- **`None` is not "assume 120".** `BeatSampleMap._bpm_endpoints` falls back to
  `120.0` for a beat preceding every segment, with the comment "cancels in the
  rescale" — true for the map, false for an absolute duration. A span check that
  inherited that fallback would compare real audio against a fabricated 120-BPM
  duration and invent findings on every song not at 120. The new function must
  refuse instead, and a test pins the refusal.
- Refactor `BeatSampleMap.__init__` to obtain its `raw_total` from the shared
  helper. Behavior-preserving: existing `section.py` tests must pass unchanged.

`alignment.py` gains the measurement, because it already owns whether the captured
audio has the length it should and its `AlignmentReport` already reaches the report:

- `@dataclass(frozen=True) class CaptureSpan` with `declared_beats`,
  `declared_seconds`, `captured_seconds`, `excess_beats`, `tolerance_beats`,
  `within_tolerance`, and `to_json_dict()`.
- `measure_capture_span(capture, tempo_segments, *, tolerance_beats=DEFAULT) -> CaptureSpan | None`,
  measuring the **common** length (post-trim), per Requirements Confidence #1.
  `None` when `declared_span_seconds` refused.
- `DEFAULT_SPAN_TOLERANCE_BEATS = 0.25`, carrying its *why* inline: the measured
  healthy spread is under 0.05 beats and the defect is 1.06, so a quarter-beat
  sits an order of magnitude clear of both. Not a tuned value.

**Tests.** Both `None` paths (no segments, zero-bpm segments); a clean span; a
+1.07-beat span; a variable-tempo map where a naive constant-BPM computation would
give the wrong duration and the integrator gets it right; and the behavior-preserving
`BeatSampleMap` refactor.

**Done when.** `_integrate_span` is the only place a beat SPAN is integrated into
seconds — `BeatSampleMap` and `declared_span_seconds` both read it, and the only
other `_partial_seconds` caller is `beat_to_sample`'s interpolation WITHIN an
already-integrated interval, which is a different question. And
`measure_capture_span` reproduces the three measured numbers in the table above
from synthetic fixtures.

---

### Chunk 02: the finding, the report block, and the regression that reproduces #491

**Spec.**

- `analyze_mix` calls `measure_capture_span` after `trim_to_common_length` and
  before `BeatSampleMap`, and threads the result into `_derive_findings`.
- On `not within_tolerance`, emit
  `Finding(kind="capture_span_mismatch", severity="warning", subject="capture",
  metric="span_beats", observed=<captured>, expected=<declared>)` with a
  `db_reference` that states what is and is not known: the audio does not span
  what the manifest declares, so every per-section window and every beat this
  report cites is computed on a stretched map, and the report cannot say whether
  the excess is at the head or the tail.
- **Severity is `warning`, not `blocking`.** `blocking` in this report vocabulary
  is for a reading that cannot be produced; this one is produced and is wrong by a
  known amount, which the reader needs to *see* in order to distrust the rest.
  Suppressing the numbers would remove the evidence that makes the defect legible —
  the same argument `analyze_mix` already records for why render-integrity results
  sit beside the musical numbers rather than gating them.
- The `CaptureSpan` lands in the report's existing `alignment` block, so the
  numbers behind the finding are inspectable and a *passing* span is recorded too.
  A check that only speaks when it fails cannot be distinguished from one that
  never ran.
- When `measure_capture_span` returns `None`, append a `skipped_analyses` entry
  naming `capture_span` and saying no tempo map was supplied — this module's own
  stated convention ("an empty list IS silently absent unless something names it"),
  and the exact silence this work exists to end.

**Tests.** Finding emitted above tolerance and absent below it; the skip entry when
no tempo map; the `alignment` block populated on both the passing and failing paths;
and a **regression fixture carrying the real numbers from `20260908T233753Z`**
(515 declared beats, 249.71 s at 48 kHz, 124 BPM — a +1.06-beat excess) asserting the finding fires — the
capture itself lives in the private songs repo, so the fixture carries the
measurements, not the WAVs.

**Done when.** The reported capture's numbers produce a finding; the two healthy
captures' numbers do not; suite green with no path argument.

## Definition of done (both chunks)

- Suite green with **no path argument** (`testpaths` covers both suites).
- `ruff` and `mypy` clean.
- `/prawduct:critic` cumulative-final, findings dispositioned.
- #491 updated with what shipped and what stayed open.
