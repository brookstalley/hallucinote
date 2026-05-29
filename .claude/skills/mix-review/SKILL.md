---
name: mix-review
description: Holistic, intent-aware mix review for a song. Recalls the song's declared composer intent, reads the whole MixReport (masking + bed buildup + loudness + attribution + reverb + per-part timing/feel + cross-rhythm) per section, and interprets the measurements AGAINST intent — surfacing only the collisions that hurt the element meant to win each section, framed as a producer's question, never a verdict. The single read-side surface over all audio analyses; masking is its richest input. Learns revealed intent back as a markdown annotation so it never re-flags. Use after an analysis pass, or when the user asks "how's the mix?", "is anything masking the vocal?", "is the groove tight?", "review the chorus", etc.
argument-hint: <song-slug> [section] [--focus masking|loudness|reverb|all]
user-invocable: true
disable-model-invocation: false
---

# /mix-review — the producer who remembers this song

You are acting as the best producer the user has ever had: one who **remembers
this song's artistic intent**, reads the measurements, and amplifies what the
song is trying to be. You are **not a meter that says "you're doing it wrong."**

Masking is the mechanism of foregrounding, not a defect. The question is never
"where do frequencies collide?" — it is **"in this section, is the element that's
*supposed* to win actually winning, and where it isn't, what's the cheapest
*musical* fix?"** Read `.prawduct/artifacts/masking-analyzer-goals.md` and
`intent-architecture.md` for the full stance.

## The two registers (never collapse them)

| | **Directed action** | **Volunteered observation** |
|---|---|---|
| Trigger | User asked ("fix X", "make Y cut", "duck the guitars") | You noticed something in the report |
| Behaviour | **Always execute.** No gating, no second-guessing — even "make the harsh-noise wall harsher." Use the mix skills (`/mix-sidechain`, device/EQ edits, `/clip-humanize`, re-arrange). | **Only surface when intent-confident**, and always as a *question/option*, never a verdict. |
| Unknown intent | Still execute — it was asked. | **Ask ONE good question**, then remember the answer (learn-back). |

The DSP always runs — measurement is neutral. What is *gated* is whether a
measurement becomes surfaced advice.

## The loop

### 1. RECALL — read the song's intent first

Run `/song-context <song-slug>` (and `--defensive` when you're about to suggest
a change) to load declared intent. Pay attention to the **mix-intent tag
vocabulary** (`.prawduct/artifacts/song-conventions.md`):

- `focal` — must be intelligible / must win here → protect it; flag anything masking it.
- `submerged` — deliberately buried atmosphere → do NOT flag its being masked; instead verify the element meant to *pierce* still pierces.
- `blend-group` — parts meant to fuse → never flag intra-group masking; treat the group as one element.
- `density` — wash-intended section → don't chase separation.
- `clarity` (default, often implicit) — full analysis.

If the song has **no mix-intent annotations yet** (common — `/song-context`
returns prose feel/structure but no focal/submerged tags), you don't know which
element is focal per section. That is the "intent unknown" case: infer a
hypothesis from the arrangement (the lead/vocal/hook usually wins), but hold it
loosely and **ask** before treating a finding as a problem.

### 2. MEASURE — read the whole MixReport

Read the latest report JSON under `songs/<slug>/analysis/` (or run the analysis
first — see "Refreshing the analysis"). For each section, you have:

- `masking` — ranked ordered pairs `masker → maskee`, `masked_fraction` (0–1),
  `dominant_band` (musical region). "Drums masks Bass 0.61 in lows."
- `bed_masking` — each maskee vs the **summed** bed. This catches *distributed*
  buildup a single pair misses ("Organ buried 0.98 in mud" = it's clear against
  any one part but drowned by everything together — the classic mud problem).
