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

## 2026-09-09 — The audio path ran against Live, and the one silent replace it found now speaks

<!-- prawduct: type=bugfix | scope=SMP-6V2K -->

SMP-6V2K wave 1's live clauses are discharged on Live 12.4.5 (`.prawduct/operator-verification.md`
→ SMP-6V2K wave 1, box by box; `capability-truth.md`'s audio row now says live-verified). The
run surfaced one defect, fixed here: an unlinked audio row pushed into a slot Live already holds
a clip in — the seam a pull-ingested clip falls through, since pull writes no link (#507) —
plans `create(replace=True)`, whose delete happens inside the handler, and said nothing about
it. The code comment and `capability-truth.md` both claimed the cost was stated in the create's
purpose; purposes never reach `execute`'s output. `plan_push_clip` now alerts on the operator
channel whenever the probe shows the slot occupied, naming the clip Live holds, the file it is
rebuilt from and the warp markers that do not survive; an empty or unprobed slot stays silent.
Two planner tests pin both halves; the alert was seen on a live push.

## 2026-09-09 — Push acts on the probe's verdicts: a re-pointed sample is recreated with its ride, and an envelope-hosting audio placement duplicates

<!-- prawduct: type=feature | scope=SMP-6V2K -->

The two `plan.blocked` refusals chunk 03 shipped pending the Live probe are gone, replaced by
the rule its recorded verdicts license (`lom-probe-results.md` rows 16-17). In the clips phase
a linked audio row whose `audio_file` changed — or whose slot Live reports as holding a MIDI
clip — now plans one sequence: an explicit `delete` (new ack-only key `clip_delete:`), the
`create` at the same slot, the full conform, then every envelope the row hosts written again,
because `Clip.file_path` is read-only, a create into an occupied slot is a hard error, and a
recreate drops the clip's envelopes. The re-emit reuses the envelopes phase's own planner
through a new per-clip entry point (`plan_push_envelopes_for_clip`, over
`envelope_hosts_by_clip`) rather than a copy, so the route table has one home; the recreate
is announced as an alert. In the arrangement phase an audio placement whose source clip hosts
an envelope takes the duplicate-onto-cleared route exactly as a MIDI one does — the duplicate
carries the ride off an audio session clip, and the conformed session clip with it, so the
per-placement conform gap stops firing for those rows and keeps firing for envelope-free
direct creates. Only envelope-hosting rows duplicate: the extent gap is route-independent and
filed as #509 rather than widened into here. The MCP handler's teaching-error mapping
gains Live's third path shape (`Please provide an absolute path`), which flips the wire
fingerprint — re-vendor before the live checks. `capability-truth.md`, the sync-boundary
contract (phases 6 and 13) and `operator-verification.md` (chunk 03's live clause re-queued
over the two new paths) track it; nothing in `sync/push` cites chunk 01 as pending.

The cumulative review's fixes landed as one batch. Pull now rules an absent audio clip or
placement on its **link**, not its kind: a linked one was in Live and is a real deletion, an
unlinked one may be a push refusal (sample not on disk) and is kept and reported — the
session and arrangement passes had reasoned in opposite directions. The arrangement phase's
extent gap and untouched-audio-track summary moved from `notes` (the channel the executor
discards) to one `alert` per phase, so the operator actually sees what the records claimed
they did. The sample-resolution chain, the audio create call and the sub-plan merge each got
one home (`resolve_authored_sample`, `_audio_create_call`, `PushPlan.absorb`); a duplicated
path helper was deleted; the set_property tip stopped offering a Simpler Reverse parameter
the probe found does not exist; README, known-issues and the pull skill stopped claiming a
working round trip the capability table rates ◐, and now say a pulled-in clip is *staged*
into the regenerable DB rather than made source. #504's in-wave fix is recorded as such;
wave 2 and wave 3 are filed as #511 and #510.

## 2026-09-09 — The probe session settles the reverse contract and the recreate semantics

<!-- prawduct: type=research | scope=SMP-6V2K -->

SMP-6V2K chunk 01 ran against Live 12.4.5 through the shipped `ableton_probe` bridge, and
every question the wave had left open now has a recorded call and a literal response
(`docs/research/audio-first-class/lom-probe-results.md` rows 14-20, raw records in the
JSONL). A Live `Clip` has no reverse, and neither does Simpler — its `reverse()` is a
destructive method that writes a derived file — so `clips.reverse` materializes only as a
reversed derived asset, which the schema comment and design D6 now say. The warp-mode map is
pinned by the one gap Live leaves (REX refused on a WAV). Creating into an occupied slot is a
hard error, a delete-and-recreate drops the clip's envelopes, and `duplicate_clip_to_arrangement`
carries a ride off an audio session clip exactly as off a MIDI one — a control duplicate
without an envelope was run so the `automation_state` flip could be trusted. Live also
checks path absoluteness before existence, a third error shape row 1c never saw.

Two things fell out of running the write path instead of reading about it. Simpler's sample
assignment via `replace_sample` and its `Sample` surface are recorded for wave 4 (#330), and
`ableton_probe(set)` turned out unable to write an int from this client — its untyped
`value` arrives as a string — which is backlogged as #508 with a repro. The two push refusals that
cited this chunk are now **chunk 07** in the plan; they stay in force until it is built, and
`capability-truth.md` says exactly that.

## 2026-09-09 — A sample is song material: audio clips place, conform and round-trip

<!-- prawduct: type=feature | scope=SMP-6V2K -->

Audio clips reach Live. An audio file referenced from `build.py` places into a session
slot with its warp mode, transpose, gain and markers as authored, and into the arrangement
as a placement; a clip dragged into Live by hand comes back into the song's source on pull,
in a portable path form; and a volume ride or send throw authored under an audio clip
pushes, because an audio host now routes exactly like a MIDI one. The DB has modeled all of
this since CLP-AUD1 and the LOM calls were probe-confirmed on 12.4.1 — this wave is the
wiring between them. Closes the `audio_path_deferred` no-op, the two push refuse-loudly
paths, the pull refusal, and the `refused_audio` envelope route.

**The read half was the gap nobody had noticed.** `list` reported a clip's name and length
and nothing else — no discriminator, no file path, no warp state — so pull could never have
ingested audio at all. Found by reconciling the plan against its own requirements before
building, which is the one place that gap had no owner: it sat at the far end of the
dependency chain, in a chunk whose builder would have had no authority to change the wire.

**What it deliberately does NOT do**, because guessing would be worse: re-pointing a clip
at a different file, and an arrangement placement whose clip hosts an envelope, both refuse
loudly and name what is unknown. `Clip.file_path` is read-only, so a re-point is a
delete-and-recreate, and whether a recreate preserves the clip's envelopes has not been
probed — a recreate could drop an authored ride, and re-emitting one "just in case" could
double a ride that survived. The arrangement copy also carries no conform: Live's direct
arrangement-create takes no properties and the planner cannot address the new clip until
after the call returns, so the run reports that gap rather than implying a conform it did
not apply.

**Nothing regresses the MIDI path**, and that is measured rather than asserted: a
concurrent song session pushed a pure-MIDI set through this branch's engine — 58/58 clips,
116/116 arrangement placements, `verify-arrangement` faithful with no orphans. Both
rewritten modules met a real set. The audio path itself has NOT been live-verified, and
`capability-truth.md` says so: its new audio row ships at partial, not full.

Also corrected here, because they had quietly become false: four surfaces still describing
the refusals this wave removed (the agent-facing `gaps.md`, `terminology.md`, `README.md`,
`song-authoring-conventions.md`), `authorship-model.md`'s claim that Live won't create
session audio clips, and `schema.sql`'s promise that `clips.reverse` materializes at push —
Live exposes no settable reverse at all, so the clips phase refuses a row that sets it.

Deferred with citations rather than carried: #504 (the arrangement integrity assert's
blindness to a dropped audio placement — fixed here, since this wave made that path
destructive), #505, #506, #507.

## 2026-09-09 — Doc deep-links: the parity check now covers every link, not one file

<!-- prawduct: type=bugfix | scope=docs-hygiene | status=shipped -->

`test_every_song_workflow_deeplink_resolves` only validated links whose target
was `song-workflow.md`, so a heading renamed in a design artifact left two
backlog `refs:` pointing at nothing and the suite stayed green. It is now
`test_every_markdown_deeplink_resolves` over every relative `*.md#anchor` link in
the repo, plus a sibling for the bare `path/to/doc.md#anchor` form the backlog's
`refs:` field uses (no link syntax, so the first check cannot see it).

The slugger was also wrong in a way that would have hidden a real break: it
collapsed whitespace runs, but GitHub emits one hyphen per space. Dropping an
em-dash from `Foo — bar` leaves two spaces and GitHub's anchor is `foo--bar`, so
the old helper both rejected correct links and would have accepted links GitHub
resolves to nothing.

Four dangling references fixed: two backlog `refs:` anchors, `docs/faq.md` →
`README.md#requirements` (no such heading), and
`docs/song-authoring-conventions.md` → `performance-model.md#references` (the
heading is numbered). Also corrected the README's claim that a mid-song
tempo/meter change is refused at the call site — it is authored fine and warned
about at push — and restored a missing `---` rule in the conventions page.

## 2026-09-09 — Meter is a projection concern: the DB records what the song IS

<!-- prawduct: type=bugfix | chunks=01 | scope=tmp-7b3x | status=shipped -->

`add_time_signature_point` and `update_time_signature_point` refused any
`start_bar > 1.0`. The stated reason was a Live limitation — Live 12.4's MCP has
no `song_signature` automation target_kind, so a within-song meter change cannot
reach Live. The consequence was that **the DB could not record that a song is in
7/4**, because of what the renderer cannot draw.

**The ruling, from the owner:** *the song itself is 7/4 or whatever; if we have
to represent it as 1/4 or 1/8 in Live, fine.* A song's meter is a property of the
authored work; Live's ability to render it is a materialization detail. So the
guard was in the wrong layer — the same lesson the arrangement redesign already
applied: the DB holds the authored truth, Live is a projection of it, and
projection limits are enforced where the projection happens.

**What changed.** Both refusals are deleted; `_require_bar_floor` (bars are
1-based) stays, and so does the schema `CHECK (start_bar >= 1.0)`. Nothing else
had to move: `start_bar` was already a float, and every consumer of the map —
`_split_bar`, `_position_bar_to_beats`, arrangement verify, the analysis
handlers — already reads multi-point maps through meter-aware geometry. The
planner tests had been reaching past the mutator with a raw INSERT to prove it;
that helper is retired.

**Where the limit is stated now.** `plan_push_time_signature_map` pushes the
bar-1 row and reports the rest — and reports it on the channel the operator
actually reads. The first cut used `plan.warn`, which appends to
`PushPlan.notes`, a field documented as diagnostic-only and never drained by the
executor; a mutator exception the author could not miss had been replaced by a
message nobody sees. It is a `plan.alert` now, landing in the push report, and
says what is lost and what is not: Live's ruler will read the bar-1 meter for the
whole song, the DB still holds the true map, and the felt meter has to live in
note placement and accent. Tempo's identical non-bar-1 skip was promoted with it
— the same silent drop, and asymmetry there would have been indefensible.

**A hazard the guard had been masking, now surfaced rather than inherited.** Two
bar rulers exist in this codebase: push translates bar positions through the
meter map, while `hallucinote.arrangement` accumulates whole bars against one
uniform `beats_per_bar` and never reads the map. They agree only while the map is
bar-1-only — which the guard had guaranteed. Push now DETECTS it, in the two
phases where a bar position actually becomes a Live beat: the arrangement and
cue planners run `uniform_bar_math_divergences` and alert only on the placements
whose two translations differ, naming the count and both beat positions. A
detector that fired on the mere presence of a meter change would have been
identical noise on every correct odd-meter song, so it discriminates rather than
announcing. Closing the divergence itself is `ARR-4M3T`'s (a meter-aware
`Arrangement.plan()` and meter-aware lenses); getting a declared map to actually
materialize in Live is `TMP-4J6Q`'s. Neither closes the other, and this change
closes neither — it stops the model lying about what the song is.

