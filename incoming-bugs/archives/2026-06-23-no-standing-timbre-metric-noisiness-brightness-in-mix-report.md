# Capability: standing per-stem / per-section timbre metrics (noisiness · brightness) in the mix report

**Type:** capability request (analysis lens — closes a "judge by ear only" gap).
**Severity:** M. Not blocking — a human can judge timbre by ear — but the engine
renders the audio and already owns the DSP primitives, so the composer/agent is
flying blind on a whole *class* of requests it could answer with a number.
**Engine / server:** `1.5.0` (`d80fe21`, develop). Surfaced composing `alien`
(songs repo), on a request to *"make the Noise track actually noisy — it needs more
texture."*

## Motivating request

The `alien` Noise track is conceptually broadband atmosphere, but by ear it reads as
a smooth tonal pad — not noise. The composer asked to make it noisier, and asked the
right meta-question first: **can the toolkit measure (or estimate) timbre, so a
"make X noisier / brighter / grittier" request can be verified rather than guessed?**

Today the answer is no — there is no timbre descriptor anywhere in the analysis
report. You can render the stem, you can read its device chain, but you cannot ask
the report "how noisy / how bright is this stem?" and get an answer to move against.

## Evidence (measured on the real `alien` stems)

The data exists and the request is real. I measured the rendered per-stem WAVs in
`songs/alien/captures/20260623T004649Z/` (offline numpy STFT, 4096/2048, Hann,
silence-gated frames; whole-stem medians):

| stem          | spectral centroid | HF energy >2 kHz | band-power flatness |
|---------------|------------------:|-----------------:|--------------------:|
| **Noise**     | **457 Hz**        | **0.000**        | 0.006               |
| Sub Bass      | 170 Hz            | 0.000            | 0.000               |
| Drums         | 275 Hz            | 0.023            | 0.005               |
| Human Riff    | 2041 Hz           | 0.311            | 0.000\*             |
| Alien Voice   | 1280 Hz           | 0.465            | 0.038               |
| _white-noise ref_ | —             | ~0.55            | **0.892**           |

The track literally named **"Noise" is the darkest, least-broadband element in the
mix except the sub bass** — centroid 457 Hz, *zero* energy above 2 kHz. The Human
Riff and Alien Voice are far "noisier" by every spectral measure. A single cheap
descriptor (centroid, and/or an HF/rolloff ratio) already separates "tonal pad" from
"broadband texture" by an order of magnitude, and confirms the composer's ear
objectively. This is exactly the kind of before/after a "make it noisier" edit wants
to verify.

\* Whole-stem **median** band-flatness understates transient noisiness (drums are
broadband only during hits, so the median frame looks tonal). See the methodology
note — this is a real design choice (which statistic, gated how), not a blocker.

## The gap — what exists vs. what's missing

The primitives are all here; only the standing report field is missing.

**Exists:**
- Per-stem 32-bit WAV renders on disk (`render` pipeline → `captures/<ts>/track-*.wav`).
- `src/hallucinote/audio/masking.py` — `librosa.stft` → power per bin → **24 Zwicker
  Bark critical-band powers**. Full FFT-domain per-band power on exactly these stems.
- `src/hallucinote/audio/automation.py` — `_spectral_centroid_hz()` (`np.fft.rfft`,
  magnitude-weighted mean frequency). **The engine already computes a spectral
  centroid** — but only as a before/after delta to verify a *declared device-param
  automation flip* (`EnvelopeVerification`, report.py:148), never as a standing
  per-stem value.
- `src/hallucinote/audio/attribution.py` — per-band RMS via Butterworth bandpass
  (6 musical bands), ranks which stem owns each band.

**Missing:** every persisted per-stem / per-section metric is **loudness only**.
- `report.py` `StemMetrics` (line 78) carries `loudness: LoudnessMetrics` and nothing
  spectral. `SectionMetrics` (415) likewise. `to_json_dict` per-stem block
  (686–693) emits only `lufs_*` + `true_peak_dbtp`.
- The only spectral scalar that ever reaches a report is the conditional automation
  centroid delta above — incidental, 2-point, and only where an envelope was authored.
- `energy.py:38` **already documents this as the designed extension point**: *"Open by
  design (DR-3): a future spectral-intensity correlate adds a key here without a shape
  change."* That correlate is precisely a standing per-section brightness/noisiness number.

So: the WAV + STFT + Bark-power + centroid machinery all exist; what's absent is a
small, standing timbre descriptor on `StemMetrics` surfaced through the report JSON.

