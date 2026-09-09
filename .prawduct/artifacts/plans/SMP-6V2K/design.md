<!-- Design — SMP-6V2K (sampling as compositional material). Tier 1 (Source of Truth).
     WHY and WHAT-shape. The buildable decomposition for wave 1 is build-plan.md
     beside this file; later waves are backlog items, drawn as plans when they start. -->
---
artifact: design
version: 1
scope: SMP-6V2K
branch: plan/smp-6v2k-sampling
depends_on:
  - artifact: architecture
  - artifact: data-model
  - artifact: authorship-model
    path: .prawduct/artifacts/authorship-model.md
  - artifact: discovery
    path: .prawduct/artifacts/plans/AUD-1M4V/archive/discovery.md
last_validated: 2026-09-09
lifecycle: active
---

# SMP-6V2K — Sampling as compositional material

> **`requirements.md` (2026-09-09) is authoritative on scope**, and it is wider than this
> file: elicitation after this was written added feature-driven derivation (the sample
> generates the score) and the spectral-operation family (carve / vocode against an
> addressable reference). What survives here unchanged and is still the reason to read it:
> the **capability audit**, the **three stale claims**, decisions **D1–D7**, and **wave 1**.
> The wave map below is superseded where it disagrees with the requirements.

**The song that asked for it.** Movie dialogue pulled into Live and arranged as a
conversation, with music built around it, and the samples pitch- or time-corrected
either as Live clip settings or as new audio Hallucinote makes and pushes up.

