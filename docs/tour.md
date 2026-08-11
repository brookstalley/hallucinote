# Making a song, start to finish

One real session, documented as it happened. On 2026-08-11 a Claude Code
session was handed the one-sentence prompt below and left to drive. Forty
minutes later a finished, mixed, four-track song was playing in Ableton Live —
and every artifact on this page was captured from that session, not staged for
it: the transcript excerpts are rendered from the session log, the screenshots
were shot by [`tools/capture_live_shot.py`](../tools/capture_live_shot.py)
while it ran, and the audio is the render the session itself measured.

The song ships in this repo. [`examples/punk-fate/`](../examples/punk-fate/)
is the finished source, and `python examples/punk-fate/build.py` rebuilds its
database from a clean checkout with no Live installed — that exact replay is
what this repo's CI runs. What is **not** promised: re-running the *prompt*
reproduces the *process*, not this song. An agent handed the same sentence
will make different choices, and that's the point — this is a walkthrough of
how a song gets made, not a recipe for this one.

*A ten-minute read. Ten beats, one artifact each.*

---

## 0 · The result, first

[![Punk Fate — full song waveform](assets/tour-chapter1.png)](assets/tour-chapter1.mp3)

**[▶ punk-fate — 1:55, four tracks](assets/tour-chapter1.mp3)** — Beethoven's
Fifth crammed into 115 seconds of basement punk: C minor fate riff → E♭ chorus
→ A♭ half-time break → hardcore scherzo → dominant-pedal transition → C MAJOR
finale. Everything below is how it got made.

## 1 · Ideation → intent

The whole spec the session started from:

> Make a 2-minute punk song that crams the chord progression of Beethoven's
> 5th into those two minutes. Drums, bass, lead guitar, and vocals on a
> staccato synth. Call it punk-fate.

Claude's first move (`/song-brief`) is not to start typing notes — it reads
what the prompt actually pins down, fills what it can own, and comes back
**once**, proposing rather than asking:

> **Settled from your prompt:** slug `punk-fate`, ~2:00, 4/4 punk, four parts
> — drums, bass, lead guitar, and a staccato mono-synth playing the "vocal"
> line (so: no lyrics, the synth *sings* the melody; say if you actually want
> words somewhere).
>
> **The one real fork.** "The chord progression of Beethoven's 5th" can mean
> two quite different songs, and it's the creative lock-in I don't want to
> make for you — so it's the question below. The rest I'm telling you, not
> asking.

One question — the famous first-movement material, or the whole
four-movement C-minor-to-C-major arc? The user picked the arc, agreed to
200 BPM, and that was the last decision they were asked to make. The full
brief, with every dimension marked *user / inferred / agreed-after-confirm*,
was filed as
[`annotations/01-the-brief.md`](../examples/punk-fate/annotations/01-the-brief.md);
the fork's reasoning became the first of seven
[decision records](../examples/punk-fate/decisions/).

## 2 · Scaffold + chains

A song is a directory, and the sound ships with it — device chains are
authorship, not a mix-time to-do list:

```
examples/punk-fate/
├── build.py                  # every note, as code
├── captured_session.json     # instruments, device chains, the dialed mix
├── REQUIREMENTS.md           # third-party plugins needed (here: none)
├── annotations/              # scoped intent (the brief, melody intent)
├── decisions/                # why, dated — 7 ADR-shaped records
├── attempts/                 # what was tried, including what was reverted
├── analysis/                 # the measured mix reports (beats 8-9's numbers)
└── tests/                    # shape tests; run in this repo's CI
```

Each track got a stock-Live chain picked for the brief's production stance
("raw and blown-out — Beethoven played by a band in a basement"): a Garage
Kit drum rack driven into a saturator and glue compressor, palm-muted bass
with grit, a deliberately mid-forward crunch guitar, and a square-wave
Operator as the shouted "vocal." The full table — and why the guitar
*doesn't* get a third gain stage — is
[`decisions/05-signal-chains.md`](../examples/punk-fate/decisions/05-signal-chains.md).

![The Garage Kit drum rack open in Live, bus saturation and glue macros dialed](assets/tour-drum-rack.png)

## 3 · Harmony & form

Harmony is a modeled substrate the parts compose *against*, not a comment.
The verse churns in C minor; the chorus is the relative-major lift:

