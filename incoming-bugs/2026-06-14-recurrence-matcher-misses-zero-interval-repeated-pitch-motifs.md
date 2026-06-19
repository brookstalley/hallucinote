# Recurrence matcher never matches a zero-interval (repeated-pitch) motif — not even its home

**Severity:** M (correctness — a whole class of motif is invisible) — pedal
tones, drones, ostinati, and stutter/grain cells cannot be tracked by the
recurrence / motivic-economy lens. For a song whose structural DNA is a repeated
pitch, the form lens reads empty.
**Refs:** `src/hallucinote/recurrence/match.py`, `recurrence/lens.py`. Found
wiring swell's `recurrence_report()` (songs repo, compose/swell).

## What happened

swell's structural motif is the `i-cell`: a hammered single pitch on the eighth
grid (the crushed "I" stutter — D4 in the glitch, migrating to a low-D timpani
stutter and a hammered-root celli "dumb riff" at different scales; the song's
whole thesis is one atom at many scales). Registered as a `Motif`, it reported
`never_recalled` AND no home occurrence — the lens sees it nowhere.

## Minimal repro

```python
from hallucinote.arrangement import Motif
from hallucinote.recurrence import SectionRecurrenceInput, analyze_recurrence
def n(p, s): return {"pitch": p, "start_beats": s, "duration_beats": 0.4, "velocity": 100}

# zero-interval motif (a repeated pitch)
flat = {"flat": Motif("flat", [n(62, 0.0), n(62, 0.5), n(62, 1.0)])}
secA = SectionRecurrenceInput("A", 4.0, {"x": [n(62,0.0), n(62,0.5), n(62,1.0)]}, start_beat=0.0)
secB = SectionRecurrenceInput("B", 4.0, {"y": [n(50,0.0), n(50,0.5), n(50,1.0), n(50,1.5)]}, start_beat=4.0)
r = analyze_recurrence([secA, secB], flat, song_slug="t")
# -> economy.occurrence_records == 0, never_recalled == ("flat",); NO home match either

# control: distinct-interval triad matches fine
tri = {"tri": Motif("tri", [n(60,0.0), n(64,0.5), n(67,1.0)])}
sA = SectionRecurrenceInput("A", 4.0, {"x": [n(60,0.0), n(64,0.5), n(67,1.0)]}, start_beat=0.0)
sB = SectionRecurrenceInput("B", 4.0, {"y": [n(55,0.0), n(59,0.5), n(62,1.0)]}, start_beat=4.0)
r2 = analyze_recurrence([sA, sB], tri, song_slug="t")
# -> A: var=exact home=True ; B: var="transpose -5" home=False   (correct)
```

## Likely cause

The matcher appears to key on the transpose-invariant interval sequence; a
degenerate all-zero interval vector is rejected or normalized away, so a
repeated-pitch motif never matches — including against itself at home.

## Why it matters

A repeated-pitch cell is a legitimate, common motif (pedal, drone, ostinato,
stutter/grain). Silently reading it as "never recurs" is worse than erroring:
the motivic-economy summary understates recall and a composer can't tell "my
motif doesn't recur" from "the lens can't see this motif."

## Suggested directions

1. Match zero-interval motifs — at minimum the home occurrence; ideally full
   transpose/containment like any other (a hammered cell that reappears
   transposed to another pitch IS a recall).
2. For pitch-degenerate motifs, fall back to a rhythm/onset-pattern match.
3. If a class is genuinely unsupported, surface it (a "motif not analyzable"
   note) rather than a silent `never_recalled`.

## Workaround in the song

swell registers the `i-cell` anyway (it is the TRUE structural motif, not a
lens-friendly substitute) with a docstring noting it reads empty until this
lands; the `shout` cell is left to the melody lens rather than over-matching the
recurrence transform group.