This is a **program**, not one plan: five waves, each shippable on its own, drawn as
its own build plan when it starts (`/prawduct:methodology planning` — "a plan that
will not ship in about three sessions is a program"). Wave 1's plan is
`build-plan.md` beside this file. The song itself is authored in the songs
workspace (`~/source/hallucinote-songs`), not here; this repo builds what the song
needs.

## Working backwards from the song

Seven things have to be true before that song can be made, in the order a session
would hit them:

1. **Acquire** — get the dialogue out of its source medium into the song's assets, with a
   record of what it is and where it came from.
2. **Hear it** — measure a sample the way we already measure a rendered stem: level,
   spectrum, onsets, and the two speech-specific readings that decide how music is
   written around it — its **pitch** (what key does this line imply) and its **rhythm**
   (where do the syllables and phrase boundaries fall).
3. **Conform** — pitch and time it to the song: warp mode, transpose, gain, trim.
4. **Place** — put it in Live, in a slot and in the arrangement, and get it back on pull.
5. **Play it** — assign it to a Simpler/Sampler so chops are sequenceable material the
   existing generator machinery can write with.
6. **Compose** — the conversation itself: turn-taking placement, and music that leaves
   room for it.
7. **Verify** — is the dialogue *intelligible* over the music. This is the one mix
   question the song lives or dies on, and it is the film-dialogue problem exactly.

## What already exists (audit, 2026-09-09)

Verified against the code on `develop` @ `f0d6ed3`, not from memory.

| Capability | State | Evidence |
|---|---|---|
| Audio **tracks** — create, name, route, monitor | ✓ shipped | `actions/track.py` `kind` enum `("midi","audio")`; `sync/push/tracks.py` passes `kind` through |
| Audio **clip DB model** — `kind`, `audio_file`, `audio_gain`, `pitch_coarse/fine`, `warping`, `warp_mode`, `start_marker`, `end_marker`, `reverse` | ✓ shipped (CLP-AUD1 + SMP-7K2D ch1–2) | `db/schema.sql` clips table; `db/mutations/clips.py` `create_audio_clip`, `_validate_audio_fields` |
| **Sampler sample-assignment DB model** — `devices.audio_file` | ✓ shipped (SMP-7K2D ch1) | `db/schema.sql` devices table; `capture.py:568` resolves it |
| **Portable path contract** — song-relative POSIX under `assets/`, one resolver | ✓ shipped | `paths.py` `resolve_audio_path` |
| **LOM mechanism for placement** — `ClipSlot.create_audio_clip(abs_path)`, `Track.create_audio_clip(path, beats)`, `TakeLane.create_audio_clip` | ✓ probe-CONFIRMED on Live 12.4.1 | `docs/research/audio-first-class/lom-probe-results.md` rows 1a–1c, 6 |
| **Audio-clip envelopes** — mixer/send/device automation on an audio *session* clip | ✓ probe-CONFIRMED end-to-end | same, row 3 |
| **Scripted audio recording / resampling** — routing → arm → `fire(record_length=)` | ✓ probe-CONFIRMED | same, rows 5, 5b, 5c |
| **Analysis maths** that a sample lens would reuse — bark bands, timbre (centroid/flatness/rolloff), onsets, transients, loudness/true-peak, masking, integrity (clipping/DC/dropouts) | ✓ shipped, array-level | `audio/bark.py`, `timbre.py`, `onsets.py`, `transients.py`, `loudness.py`, `masking.py`, `integrity.py` |
| **DSP libraries already in the dependency set** — numpy, scipy, soundfile, librosa, pyloudnorm | ✓ present | `pyproject.toml` dependencies |

**The foundation is further along than the shipped product suggests.** The DB models an
audio clip completely, the paths are portable, the LOM calls were probed live fifteen
months ago and confirmed, and every analysis primitive a sample lens needs already runs
on numpy arrays. What is missing is almost entirely *wiring*, not mechanism.

## What is missing

| Gap | Where it bites | Existing item |
|---|---|---|
| MCP has **no audio-clip creation** — `ableton_clip(action='create')`'s `audio_path` is a reserved no-op that returns `audio_path_deferred` and loads nothing | nothing can put a sample in Live | #284 (CLP-AUD2) |
| **Push refuses audio clips** — `sync/push/clips.py:51` and `sync/push/arrangement.py:236` warn-and-skip every `kind='audio'` row | an authored audio clip never materializes | #284 |
| **Pull refuses audio clips** — `sync/pull/clips.py:228,373` warn-and-skip; a clip dragged in by hand never becomes source | the round-trip that makes sketching work is closed for audio | #284 |
| **Envelopes on audio tracks are refused** — `sync/push/envelopes.py` `refused_audio` route | no volume ride or send throw under a dialogue line | #268 (ENV-8H1T) |
| **Sampler sample-assignment push is unbuilt** — DB model only; the Live probe that gates it never ran | dialogue can't become playable/chopped material | #330 (SMP-7K2D ch0/3/4) |
| **Reverse push is unbuilt, and the contract is contradicted** (below) | — | #237 (AUD-7R3M) |
| **No analysis front door for an arbitrary file** — `audio/io.py` reads only a render manifest, and refuses anything that isn't float32 stereo at the capture's rate | we can measure a stem we rendered, and nothing a user hands us | *new* |
| **No speech/pitch/rhythm reading** — no F0 contour, no syllable-rate or phrase-boundary detection | we can't say what key or tempo a line implies, which is what "build music around it" needs | *new* |
| **No offline transform at all** — no pitch shift, time stretch, chop, trim, fade, normalize | "pitch or time correction in Hallucinote with new samples pushed up" has no implementation | *new* |
| **No acquisition** — nothing extracts audio from a media file, and no provenance record exists for a sample | step 1 of the song | *new* |
| **No asset-store ergonomics** — `authorship-model.md` "Open problems" §2 names this open and says *file it when a song needs it*. A song needs it | where sources and derived audio live, and what git does with them | *new* |
| **No dialogue-intelligibility lens** — masking exists but is framed part-vs-part, not speech-vs-bed | the song's central mix question | *new* |

## Three stale claims found in the audit

Recorded here because "no pre-existing exception" — each is scheduled in wave 1's
records chunk rather than fixed silently in a planning commit.

1. **`authorship-model.md` "Open problems" §2** says *"Live won't let us create session
   audio clips (`gaps.md`, `NotImplementedError`)"*. Refuted by probe row 1a
   (2026-06-10). The open problem it names — asset-store ergonomics — is still real; the
   stated reason for it is not.
2. **`db/schema.sql`'s `clips.reverse` comment** says reverse is *"materialized at push
   as Live's clip reverse (a playback parameter)"*. Probe row 4 of
   `lom-audio-clip-surface.md` says the opposite: **there is no `reversed` property on a
   Live clip — confirmed absent.** A DB column whose stated materialization does not
   exist is a contract that will fail the first time someone sets it. SMP-7K2D's chunk 0
   existed to settle this and never ran (wave 1 chunk 01 runs it).
3. **`capability-truth.md`** has no row for audio material at all, so the honest answer
   to *"can you use samples?"* today is unwritten. It gains a row when wave 1 ships, and
   again at wave 3 and wave 5 — that table is the anti-confabulation spine and it must
   not lag the code.

## Design decisions

**D1 — The asset store is `assets/sources/` + `assets/derived/`, and the manifest is
the third leg.** `authorship-model.md` names three legs: generative code, materialized
state, and *recorded assets* whose reproducibility means **retaining** them. A sample is
that third leg. Sources are immutable and never edited in place; every derived file is
produced by a recorded recipe. A `assets/manifest.json` (or per-file sidecar — settled in
wave 3) carries, per source: origin (title, media file, in/out timecode), duration, sample
rate, checksum, and a free-text note. Provenance is not bookkeeping here — for movie
material it is the only record of what the sample actually is.

**D2 — Derived audio must be regenerable from source + recipe, and the recipe lives in
`build.py`.** This is the `data-model.md` Direction norm applied to audio: source is
what is in git, and everything downstream is rebuildable. A pitch-shifted, trimmed,
chopped dialogue line that exists only as a WAV nobody can regenerate is exactly the
"binary blob you must back up rather than version" the norm rejects. The derived file is
*cached* in the repo (regenerating it must not be required to open the song, and DSP is
not bit-reproducible across library versions), but the recipe is the authored thing and
the WHY goes in `decisions/` per the rationale-is-authorship norm.
`[DECISION: derived audio is a cached artifact of an authored recipe, not a source |
engages the data-model Direction norm's why — a song must be rebuildable and diffable
from what is in git, and a recipe diffs while a WAV does not | user can override]`

**D3 — Conform in Live first; commit a derived asset when the ear demands it.** Live's
warp (Complex Pro for speech) plus `pitch_coarse/fine` and clip gain are non-destructive,
already modeled in the DB, and cost one push. An offline transform is higher quality,
costs a file, and is the right answer for formant-sensitive work and for chopping. The
doctrine is *reach for the clip settings, commit an asset when you can hear why* — and
the producer-practice guardrail from AUD-1M4V R1.4 still holds: cut-and-slide before
time-stretch; stretch smears formants.

**D4 — DSP library: start with what is already installed, gate a new dependency on a
listening test.** librosa (present) gives F0 (`pyin`), onsets, HPSS, phase-vocoder
stretch and resampling-based pitch shift. Its stretch is mediocre on speech — formants
smear, which for movie dialogue means the actor stops sounding like themselves. The
alternative is Rubber Band (via `pyrubberband` + a CLI binary, i.e. a non-Python
dependency the plugin env cannot vendor). Wave 3 builds behind one narrow transform
interface with librosa as the default, and only adds Rubber Band if the A/B is audible.
`[ASSUMPTION: librosa-first is acceptable for wave 3's first cut | MED impact | user can
override — say so and wave 3 prices in the binary dependency up front]`

**D5 — The entry point is an already-cut clip the user drops in; Hallucinote does not
extract from media and does not fetch from the internet.** *(User ruling, 2026-09-09 — the
earlier assumption was ffmpeg extraction from a local media file with a timespan.)* What
"acquire" reduces to is therefore: **normalize** (any sample rate, any channel count, WAV
or MP3 → the analysis-ready form, and a canonical WAV under `assets/sources/` if the drop
was lossy) and **record provenance** — what the line is, what it is from, and a checksum.
The `ffmpeg` decode path stays (MP3 in, and `soundfile` alone will not read it), but the
in/out-timecode cutter does not get built. Note plainly, once, in the docs this touches:
movie dialogue is somebody's copyright — personal and creative use is one thing,
distributing a released track built on it is another, and clearance is the user's call,
not the tool's.

**D6 — Reverse goes through a derived asset or the sampler, never a clip property.**
Follows from stale claim 2 once the probe confirms it. This changes `clips.reverse`'s
contract from "push sets a Live property" to "push selects a reversed derived asset (wave
3) or sets Simpler's Reverse parameter (wave 4)" — and the schema comment has to say so.