```python
# examples/punk-fate/build.py
PROG_VERSE = Progression.of(
    "C", "Minor", ["Cm", "Ab", "Eb", "G"], beats_per_chord=4.0, functional=True)
PROG_CHORUS = Progression.of(
    "Eb", "Major", ["Eb", "Bb", "Cm", "Ab"], beats_per_chord=4.0, functional=True)
```

Beethoven's great third-to-fourth-movement transition — the bass pedals low C
for eight bars while the harmony above it tightens — compresses into a
progression whose *rhythm* accelerates into the cadence:

```python
# examples/punk-fate/build.py
# Accelerating harmonic rhythm into the cadence — the transition's whole point.
PROG_BRIDGE = Progression.of(
    "C", "Minor", [("Ab", 8.0), ("G", 8.0), ("Ab", 4.0), ("G", 4.0), ("G7", 8.0)],
    functional=True)
```

These progressions are rulers: the melody lens in beat 5 reads every vocal
note against them for harmony-fit. How `build.py` is organized —
[`song-authoring-conventions.md`](song-authoring-conventions.md).

## 4 · Rhythm & feel

Microtiming is written into the parts at generation time — deterministic
push and pull per instrument, never a "humanize" pass of random jitter:

```python
# examples/punk-fate/build.py
GTR_FEEL = {i * 0.25: -0.010 for i in range(16)}
BASS_FEEL = {i * 0.25: +0.006 for i in range(16)}
DRUM_FEEL = {1.0: -0.012, 3.0: -0.012}
SYN_FEEL = {0.0: -0.014, 0.5: -0.014, 2.0: -0.014, 2.5: -0.014}
```

The guitar pulls the band forward; the bass refuses to be pulled; the snare
leans into the backbeat; the singer leans into the top of every phrase. The
groove lives in the ~16-tick gap *between* guitar and bass
([`decisions/04-per-part-feel.md`](../examples/punk-fate/decisions/04-per-part-feel.md)).
In the clip editor you can see it — the snare sits just left of the gridline
while the kick sits on it:

![Off-grid MIDI in Live's clip editor — the snare backbeat lands ahead of the grid](assets/tour-offgrid-midi.png)

## 5 · Melody

`hallucinote melody` reads every line against its *declared* profile — there
is no universal "good melody" score, only measurements against stated intent.
Real output from this song:

```
[break-ab]
  Voice — active (confidence 100%, 39 notes) · profile 'shouted-hook' · shaped
    contour: level · apex 79@95% · 16 direction-changes · gradient-stdev 3.41 · repetition-coverage 68%
    phrases (LBDM): 7 · arch → arch → ascending → arch → ascending → ascending → insufficient-data
    intervals: step 62% / leap 38% · post-skip-reversal 67% · alphabet 9 · ambitus 16 semitones
    harmony: 64% chord-tone · 36% non-chord-tone · NCT-resolves-by-step 69% · chord-tone-on-strong-beat 100%
    ? Voice: you declared a low step appetite, but 62% of moving intervals are steps (moderate) — intended proximity/leap balance, or has the line's motion drifted?
```

Those `?` lines are coaching questions, not verdicts — and this one's answer
is *intended*: the A♭ break is the one section where the synth genuinely
*sings* instead of chanting, so its step-heavy motion is the point. That
answer lives in
[`annotations/02-the-vocal-line-leaps-on-purpose.md`](../examples/punk-fate/annotations/02-the-vocal-line-leaps-on-purpose.md),
which also records the first lens run *correcting the profile itself* — the
declared contour was wrong for a line built on Beethoven's leaping cell, and
fixing the declaration (not the notes) took the lens from twelve questions to
six.

## 6 · Arrangement

The whole form at a glance — eight sections in 96 bars, every one in a
different harmonic place, because at 1.2 seconds a bar there is room for a
narrative *or* a repeat, not both:

![The arrangement in Live: scherzo, bridge-pedal, finale-cmaj, coda across four tracks](assets/tour-arrangement.png)

The section budget — and why the finale had to be at least as long as the
verse — is
[`decisions/02-tempo-and-the-section-budget.md`](../examples/punk-fate/decisions/02-tempo-and-the-section-budget.md).

## 7 · Materialize

The push is fourteen ordered phases driven against a running Live set. From
the session, verbatim:

> `Bash` — Probe and link a new Ableton session
>
> `Bash` — Execute the fourteen-phase push
>
> All 14 phases OK — the song is in Live. [...] The song is in Live and the
> timeline verifies faithful.

And Live, mid-pipeline — all 32 clips landed, meters live as the set plays:

![Live's session view during the render: four tracks, eight scenes, meters moving](assets/tour-session-render.png)

Re-pushes are idempotent: change one part and re-push, and the phases that
have nothing to do report `ok` with zero calls dispatched. The phase list and
what each one owns — [`skills.md`](skills.md).

## 8 · Production & mix

The agent rendered its own work and measured it. First render:

- master at **+5.51 dBTP** with **257 true-peak overshoots** — clipping, hard
- the bass flagged as the masked instrument in **all eight sections**
  (0.56–0.70 against the summed bed), sitting **9.7 LU** below the loudest stem

The measured numbers ship with the song —
[`analysis/`](../examples/punk-fate/analysis/) holds the before and after
reports. What makes this a *mix review* rather than a meter readout is what
the agent did with it, in its own words:

> The report is unanimous: **the bass is the maskee in every one of the eight
> sections** [...] That directly contradicts the arrangement decision I filed
> an hour ago — the verse holds the guitar back specifically so the *bass*
> carries the engine, and right now the bass is inaudible.

The mix contradicted the song's own composition decision — so the fix was a
rebalance *around the bass*, not "turn things down until the meter is happy."

## 9 · Iterate

One change, its diff, and the before/after. The rebalance
([`decisions/07-the-bass-carries-the-engine.md`](../examples/punk-fate/decisions/07-the-bass-carries-the-engine.md)):

| fader | before | after |
|---|---|---|
| 01 Drums | +1.2 dB | **−6.2 dB** |
| 02 Bass | 0.0 dB | **−0.8 dB** — the least-trimmed track; the whole fix |
| 03 Guitar | −0.4 dB | **−4.9 dB** |
| 04 Voice | −2.0 dB | **−12.0 dB** — it was out-shouting the band |
| Master | 0.0 dB | **−4.0 dB** — headroom |

…plus sends raised 2–3× and the reverb cut from a 2.5 s hall to the 1.1 s
room the brief actually asked for. Hear it — the same verse-into-chorus
passage, first render against the fix:

[![before — clipping, buried bass](assets/tour-chorus-before.png)](assets/tour-chorus-before.mp3)
**[▶ before](assets/tour-chorus-before.mp3)**

[![after — the bass carries, the master holds](assets/tour-chorus-after.png)](assets/tour-chorus-after.mp3)
**[▶ after](assets/tour-chorus-after.mp3)**

Verified, not assumed: the A/B render measured **+5.51 → +1.29 dBTP** on the
bus and **257 → 1** overshoots. And one thing stayed honestly *unverified* —
the analyzer reads stems pre-fader, so the masking improvement couldn't be
confirmed by measurement in the same pass. That limit is written into the
decision record and the
[attempt ledger](../examples/punk-fate/attempts/2026-08-10-master-clipping-and-buried-bass.md)
rather than glossed.

## 10 · Bake, commit, fork

The dialed mix was captured back into `captured_session.json`, the song
rebuilt from scratch, and re-pushed — proving the whole thing survives
`build.py --reset`. From the session's close:

> Everything is baked into `captured_session.json`, so the mix survives a
> `build.py --reset` — rebuilt and re-pushed to prove it. Brief, 7 decisions,
> 2 annotations, and 2 attempt entries are on disk; arrangement verifies
> faithful; tests pass.

A song is a directory in a git repo: diff it, fork it, hand it to a
collaborator ([`collaboration.md`](collaboration.md)) — their machine gets
its plugin requirements checked before anything pushes. The last gesture in
the source is the song's whole argument, one semitone wide:

```python
# examples/punk-fate/build.py
    # bar 7 — the thesis. G-G-G-E natural.
    _motif(gtr, 7, G_G_HI, G_C, vel=127, feel=GTR_FEEL, power=True, long_dur=2.0)
    _motif(bas, 7, G_G_HI - 12, G_C - 12, vel=125, feel=BASS_FEEL, long_dur=2.0)
    _motif(syn, 7, S_G4, S_E5, vel=127, feel=SYN_FEEL, long_dur=2.0)
```

The song opened on G-G-G-E♭. It ends on the identical rhythm, E natural —
darkness to triumph, exactly as advertised.

---

**Do it yourself:** [`quickstart.md`](quickstart.md) is the ten-minute
version with your own song. **The map and the why:**
[`song-workflow.md`](song-workflow.md).