Unblocks the tour demo song's v2 take, whose chorus is in true 7/4, and makes
`/song-new`'s meter exit criterion satisfiable: the meter row now resolves
DECIDED instead of UNDECIDED-owned-by-the-engine.

(`backlog TMP-7B3X`)

## CAPSPAN-491 — a capture that does not span what it declares now says so

<!-- prawduct: type=fix | scope=CAPSPAN-491 -->

A peer session reported that one render of `songs/alien` came out with every
stem shifted about a beat, and that nothing in the analysis pipeline noticed:
the manifest said `status: ok`, and the mix report attributed a reverb peak to
the beat *after* the one it landed on.

**Why nothing noticed, which is the interesting half.** `BeatSampleMap` maps the
declared beat span onto whatever sample count it is handed and rescales. That is
deliberate — its docstring says the rescale exists so "a global tempo offset
between the DB `tempo_map` and what the render actually played can't shift
boundaries". It is a good property against a tempo mismatch and an
indistinguishable one against audio of the wrong length. The map is not the bug
and is unchanged; the excess is now measured before the rescale absorbs it.

`measure_capture_span` compares the captured duration against the span the
manifest declared, and a mismatch beyond a quarter beat emits a
`capture_span_mismatch` finding. The numbers land in the report's `alignment`
block on the passing path too — a check that only speaks when it fails cannot be
told apart from one that never ran, which is the failure being fixed.

**Three things measurement decided that a reading of the report would not have.**
Three real captures of the same song were measured first: the defective one ran
1.06 beats long and the two healthy ones sat inside 0.05, which is what makes a
quarter beat a bright line rather than a tuned threshold. Within *every* capture,
healthy ones included, the returns run up to 0.38 beats longer than the master —
the known independent-`sfrecord~` tail spread — so the check reads the common
(post-trim) length and a per-surface check would have flagged all three. And the
finding claims only what length can support: a capture that armed early and one
that disarmed late produce the same number, so it never says "started early",
though that is what the evidence in the report suggests.

**Where it declines, and why that is not timidity.** The comparison is against
the *declared* tempo, and push materializes only the bar-1 row today — Live plays
the whole song at that one value — so wherever the declared tempo differs from
it, the declared duration is not what was rendered. The check refuses there and
names the push gap, rather than reporting it as a bad capture.

That gate asks about the **render**, not the score, and it took a round to get
right. A first version asked whether the declared tempo was constant across the
captured span, which accepts a song declaring 90 bpm at bar 1 and 124 from beat 8
rendered from beat 16: declared-constant at 124, actually played at 90. It would
have compared real audio against a duration nobody performed and reported the
push gap as a broken capture — in the one lens the mix-review skill tells the
reader never to hedge. The predicate now takes the bar-1 bpm and requires
the declared tempo to agree with it from beat 0 through the span's end —
stricter than the span alone needs, and deliberately so, because the error it
gives up is a false decline and the one it refuses is a false alarm.

It also refuses on a missing tempo map, on a malformed manifest whose
declared span is non-positive, and on a capture starting before the song's first
tempo point — `declared_span_seconds` will not reuse `BeatSampleMap`'s constant
fallback, which cancels in a rescale but would be a fabricated duration here and
would manufacture a finding on every song not at that constant. **Each of the
four declines carries its own reason** in `skipped_analyses`: they send an
operator to four different places, and a shared message would replace the silence
this work removes with a wrong answer, which is worse.

**One refusal will go stale, and saying so is the point.** The variable-tempo
guard reads the DECLARED tempo, not what the renderer can honour, so it does NOT
retire itself when variable-tempo rendering lands — every such song would keep
declining and keep blaming a gap that no longer exists. An earlier draft of this
entry called it self-healing; the review caught that the code does not do that.
The obligation to delete the guard is written where whoever lands that capability
will meet it, rather than asserted as automatic.

The beats-to-seconds integration is now shared by the map and the check, because
two integrators disagreeing about how long 515 beats is would produce a finding
that contradicted the section windows in the same report.

Verified against the reported capture itself, not only fixtures: it produces the
finding at 1.06 beats and the healthy capture beside it produces none.
`SCHEMA_VERSION` does not move, and three things shipped under that call rather
than the two an earlier draft of this entry counted. Two are plainly additive: a
new `Finding.kind` extends no enumeration, and the `alignment` block gains a key.
The third — re-keying the `skipped_analyses` entries below — is **not** additive,
and was held to the same version deliberately after checking what could read it:
`compare.py` never touches the field, the MCP handler never emitted the old key,
and no checked-in report carries it. Bumping the version would make every
existing report un-diffable (`compare.ensure_comparable` refuses across versions)
for no consumer's benefit.

One seam that call leaves open, worth knowing before reading an old report:
`capture_span: null` means the check declined and `skipped_analyses` says why,
while the key being **absent** means the report predates the check entirely. Same
schema version, different meanings — the skip entry is what tells them apart.

**One thing found on the way.** Skip entries are selected by `kind`, and
consumers index it unguarded — but the render-integrity and imaging skips were
keyed `analysis` instead. They never reached a real report only because the MCP
handler happens to enable both lenses, so the inconsistency sat one default away
from a `KeyError` in every reader of a report produced by a direct
`analyze_mix` call. Copying the wrong key for the new entry is what exposed it.
All three are `kind` now, and a test walks every skip the pipeline can emit
rather than the few any one test happens to trigger.

Detection only. Correcting the offset, and the Live-side reason `sfrecord~` armed
early, stay open on #491 — both live in the fingerprint-bearing render handler
and would force a re-vendor.

