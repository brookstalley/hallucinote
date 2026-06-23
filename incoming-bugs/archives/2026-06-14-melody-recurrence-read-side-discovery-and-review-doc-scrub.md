# Read-side authoring (melody_report / recurrence_report) is hard to discover, and the review docs need a scrub

**Severity:** M (adoption / correctness-of-use) — the read-side lenses are
powerful but wiring a song's `melody_report()` / `recurrence_report()` correctly
required reading three other songs + the lens source. A composer following the
in-file guidance lands on a pattern that compiles but mis-grades.
**Refs:** `src/hallucinote/melody/profile.py`, `melody/lens.py`, `recurrence/lens.py`,
`docs/melody-model.md`; skills `/compose-review`, `/mix-review`. Surfaced wiring
swell's `melody_report()` + `recurrence_report()` (songs repo, compose/swell).

## What happened

Wiring swell's two read-side functions from scratch, the friction was discovery
and correctness-of-use, not the API itself:

1. **Two competing "how to wire melody_report" patterns, no canonical one.**
   swell's scaffold docstring pointed to `sun-zone-done/build.py` and an
   `analyze_arrangement(arr, …, melody_layers=("Lead",))` call over an in-memory
   `Arrangement`. The pattern that actually works for a breath/cell-engine song is
   the *other* one — per-section `SectionMelody(name, length_beats, layers,
   melody_layers, profiles={track: MelodicProfile})` + `analyze_melody(sections)`,
   as used in `missing/build.py`. Nothing tells you which to use when, or that
   per-section profiles even exist (the profile.py example shows a single song-wide
   profile). I only found the per-section pattern by grepping `missing`.

2. **The "declare a profile and it never re-flags" promise doesn't hold for
   phrase-looping material.** `profile.py` says: "once the revealed intent is
   written down as a `MelodicProfile`, the line grades as matched and never
   re-flags." But `contour_intent`/`apex_position` are measured at SECTION
   altitude, and a phrase-looping line (an arch repeated every phrase) reads
   "level" / apex-early at section scale no matter how well each phrase arches. So
   declaring `contour_intent="arch"` keeps emitting `aimless-line` /
   `apex-position-mismatch` forever — declaration can't silence it, because the
   measurement is altitude-mismatched, not intent-mismatched. There's no documented
   caveat that these fields are section-level, nor guidance on what to do (declare
   `free`? accept the finding? wait for a per-phrase/LBDM read?). A composer can't
   tell "your line is wrong" from "the lens can't see this at this altitude."

3. **No motif-sizing guidance for recurrence.** A 3-note motif over-matches the
   full transform group (swell's `shout` cell read as a recall on nearly every
   layer — transpose/invert/retrograde/fragment of a 3-note figure is almost
   anything); a zero-interval motif matches nothing (separate bug, filed same
   day). Nothing documents how long / how distinctive a motif must be to produce a
   trustworthy reading, so a first attempt yields either noise or silence.

4. **The read-side surface isn't enumerated in one place.** "Which functions
   should a song define, with what signatures, and a worked example" is spread
   across `melody-model.md`, `sun-zone-done`, `missing`, profile.py's docstring,
   and the skill descriptions. There's no single "song read-side authoring" doc.

## Why it's framework-shaped

These lenses are the spine of `/compose-review` and `/mix-review`. If wiring them
correctly takes archaeology and the in-file guidance points at a mis-grading
pattern, the reviews under-deliver for every new song.

## Suggested directions

1. **One canonical "song read-side authoring" guide**: the functions a song
   defines (`melody_report`, `recurrence_report`, and the mix-side equivalents),
   their signatures, ONE worked example, and explicit "use `SectionMelody` per
   section when … / `analyze_arrangement` when …".
2. **Profile-field altitude caveats** in `profile.py` + melody-model: mark which
   measures are section-level, document the phrase-looping interaction, and give
   the recommended handling (so `contour_intent` isn't declared into permanent
   noise). Ideally a phrase-level contour read so per-phrase arches grade true.
3. **Recurrence motif guidance**: minimum distinctiveness/length, what the
   transform group will over-match, and that pitch-degenerate motifs don't match.
4. **Broader review doc scrub** ("how to review and document songs"): the
   relationship between profiles (declared intent), annotations (learn-backs),
   decisions (the why), and what each lens can/can't read at which altitude — so a
   composer knows which findings are theirs to act on vs. tooling limits.

## Workaround in the song

swell's `melody_report()` now declares per-section profiles to genuine INTENT
(not fitted to output), leaves contested fields `None`, and treats the section-
level contour reading as a known altitude limit rather than chasing it.
