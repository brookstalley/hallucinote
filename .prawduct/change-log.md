# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously.

     TAG-LINE FORM (canonical — the lifecycle tooling only reads this shape).
     One HTML comment at the HEAD of the entry body (before any prose), wrapping
     exactly this payload (NOTE: delimiters written as words, because a literal
     closing delimiter here would end THIS comment early — HTML comments do not
     nest, and that bug hid the paragraph below as visible body text):
         open-comment prawduct: type=<t> | scope=<tag> | release=<r> close-comment
     Pipe ` | ` separates keys; keys are freeform (unknown keys are preserved).
     A tag line placed after prose is treated as body text, not metadata.

     RETIRED KEYS — do not write these on a NEW entry. `chunks=<a,b,c>` (a COMMA
     list, never pipe) and `status=<s>` are both documented RETIRED in the
     plugin's lib/change_log.py: the derived-view regenerator that read them is
     gone and no gate, view or lint consumes either value. They are listed here
     only because older entries carry them and are preserved verbatim — this
     paragraph exists because the form above USED to advertise both, which is
     how a new entry came to be written with an invented `status=complete`.

     RELEASE VOCAB for in-flight work: an entry sitting on develop with no release
     cut carries NO `release=` key at all — that ABSENCE is the release-pending
     state, and it is what `check-releasability` enumerates. At release cut, ADD
     `release=vX.Y.Z`. Do not write a placeholder: the checker treats ANY value as
     "already released", so `release=unreleased` silently drops the entry's whole
     scope out of the pending set and the work never ships. (This supersedes the
     VEW-9QH4 placeholder convention, which four entries followed until 2026-08-10
     — the checker rejects it outright. Omitting the key satisfies the same
     original concern: no version is pre-bumped, and nothing is mislabelled as
     already shipped.) -->

## 2026-09-12 — A release publishes its change log and resets it

<!-- prawduct: type=fix | scope=release-log-roll -->

The roll had an unsatisfiable rule and so it was never really done. Step 1 of the
release procedure said to move the oldest entries out "until the live log is
comfortably under the ceiling, keeping the last few releases for context" — and one
release of entries is larger than the whole 55 KB ceiling. Both halves could be
honoured exactly and still leave the log 2.5× over, which is what happened: v1.9.0
shipped and `change-log.md` stood at **142 KB**, 25 tagged entries of it, against a
55 KB nudge that then fires every session and means nothing.

**The fix is an ordering, not a redesign.** The reason the shipped entries could not
simply be folded at stamp time is real but narrow: `plan-backfill` reads `scope=` and
`release=` out of `change-log.md` (`lib/plan_backfill.py` → `shipped_scopes`) to decide
which build plans retire, and `check-releasability` reads it too. Fold at step 1 and the
plan sweep two steps later sees nothing to archive. So the roll moves to the **last act
of step 3**, once both hooks have read what they need — and then nothing downstream
wants those entries at all.

**The rule is now "every entry carrying `release=`", not "enough to get under the
ceiling".** A release publishes its entries and resets the file to its header. That
makes the file's size mean something it did not mean before: it measures *unreleased*
work, so the oversized nudge becomes a real signal that a lot is unshipped instead of a
guaranteed post-release artifact. The one safety assert is unchanged and is still the
only failure this step can cause — never move an entry without a `release=` key,
because that absence IS the release-pending marker.

Applied to the v1.9.0 backlog in the same change: 24 entries folded, `change-log.md`
**141 KB → 15 KB**, and both hooks verified to read identically across the move
(`check-releasability` still 1 release-pending scope; `plan-backfill` still names the
same one plan it refuses).

**One entry is held back by hand, and it is the known gap.** `scope=SMP-6V2K-W2` is
tagged `release=v1.9.0`, but its plan has an unticked operator-gated chunk (Chunk 17,
the Live session) that `plan-backfill` rightly refuses to archive without a person. The
archive is invisible to `shipped_scopes`, so folding that entry would leave the plan
with no automatic path to retirement ever. It stays in the live log until the chunk
closes. That blindness is a prawduct limitation rather than a Hallucinote one and is
filed upstream; the release doc now names the manual recovery
(`archive-plan --state completed --release vX.Y.Z`) for anyone who hits it.