## JANITOR-2026-09 — first Norm Health sweep, and the bookkeeping that had fallen behind the work

<!-- prawduct: type=chore | scope=JANITOR-2026-09 -->

The survey found a codebase in good order and bookkeeping that had fallen
behind it. Six TODO markers, all deliberate scaffold placeholders; every
relative link across 26 docs resolving; no dead top-level modules; backlog
groomed with 0 stale and 0 unstaged. What had accumulated was records, not rot.

**Plans (Chunk 01).** `plans/` held 51 entries and had archived 4. Forty-seven
were archived here (46 plan directories plus the EXECUTION-ORDER wave doc), and
the Critic round added six finished `build-plan-*.md` at the artifacts root that
sat outside the same lifecycle — 53 units in all. Eight were superseded, each
naming what absorbed it; the rest completed. (An earlier draft of this entry
said "50, 39 completed, 11 superseded" — the review caught it. The counts here
were derived from the tree, not carried over from that draft.) Classification was per-plan because a mechanical read gets it wrong
in both directions: NODE-ADDR's boxes are unticked while its text says DONE +
LIVE-VERIFIED, and ENV-9P4T uses a `[~]` box no box-counting regex matches, for
a chunk its own Live probe invalidated. Every superseded plan's open work was
confirmed to hold a backlog id BEFORE archiving — archiving a plan whose
remainder is untracked buries it. `build-plan.md` was deliberately left live
(gitflow, merged-but-unreleased) and now says so.

**Norms (Chunks 02-03).** Ten measured: six clean, four with distance, split
evenly between statement drift and code drift — the finding that a sweep must
ask which side moved, now a learning. Statement drift: the raw-SQL norm narrowed
to writes (owner ruling R1) with markdown_refs' projection rebuild recorded as a
bounded exception; the `sync.*` row restated to planners-vs-executor, matching
the contract artifact that already modelled it. Code drift: `kit.py`'s db import
inverted into a new `hallucinote.kits` loader, with `Kit.from_device` kept as a
one-major alias because it is a published authoring API (two ratified norms
collided; the owner ruled the seam), locked by an import-GRAPH test rather than
a source grep; and the future-annotations norm mechanized as ruff `I002`, which
is what its unacted-on "promote to a ruff rule" note should have been. `I001`
was measured at 248 files and deliberately left off as formatting churn (#487).

Two norms were closed on governance rather than code: the push-projection norm
had sat AGENT-PROPOSED / PENDING OWNER VETO for 19 days (ratified), and
`architecture.md` now states its altitude — runtimes and boundaries, not a
module inventory — naming the ten packages as bare pointers because the
briefing's staleness probe is a substring test with no way to declare a doc
deliberately module-free.

**Deferred, not dropped (Chunk 04).** #484/#485 the two cold branches carrying
real unmerged work, #486 whether the 17 raw-SQL reads should consolidate, #487
the ruff churn decision, #488 the two worthwhile artifact templates. #489 was
added at the PR-review gate: Chunk 04 also specified filing two findings upstream
to prawduct and neither was sent, so the reports are descoped to that item —
they cross an owner boundary, which makes sending them the owner's call and not
the sweep's. The chunk's own done-when is satisfied by the id, not by the tick.

**Baseline (Chunk 05).** `norm_health_last_run` and the first `norm_health:`
entry are stamped, so the next sweep reads a trend instead of measuring from
zero. That absence is why this one existed.

Suite green with no path argument at every chunk boundary and after the Critic round; ruff and mypy clean. Exact totals live in the evidence store, not in this prose, because a copied count drifts the moment a test is added.

## 2026-09-08 — The report learns to ask whether the audio is damaged

<!-- prawduct: type=feat | scope=render-integrity -->

Every lens in the mix report measured *musical realization against intent*.
Nothing measured whether the captured audio was **defective**. Across 23 modules
in `audio/` there was no clipping detection, no DC offset, no click or dropout
detection, no polarity check and no stem-vs-master reconciliation; the only
clip-adjacent number anywhere was the master's delivered true peak. The string
`click` appeared only as a *musical* term — the kick beater's 2-6 kHz band.

Four new lenses close that. `integrity.py` finds clipping, DC offset, dropouts,
clicks and truncated decays per surface; `phase.py` finds polarity inversions,
time offsets and per-band cancellation between surfaces; `imaging.py` gives
per-band correlation, width and image position; `reconcile.py` asks whether the
captured surfaces sum to the captured master.

This family is exempt from the analyzer freeze, and the reason matters: the
2026-08-10 owner ruling gates lenses whose thresholds *encode taste*, and a
sample discontinuity has physical ground truth. It is also the only family that
may name a defect as a defect rather than reporting against declared intent.

**It is upstream of the rest of the report.** A click reads as an onset to
`onsets.py`, so the timing and cross-rhythm lenses faithfully report a groove
nobody played; a dropout reads as a written level move; a truncated capture
reads as a short decay. `/mix-review` now reads integrity before any musical
number and treats a damaged surface's musical readings as suspect.

**Two false positives were found by running the lenses over a real render, and
neither would have survived to a listening test.** The clipping detector keyed
on amplitude — but captured stems are pre-fader float32, so a healthy part
peaking at +6.30 dBFS spends most of every cycle above full scale without ever
going flat, and it drew 7970 clip runs from undamaged audio. Clipping is a flat
top, not a loud one, and keying on samples pinned to one value takes that to
zero while still catching flat-topping at any level. Separately, a
cross-correlation always peaks somewhere: every uncorrelated stem pair reported
a confident-looking offset of tens of milliseconds at r ~ 0, which is two parts
sharing a downbeat rather than a device delay. `lag_correlation` now carries how
much of a lag reading to believe, because reporting coincidence as latency is
worse than reporting no lag at all.

Two delegates building different lenses independently reached for the same two
private helpers rather than write a second definition of "energy in this band"
and of the degenerate-correlation cases. Two arrivals at one seam is the signal
that these were public in all but name, so `attribution.band_energy` and
`stereo.channel_correlation` now say so. The unification is only partial and
deliberately so: `phase` and `reconcile` keep their own correlation conventions
because they answer different degenerate cases, and consolidating them would be
a behaviour change wearing a refactor's clothes.

**An independent review then found four blocking defects, three of them the same
shape as the two above — a threshold that is physically grounded but wrong for
real material.** `stem_gains` was being run through Live's fader curve a second
time, mis-levelling a unity fader by +6 dB and a −14 dB one by −20 dB while the
report asserted the levels were modelled. The discontinuity detector derived one
global sigma over a non-stationary signal, so any percussive part read as tens of
thousands of clicks — 32,752 against 31 real onsets on drum-like material; it is
now computed per 25 ms window. The new flat-top clipping rule had picked up a
false positive at the *opposite* end of the range from the one it fixed, because
its tolerance was absolute while a crest's flatness scales with amplitude — a
clean 20 Hz sine at −12 dBFS drew 32 phantom runs. And a zero-run gap was
accepted if *either* edge was abrupt, which made every musical rest a dropout.

Running the fixed detectors back over the finished song then found the last one,
which no synthetic fixture would have posed: a heavily-processed vocal produced
42,578 flagged steps inside 660 windows — about 65 per window, which is very
nearly every sample in those spans. That is one *region* of step-rich material,
not 65 defects, and distortion, bitcrushing and granular processing produce it
because it is the sound. Events now collapse to one region per window, which took
the drum stem from 638,099 to 4 and the vocal to 1,296 regions over 6.5% of its
length. No threshold separates "a splice" from "a texture" — that decision needs
the song's intent, so the lens reports the count and `/mix-review` reads it,
exactly as every other lens here works.

The lesson the plan recorded after the first real-capture pass generalized further
than it was written: being *exempt from the analyzer freeze* is not the same as
being *calibrated*. Physical ground truth belongs to the quantity, not to the
threshold placed on it.

`cross_correlation_peak_lag` also came out of the test tree, where it had sat
since the MVP behind a docstring promising a promotion that never happened,
leaving `alignment.py` pointing at a function in `tests/`.

## 2026-09-08 — Live plays from a position `current_song_time` never moved

<!-- prawduct: type=fix | scope=perform-start-position -->

Issue #471 opened as "a perform pass reports success and records nothing", and
the reporter closed it themselves with the mechanism: `song.current_song_time`
is the playhead, and `start_playing()` rolls from Live's **start playing
position**, which that write does not move. The LOM exposes no writable
property for the second — `CuePoint.jump()` is the one surface that moves it.

The two agree on a set nobody has listened to and part company the moment
someone presses play in the arrangement, so locate-then-play was only ever
coincidentally correct. On `songs/alien` the start position had drifted to ~351
while the arcs lived at 96-104: three passes in one day each seeked correctly,
read the seek back correctly, rolled from 351, exited the ramp loop on the first
tick already past the span, and returned a clean result. The divergence was
found by ear, from a reverb wash that did not match what the DB said was there.

**The settle-verify was not missing — it was answering about the wrong
property.** `perform_batch` already had a worker-thread poll on
`current_song_time` (PSH-4L6C), and it passed every time, honestly. That is what
makes this class hard to see, and it is why the fix has two halves rather than
one.

`handlers/_transport.py` is the first: `locate_start_position` moves the start
position by jumping to a cue at the target — the operator's own where one is
there, otherwise borrowing one (create, jump, delete) and reporting rather than
swallowing a locator it fails to give back.

**Borrowing writes to the operator's set, and that was the decision worth
weighing.** A locate now costs two Undo entries and shows a locator flickering
in the arrangement — a mutation nobody asked for, in a set that is somebody's
song. The alternative was to jump to the nearest cue at or before the target and
let each arc's window gate the writes, which mutates nothing. It was rejected on
cost: for an arc at beat 345 on a set whose nearest earlier locator is at bar 1,
that is a realtime pre-roll of several minutes per pass, on a mechanism whose
whole expense is already wall-clock. The borrow is bounded instead — one cue, at
one beat, given back in a `finally` so it survives a raise, and its failure to
come back is logged with the beat named. A third option, requiring the operator
to place a locator at every span they author, was not seriously considered: it
makes the tool's mechanism their problem. A cue that exists but cannot be
jumped degrades instead of falling through to the borrow path, because that
path's toggle fires at the same beat and a toggle where a cue already sits
DELETES it.

The second half is `require_playhead_within`, which judges where the transport
ACTUALLY rolled from. That one is mechanism-independent — it holds when the
locate is defeated by something nobody has seen yet — and it is why a wrong
position is now a loud error rather than silent divergence. Both callers hand it
a beat they already read (the ramp loop reads one every tick; the render reads
one for its engine pre-flight), so the guard costs no extra Live touch — and
both read it only once the transport is demonstrably rolling, because Live's
playhead mirror lags the audio thread and the first read after `start_playing()`
still shows the position the locate parked, which is the one value that would
make the check pass at the moment it must fail.

**The same two lines were in two more places.** `render.py`'s capture seeked and
played, and its engine pre-flight asks whether the transport ADVANCES — a
transport in the wrong place advances exactly as well as one in the right place,
so a render could capture minutes of the wrong section and report a healthy
capture. And `session.py`'s play note *told operators* that "seek then play
locates-and-plays: the render capture path relies on exactly that", which is the
false belief that cost the reporter six hours, shipped as documentation and read
at precisely the moment someone is debugging this. `seek` now moves the start
position too and says which method did it, so the read-back workflow that
diagnosed the bug is trustworthy.

A source-level test now fails on any handler that reaches `start_playing()` for
a positioned pass without locating first, with a two-entry exemption list for
the bare transport verbs. The mistake leaves no trace in the code that made it,
so it is checked rather than left to reviewers.

**Reporting, the other half of the issue.** `automation_state` cannot verify a
perform: it reads 1 whenever ANY lane exists on the parameter, so on every
iteration after the first it is 1 regardless of what the pass did. A parameter
with no prior lane failed honestly; one with a lane could not. Each arc now
carries a stated `outcome` (`recorded` / `unverified`) plus the reason, computed
where the pass happened, and the apply layer branches on that with the old two
field checks kept as the floor for a server predating it. `apply_push_results`
gains a `notes_sink` — a benign channel next to the actionable one, since the
returned warnings ride `.last-push-errors.json` and a per-arc roll-up there
would make a clean push look failed — and every arc gets a line naming its span,
its verdict and its write count.

**Not built, and why.** The issue's ask 1 (verify each arc by sampling the
parameter back across its span) was written before the mechanism was known, when
read-back shape was the only diagnostic available from outside. `updates_written`
is a direct count of what the pass wrote and the position guard catches the
failure before the ramp even runs, so it is filed as defence-in-depth rather
than built. Ask 4 (prefer the `session_clip` route wherever the span allows) is a
routing-policy change with real consequences the reporter names themselves —
`insert_step`-only, so a ramp must be authored as an explicit staircase — and
deserves its own design pass. Filed as #478 and #479; #479 should be read
alongside the already-open #474, which asks for the inferred route to be
surfaced at all.

