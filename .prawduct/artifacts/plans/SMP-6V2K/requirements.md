<!-- Requirements — SMP-6V2K. Tier 1 (Source of Truth). THE authoritative statement of
     what this capability must do. `design.md` beside it carries the capability audit and
     the mechanism decisions; where the two disagree about scope, this file wins. -->
---
artifact: requirements
version: 1
scope: SMP-6V2K
branch: plan/smp-6v2k-sampling
stage: requirements
depends_on:
  - artifact: design
    path: .prawduct/artifacts/plans/SMP-6V2K/design.md
  - artifact: architecture
  - artifact: data-model
  - artifact: authorship-model
    path: .prawduct/artifacts/authorship-model.md
  - artifact: arrangement-model
    path: .prawduct/artifacts/arrangement-model.md
  - artifact: discovery
    path: .prawduct/artifacts/plans/AUD-1M4V/archive/discovery.md
last_validated: 2026-09-09
lifecycle: active
---

# SMP-6V2K — Audio as a source the music is derived from

**Requirements.** Elicited in conversation 2026-09-09; the reference song is a
Skinny Puppy *Rivers*-shaped piece — roughly thirty film-dialogue samples across one
song, three sources, used continuously rather than as punctuation, exploring one theme.

The song is the *occasion*, not the specification. Per owner ruling L2 below, these are
requirements for a **capability**, sized to what the capability coherently is, not to what
one song will exercise.

## Feature-discovery — the three questions

**1. Problem.** Today a sample can be authored in the DB and reaches Live through nothing:
push refuses it, pull refuses it, and there is no way to measure a file we did not render
ourselves. Beyond that plumbing gap sits the real one — **the sample can only ever sit
next to the music.** Nothing lets the music be *derived from* the sample: no feature
extraction, no way for a spoken line's pitch to become a synth line, no way for the
score's own notes to carve space out of a recording. Sample-and-music layering is what
every DAW already does; it is not what this architecture is for.

**2. Success — the verifiable signal.** A sample is song material a generator can compose
*from*: its measurable features (pitch, formants, onsets, energy) reach the authoring layer
as beat-domain streams; a generator consumes one and emits score; and a spectral operation
can add or remove content in the sample using **the score itself** as the reference —
exactly, because the DB knows which pitches sound when, which no plugin can know. All of it
reproducible from what is in git, and all of it audible in Live.

**3. Out of scope** (each with its home): recording takes and comping (#278, AUD-1M4V's
R1); extraction of audio from a movie file with in/out timecodes (owner ruling L1 — clips
arrive already cut); warp-marker-level authoring (AUD-1M4V lock 3); realtime/live
processing of any of this inside Live (see R6.5 and the DEV-9C4L note); sung-vocal
synthesis.

## Owner rulings and locks (2026-09-09)

- **L1 — The entry point is an already-cut clip.** The user drops WAV/MP3 into the song;
  Hallucinote normalizes and records provenance. No media extraction, no fetching.
- **L2 — Do not overspecify tool capability to one song.** *"These are all tools."* A
  requirement earns its place by being what the capability coherently is, not by appearing
  in the reference song. The counterpart standing norm: the toolkit reduces work, it never
  caps what is authorable.
- **L3 — The spectral reference is any node, uniformly.** Single instrument, submix,
  return, main mix, or any combination — one addressing scheme, not a list of supported
  cases. (This is the project's existing generalization stance: uniform mechanism over
  registry over whitelist.)
- **L4 — Deeper than layering.** The sample is the source the music derives from, not a
  layer over or under it.
- **L5 — Not everything lands at once.** The three worked gestures (R4) are illustrations
  of a shape, not a delivery list; the shape is what gets built.

## The governing idea

Two abstractions carry every requirement below.

**A feature stream is a generator input.** Generators in this project are already pure
functions from musical parameters to tagged note arrays. An F0 contour extracted from a
spoken line is another parameter. That makes "a synth line that follows the voice" a
*generator*, not a subsystem — and it means the sample's influence on the score is
authored, diffable, arrangeable and overridable like every other musical decision.