**D7 — Sample analysis is a second front door, not a widening of the capture loader.**
`audio/io.py` refuses anything that isn't the analyzer's float32 stereo because the mix
maths depends on it, and that refusal is correct — do not loosen it. A sample lens gets
its own loader that normalizes *into* the same array shape the measurement modules
already take, so every existing lens is reused unchanged.

## The waves

Each wave is independently shippable and leaves the product honest — `capability-truth.md`
is updated by the wave that changes what is true.

### Wave 1 — Place and conform *(the spine; plan drawn: `build-plan.md`)*
The MCP handler, push materialization, pull ingest, and the audio-track envelope unblock.
**Exit:** a WAV in `assets/` authored in `build.py` lands in a Live slot and in the
arrangement, warped and transposed as authored; a clip dragged in by hand in Live comes
back into the DB on pull; a volume ride under it pushes. Existing items: **#284**, **#268**.
Live-gated (probe + operator verification). ~2–3 sessions.

### Wave 2 — Hear the sample
An arbitrary-file loader (D7) and a **sample lens**: level and true peak, spectrum via the
existing bark/timbre modules, onsets and segment boundaries, integrity, plus the two
readings the song turns on — **F0 contour → implied pitch centre and key relationship**,
and **syllable rate / phrase boundaries → where the line wants to sit against a bar**. A
skill surfaces it so the agent can say *"this line sits around D, the phrase is 2.4
seconds, three beats at 92."* **Exit:** hand it a movie line, get a musical reading you can
compose against. New backlog item. Not Live-gated. ~1–2 sessions.