Also corrected while here: the release checklist still told the operator to write
`status=shipped | release=vNEW`, and `status=` has been RETIRED since the derived-view
regenerator was removed — no gate, view or lint reads it, and the change-log header
documents it as a key not to write on a new entry.

## 2026-09-12 — One bar ruler: the arrangement places against the meter map

<!-- prawduct: type=feature | scope=meter-map-ruler -->

#566, and #567 with it. Hallucinote carried **two bar rulers**, and the schema
said so outright: `map` — a position resolved through `time_signature_map`,
which is how push resolves every bar position — and `uniform` — bars
accumulated against ONE `beats_per_bar` by `hallucinote.arrangement`, which
never read the map. They agree until a meter change, and `Arrangement`'s own
docstring predicted the failure it could not fix: in a 4/4 song turning 7/4 at
bar 9, the authoring class put bar 13 at beat 48 and push put it at 60.

On `alien` that was not hypothetical. One hand-placed 7/4 bar at 86 put an
instrument in the wrong place, and the song was rescued by spelling every
downstream section as `bar N + 0.75` against a 4/4 map — 89.75 and 113.75 for
chorus3 and the outro, which resolve to the right absolute beats and to the
wrong bar numbers forever.

**The deliverable was never a meter system.** The DB has accepted an arbitrary
map since #221 and push has always walked it. It was retiring the second ruler.

**`hallucinote.meter` is the one ruler**, a leaf module importing nothing else
in the package — which is what lets the authoring side and the sync side share
it without either depending on the other. `MeterMap` owns every bar↔beat
conversion; `sync.geometry` keeps its row-shaped signatures and delegates the
arithmetic. Extracting it fixed a latent inconsistency the two sides had between
them: the forward walk took the first map point's meter for the bars before it
while the inverse assumed 4/4, so on a map with no bar-1 row the pair were not
inverses. They are now, and a test says so in both directions.

**The arrangement declares the song's meter** — `Arrangement(meter="7/4")`,
`meter_change(at_bar=86, meter="7/4")`, or `section(..., meter="7/4")` as sugar
for a point at that section's start bar. A meter persists until the next point,
because that is what a map means; a borrowed bar is two points, not one, and the
docstring says so with that example. `plan()` walks the map, `PlacedSection`
carries `start_beat` and `length_beats` resolved through it, and
`beats_per_bar=` survives as the scalar spelling of the bar-1 default because a
song passes it.

**`materialize()` writes the declared map and then refuses to disagree with the
song.** The check runs BEFORE the write, and the reason is the bug the test
caught: `add_time_signature_point` UPDATES the row at a bar it already holds, so
an arrangement declaring 4/4 at bar 1 would have silently overwritten a song
declaring 3/4 there and read back perfect agreement. Every point the song
already holds must be one this arrangement declares, identically. Nothing in the
tree writes `bar_ruler="uniform"` any more — a test greps for a writer and
expects none — and the push planner's detector keeps it as provenance on rows
written before this.

**The read side landed with it**, per the BOTH-SIDES rule. The cost was far
below the 138 `beats_per_bar` call sites #566 sized it at, and the reason is
worth recording: most of those are not the song's ruler. The 74 in `generators/`
are a *pattern's* bar length — a per-call parameter a 7/4 bar should be able to
set freely. What genuinely mis-graded an odd bar was the four arrangement
bridges (three of which became correct for free once `PlacedSection` carried
beats) and one strong-beat predicate, which now reads the bar the note is in:
a 7/4 bar's strong beats are its 1 and its 4.5, where `start % beats_per_bar`
called its beat 4 strong because 4 divides the *song's* bar length.

**MIGRATION — `hallucinote.melody` breaks, deliberately and without a shim.**
`SectionMelody.beats_per_bar` (a float) becomes `bars` (a `BarGrid`), and
`analyze_harmony_fit(..., beats_per_bar=)` becomes `bars=`. Four songs in the
separate `hallucinote-songs` repo construct `SectionMelody(...)` directly and
none passes either keyword — every one relies on the 4/4 default, which
`bars=None` reproduces exactly — so nothing needs migrating today. A song that
does pass one changes:

    SectionMelody(..., beats_per_bar=n)
    ->  SectionMelody(..., bars=MeterMap.uniform(n).grid_for(start_bar, end_bar))