**Verified against Live 12.4.2 the same day — and the verification found a
regression before it confirmed anything.** `song.record_mode = True` is Live's
Record BUTTON, and pressing Record starts the transport (beat 0 → 2.768 at
+1.0s → 8.402 at +1.5s). The fix as first written located AFTER the record-mode
settle, reasoning that arming was the last thing that could disturb the
playhead. Arming does not disturb the playhead; it starts it. So the locate
aimed at a moving target, could never place its cue — the toggle fires at the
transport's real position, so an imprecise one is refused by design — and every
locate degraded to `playhead_only`. The whole fix was inert while reporting
itself accurately: the first live pass wrote 21 values, recorded no lane, and
read back flat at 0.9000 on every beat.

Stopping between the arm and the locate is not the escape hatch either: a stop
DISARMS `record_mode`. The order is now quiet-the-transport → locate → arm, and
the arm rolls from the start position the locate just set, which is where the
pass wanted it. Two tests that encoded the old sequence were updated with the
measurement as their reason, and a third now pins locate-before-arm.

After the reorder, on the same set: a virgin parameter records and reads back as
a real ramp (0.315 → 0.859). Then the start position was poisoned to beat 104
the way a human does it — click late, roll, stop — and a second arc was
performed against that same, now lane-bearing parameter. It recorded, and the
read-back DESCENDS (0.834 → 0.204) where the first pass ascended, which is what
proves the second pass landed rather than the first still answering for it. That
is the exact case that silently did nothing three times in one day. The borrowed
locator came back every time (`cue_count: 0`), and the past-the-extent refusal
fires with its teaching message.

The reorder had one consequence the live run could not show, because every pass
there was single-arc: the initial gesture-open read the live playhead to decide
which arcs were already active, and with the transport now rolling since the arm
that read is `union_start` plus whatever the settle let it travel. An arc whose
span began inside that drift opened early, and `start_playing()` re-asserts
`union_start` a line later — so the ramp would write that arc's first breakpoint
value across beats it was never authored over. The read was only ever a proxy
for `union_start`; it now asks `union_start` directly, which is the question it
was always answering. The fake that catches it is the first one here to model
arming as a transport event rather than an inert flag — and a multi-arc live
round then confirmed it in Live: two arcs on staggered spans (32 beats and 16)
came back with 41 and 21 writes, a ratio that tracks the spans rather than the
union, and the later arc's parameter read exactly centred through its own span
start. An early open would have shown in both numbers.

The same reorder moved one more thing under the guard's feet, caught on review
rather than by measurement. The ramp's movement gate — the thing that decides a
read is evidence the mirror caught up — compared against the beat the LOCATE
settled at. Since the arm now rolls the transport away from that beat before
play, a stale first read reporting the pre-play position looked like movement
and retired the position check on the read that proves the least. The baseline
is now the beat read immediately before `start_playing()`, which is the only one
a stale read can equal.

Handlers changed, so the wire fingerprint flips: re-vendor and a full Live
quit/reopen precede any of this reaching Live. **The render capture path is NOT
covered by that verification** — same defect, same fix, but it needs analyzers,
OSC and written WAVs and none of that was exercised; nor was `songs/alien`
itself, only the mechanism on a scratch set. Both stay in
`operator-verification.md`.

## 2026-09-08 — The governance files stop growing without a ceiling

<!-- prawduct: type=chore | scope=governance-file-sizes -->

Two session-briefing advisories had been relayed unactioned for weeks:
`project-state.yaml` at 51 KB and `change-log.md` at 285 KB, both over the 40 KB
nudge threshold that every reader of them pays once per session. They look like one
complaint and are two different problems, so they get two different answers.

**`project-state.yaml` — the ceiling was wrong, not the file.** About 20 KB of its
51 KB is `technical_decisions` + `design_decisions`. That is the Reasoned Decisions
principle working: the more faithfully a repo records reasoning, the louder a fixed
ceiling complains at it. `oversized_file_threshold_kb: 55` raises this repo's ceiling
rather than cutting the reasoning.

**`change-log.md` — the file was wrong, not the ceiling.** An append-only log with a
year of history behind it should be *rolled*, not exempted. The 92 entries older than
v1.8.3 moved verbatim into `change-log-archive.md`; the live log keeps 13 entries
(50 KB), covering the last four releases and all four release-pending scopes.

**The one failure this could cause, and the guard against it.** An entry with no
`release=` key IS the release-pending marker, so archiving one drops its whole scope
out of the release gate *silently* — the work would never ship and nothing would say
so. The roll asserts before it writes that every moved entry already carries a
`release=`, and `check-releasability` confirms the result: 4 release-pending scopes
across 4 entries, unchanged. Nothing reads the archive — `lib/change_log.py` names
`.prawduct/change-log.md` specifically — so a tag in it is inert.