**A spectral field is addressable, and comes from two places.** Any operation on a
sample's spectrum needs a reference field: a time-frequency magnitude surface saying what
is present, where. It can be **symbolic** (read the score's notes, expand to harmonics —
exact in pitch, free, instant, timbre-blind) or **measured** (the STFT of a captured
surface — full truth including device colour, saturation and reverb tails, costs a render).
The same operations consume either. This is the *only* structural difference between the
two, and it is a discriminator on one mechanism, not two features.

## Requirements

Each carries its mechanism and the evidence for it. `CONFIRMED` means probed against a
running Live and recorded in `docs/research/audio-first-class/lom-probe-results.md`.

### R1 — Material: a sample is first-class song material

- **R1.1 — Place and conform.** An authored audio clip materializes into Live in the
  session and the arrangement, with its warp mode, transpose, gain and markers as authored.
  *Mechanism:* `ClipSlot.create_audio_clip` / `Track.create_audio_clip` — CONFIRMED (probe
  rows 1a–1c). DB model shipped (CLP-AUD1). → **#284**
- **R1.2 — Round-trip.** A clip placed by hand in Live comes back into the song's source on
  pull, in the portable path form, with its conform settings. → **#284**
- **R1.3 — Sampler-hosted playback.** A sample assigned to a Simpler/Sampler, so notes drive
  its pitch and timing. This is what makes a treatment *score* rather than a rendered file,
  and R4 depends on it. *Mechanism:* DB model shipped; the LOM assignment path is unprobed.
  → **#330**
- **R1.4 — Automation on audio hosts.** Mixer, send and device envelopes on an audio-track
  session clip. *Mechanism:* CONFIRMED end-to-end (probe row 3); blocked only by R1.1.
  → **#268**
- **R1.5 — Reverse.** As a playback parameter where one exists, otherwise as a derived
  asset. The current schema comment asserts a Live clip property the LOM research says is
  absent; the contradiction is settled by probe before anything depends on it. → **#237**
- **R1.6 — Asset store, normalization and provenance.** Sources land under
  `assets/sources/` immutable, normalized to a canonical decodable form (MP3 in — which
  `soundfile` alone cannot read); each carries origin, duration, rate, checksum and a note
  saying what the line *is*. Provenance is not bookkeeping for film material; it is the only
  record of what the sample is.
- **R1.7 — Derived audio is regenerable.** Every derived file is the output of a recorded
  recipe, and the recipe is the authored thing. The file is cached in the repo (DSP is not
  bit-reproducible across library versions and opening a song must not require a re-render),
  but a song that only has the WAV has lost its source. *Governed by:* `data-model.md`
  Direction — source is what is in git; the DB and everything downstream is rebuildable.

### R2 — Features: what can be known about a sample

- **R2.1 — Ingest anything.** Any sample rate, channel count and common format, normalized
  into the array shape the existing measurement modules already take. This is a **second
  front door**, not a loosening of the render loader — that loader's refusal of anything but
  the analyzer's float32 stereo is correct and stays.
- **R2.2 — Feature streams, in the beat domain.** At minimum: **F0** contour with
  voiced/unvoiced confidence, **formant** tracks, **onsets** and segment boundaries,
  **energy** envelope, and the spectral descriptors already implemented (centroid,
  flatness, rolloff, bark-band energies). Computed in seconds against the file, and mapped
  to **beats** at consumption through the clip's placement and the song's tempo map — so a
  generator sees musical time, and a re-tempo does not invalidate the extraction.
- **R2.3 — A feature stream is inspectable before it drives anything.** The user can see
  where a detector *would* fire, against bars, before hearing a note of it. The detectors in
  R4.2 have musical thresholds, not technical ones, and tuning them blind is the failure
  mode.
- **R2.4 — A clean source from a dirty one.** Film dialogue arrives with score, foley and
  room underneath it, and every feature in R2.2 degrades on that mix. Separation is required
  both to *measure* the voice and to *use* it as material. → **#266**
- **R2.5 — A measured spectral field from any captured surface.** Per-track stems,
  per-return and master are already produced by every render, float32, time-aligned, with a
  loader. That capture set **is** the measured-field library; no new acquisition is needed.
- **R2.6 — A symbolic spectral field from the score.** The sounding pitches at any beat,
  expanded to a harmonic series, from the DB. Exact and instant, and available before
  anything has been rendered.

### R3 — Spectral operations: carve, vocode, and what sits between

