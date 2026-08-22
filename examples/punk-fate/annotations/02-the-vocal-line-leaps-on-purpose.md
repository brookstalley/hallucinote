---
kind: annotation
scope: song
date: 2026-08-10
tags: [melody, profile, intent, learn-back, compose-review]
---

# The vocal line leaps on purpose — don't re-flag it

The first `melody_report()` declared the Voice line as
`contour_intent="arch", step_appetite="moderate"`. The lens then asked about it
eight times across six sections, correctly: the line reads **3–10% steps** in the
verse, scherzo and finale, and its contour is descending, level, or ascending
depending on the section — never an arch.

**The declaration was wrong, not the notes.** This line *is* the fate cell: a
repeated note followed by a drop of a third. It leaps because Beethoven's motif
leaps, and a version of it that moved by step would not be the motif. Its
per-section contour is whatever re-harmonizing that cell produces — descending in
the intro, level wherever it loops, ascending where the song climbs out of C
minor into C major.

So the profile is now `contour_intent="free", step_appetite="low"`, with
`harmonic_freedom="low"` and `repetition_appetite="high"` unchanged (those two
were right: 91–100% chord-tone, 97–100% repetition coverage in the looping
sections). The lens went from 12 questions to 6.

**The 6 that remain are all correct and all answered here:**

- **`break-ab` is 36% non-chord-tone.** That's the A-flat andante — the one
  section where the synth genuinely *sings* rather than chants, and every
  non-chord-tone is a diatonic passing or neighbour tone that resolves by step
  (69%). Intended.
- **`bridge-pedal` reads 80% steps and `ascending`.** That's the transition
  climbing Ab4→C5→D5→Eb5→F5→G5 over the pedal. Being the one part of the song
  that moves by step is the *point* — it's the only place the line goes somewhere
  instead of hammering.
- **`intro-fate` and `coda` show low repetition coverage** (0% and 68%). Both are
  eight-note and short: two statements of the cell at different pitches. There is
  nothing to repeat yet in the intro, and the coda is the cell answering itself.

None of these should be raised again.