Rolling the log is now **step 1 of the release procedure**, not a periodic cleanup
somebody remembers; otherwise this recurs every few months. Reconciling that step
against the code exposed that it had gone stale in three ways: it told a releaser to
run `prawduct-hook stamp-merged` (deprecated and inert — it warns and does nothing),
to flip a `status=merged` → `status=shipped` key (retired; nothing reads it), and
published a tag grammar containing `chunks=` (also retired). The absence of `release=`
has been the only merged-not-shipped marker for some time. Step 1 now says so.

**`learnings.md` is deliberately left above the ceiling** at 60 KB. Its nudge points at
real, unwalked work — rule here, narrative in `learnings-detail.md` — and because the
threshold is repo-wide, raising it past ~58 would silence that as a side effect. The
key's comment says so, so the next raise has to decide that on purpose.

## 2026-09-08 — Two read-side lenses: psychoacoustic sharpness and drum-hit transient shape

<!-- prawduct: type=feature | scope=aud-lenses -->

Dogfooding `alien`'s listen turn left two by-ear complaints with no number in the
MixReport to reason over — "the high elements are a bit shrill" and "the kick is a
thud". Both now have one.

- **`timbre.sharpness_acum`** — psychoacoustic sharpness (von Bismarck / Zwicker
  weighting over Bark specific loudness) on every surface and section. A piercing
  lead reads higher than a warm pad at the same centroid; scale-invariant.
  Provisional 0.10 acum significance floor.
- **`per_section[].transients`** — per-part low-band (40–150 Hz) hit shape: rise,
  T20 ring, the attack window's sub / low / low-mid / click levels, and the two
  level-blind reads `click_minus_sub_db` / `low_minus_sub_db`. Estimators that hit
  their own boundary are censored and counted, never reported as measurements, and
  every part without a reading has a structured reason in `transient_skips`.
- **`compare_to.section_deltas`** — the timbre family per section on every surface
  the window measured (stems, returns and the master) plus transient shape per
  part, counted in the summary as `significant_section_delta_count`, so a
  "de-shrill chorus 3" or "sharpen the kick" edit is A/B-able where it was made.

**The lens found its own defect, which is the part worth remembering.** Used on
alien, `rise_ms` read 42 ms in verse 1 and ~16 ms in eight other sections off the
*same kick sample*. The kick had not changed — the estimator was bimodal. This kick's
low-band envelope has two comparable lobes 31.8 ms apart, and the rise was found by
scanning FORWARD from the search window's edge for the first 90 % crossing, so
whether the first lobe cleared 0.90 × peak decided which lobe was measured. A mix
edit that lowered every section's first lobe by the same amount flipped exactly the
two that crossed the line. Scanning BACKWARD from the peak fixed it; a second pass
found the same defect class one step later, where a censored rise left the attack
window anchored on the search window's edge and read band levels over 75 ms instead
of 30. Recorded as a learning: an estimator that reports the FIRST threshold
crossing is bimodal on multi-lobe material.

Build plan: `.prawduct/artifacts/build-plan-aud-sharpness-transients.md`. Six Critic
rounds (three cumulative, three verify-resolutions), the last clean.

## 2026-09-01 — Elicitation becomes a conversation: read the turn, build to the hearable unit, offer a hearing

<!-- prawduct: type=feat | scope=collab-turn -->

The owner's complaint was that the agent "does a poor balance of assisting the
user versus taking over and building too much before discussing" — the same
complaint they had made three weeks earlier. The first fix rewrote the opening
turn; the next take had the best opening turn in the evidence corpus and then
declared *"That's identity resolved. Scaffolding now"* while the user's answers
were still arriving. A failure that moves one exchange later is structural, not
a wording problem.

Five structural causes were diagnosed and are recorded in
`.prawduct/artifacts/collaboration-turn-model.md`, with a twenty-case evidence
corpus beside it. The load-bearing one: **two different complaints had been
collapsed onto one dial.** The June complaint was about *procedural* stops
("scaffold done, what next?"), and it became the loudest norms in the repo —
stop only on high-stakes decisions, the burden of proof for stopping is high.
The collaborative stance was then written as a *carve-out* to those rules, and
under pressure an agent obeys the hard rule and treats the carve-out as
optional. The agent named its own inversion: it *"asked permission for craft and
took authorship of identity."*

What changed:

- **"The user leads the creative project" is now the primary norm**, and
  stop-less is scoped to *procedural* stops. Not a carve-out — that shape was
  the cause. Both failures stay named: never stop to summarize-and-ask, and
  never build past a hearable unit without offering to play it.
- **Every turn is read before acting.** Six kinds — directing, reacting,
  exploring, asking, delegating, handing-off — and only two of them authorize
  building. Musing touches nothing.
- **The one-turn elicitation bound is retired.** `/song-brief` is a conversation
  that runs until the user hands off. The two failures the bound prevented (the
  stage that never converges, the turn that fragments) are now bounded by the
  hearable unit and the status offer. The three-state model and *a stage may not
  emit an unresolved gap* were right and are untouched.
- **Identity closes at hand-off, never by inference.** An answer that adds a
  noun is not a closure; silence on an asked item is still-thinking.
- **The brief gains an owner column** (*yours / offer me options / mine*),
  learned from the conversation rather than asked for, and is a ledger updated
  every turn.
- **A loaded prompt opens its domain.** A genre, a form, an era, an artist:
  unpack it, say what you take as read, ask the two or three that would change
  the song most. The checklist's "a reference collapses 5 other answers into
  one" framing is deleted — that compressor reading is what produces
  "run off and build".
- **Song work belongs in a songs workspace.** `init-workspace --check` now
  reports `governed_repo`, and both entry skills give a heads-up — never a
  block — before scaffolding inside a governed repo.

Verification is honest about its own limit: no test can judge a conversational
register. `tests/unit/test_collaboration_norm_parity.py` locks what *is*
mechanical — that no live surface promises the retired rule, that the vocabulary
is defined only in its sanctioned homes, that the brief template still parses
against the live validator — and an operator session is queued as the acceptance
test for the rest. The retired-phrase check matches over collapsed whitespace,
because the plain grep the plan specified could not fail: the phrase wraps
across line breaks, and did so in two of the files being swept.

Built by four parallel delegates in isolated worktrees with disjoint file
ownership; the delegation shape they used is now a pre-approved
`project-preferences.md` row. Three of the four independent chunk reviews
converged on the same finding — a file promising it did not restate the
vocabulary and then restating it — which made it the plan's defect rather than
any delegate's, and the plan gained a `definition` vs `rule` amendment.
## 2026-08-20 — Three post-sync advisories cleared: a merge driver, a triaged bug report, and a norm re-affirmed

<!-- prawduct: type=chore | scope=advisory-clearing -->

Housekeeping against the three advisories the session briefing had been carrying.

- **`.gitattributes` now marks `.prawduct/change-log.md` `merge=union`.** Every
  branch prepends its entry at the same offset, so a three-way merge conflicted on
  content that never actually disagreed and always resolved to "take both". The
  selection criterion is written into the file: union engages only where git would
  otherwise conflict, so what matters per file is whether "keep both" is right *at a
  collision* and whether a wrong answer is **visible**. The exclusions are recorded
  there too, because that second half is what does the work. `learnings.md` +
  `learnings-detail.md` were added and then **reverted** when the Critic found the
  visibility claim false: `audit-learnings` pairs the two by exact title and
  `_take_active_narrative` breaks on the FIRST match, so a union-duplicated heading
  makes a retirement run cut one block and silently orphan the other — against a file
  whose stated invariant is *never delete an entry* — and no doctor or janitor check
  pairs them, so nothing would report it. `operator-verification.md` is excluded for
  the same reason in a sharper form: its entries flip PENDING to PASSED in place, so
  union would leave one entry asserting both, silently, in the file `/prawduct:pr`
  reads to decide whether live checks block a release. `reflections.md` is gitignored
  and never merges at all.

- **The `incoming-bugs/` drop-box is empty again.** The 2026-08-10 MixReport report
  is filed as #465 — a fader-only level move is invisible in the mix report, via two
  mechanisms (a stale `master_fader_db` making `delivered_true_peak_dbtp` equal the
  bus number, and per-stem loudness / per-section masking being computed pre-fader
  without saying so in the report). Cross-linked to #253 and #397; the source report
  moved to `incoming-bugs/archives/` (the drop-box is gitignored, so that move is
  local only).