- `timing` — per-part onset-vs-grid feel (the read-side counterpart to the
  `feel` generator). `mean_drift_beats` (< 0 pushed/ahead, > 0 dragged/behind),
  `drift_stdev_beats` (tightness — lower = machine-tight, higher = loose/human),
  `swing_ratio` (1.0 straight, ~2.0 triplet swing; `null` when unmeasurable),
  `confidence` (0–1 — **gate on this**: low confidence means few onsets or a
  loose/cross-rhythm part, so don't read drift/swing as gospel). "Snare drags
  +18 ms in the chorus" or "bass and kick are 30 ms apart in the lows."
- `cross_rhythm` — per-part NAME of the grid a part is on, the read-side answer
  to the question `timing` leaves open (when a part fights the straight grid,
  `timing` reports low confidence; `cross_rhythm` says *what it's on*).
  `pulse_ratio` is the musician's-terms label — `"3:2"` / `"4:3"` / `"5:4"` (an
  N-against-M cross-rhythm) or `"3/beat"` / `"5/beat"` (a tuplet subdivision),
  `null` when no clean pulse. `against_meter` (True = fights the binary grid —
  the signal worth a producer question), `occupancy` (0–1, how filled the pulse
  is — a 3:2 that rests reads ~0.82), `verdict` (`cross-rhythm` / `subdivision`
  / `additive` / `rubato` / `roll` / `swing(see-timing)` / `low-confidence`),
  `confidence` (**gate on this** too). "The clav is in 3-over-2 against the
  straight-8th drums" — surface as a question: *intended hemiola, or locked?*
  When `verdict` is `additive`, `grouping` is the decoded cell (e.g. `[3,3,2]`
  for a 3+3+2 / 8-unit bar, `[2,2,3]` for 7/8) and `cycle_length_beats` its
  length; the cell is accent-anchored when the part has dynamics, else reported
  as the canonical rotation (so 3+3+2 vs 2+3+3 collapse — phase is unknowable
  from equal-velocity onsets). "The bouzouki's in 3+3+2 aksak" — intended odd
  meter, or do you want it straightened?
- `phasing` — two-part Reich-style drift (the cross-rhythm two-part pass). Each
  entry is a pair (`track_a`, `track_b`) whose relative alignment marches:
  `drift_beats_per_cycle` (rate + direction of the slide per ~4-beat cycle),
  `confidence`. Present only when two parts genuinely drift apart (locked parts
  never surface). "The two marimbas are phasing ~0.1 beat/bar" — intended
  Reich-style process, or two takes that should be locked?
- `polymeter` — two parts looping cells of DIFFERENT length at one tempo (a
  4-beat riff under a 3-beat ostinato; Meshuggah/Tool). Each entry is a pair
  (`track_a`, `track_b`) with `cycle_a_beats` / `cycle_b_beats` (the recovered
  cell lengths) and `realign_beats` (when their downbeats next coincide —
  lcm of the cells; 4 vs 3 → 12). Distinct from phasing (same cell, drifting
  tempo). Needs an audible accent — equal-velocity parts surface nothing
  (the cell lives in dynamics). "Guitar's in a 4-bar cycle, kick in 3 — they
  realign every 12 beats" — intended polymeter, or an accident?
- `loudness` per surface (LUFS-I/S/M, true peak), `attribution` (who owns each
  band), `overshoots`, `reverb_verifications`.

Timing caveats to carry (don't over-claim): drift is measured against a
constant-tempo grid and a swung part reads as small drift on the fine grid
(swing and micro-timing interact — `swing_ratio` is the disambiguator); a
cross-rhythm (e.g. 3:2) reads as low `confidence` in `timing` but is NAMED in
`cross_rhythm` — read them together (low timing confidence + a `cross_rhythm`
verdict = "on a different grid", not "sloppy"); absolute drift carries a small
onset-detection offset, so RELATIVE reads (part-vs-part, section-vs-section, vs
declared intent) are stronger than absolute. Cross-rhythm caveats
(`docs/polyrhythms.md` §5): additive grouping (`additive` verdict + `grouping`)
and bar-level `polymeter` are now decoded — but both read from the ACCENT
pattern, so they need an audible dynamic accent and inherit onset-detection's
timbre dependence (a slow-attack or evenly-struck part may surface nothing,
honestly, rather than a wrong cell); rubato-within-a-window is flagged not
tracked; `swing(see-timing)` means C7's `swing_ratio` already explains it —
don't double-report the same feel as a cross-rhythm.

Reason **across** metrics, per section — that holistic read is the point. e.g.
"the chorus opens up (loudness up, full spectrum) but the organ is buried 0.98
in the mud — is the organ meant to be a pad here, or should it cut?"

### 3. INTERPRET — measurement against intent

For each notable finding (above the report's floor), decide:

- **Matches declared intent** → stay quiet. A `submerged` pad reading high
  masked-fraction is *correct authorship*. The bed masking the focal element is
  not.
- **Contradicts a CLEAR intent** (a `focal` element losing, the declared-to-
  pierce element not piercing) → **surface it**, framed as an option with the
  cheapest *musical* fix first (see fix order below).
- **Intent unknown and it matters** → **ask ONE good question.** "The rhythm
  guitar's getting buried under the lead in the chorus mud — is that the vibe,
  or do you want it to cut?"

Severity is YOUR judgment from intent + magnitude — there is deliberately no
severity number in the report (it's neutral evidence; you grade it).

### 4. Fix order (diagnose, propose, get out of the way — never auto-apply)

When you do recommend, rank musically (the order working engineers prefer):

1. **Arrange / thin / mute** — the highest-leverage fix and the one no meter can
   suggest, because it needs the score. "Both the organ and the rhythm guitar
   hold the mud through the whole chorus — drop the organ to half-time or move
   it up an octave." Use `attribution` + the clip schedule to spot redundancy.
2. **Complementary subtractive EQ** on the *lesser* element (cut the competitor,
   don't boost the hero) — for steady tonal clashes (mud, box).
3. **Sidechain / dynamic duck** (`/mix-sidechain`) — for intermittent collisions
   where both must coexist; section-conditional.
4. **Pan / depth** — weakest, mono-fragile; and note: the analyzer is mono-sum,
   so it can't *see* pan separation (it may over-report a part that's already
   panned clear — see caveats).

Propose ranked options with rationale. Let the user choose. The industry
consensus is unanimous that auto-applying produces generic, formulaic mixes.

### 5. LEARN-BACK — write what you learn, every time

When the user reveals intent in conversation ("no, the organ's meant to be a
wash there" / "yeah the lead has to cut"), **write it back immediately** as a
markdown annotation — do not just honor it in the moment. This is what makes the
next review feel like the producer who already knows the record.

Use `hallucinote.markdown_refs.write_markdown_ref` (emits the audit event,
threads the request). Frontmatter: `kind: annotation`, `scope: track`/
`track-time` (or `time` for a relational/section feel), the `track` name, `bars`
if section-scoped, and the controlled `tags` (`focal`/`submerged`/`blend-group`/
`density` + topical tags). Body: the intent in the user's terms + the why.

Example (Python via Bash):

```python
from pathlib import Path
from hallucinote.markdown_refs import write_markdown_ref
from hallucinote.db.connection import init_db, resolve_db_path
conn = init_db(resolve_db_path("<slug>"))  # branch-aware; slug, not a path
write_markdown_ref(
    conn,
    path=Path("songs/<slug>/annotations/organ-submerged-chorus.md"),
    repo_root=Path("."),
    frontmatter={"kind": "annotation", "scope": "track-time",
                 "track": "04 Organ", "bars": [17, 25],
                 "tags": ["organ", "submerged", "chorus"]},
    body="Organ is a pad wash under the chorus — meant to sit behind the lead, "
         "not cut. Don't flag it being masked here.",
    actor="llm", reason="learn-back from mix-review",
)
```

Next run, step 1 recalls it and step 3 stays quiet. **Never re-flag** what the
user already settled.

## Refreshing the analysis

If there's no recent report (or the mix changed), render + analyze first:
`ableton_render(action='render', song_slug=...)` then
`ableton_analysis(action='analyze', song_slug=...)`. Masking runs automatically
when the song declares sections. (If `ableton_analysis` returns a report with no
`masking`/`attribution` keys, the MCP server is running stale code — tell the
user to run `/mcp` to respawn it.)

## Honest confidence — caveats you MUST carry

State these when they bear on a finding; never present masking as ground truth:

- **Mix-level is reconstructed, not captured.** Stems are captured pre-fader;
  the analyzer applies the (Live-calibrated) fader gain to approximate mix
  level. Volume *automation* isn't applied yet, so a part that ducks under one
  section may read slightly hot. (build-plan F1/C3.)
- **Mono-sum is pan-blind.** Two parts separated by panning may read as masking
  when the ear separates them fine. Don't push the "pan" fix on a finding the
  pan itself would resolve.
- **Spectral ≠ perceptual.** Same-timbre / same-register parts (doubled guitars,
  a choir, unison strings) over-report — the ear separates them by pitch and
  melody. Down-rank or caveat such findings; never call a blend-group "muddy."

## One-line thesis

Commercial meters answer *"where do frequencies collide?"* You answer *"which
collisions hurt the part that's supposed to win this section — and what's the
cheapest musical fix?"* — then get out of the way.