## Requirements

1. **Standing per-stem timbre descriptor** in the analysis report — available for every
   stem without authoring an automation envelope first.
2. **Per-section** as well as whole-stem (reuse the existing `_measure_window` path), so
   "is the Noise track noisier in chorus 3 than in verse 1?" is answerable.
3. **A small complementary set**, not one number — at minimum:
   - **spectral centroid (Hz)** — brightness (already implemented in automation.py;
     promote it to a standing metric).
   - **spectral flatness (0–1)** — noisiness / tonal-vs-noise, computed over **band
     powers** (see methodology), not raw FFT bins.
   - **spectral rolloff (Hz) or HF-energy ratio** — corroborates brightness / "air".
4. **Comparable before/after** — flows through `compare.py` so a re-render after a patch
   change reports the timbre delta (the whole point: verify the edit moved the needle).
5. **Robust to silence / sparse stems** — silence-gate frames; emit a JSON `null`
   sentinel for stems with no measurable signal (mirror the loudness `_finite_or_none`
   convention), don't emit `0`/`NaN`.
6. **Cheap** — reuse the STFT already computed for masking; don't add a second transform.

## Implementation suggestions

Smallest change that reuses existing machinery:

- **New `src/hallucinote/audio/timbre.py`** (or fold into `masking.py`, which already
  has the STFT + Bark-band power). One function `measure_timbre(audio, sr) ->
  TimbreMetrics` returning `{spectral_centroid_hz, spectral_flatness, spectral_rolloff_hz}`,
  median over silence-gated frames. Lift `_spectral_centroid_hz` out of `automation.py`
  into here and have automation.py call the shared impl (removes the duplicate).
- **`report.py`**: add a `TimbreMetrics` dataclass; add `timbre: TimbreMetrics | None`
  to `StemMetrics` (78) and the per-section stem metrics; extend `to_json_dict`
  (686–693) with a `"timbre": {...}` block beside `"loudness"`.
- **`analyze.py`**: compute it where loudness is already computed per surface —
  `_measure_surface` (line 342, whole-stem) and `_measure_window` (853, per-section).
  The `Surface` already exposes `.audio`, so the input is in hand; no new I/O.
- **`energy.py`**: register the section centroid as the "spectral-intensity correlate"
  the module's DR-3 comment (line 38) reserves a slot for — one new key, no shape change.
- **`compare.py`**: include the timbre fields in the before/after delta surface.

### Methodology note (matters for getting flatness right)

Naïve per-frame spectral flatness over **raw FFT bins** is crushed for any pitched
material — inter-harmonic gaps drive the geometric mean toward zero, so every tonal
stem reads ~0.000X and the metric can't discriminate (verified: raw-bin flatness gave
Drums 0.0004, Noise 0.0001 — useless). Computing flatness over **band powers** (the
24 Bark bands `masking.py` already produces, or log/third-octave bands) is the standard
fix and separates white noise (~0.89) from tonal pads (~0.006) cleanly. **Reuse the
Bark-band power vector masking.py already computes** rather than re-deriving it.

Second subtlety: **which statistic**. A whole-stem *median* understates transient
broadband content (drums look tonal because the noisy frames are sparse). Consider
reporting a high percentile (p90) alongside the median, or onset-gating, or simply
leaning on centroid + rolloff for the whole-stem read and using flatness mainly
per-section. Worth a short design decision, not a guess.

## Acceptance criteria

- `analysis/*.json` per-stem (and per-section) blocks carry a `timbre` object with
  centroid / flatness / rolloff (or documented subset).
- Re-running analysis on `alien` reports the Noise stem as low-centroid (~450 Hz) and
  low-flatness — i.e. the report objectively agrees it's a dark tonal pad.
- After a patch edit that adds broadband texture and a re-render, `compare.py` shows the
  Noise stem's centroid / flatness / rolloff increase — the composer can **verify** the
  edit, not just hope.

## Notes / scope

- Read-side only — a measurement/lens, not a generator. It never grades a mix or
  re-authors anything (consistent with the energy lens's stance, report.py:527).
- Doesn't need new capture infrastructure — the stems and the STFT primitives already
  exist; this is a report field + a ~one-function measurement on top of them.
- Device-param introspection is a *separate*, complementary path (you can already read
  that `alien`'s Noise chain is `Inclement Drone Pad → Auto Filter (LP 24 dB) → Erosion`
  and reason about it). This request is the **render-measured** side, which is what
  lets you confirm a timbre change actually happened in the audio.