- **The arrangement-projection norm was re-affirmed, not retired** (`architecture.md`
  → Direction). Its `Why` cited ARR-PROJ (#350), which has since shipped, so the
  decay probe correctly asked for a decision — but the citation was *evidence for*
  the norm rather than work it was waiting on. The `Why` now carries the rationale
  with no tracked-work dependency, the provenance (#350 shipped 2026-06-22, #349
  closed) moved to `Retroactivity` where it belongs, and a new `Status: steady-state`
  line records the re-affirmation plus the one genuinely residual item: the flagship
  projection path has still never run full-scale against real Live, scheduled under
  #306. The Status line is marked **agent-proposed, pending owner veto** — the
  2026-08-10 batch above it was owner-ratified and this one was not, and the
  Statement is byte-identical to the ratified text, so a veto costs only that line.

## 2026-08-12 — README: the demo video embeds, and the owner's copy edits merge

<!-- prawduct: type=docs | scope=docs-launch-readiness | release=v1.8.6 -->

**The demo video plays inline.** `#329`'s conversion gap is closed: the README's
only demo was an `.mp3` link, which GitHub will not play inline, so a reader had
to download a file to hear anything. The 2:13 cut now leads *See it* as a player,
hosted on GitHub's user-attachments CDN at zero repo weight. Committing the
`.mp4` would not have worked — GitHub strips `<video>` pointing at repository
files and blocks `raw.githubusercontent.com` from serving video — and would have
spent a one-way-door slice of the 12 MB `docs/assets` budget for a download link.
Acceptance was verified rather than asserted: envelope correlation **+0.993**
against the stitched renders with matching RMS, the ±1024-sample per-state offset
correction measured at 0.80–0.95, and the caveat legible at three timestamps.

**The owner's copy edits merged from `main`.** `f10c92d` landed directly on
`main` against the pre-sweep, pre-rewrap README, so it collided with all three
passes on the branch. The copy was taken as authored; only mechanics were
reconciled (semantic line breaks, one trailing-whitespace line, the video block
kept above the punk-fate example their intro now leads into).

**Two owner decisions recorded so neither is re-litigated as a defect:**

1. **The README and the tour quote the punk-fate prompt differently, and both
   stay.** The README says "rhythm guitar, and vocals emulated by a lead
   guitar"; `docs/tour.md` quotes the session log verbatim as "lead guitar, and
   vocals on a staccato synth". The README's version describes what the song
   became — chapter 15 turns track 4 into a lead guitar — rather than what was
   typed. Flagged as a contradiction of the kind the launch-readiness pass
   existed to close; the owner ruled to keep both as they are. A future docs
   review should treat this as decided, not as drift.
2. **"What you end up with is an ordinary Ableton set you finish yourself" is
   deliberately gone**, though the launch-readiness pass added it to answer a
   question the FAQ devotes a section to. The FAQ still answers it in full.

Docs-only. Suite green at 5005 passed / 2 skipped.

## 2026-08-12 — The release process gains a GitHub Release step

<!-- prawduct: type=docs | scope=release-process-docs | release=v1.8.6 -->

**Six annotated tags, zero Release objects.** The ten-step release procedure
ended at *Verify*, so every cut since v1.8.0 produced a tag and nothing a person
landing on the repo would see. Found while checking whether `gh` could upload
the demo video; the repo had no releases at all.

Step 11 now covers it, and encodes four things learned doing it:

- **Draft first, always.** A published Release notifies watchers and is the most
  outward-facing artifact the process produces. A draft is invisible and
  deletable, so it gets reviewed before it exists publicly.
- **`--verify-tag`**, so a typo fails rather than inventing a tag pointing at
  nothing.
- A draft's URL reads `releases/tag/untagged-<hash>` until published — normal,
  and worth writing down before someone reports it as a bug.
- **Release notes are reader-facing positioning prose**, so the § Documentation
  & prose norm governs them. The v1.8.5 notes were written to it and checked
  against it.

Also recorded: a release asset serves from `github.com/.../releases/download/`,
which will **not** render as an inline player in markdown. Only a
`user-attachments` URL does, and obtaining one is a web-UI upload with no `gh`
equivalent — verified against the API, which 404s on the uploader endpoint.

v1.8.5 is drafted from the two change-log entries carrying `release=v1.8.5`,
with the 6.1 MB demo cut attached as an asset.

Docs-only. Suite green at 5005 passed / 2 skipped.

## 2026-08-12 — Semantic line breaks for markdown prose

<!-- prawduct: type=docs | scope=docs-positive-framing | release=v1.8.6 -->

**Owner decision, prompted by a fair question about the sweep.** The positioning
sweep produced a whitespace-only reflow commit — sentences got shorter, so
hard-wrapped paragraphs had to re-flow. Asked why the files were hand-wrapped
at all, the honest answer was that two conventions were in play and neither was
written down: `CONTRIBUTING`, `SECURITY`, `faq` and `tour` wrapped at ~70
columns, while `README` and `VISION` put each paragraph on one long line.

All six now use **semantic line breaks — one sentence per line**. A hard wrap
makes a one-word edit reflow its paragraph, so the diff reports a paragraph
where a word changed; one-sentence-per-line keeps the short lines an editor
wants and makes diffs word-accurate. Rendered output is identical, since
markdown folds single newlines inside a paragraph.

Applied mechanically, with two guards worth keeping: the transform **refused to
write any file whose word stream changed**, and it caught a real bug doing so —
an optional closing-quote class sat inside the split pattern, so `re.split`
silently ate the quote in `B."`. Each file was then verified token-identical
against its committed version. Code fences, tables, blockquotes, headings and
link-only lines passed through untouched, so the tour's quoted session
transcript and `build.py` excerpts are byte-identical.

The norm is recorded in `project-preferences.md` § Documentation & prose,
including the honest scope: the rest of `docs/` and `skills/` are still
hard-wrapped, and convert when next touched substantially — in their own
whitespace-only commit, never mixed with a wording change.

Docs-only. Suite green at 5005 passed / 2 skipped.

## 2026-08-12 — The prose norm's absolute reading, restored by owner ruling

<!-- prawduct: type=docs | chunks=C1,C2,C3 | scope=docs-positive-framing | release=v1.8.6 -->

**The norm was narrowed twice by the agent on the day it shipped; the owner has
now ruled on both narrowings.** *Write what a thing IS; never define it by what
it isn't* was ratified 2026-08-11 from the owner's own correction. Within hours
the agent narrowed it twice, each time immediately after a review round found
shipping prose that violated it — the textbook shape of amending a rule to fit
your own work. Both narrowings were recorded as pending veto rather than as
ratified, which is the only reason they were still reversible.

- **Narrowing 1 — REJECTED.** The "competitor/critic (banned) vs mechanism
  (fine)" test is withdrawn. The owner's original clause — *no "this isn't a
  Y"* — means what it says, whatever the sentence is describing.
- **Narrowing 2 — RATIFIED.** Naming prior art as lineage stays permitted;
  ranking this product against it remains banned. VISION's TidalCycles /
  Sonic Pi / Lilypond / DAWproject paragraph keeps its place.

**The owner also set the norm's scope, which had never been stated.** It governs
positioning prose — `README.md`, `CONTRIBUTING.md`, `SECURITY.md`,
`docs/VISION.md`, `docs/faq.md`, `docs/tour.md`. Reference docs elsewhere under
`docs/`, agent-read `skills/`, `.prawduct/artifacts/` and the frozen
`docs/archive/` sit outside it: in operating instructions the construction
disambiguates ("the list itself, not the wrapper") rather than defends, and the
absolute rule applied there would have cost precision across ~1,400 sites for no
positioning gain. Scope is now written into the norm so the next agent inherits
it instead of re-deriving it.

**What the sweep changed.** Every contrast-definition in the six in-scope files,
rewritten positively — the flagship "a long agentic workflow, not a chat"
(`faq.md`), "Ableton is the speaker, not the score" and "A diff is not '33 notes
changed'" (`VISION.md`), "Verified, not assumed", "Grit as timbre, not level",
"a preset name is a claim, not a measurement" and a section heading
(`tour.md`), "a cloned `build.py` is not data, it's a program" (`SECURITY.md`),
and the symbolic-review and cost lines in `README.md`. Most rewrites are the
better sentence, because dropping the foil forces the claim to be stated
outright.

**The test the sweep applied, recorded so it is checkable.** The banned form is
a *contrast-definition*: a sentence characterizing the product, a component or
the process by naming a **foil** — an alternative the subject is set against.
Plain negation names no foil ("Live isn't running") and stays. (The row first
carried a different test — whether removing the negated half left the subject
undefined — which the Critic showed to be self-invalidating: "Ableton is the
speaker" survives that deletion, so the test cleared the sentence the norm
bans. Replaced in every carrier the same day.) Four categories were
deliberately left standing: plain negations, prescriptive rules (an instruction
may prohibit), the ratified limitations register (`## Non-goals`, SECURITY's
out-of-scope list), and **verbatim quotation** — the tour's session transcript,
the user's own words, and code quoted from `build.py`. Rewriting captured
evidence to satisfy a prose norm would falsify the thing the tour exists to
show; that boundary is worth more than uniformity.

**What the Critic caught (0 blocking, 9 warnings, 11 notes).** Three fixes
worth naming. The row's discriminating test was **self-invalidating**: it asked
whether removing the negated half left the subject undefined, and "Ableton is
the speaker" survives that deletion — so the test cleared the very sentence the
row bans. Replaced in all four carriers with the foil test. **The carve-out
count was dishonest**: the norm advertised two while the sweep applied four, so
prescriptive rules and verbatim quotation were recorded explicitly as *pending
owner ratification* rather than folded in silently — the same leave-the-veto-real
pattern that made this session's ruling possible. **The owner ratified both the
same day**, so the row now carries four owner-ratified carve-outs and nothing
pending; a fifth is a ruling, not a judgment call. (One
reviewer claim was wrong and is worth recording as such: the limitations
register did **not** arrive with the rejected narrowing — it is in the owner's
original 2026-08-11 wording as "Narrow exception".) And **four survivors** the
Done-when had called clean, the worst being VISION's "Reach music Ableton was
not built for … the DAW alone makes it actively hostile", which ranks against a
named tool under `## Why` with no carve-out covering it.

Docs-only. Suite green at 5005 passed / 2 skipped, before and after.

## 2026-08-11 — Release process: the back-merge is a fast-forward, and `main` may be elsewhere

<!-- prawduct: type=docs | scope=release-process-docs | release=v1.8.5 -->

Reconstructed at the v1.8.5 cut from commit `f4f9ad2`, which landed on
`develop` with no entry of its own — exactly the gap step 1 of
`docs/release-process.md` warns about, found by running the audit it
prescribes (`git log --oneline --no-merges origin/main..develop`).

Two traps hit during the v1.8.4 cut, both fixed at the source that allowed
them. **Step 9's back-merge is the one merge in the process that is
deliberately not a merge commit**, and nothing said so — it sits two
paragraphs under step 8, which *does* require `--no-ff`, against a repo-wide
`--no-ff` habit, so the bare `git merge` read as an omission rather than a
specification. Passing `--no-ff` there leaves `develop` permanently one commit
ahead of `main` and makes step 10's `rev-list` count read 1 instead of 0 — a
check that appears to fail while the trees are identical. Now stated outright,
with the false alarm named so the next reader recognizes it.

**Step 8 assumed `git checkout main` works.** Where `main` is checked out in
another worktree it refuses outright, and that worktree must not be disturbed
to satisfy a release. The plumbing path is now written down: verify the merged
tree equals `develop`'s, build the two-parent commit with `commit-tree`, push
it straight to the remote ref — the same merge commit step 8 describes,
without the checkout.

## 2026-08-11 — Launch-readiness docs pass: contradictions closed, framing recentred

<!-- prawduct: type=docs | scope=docs-launch-readiness | release=v1.8.5 -->

A critical review of the user-facing docs from the README outward, then the
fixes, across four review rounds. No product behavior change. Five non-`.md`
files: the two plugin manifests and `ci.yml`, all carrying stale or retired
prose in strings and comments; `project-state.yaml` for the norm registry;
and one new test — `test_marketplace_manifest_tool_count_matches_actual_registry`,
which pins the tool count shown in the `/plugin install` dialog. That count was
the only one of four such claims no guard read, because the sibling README
guards match "N unified tools" and the manifest says "N Ableton Live tools";
verified by mutating the manifest to 99 and watching the test fail.

**Four contradictions.** `.claude-plugin/marketplace.json` told every installing
user the plugin "Requires the `hallucinote` Python engine installed" — stale
since the plugin absorbed the engine, and against the README's "self-contained".
It is the first sentence a user reads, in the install dialog. `VISION.md`
claimed audio recorded against a click flows back into the DB in the present
tense, which `known-issues.md` contradicts; it now separates the symbolic
round-trip (real today) from audio (a goal). VISION's "impossible in every other
tool" invited an argument it would lose — TidalCycles, Sonic Pi, Lilypond and
DAWproject all exist — and now claims the defensible combination instead.
`CONTRIBUTING.md` taught a pip/venv setup while CI runs `uv --locked` and the
plugin ships `uv --frozen`, and taught the deprecated `ok-broad-except` spelling
that `project-preferences.md` marks legacy.

**Omissions a prospective user hits before installing.** What it costs to run
(Claude usage and the Ableton bill) appeared nowhere; both are now in README
Status and the FAQ. No token figure is published because none is measured
anywhere in the repo — the shape of the cost is stated instead, and #458 tracks
measuring it. "The melody is yours" was the single most load-bearing product
fact and lived only in `capability-truth.md`, an internal doc, while the README
advertised "any genre, any shape". Also added: whether you end up with a normal
Live set you can finish and release (yes — it was buried in `collaboration.md`),
build determinism, and output ownership.

**Editions and CI honesty.** "Any Live 12 edition" narrowed to the editions
actually exercised (Standard, Suite); Intro and Lite are named as untested in
`known-issues.md` with the two failure modes that will bite. `CONTRIBUTING.md`
gained a section stating what CI covers: no Ableton, no macOS or Windows leg,
one interpreter. #459 and #460 track the underlying decisions.

**Framing.** The README had put Claude in the subject position of every creative
verb — "You describe a song; Claude writes it", "You talk; Claude authors code"
— which reads backwards to the audience most primed to distrust AI tooling. The
user now holds the creative verbs; the tool builds, measures and reports. A
"Who it's for" section covers the three registers (curiosity, reach, leverage)
without describing anyone by their deficits, and the cheap-experiment loop that
makes the tool fun is stated where it was previously missing.

**Two norms came out of it, and the first one had to be narrowed the same day**
(`project-preferences.md` → Documentation & prose + two Enforcement rows;
`norm_registry_ratified` 27 → 29). As first written, **write what a thing IS,
never what it isn't** was absolute — and the cumulative Critic caught it being
violated inside its own ratifying bundle, twice in `VISION.md`. Both sites were
rewritten. But the verify pass then made the sharper point: read absolutely,
the row also outlaws ordinary factual distinctions the corpus legitimately
needs — "a long agentic workflow, not a chat", "the song is reproducible; the
act of composing it isn't" — and a norm the corpus violates on the day it
ships is aspirational, not binding. So the row now names the two moves it
actually targets (positioning against alternatives; rebutting an unraised
objection) and states the test explicitly: a sentence about a competitor or a
critic is banned, a sentence about how the thing works is fine. It was then
narrowed a **second** time, in the same pass, when the next round pointed out
that the test as worded condemned the VISION prior-art paragraph the first
narrowing existed to permit: naming other tools as lineage is now explicitly
allowed, and ranking yourself against them is the banned move. Worth recording
plainly, because twice-narrowing a norm the day it ships is the shape of
*amending a norm to match your own prose* — the reviewer weighed exactly that
and let it stand only because each narrowing states a general discriminating
test rather than exempting a specific paragraph. It remains vetoable. The
second norm — the user holds the subject position on the creative verbs — was
uncontested, and gained the ratification date and retroactivity clause it
shipped without.

Two artifacts were resynced while the corpus was open: `api-contract.md` and
`project-preferences.md` § Package manager both described skills invoking
`uv run --project <plugin-root> --frozen hallucinote <cmd>`, which is no longer
what ships — every skill uses `"$PY" -m hallucinote.cli`, with `$PY` resolved
from `ableton://server/info`. Both prose norms carry mechanism and audit home in the Enforcement index,
because a norm outside that index is one the janitor's Norm Health sweep never
walks.

What prompted it: an intermediate draft of this very pass added a "What it
isn't" section and Suno/is-this-cheating FAQ entries. They argued with a critic
the reader had not met and planted the doubt they answered. They were removed
rather than softened, and the fact underneath them — the notes come from
parametric generators you can read — now states itself positively, as
mechanism.

Backlog filed from the review: #457 (a second worked example in an exposed
genre), #458 (measure per-song usage), #459 (CI platform matrix), #460
(Intro/Lite). The demo-video finding folded into existing #329 rather than
duplicating it, with a comment recording the part its acceptance was missing:
the delivered `.mp4` has to be embedded in the README to play inline.