- **R3.1 — One field, one mask, a polarity.** A spectral operation is: take a reference
  field, build a time-varying mask from it, apply it to the target sample's magnitude
  spectrum, resynthesize against the original phase. **Carve** attenuates where the
  reference has energy; **vocode** keeps only where it does. The same code, one parameter
  apart. No separate vocoder feature.
- **R3.2 — The reference is addressed like any other node.** A single instrument track, a
  submaster bus, a return, the main mix, or any set of them — resolved through the project's
  existing node addressing (`NodeAddr`, shipped), not an enumerated list of supported
  sources. Submixes already exist as first-class here (PRE-MAIN routing busses, because Live
  groups are not LOM-creatable).
- **R3.3 — The reference may change over time.** *"A spoken line where only frequencies
  from an instrument pass through, but the instrument changes."* The reference is
  **scheduled** — which makes it score: authored per section or per bar, diffable, and
  varied by the arrangement machinery that already exists.
- **R3.4 — The parameters are musical.** Harmonic depth (how many partials of each
  reference pitch are carved), notch width in **cents** scaled by perceptual band width
  (`bark.py`), attenuation depth (bounded — never to silence), and temporal smoothing.
  Each automatable, so the carve itself can be an arrangement gesture that opens and closes.
- **R3.5 — "Main mix" means the mix minus the target.** Carving a sample against a mix that
  contains it hollows it against its own energy. Since every stem is captured, the
  everything-else field is computed by summing the others — machinery that already exists
  for stem-sum-versus-master reconciliation.
- **R3.6 — Sample-accurate alignment between reference and target.** A one-beat drift
  carves the wrong moment. This inherits the capture-alignment guarantees rather than
  restating them, and a field that cannot be aligned must refuse rather than approximate.
- **R3.7 — A score-dependent derived asset knows what it was derived against.** This is a
  new shape: R1.7's recipe plus *the arrangement as it stood*. Change the bassline and the
  carved sample is silently stale — still carving against a note nobody plays. The derived
  file records a fingerprint of the notes and surfaces (or the render) it was made against,
  and says so when they move. *Mechanism:* the project's existing staleness/identity
  machinery, not a new one.
- **R3.8 — Low-frequency precision is bounded, and says so.** A semitone at 55 Hz is ~3 Hz
  wide; at a 2048-sample window the bins are ~21 Hz apart. Precise bass carving needs long
  windows, which blur time. Multi-resolution analysis is the answer where it is worth the
  cost; where it is not, the operation reports the resolution it actually achieved rather
  than implying a precision it does not have.

### R4 — Derivation: the sample generates the score

- **R4.1 — A line's pitch becomes a part's pitch.** An F0 contour becomes notes plus a
  continuous bend, following the voice as closely as the instrument allows. *Mechanism:*
  clip envelopes exist; whether they reach pitch bend, CC and smooth curves is unprobed and
  gates this. → **#281**
