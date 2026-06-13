# Feature request — first-class audio reverse / fold (parity with note-level retrograde) (2026-06-12)

Context: hallucinote-songs `swell`. Engine 0.9.0. Design:
`songs/swell/decisions/17-buried-we-centerpiece.md`.

## The need
The framework ask here is **only the general reverse capability** — the *fold*
gesture itself (forward→center→reverse) is swell's composition in `breath.py`,
not a framework feature.

swell's centerpiece fold plays the sample **forward into the phrase center, then
reversed out** — a per-phrase time-palindrome (the song's axis-of-symmetry motif,
`decisions/04-key-and-mode.md`). Today there is **no authorable way to reverse
audio from build.py/DB**:
- no clip-level reverse flag (verified: no `reverse`/`reverse_mode` column in
  `db/schema.sql` clips table or `db/mutations/clips.py`),
- no sample-instrument part type at all (see
  `2026-06-12-sample-instrument-authoring-simpler-sampler.md`).

**Probe finding (scratch Live set, 2026-06-12):** **Sampler *does* expose
`Reverse`** as an automatable enum DeviceParameter (Off/On) — so a live,
automatable reverse is reachable *at runtime*. The catch: **Sampler has no
automatable window** (`S Start`/`S Length` are Simpler-only), so choosing Sampler
for live-reverse costs the breath-windowing mechanism. **Simpler** gives the
window but **no Reverse**. So no single stock device gives *both* automatable
window *and* automatable reverse.

The pre-rendered-reversed-asset path (`…-rev.wav` in a second Simpler) keeps the
window and bakes the reverse into an asset — workable, but the reversal is then
**baked, not an authorable operation**, so flipping the fold's direction
parameter means re-rendering files.

## Precedent
Note-level **`retrograde`** (time-reversed motif) already exists in
`generators/variations.py`. An **audio analog** would give conceptual parity —
retrograde for samples.

## Concrete shape requested (any one; engine team's call)
1. A **clip-level `reverse` flag** on `kind='audio'` clips (schema column + push
   honoring Live's clip/warp reverse), **or**
2. Once the **sample-instrument** part type lands, bless **Sampler's `Reverse`
   device-parameter automation** (probe-confirmed automatable) as a fold path —
   real-time reverse at the phrase center via a `device_parameter` envelope —
   accepting that Sampler forfeits the automatable window, **or**
3. A **build-time derived-asset pipeline** that pre-renders + registers a
   reversed asset so the author writes `fold='forward-mirror'` and the engine
   manages the `…-rev.wav` file transparently — see the broader request
   `2026-06-12-build-time-derived-audio-assets.md` (reverse is one transform).

## Acceptance
swell can author the forward→center→reverse fold — and **flip the direction
parameter** — **without hand-managing reversed audio files**.