## 2026-08-11 — The effort:S backlog burns down: a guard override deleted, a gate that agreed with itself, and a DB that stops depending on your shell

<!-- prawduct: type=fix | scope=effort-s-burndown -->

**Operators: this release flips the MCP wire fingerprint.** Seven files inside
`_FINGERPRINT_PATHS` changed, and `_compute_content_fingerprint` hashes bytes,
so the comment-only pragma rewrites flip `__version__` alongside the behavioral
ones. Re-vendor the Remote Script (`/ableton-mcp-install`) and quit/reopen Live
before expecting the `duplicate_to_arrangement` fix below to do anything —
until then the vendored script fails the version handshake.

One branch working through every `effort:S` item open on the tracker. Chunks 1-2
covered the PR #213 deferred-warning cluster and a sweep of prose the tree had
outgrown; chunk 3 is two real bugs where a check disagreed with the thing it
checked.

- **`capture restamp` is gone** (#318). It moved a snapshot's `captured_at`
  forward with no re-capture, durably disarming the replay staleness guard on
  evidence nothing had checked. The two sanctioned exits already cover the
  ground — a fresh capture (durable) and `--force-replay` (conscious revert,
  which re-warns every build rather than switching the guard off). Deleting it
  makes `migrate_snapshot`'s "only a real capture stamps" invariant exactly
  true instead of approximately true.

- **BREAKING (resolution semantics), `resolve_db_path`** (#327): with an
  explicit `root=`, the git branch is now probed in the **song's own
  directory** instead of the process cwd. This **remaps DB filenames for anyone
  who has been running a song's `build.py` from a foreign cwd** — that shell
  was minting `<slug>-<the-other-repo's-branch>.db` while every reader looked
  for `<slug>-<songs-repo-branch>.db`, so one song silently owned two DBs. The
  sibling push-state files are the sharp end, and by SHARING rather than
  duplicating: `.last-push-state.json` / `.last-notes-push.json` have fixed
  names and live in the song dir, which both DBs share — so two DBs wrote one
  set of fingerprints, and a scoped `--changed` push compared one DB's clips
  against the other DB's fingerprints. It is a resolution-semantics change,
  not a pure bugfix: a DB written under the foreign name will not be found
  under the new one. A runtime warning naming orphaned sibling DBs was tried and
  **reverted**: under per-branch naming a routine `git switch -c` produces
  exactly the same shape (a new DB name beside an older sibling), so it could
  not tell a foreign-cwd orphan from an ordinary new branch without becoming
  noise — and it sat inside a resolver that `provenance.auto_request` calls on
  every mutating MCP tool call. `resolve_db_path` stays a pure resolver.
  **If you have been building a song from another repo's checkout, look for a
  `<slug>-<other-branch>.db` beside the new one before deleting anything:**
  `build.py` regenerates authored content, but rows pulled from Live — and the
  pull events arming the replay guard — live only in the DB that recorded them.
  The legacy
  `<slug>.db` fallback readers already carry is unchanged. Both root paths now
  probe the same place, so `resolve_db_path(slug)` and `resolve_db_path(slug,
  root=...)` agree by construction.

- **`compat check --probe` stopped lying about ambiguity** (#326). The dry-run
  cache key omitted `mode` and `case_sensitive`, and the probe never sent them,
  so a query authored `mode='exact'` was searched with the browser's default
  substring matcher and classified on a count the real loader would never
  produce — refusing `kind_ambiguous` at the push gate on devices that load
  perfectly. Both fields now ride the key and the wire. The second, quieter
  half is closed too: two devices differing only in `mode` no longer collide on
  one cache entry and share a match count.

- **The BAK-7D2V closure note** (#317) was stale on two counts — it advertised
  the superseded empty-diff re-stamp, and said "checks 7-8" where
  `operator-verification.md` carries 7-9. Fixed on **closed issue #337**, not in
  `.prawduct/backlog.md`. That file was frozen on 2026-08-10 as the migration's
  source corpus with an explicit "preserve it verbatim" — it is what
  `verify-migration` and any rollback read, so editing it would corrupt them.
  The note migrated verbatim into #337, which is the record a future scrub
  actually reads; the frozen copy stays wrong on purpose, as history.

- **The screen-recording grant is now REQUESTED, not just reported** (#223).
  `assert_capture_permission` preflighted but never called
  `CGRequestScreenCaptureAccess`, and nothing else in the tool raises a TCC
  dialog — so a denied grant was a dead end that sent the operator hunting
  System Settings mid-capture. The actionable error survives the request on both
  branches, deliberately: the grant is read at process launch, so granting
  through the prompt does not enable a *running* process, and the relaunch
  instruction stays load-bearing.

- **New: `hallucinote overview-drift <slug>`** (#233) reports a `<slug>.md`
  Structure table that has drifted from the form `build.py` materialized. The
  generate-vs-warn question is **decided as warn**: both derived surfaces carry
  composer prose (the table's Feel column, and `build.py`'s docstring in the
  composer's own source), so regenerating them would clobber real work to fix a
  bookkeeping problem. The canonical form is the DB — what `build.py` actually
  materialized, and what every other reader already treats as true. It checks
  **both** derived surfaces (the markdown table and `build.py`'s docstring
  layout) and is wired into the scaffold's build close, so a song scaffolded
  from now on checks itself on every build. **Songs scaffolded before this do
  not get it automatically** — retrofitting means rewriting their `build.py`,
  the clobbering this decision rejected — so they use the subcommand on demand.

- **The analysis extract reaches inside racks** (#256). `_extract_song_structure`
  walked only the top-level device chain, so a song built on Instrument or Audio
  Effect Racks reported its rack *containers* and none of the signal path inside
  them — while looking complete. It now descends `device_chains` recursively.
  **This item was filed as blocked on upstream work and wasn't:** the gate was
  real when written (2026-06-15), but DEEP-RACK-ADDR has since made
  `device_chains` a true recursive tree (`parent_rack_device_id` self-referencing
  through `devices`), so the data has been there. No Live probe and no schema
  change were involved. Nested entries carry `rack_depth`, which is what keeps
  them distinguishable from top-level siblings (`chain_id` is NOT NULL on every
  device row, so it does not), and the depth cap is imported
  from the wire-side resolver rather than restated. The prior lock test — which
  pinned the exclusion and said in its own body "when nested-rack pull lands,
  this test is the one to flip" — was flipped, and the agent-facing action tip
  that taught the old limitation was corrected with it.

- **Two decisions recorded rather than built.** `arrangement-model.md` now
  carries the ARR-2S9D call (#274 — two energy correlates suffice; the spectral
  one waits for logged friction and for the listening day) and a re-run of the
  ARR-8P5K taxonomy coherence guard (#248), which found that STR-4C8N shipped a
  **stereo lens for a dimension the taxonomy never named**, in the
  measured-but-un-authorable half-built state the doc itself warns about. Spatial
  image is now placed in the sound-design subsystem, its authoring half named
  (STR-9P4M, gated), and the 2026-08-10 owner ruling — *no new lens that grades
  or coaches* — written where a lens-adder will meet it.

- **Also shipped, smaller but real:** spurious-clip detection after a
  `duplicate_to_arrangement` now counts occurrences instead of testing a
  start-time set, so a pre-existing clip sitting exactly where Live's B-24 split
  emits its copy can no longer mask the surplus one (#264); `events.AUDIO_CAPTURED`
  + `mutations.record_audio_capture` put capture timestamps into the audit log,
  emitted server-side off the render status response and deduped on
  `captures_dir` because the caller is a poll (#263); and tools now ignore their
  own regenerable output where they write it — a blanket ignore for
  whole-directory output (`captures/` — every take under it is regenerable),
  a named list for the song dir, which also holds authored work (#303).
  **`analysis/` is deliberately NOT self-ignored:** the root `.gitignore`
  and `hallucinote.paths` both say MixReports there are meant to be
  committed (`portable_path` exists precisely because they land in git),
  while `init_workspace`'s root block carries `**/analysis/`. That
  contradiction predates this branch and is the owner's to settle — it is
  named in the code rather than resolved by whichever writer ran last. A confirmation lock pins that a `device_parameter`
  envelope covered by its session clip stays on the sample-accurate path rather
  than regressing to the ~2.5 Hz perform path, together with the note-on
  ordering convention that makes per-phrase sample windows land right (#236).

- **Waivers and citations** (#447, #445): all 21 legacy
  `prawduct:ok-broad-except` pragmas migrated to the current form carrying a
  per-catch reason; the four source citations into the frozen
  `.prawduct/backlog.md` repointed at stable `id:PFX` handles (and dropped
  entirely from the one user-facing error string). **#320** — the pre-split
  layout in `project-preferences.md` — was fixed on this branch too, but
  `develop` landed the same correction first, so this release ships nothing
  for it and does not claim it.

---

## Older entries

Everything shipped in **v1.8.4 and earlier** lives in
[`change-log-archive.md`](change-log-archive.md), verbatim and unedited. It was moved
there, not deleted — git carries the full history either way. Several archived entries
share the date 2026-08-11 with entries kept above, so the release each one names, not
its date, is what says where it lives.

**Nothing release-pending is ever archived.** An entry with no `release=` key IS the
release-pending marker (see the format note at the top of this file), so the roll only
ever moves entries that already name the release that carried them. Rolling the log is
a step of the release procedure — see `docs/release-process.md`.