- **R4.2 — Feature events trigger musical gestures.** *Worked example:* when the tracked
  pitch crosses a scale tone, launch a cascade of short grains of that moment, delayed onto
  the grid, each transposed up the scale. The detector needs musical gates — voiced-only, an
  energy floor, dwell time, minimum spacing — or it fires continuously on real speech.
  Calibrated by ear (R2.3, and → **#279**).
- **R4.3 — Grain-scatter with time preserved.** Re-pitch on a fine grid (64th notes) while
  duration holds, so the line stays intelligible but moves in pitch. **Formant preservation
  is not optional here** — it is the entire difference between the intended effect and a
  chipmunk. See R6.2.
- **R4.4 — Score-first; frozen audio when it must be.** Each gesture lands either as
  *score* (a sampler plus notes/envelopes — editable, arrangeable, diffable, variable per
  section) or as *derived audio* (full DSP freedom, frozen). Score is the default because it
  keeps the gesture inside the authoring loop; derived audio is chosen when the sound
  requires it. Which one a gesture used is recorded, because it is a real authorial
  decision.
- **R4.5 — The circular dependency is declared, not discovered.** When a part is derived
  from a sample (R4.1) *and* the sample is carved against that part (R3), the sample loses
  its own melody to the instrument that took it. Pipeline order is declared per song. This is
  as likely to be the best gesture in the piece as it is to be a bug, and it must be the
  author's choice either way.
- **R4.6 — Derivation never makes the musical decision.** A follower proposes a line; the
  key, the register and whether the sample or the music leads at a given moment stay
  authored. *Governed by:* the standing ruler-not-stamp norm — helpers may remove
  bookkeeping, never the musical judgment.

### R5 — Composition and verification

- **R5.1 — Continuous samples across sections.** A sample spanning several sections must
  still carry per-section automation, which is the existing per-section envelope partition
  problem. → **#267**
- **R5.2 — Turn-taking as arrangement material.** Call, response, overlap, interruption, and
  the gap that does the work — expressed on the existing `Section`/`vary` primitives. No new
  abstraction until a song has been hand-authored once and the repetition is visible.
- **R5.3 — Is the line audible?** A dialogue-intelligibility lens: the speech band measured
  against the music bed, per turn. This is the film mix problem, and it is the existing
  masking analyzer re-framed — the same math the carve in R3 runs backwards. It is also the
  verification for R3: a carve that ate the voice shows up here.
- **R5.4 — The WHY ships.** A treatment is a substantive creative decision — which reference
  carved, why that gesture, what the migration of pitch from voice to instrument means for
  the song. It lands in the song's `decisions/`, per the standing rationale-is-authorship
  norm, as part of finishing the move.

### R6 — Non-functional

- **R6.1 — Iterate symbolic, commit measured.** The symbolic field is instant, so depth and
  harmonic count are tuned by ear in seconds; the measured pass costs a render and is what
  gets baked. The tooling must make both routes available on the same operation, and must
  never silently substitute one for the other.
- **R6.2 — Formant preservation is a quality floor, and it is a dependency decision.**
  librosa's phase vocoder will not carry R4.3. Rubber Band would, at the cost of a non-Python
  binary the plugin environment cannot vendor. The decision is made against an audible A/B on
  real dialogue, not a library's reputation, and it is made **before** R4.3 is built rather
  than discovered inside it.
- **R6.3 — Reproducible on another machine.** A cloned song rebuilds: portable paths, a
  recorded recipe, a checked-in derived cache, and a stated tolerance for DSP that is not
  bit-identical across versions.
- **R6.4 — Nothing here regresses what exists.** The MIDI authoring path, the stdlib-only
  MCP server at import time, mutator-and-event discipline for every write, and the render
  loader's format refusal all hold unchanged.
- **R6.5 — Offline, not realtime.** Every operation here runs Mac-side and produces either
  score or a file. A Max for Live device could do a version of this in realtime, but it
  would not know the score, which is the whole advantage — so the realtime route is
  *declined*, not deferred. → **#282** records the general escape hatch; this capability
  deliberately does not use it.

## Mechanism status — what is proven and what is not

| Requirement | Mechanism | Status |
|---|---|---|
| R1.1, R1.2 | `create_audio_clip` on ClipSlot / Track | **CONFIRMED** (probe 1a–1c) |
| R1.4 | `create_automation_envelope` on an audio session clip | **CONFIRMED** (probe 3) |
| R1.3 | LOM sample assignment to Simpler/Sampler | **UNPROBED** — gates R4 |
| R1.5 | clip reverse as a Live property | **CONTRADICTED** — research says absent, schema says present |
| R2.5 | render capture set (stems + returns + master) | shipped |
| R2.6 | DB note reads | shipped |
| R3.2 | `NodeAddr` addressing | shipped |
| R3.5 | stem-sum reconciliation | shipped |
| R2.2, R3.1, R3.4 | numpy/scipy/librosa STFT + bark bands | libraries present, no implementation |
| R4.1 | clip pitch-bend / CC / smooth-curve envelopes | **UNPROBED** — gates R4.1 |
| R2.4 | source separation | not built |
| R4.3 | formant-preserving pitch shift | **library decision open** (R6.2) |

## Backlog items this capability consumes

**Solved by this work** — these close when their requirement ships:

| Item | Id | Requirement |
|---|---|---|
| [#284](https://github.com/brookstalley/hallucinote/issues/284) — clip: session-view audio clip creation and push/pull surface | CLP-AUD2 | R1.1, R1.2 |
| [#268](https://github.com/brookstalley/hallucinote/issues/268) — envelope: mixer envelopes on audio tracks via audio-clip model | ENV-8H1T | R1.4 |
| [#330](https://github.com/brookstalley/hallucinote/issues/330) — clip: author a Simpler or Sampler with an assigned sample | SMP-7K2D | R1.3 |
| [#237](https://github.com/brookstalley/hallucinote/issues/237) — clip: reverse as a playback parameter for audio and samples | AUD-7R3M | R1.5 |
| [#281](https://github.com/brookstalley/hallucinote/issues/281) — envelope: probe clip pitch-bend, CC and smooth curve support | ENV-6P3R | R4.1 (gating spike) |
| [#266](https://github.com/brookstalley/hallucinote/issues/266) — audio-analysis: source separation fallback for stemless input | AUD-6T2K | R2.4 |

**Consumed in part** — the requirement overlaps but does not close the item:

| Item | Id | Relationship |
|---|---|---|
| [#262](https://github.com/brookstalley/hallucinote/issues/262) — audio-analysis: realtime feature set and streaming dashboard | AUD-7W1N | R2.2 builds the *feature set*; the realtime/streaming half stays open and is explicitly declined here (R6.5) |
| [#253](https://github.com/brookstalley/hallucinote/issues/253) — masking: level-reconstruction refinements from C3 | MSK-8R3D | R3's carve and the masking analyzer are the same math in opposite directions; refinements to one should land in both |
| [#267](https://github.com/brookstalley/hallucinote/issues/267) — envelope: auto-partition envelopes across per-section clips | ENV-3M7K | R5.1 — a continuous sample across sections is exactly this case |
| [#279](https://github.com/brookstalley/hallucinote/issues/279) — quality: listening day to ear-validate shipped analyzers | QLT-3D8R | R2.3 / R4.2 — the detectors are calibrated by ear or not at all |

**Adjacent — informs, is not solved:**

| Item | Id | Note |
|---|---|---|
| [#278](https://github.com/brookstalley/hallucinote/issues/278) — clip: in-Live vocal and audio takes with comping | AUD-9R3V | Same family (AUD-1M4V), out of scope here; R1.1's placement unblocks it |
| [#240](https://github.com/brookstalley/hallucinote/issues/240) — audio-analysis: make capture stop transport-bracketed | AUD-4S8T | R3.6 depends on capture alignment |
| [#282](https://github.com/brookstalley/hallucinote/issues/282) — device: model Max for Live as a first-class escape hatch | DEV-9C4L | The realtime alternative, declined with reasons (R6.5) |
| [#234](https://github.com/brookstalley/hallucinote/issues/234) — instruments: audition a candidate instrument by ear | SNG-CEG4 | Auditioning a *treated sample* is the same interaction |

## Open questions

Three were asked in the eliciting conversation and are not yet answered. None blocks
writing a build plan for R1; each changes R2 and R4.

1. **Which films, and how clean are the source clips?** Isolated dialogue and a 5.1
   downmix with score underneath demand very different things of R2.2 and decide whether
   R2.4 (separation) is on the critical path or an optimization.
2. **Uniform treatment or per-sample treatments?** One detector applied to thirty samples
   is a different tool from thirty hand-designed gestures — it changes whether R4's surface
   is a small set of parameterized generators or an authoring vocabulary.
3. **Does the music ever lead?** If pitch derivation runs everywhere, the song's harmony is
   whatever the actors happened to say. Where the sample proposes and where the key
   constrains is a compositional decision (R4.6) that wants an answer before R4 is designed.

**Open assumptions:**

- `[ASSUMPTION: the reference song's ~30 samples are placed from code, not by ear | HIGH
  impact | user can veto]` A 64th-note cascade cannot be hand-placed, and thirty continuous
  samples cannot be moved a bar by hand. This is what puts R1.1 first.
- `[ASSUMPTION: symbolic carving is useful on its own, not merely a draft mode for measured
  | MED impact]` The score-derived field is exact in pitch and blind to timbre; whether that
  alone sounds like the intended effect is unknown until it is heard.
- `[ASSUMPTION: separation quality on film dialogue is adequate for feature extraction |
  MED impact]` Untested here. If it is not, R4.1's follower degrades on exactly the material
  the song is made of.
