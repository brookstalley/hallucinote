# Feature request — author a sample-instrument (Simpler/Sampler) with an assigned sample, from build.py/DB (driver: swell's buried-"we" centerpiece) (2026-06-12)

Context: hallucinote-songs `swell`. Engine 0.9.0, hallucinote-mcp 0.1.0, Live 12.x
Suite. Design: `songs/swell/decisions/17-buried-we-centerpiece.md`. **Supersedes
the audio-clip-push framing** — a live probe (below) found a lighter path.

## The high-leverage finding (probed in a scratch Live set, 2026-06-12)
Loaded Simpler and Sampler on scratch tracks and dumped `get_parameters
detail=full`:

- **Simpler exposes automatable windowing**: `S Start` (0.0–1.0) and `S Length`
  (0.0–1.0) are continuous **DeviceParameters**. Empirically confirmed settable:
  `set_parameter S Start=0.5` → `"50.0 %"`. These are exactly what a
  `device_parameter` envelope targets — so **per-phrase windowing is automatable
  today**. (Simpler has **no** Reverse parameter.)
- **Sampler exposes `Reverse`** as an automatable enum DeviceParameter (Off/On) —
  so **live reverse is automatable** — but Sampler has **no** `S Start`/`S Length`
  window params (only `Time` stretch + the non-automatable zone editor).
- Both devices are present in the target Live install.

**Consequence:** swell's centerpiece (a windowed sample reveal, widening with
`breath`, with a fold) is buildable on the **existing push surface** — MIDI notes
that trigger the instrument + `device_parameter` envelopes (`S Start`/`S Length`,
or `Reverse`) + `mixer_volume` envelopes (the aura). **No CLP-AUD2 / audio-clip
push is required.**

## The one missing primitive (the ask)
There is **no way to author a sample-instrument with an assigned sample file from
`build.py`/the DB** (verified: no `simpler`/`sampler`/`load_sample`/`set_sample`
authoring path in `src/` or `hallucinote_mcp/`; instruments can be *loaded* at
MCP runtime but the sample assignment isn't part of the DB source-of-truth, so it
doesn't survive a rebuild/push).

Requested: a **sample-instrument part type** — a track whose instrument is a
Simpler (or Sampler) with an **assigned `audio_file`** (reuse the existing
clip-side `audio_file` resolution + `assets/` convention in `paths.py`). On push:
load the device, point it at the resolved sample, materialize it like any other
instrument. Then the existing `device_parameter` + `mixer_volume` envelope push
drives the rest.

## Recommended architecture for swell (so the request is concrete)
- **Forward Simpler** (the sample) — `S Start`/`S Length` envelopes per phrase =
  the center-pinned window that widens with `breath`.
- **Reverse half of the fold** — either (a) a **second Simpler with a
  pre-rendered reversed asset** (`…-rev.wav`), windowed the same way (keeps
  automatable windowing), or (b) a **Sampler with `Reverse` automated** at the
  phrase center (live reverse, but loses automatable windowing). swell leans (a).
  See the companion reverse/fold request.
- **Aura** — `mixer_volume` envelope, center-peaked.

## Scope boundary — what the framework owns vs what the song owns
This request and its companions ask the framework for **decision-free primitives
only**:
- a sample-instrument part with an assigned sample (this file),
- sample-accurate device-parameter clip envelopes
  (`2026-06-12-sample-accurate-device-parameter-clip-envelopes.md`),
- a reverse capability (`2026-06-12-audio-clip-reverse-and-fold.md`),
- a derived-asset pipeline (`2026-06-12-build-time-derived-audio-assets.md`).

The **windowed-reveal generator** — center-pinning, `width = f(breath)`, the
forward-mirror fold, the summit release — is deliberately **NOT** a framework
ask. It encodes per-song musical decisions (where the landmark sits, how the
reveal grows, what the fold *means*), which the house norm keeps with the author
(*"helpers may remove bookkeeping but must never make the musical decision for
you"*). It lives in `songs/swell/breath.py`, composed on top of the four
primitives above. The only promotable seam is the thin, decision-free
translation *(window start/length, reverse, level) per phrase → trigger note +
device-parameter envelopes* — promote that **on the rule of three** (when a
second/third song wants windowed-sample playback), not pre-emptively. Please
don't build a windowed-sample *generator* in the framework now.

## Alternative (heavier; not required for swell): CLP-AUD2 audio-clip push
The originally-planned audio-clip push/pull (`kind='audio'` clips don't sync —
`sync/push/clips.py` refuses) would also serve, and is the right tool for true
arrangement audio / non-instrument material. But for this song it is **not the
critical path** — the sample-instrument primitive above unblocks the centerpiece
on machinery that already ships. Recommend prioritizing the instrument primitive;
keep CLP-AUD2 on its existing roadmap for the general audio-clip case.

## Acceptance (for swell)
A `build.py` authoring a Simpler-with-assigned-sample part + `S Start`/`S Length`
device-parameter envelopes + a volume aura **pushes to Live and plays the
windowed, center-pinned reveal audibly**, idempotently — with no audio-clip-push
dependency.