### Wave 3 — Transform, as reproducible derived assets
Asset store + manifest (D1) — which under D5 is also the whole of "acquire": normalize a
dropped clip and record its provenance. Then the recipe model in `build.py` (D2), and the transform set:
trim, fade, normalize, reverse, pitch shift, time-stretch-to-N-bars, chop-at-onsets. This
is "pitch or time correction in Hallucinote with new samples pushed up to Live" — the
derived file is written to `assets/derived/` and referenced by an audio clip wave 1
already knows how to place. **Exit:** a recorded recipe regenerates a derived WAV; the song
opens on another machine and rebuilds. New backlog item; closes `authorship-model.md`
open problem §2 and #237. ~2–3 sessions.

### Wave 4 — Play it (sampler)
SMP-7K2D's unrun probe (chunk 0) and the push it gates: assign a sample to
Simpler/Sampler, map chops across keys, expose Reverse / S Start / S Length. Dialogue
becomes sequenceable material the existing generators and note machinery can write with —
and the learnings entry stands: a sampler part's note mapping is only verifiable by
rendering. **Exit:** a chopped line plays from a MIDI clip. Existing item **#330**.
Live-gated. ~2 sessions.

### Wave 5 — The conversation, and whether you can hear it
Two halves. *Composition:* turn-taking as arrangement material — call, response, overlap,
interruption, and the gap that does the work — built on the existing `Section`/`vary`
primitives, ruler-not-stamp (the helper places; the line order is the user's). *Verification:*
a **dialogue-intelligibility lens** — the speech band measured against the music bed
per turn, which is `audio/masking.py` re-framed for the film problem, with the existing
sidechain/duck machinery as the fix it recommends. **Exit:** the mix report answers "can
you hear the line" per turn. New backlog items. ~2–3 sessions.

**Order.** 1 → 2 → 3 is the critical path; 4 and 5 can swap or run after. Waves 1 and 2
together are the minimum that makes the song *startable* — place a line, hear what it is,
write to it — with conforming done in Live until wave 3 lands.

## Risks

- **Live-gated chunks stall on the operator.** Waves 1 and 4 need a running Live and a
  human at it; the attended-verification queue already has a drain problem (#306). Mitigation:
  wave 1 chunk 01 batches every probe question into one Live session, including wave 4's.
- **File-path immutability forces delete-and-recreate.** `Clip.file_path` is read-only
  (probe row 4), so changing which file a clip plays is a destructive reconcile — and
  destructive reconciles against arrangement clips are where this project has been bitten
  before (ARR-PROJ). Wave 1 designs the reconcile explicitly rather than discovering it.
- **Binary weight in a song repo.** Movie sources are large and git is bad at them. Wave 3
  decides the policy (size ceiling, LFS or sources-outside-the-repo-with-checksum) — and
  it must be decided *before* the song starts, because a poisoned history is expensive to
  clean.
- **Speech DSP quality** (D4) — the honest failure mode is a stretched line that no longer
  sounds like the actor. The A/B is the gate, not the library's reputation.

## Advisory — what I would do differently

- **Do not build wave 3 before the song starts.** The strong instinct here is to build the
  transform kit first because it is the most interesting engineering. It is also the part
  most likely to be built to the wrong spec: which transforms matter is a question the
  first ten minutes with real dialogue in a real set answers for free. Ship waves 1 and 2,
  start the song, and let it name the transforms.
- **Wave 5's composition half may need no code.** Turn-taking is placement, and placement
  is something the arrangement model already does. Resist a `Conversation` class until the
  song has been hand-authored once and the repetition is visible — "tools are conveniences,
  never limits" cuts both ways.
- **The intelligibility lens is the highest-value new analysis in this program**, and it is
  in the last wave. If any wave gets pulled forward, make it that one: it is the only
  measurement that tells you whether the song works, and it is mostly a re-framing of
  `masking.py` rather than new maths.
- **What I would cut:** take lanes and comping (probe row 6) are in AUD-1M4V's scope and
  not in this song's path. Leave them.