No compatibility shim: a scalar cannot say whether 3 beats is 3/4 or 6/8, and
accepting one back would re-admit the ambiguity the grid exists to remove.

One behaviour the grid had to be taught: `start % beats_per_bar` extrapolated
past the end of a section forever, and a grid that stopped at its last bar line
would silently re-grade any note overhanging the section's declared length —
which nothing filters, so overhanging notes are ordinary. The grid continues
the last bar's own meter instead.

**#567 — the alert stopped advising despair.** `plan_push_time_signature_map`
is the one place Live's meter reach limit is stated, and its advice — "the felt
meter has to live in note placement and accent" — predates #221 and was the
opposite of what the owner actually did for `alien`. It now says playback is
unaffected (every position is authored in absolute beats, which is the unit Live
anchors content in), names what is actually lost (Live's ruler and metronome),
and lists each non-bar-1 point as `bar N -> num/den` in bar order as an offered
hand-add. The reach limit itself is still stated, on the same channel — and so
is the open question: the alert says in as many words that whether inserting a
meter change leaves already-placed content where it is has not been checked
against a real set, and names the two-second check. It is the one place this
reaches a human, so it may say what is known and not what is assumed.

**One assumption is unsettled and is enqueued, not waived.** R1 rests on Live
anchoring arrangement content in beats, so that adding a meter change relabels
the ruler without moving what is placed. It gates the *advice*, not the
placement — the engine is correct in absolute beats either way — and
`operator-verification.md` METER-0912 is the two-minute check against `alien`'s
own set.

**Not in this branch, deliberately:** re-authoring `alien` on the map. It is
#566's last acceptance criterion, it lives in the separate `hallucinote-songs`
repo, and the owner declined it here.

**What the cumulative review changed, beyond paperwork.** Two findings were
worth the round. The first: the bundle moved the ruler in `src/` and amended the
design artifacts, and left every document that *instructs* the composing agent
still describing the two-ruler world — `docs/song-authoring-conventions.md`
(cited by seven skills) told an author "there is no setting that makes them
agree", and `skills/song-new` told it to carry the meter as felt groove. A
composing agent reads those, not the code. Swept.

The second: the R4 guard was point-in-time. `materialize()` checks map agreement
when it runs, so meter written AFTER positions exist was unguarded — and worse
than before this change, because those rows now carry `map` and push's
divergence detector drops `map` rows by design, where the same song's rows used
to say `uniform` and raise. Closed where the map changes rather than where the
positions are written: all three `time_signature_map` mutators — add, update and
remove — warn when a meter write actually moves an existing position's resolved
beat. The guard asks whether beats MOVE, not whether the map was touched; the
first cut asked the cheaper question and fired on four existing tests, which is
what a warning every build prints looks like before you catch it.

It covers all three because the finding was a CLASS and the first fix covered
one member — which the verify pass said out loud rather than passing.
`update_time_signature_point` has a live caller in `sync.pull.mix`, so an
`/ableton-pull` that changed a song's bar-1 meter would have re-timed an already
authored arrangement down the path nothing watched. That is why the guard takes
the RESULTING map rather than a point: a removal and a numerator edit are
ordinary members of it, not special cases.

## 2026-09-09 — A sample is now something the music can be derived from
<!-- prawduct: type=feature | scope=SMP-6V2K-W2 | release=v1.9.0 -->

SMP-6V2K wave 2, built by eleven parallel delegates on a file-disjoint partition and three
more in a second wave, integrated on `plan/smp-6v2k-w2`. What a song can now do with a
sample beyond placing it: **keep it** — `hallucinote asset add` normalizes a file under
`assets/sources/` and records its provenance in `assets/manifest.json`; `derive(line, ...)`
in `build.py` runs a recipe (trim, fade, normalize, reverse, pitch shift, stretch-to-bars,
chop-at-onsets, carve / vocode against a symbolic or measured reference) into a
content-addressed cache under `assets/derived/`, so a `reverse=1` row places the reversed
file in the session and the arrangement; **hear it** — a second audio front door
(`audio/sample_io.py`) and feature streams in seconds mapped to beats through the clip's
placement (F0, formants, energy and spectral descriptors, onsets and phrases), detectors
with musical gates, a follower generator that turns a contour into a part with the key as
a parameter, and `hallucinote sample-lens` / `/sample-lens` rendering the reading against
bars; **play it** — a Simpler row's `audio_file` is assigned on push (`assign_sample`, a
new `ableton_device` action; the wire fingerprint flipped) and captured back; and the mix
report can carry a per-turn speech-over-bed measurement (`speech_track=`), numbers only
under the 2026-08-10 analyzer-freeze ruling. Wave-1 leftovers closed: pull links the
audio clip it ingests (#507), the clip mutators refuse slot 0 (#473). Deferred at
dispatch: source separation (#266). The Live session (sampler, reverse, the #509 and
Sampler probes, the first hearing) RAN on 2026-09-09 against Live 12.4.5 —
`operator-verification.md` has it box by box and `lom-probe-results.md` rows
21-31 hold each verdict with its literal response. Sampler assignment and its
idempotence, the hand-drop capture round trip, and reverse in both the session
and the arrangement all passed. Two things did not and are recorded as open:
the symbolic carve was never pushed, and the first hearing's musical result was
not accepted by the operator ("it does not really read as tracking") — the
pipeline ran end to end on real material, the music did not land. R6.2 was
decided by ear: **Rubber Band**, which commits the R4.3 path to a non-Python
binary dependency. The CLIs shipped are `asset`, `derived`, `sample-lens` and
`stretch-ab`.

`SCHEMA_VERSION` does not move (D17): `SectionReport.intelligibility` defaults to `None`,
so a reader written against `"1"` still loads a report that carries it and still means the
same thing by every field it already knew. The bar for a bump is a change to what an
existing field MEANS, because bumping makes every existing report un-diffable
(`compare.ensure_comparable` refuses across versions).

One-time cache churn to expect: a file derived through `derived.derive` or a
`Recipe` before this landed was addressed without its reference fingerprint, so
it now resolves to a different address and the old file becomes an orphan.
`hallucinote derived prune` will list a long set the first time after this
change — that is the fix working, not a defect, and every file in it is
regenerable from its source and recipe.

`hallucinote derived prune` reads what the song's clips and devices point at, which is a
mixed set — a song references its ingested sources as well as its derived files — so an
addressed path naming nothing in the cache keeps nothing rather than raising. It refuses
outright when it cannot read the song's DB at all: an empty reference set is
indistinguishable from a complete one at the point where it would condemn every file in
the cache, and only one of those is an answer.

Tests consolidated: `test_reverse_is_refused_loudly_but_the_clip_is_still_placed` into
`tests/unit/sync/test_push_clips_reverse.py`, which pins the contract that replaced it;
three fixtures that used `slot=0` incidentally now use 1. `recipes.prune`'s contract
changed deliberately: it raised on an addressed path that named no derived file, which
contradicted its own docstring and made the CLI traceback on any song with a source.

## Older entries

Everything shipped in **v1.9.0 and earlier** lives in
[`change-log-archive.md`](change-log-archive.md), verbatim and unedited. It was moved
there, not deleted — git carries the full history either way. The release an entry
names, not its date, is what says where it lives.

**This file resets at every release.** The roll is the LAST act of the release
procedure's step 3 — after `plan-backfill` and `check-releasability` have read the tags
they need — and it moves *every* entry carrying a `release=` key, leaving this file
holding just its header plus whatever is release-pending. So the size of this file
measures **unreleased** work, which is what makes the `oversized_file_threshold_kb`
nudge worth listening to. See `docs/release-process.md` → step 3, *Roll the log*.

**Nothing release-pending is ever archived.** An entry with no `release=` key IS the
release-pending marker (see the format note at the top of this file), so the roll only
ever moves entries that already name the release that carried them.

One deliberate exception is held back by hand: **`scope=SMP-6V2K-W2`** is tagged
`release=v1.9.0` but stays above, because its build plan has an unticked
operator-gated chunk and `plan-backfill` reads `scope=`/`release=` out of THIS file
only — folding it would strand the plan with no automatic way to retire it. It rolls
once that chunk closes.
