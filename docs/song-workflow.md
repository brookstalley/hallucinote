# Song creation in Hallucinote — the full picture

This is the map for making a song here: the **lifecycle** (which skill runs each
phase, where in the loop the user first hears something, and the checkpoints
agents most often miss), each stage's
[**definition of done**](#stage-exit-criteria), and the **expertise** behind
every tool — grounded in the framework's research corpus,
linked so it never rots out of sync. Read it when you start song work, or when
you want to understand *why* a tool does what it does and how to go deeper.

For the always-in-context short version, the `/song-workflow` skill is the same
map at a glance. This doc is the depth.

---

## The one idea: creativity first, depth on demand

Two commitments shape everything below. They are not in tension — they're the
same stance seen from two sides.

**Creativity first — intent is the ruler.** Hallucinote is a *producer*, not a
gatekeeper. It never declines a directed request, never makes a creative
decision on the user's behalf without surfacing it, and treats every measurement
as a *producer's question* ("is the chorus landing?"), never a verdict. A
near-silent part, a drone, a dissonance, a 3/4 bar in a 4/4 song — these are
valid art, and nothing in the build blocks them.

A producer also knows when to hand over the headphones. The pacing rule is
**two-sided**, and each half exists because the other, alone, produced a real
failure: **never stop to summarize-and-ask** at a procedural seam — a finished
phase is not a decision point — and **never build past a hearable unit without
offering to play it** — the hearable unit is the bound on what gets authored
unheard. Drop the first half and every skill boundary becomes a checkpoint;
drop the second and the user asks "shouldn't I be hearing something?" forty-five
minutes in, with zero notes taken. The offer is for what the user left open: a
choice they directed, or a hearing rhythm they set, is theirs and is not
re-opened.

- The producer stance, the propose-and-react discipline, and the three intent
  registers (directed / volunteered / directed-but-underarticulated):
  [intent-collaboration-model.md](../.prawduct/artifacts/intent-collaboration-model.md).
- The vocabulary the pacing rule is written in — *turn kind*, *hearable unit*,
  *the status offer*, *decline with scope*, *owner column*, *loaded prompt* —
  is defined there, and short-defined in `CLAUDE.md`, which an agent loads every
  session. This page carries a one-line gloss of the hearable unit at stage 3,
  because a human reader here auto-loads neither, and links for everything else:
  [collaboration-turn-model.md](../.prawduct/artifacts/collaboration-turn-model.md).
- Why nothing aesthetic can fail a build (BLOCKING is reserved for *likely
  errors* — pitch out of range, zero duration — never choices):
  [gate-verdict-policy.md](../.prawduct/artifacts/gate-verdict-policy.md).
- Why helpers are **rulers, never stamps** — a generator removes bookkeeping but
  must never make the musical decision:
  [generator-altitude-policy.md](../.prawduct/artifacts/generator-altitude-policy.md).

**Depth on demand.** The same song can be a five-minute sketch or a deeply
authored piece. The toolkit reduces work; it never caps what's authorable. When
a helper doesn't reach far enough, you drop a level — down to hand-authored notes
if that's what the art needs (the [depth ladder](#going-as-deep-as-you-want)
below). Tools are conveniences, not limits.

---

## The lifecycle

Song-making here is a **loop, not a line** — you'll circle back through compose
and mix many times, and the **first pass is short on purpose**: compose the
first hearable unit → push it → **offer** a hearing (the status offer) →
continue to the next unit. The user hears something after one unit of
authoring, not after the song; "keep going" is a complete answer to the offer,
and a decline with scope is remembered rather than re-asked. The hearing is a
property of the loop, not a stage in the table below — every pass through
compose ends at something the user could hear. But the arc has a natural order,
and two of its phases are *review checkpoints* that are easy to skip and
shouldn't be:

| # | Phase | Skill(s) | The expertise behind it |
|---|-------|----------|-------------------------|
| 0 | **Elicit the brief** ⭐ | **`/song-brief`** | [collaboration-turn-model.md](../.prawduct/artifacts/collaboration-turn-model.md), [elicitation-and-stage-exit-criteria.md](../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md), [onboarding-and-teaching-model.md](../.prawduct/artifacts/onboarding-and-teaching-model.md) |
| 1 | Frame the intent | `/song-new`, `/song-context` | [onboarding-and-teaching-model.md](../.prawduct/artifacts/onboarding-and-teaching-model.md), [intent-architecture.md](../.prawduct/artifacts/intent-architecture.md) |
| 2 | Pick instrument **chains** | `/song-pick-instruments` | sound design is composition (below) |
| 3 | Compose the parts | `/compose-part` | [melody-model.md](../.prawduct/artifacts/melody-model.md), [performance-model.md](../.prawduct/artifacts/performance-model.md), [arrangement-model.md](../.prawduct/artifacts/arrangement-model.md) |
| 4 | **Read the composition** ⭐ | **`/compose-review`** | melody + recurrence lenses vs declared intent |
| 5 | Materialize in Live | `/ableton-push` | [push-execute-design.md](../.prawduct/artifacts/push-execute-design.md) |
| 6 | Capture + analyze | **`/render-analyze`** (`ableton_render` → `ableton_analysis`, poll loops kept out of context) | [masking-analyzer-goals.md](../.prawduct/artifacts/masking-analyzer-goals.md) |
| 7 | **Read the mix** ⭐ | **`/mix-review`** | masking · loudness · feel · energy vs intent — *needs Max for Live* |
| 8 | Snapshot + iterate | `/song-snapshot` (durable mix bake), `/ableton-pull` (build.py-staging) | — |

The ⭐ checkpoints are the ones agents forget exist. **They are not optional
polish** — stage 0 is where the work gets specified, and stages 4 and 7 are how
the framework's ear gets applied to it.

### 0 — Elicit the brief ⭐ `/song-brief`
A starting prompt is not a brief. `/song-brief` sweeps the load-bearing
dimensions the prompt left open — harmony, tempo, production stance, what a
named narrative turn means musically, meter, the section time budget, and the
**mechanism behind every named gesture** — and closes them in a **conversation
that ends at the user's hand-off**: it opens with the two or three identity
questions it cannot guess, proposes the rest as informed, redirectable reads
(each carrying its reasoning so a one-word reaction settles it), and keeps
reading each reply for whether the user is done. An answer that adds a noun is
not a closure; silence on an asked item is still thinking; identity closes when
the user hands off, never by inference. Never a questionnaire, never sequential
Q&A — and never a form on a creative question. A loaded prompt ("make a rap
song", "write a symphony") opens its domain rather than being run with.

Its output is `annotations/01-the-brief.md`: the prompt verbatim, plus the
resolution table every later stage reads — a ledger the stage updates every
turn, carrying for each dimension not only its state but **who owns it**
(*yours* / *offer me options* / *mine*), learned from the conversation rather
than asked for. It also produces the tempo, meter and section values `/song-new`
requires as command arguments — which is why it runs first. What the user
directed is taken as read, not re-asked; when a directed prompt leaves nothing
applicable open, there is nothing to ask and the stage executes.

→ [collaboration-turn-model.md](../.prawduct/artifacts/collaboration-turn-model.md)
(the conversation, the turn kinds, the owner column) ·
[elicitation-and-stage-exit-criteria.md](../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md)
(the three states and the no-unresolved-gap rule)

### 1 — Frame the intent
`/song-new` scaffolds `songs/<slug>/` (build.py, captured_session.json, tests,
decisions/, annotations/, attempts/, song.md). Before that, and throughout, the song's
*intent* — key, the central tension, what the chorus does, the energy arc — is
the thing everything else serves. Don't auto-decide it: at an elementary musical
fork the user hasn't directed, **propose and read their reaction** (the third
register). Three recall surfaces, one per question: prior *intent* → `/song-context`;
the audit trail of compose-time decisions → `/decisions`; **what you already tried on a
part and how it turned out** (incl. reverted dead ends) → `/song-attempts`, before you
re-touch a part you've worked before. A song built on a sample has a fourth: what the
line *is* — its pitch centre, phrases and where a detector would fire, against bars —
→ `/sample-lens`, before composing to it.

### 2 — Pick the instrument chains (sound design *is* composition)
`/song-pick-instruments` picks a *chain* per track — instrument **plus**
post-instrument FX **plus** initial send levels — not a bare instrument. The
saturation, the drum bus, the room reverb send ship *in the snapshot*; they're
authorship, not a mix-time todo. A finished song has the sound it's supposed to
have as part of being finished.

### 3 — Compose the parts (author-as-code)
`/compose-part` writes note-generating code in the song's `build.py` using
`hallucinote.generators`, runs the build (DB through mutators; events fall out),
and scoped-pushes the changed clips. Notes are authored as code and never enter
the agent's context.

**Compose the first hearable unit first, and offer it before the next.** The
hearable unit is the smallest thing that, once heard, tells the user whether the
idea works — one idea in a study, a few bars of one section with the parts that
carry it in a sketch; it is read fresh every turn, never fixed per song. Getting
it into the user's ears has one precondition: a brand-new track or clip needs
one full `/ableton-push` to create and link the structure before `/compose-part`'s
scoped `push-notes` can reach it (it only touches already-linked clips, and
returns a teaching error per clip otherwise — see `/compose-part`'s
precondition). After that first full push, every pass is audible in Live as soon
as it exists — and that is when the **status offer** is made: what is settled,
hear it or keep going, what has not come up — named, not asked. It fires when
the settled material has reached a hearable unit *and* the user's last turn was
a closure rather than an opening; if their last turn opened something, follow
the opening; if nothing is hearable yet, propose one concrete thing toward it.
"Keep going" authorizes the next unit, after which the offer is made again; a
decline with scope ("build it all, I'll listen at the end") is recorded in the
brief's owner column and not re-asked inside that scope. A decision you expect
the user to overturn is played to them, not filed past. And after the user
listens, their report is a *reacting* turn, not authorization to build the next
unit: interpret it, adjust what they pointed at, name any confound in your own
study's design, offer at most one concrete next study, and wait. What this rules
out is the whole-song pass: twelve chains and every section authored, rendered
last, with the first audio at the end. The bound is on the *offer*, never on the
listening — the user is never required to hear a unit in order to continue.

This is where the line-level craft lives:

- **Melody** is a structural dimension — contour, intervals, harmonic fit,
  motivic economy. There is *no universal "good melody"*: a line is graded
  against a **declared profile**, not a universal substrate.
  → [melody-model.md](../.prawduct/artifacts/melody-model.md)
- **Microtiming feel is authorship**, not a post-hoc humanize pass. Per-part
  push/pull/swing/drag is baked into the pattern at generation time, coordinated
  across instruments where the genre calls for it (human timing is 1/f-correlated,
  not white noise). → [performance-model.md](../.prawduct/artifacts/performance-model.md)
- **Form, energy, and recurrence** — sections, the energy arc, which motifs
  recur where and as which variation — are authored on the arrangement model, not
  raw mutators. → [arrangement-model.md](../.prawduct/artifacts/arrangement-model.md)

### 4 — Read the composition ⭐ `/compose-review`
After a first compositional pass — or whenever you'd ask "does this work?", "is
the hook landing?", "what's missing?" — `/compose-review` recalls the declared
intent, reads the *composition* (sections, density, register, the energy arc)
plus the symbolic **melody lens** (contour, intervals, harmony-fit) and
**recurrence lens** (which motifs return, as which variation), and interprets it
*against intent*: "you wanted the chorus to lift — does it? here's the one thing
holding it back." A producer's question, never a score. This is the
compositional sibling of `/mix-review`, and it runs **before** the mix stage.

### 5 — Materialize in Live `/ableton-push`
`/ableton-push` drives fourteen ordered phases (tempo → meter → tracks → returns
→ scenes → clips → mix → devices → routing → device-sidechain → envelopes →
performed automation → arrangement → cues) against a fresh or partial Live set —
idempotent, with preflight and rollback. → [push-execute-design.md](../.prawduct/artifacts/push-execute-design.md)

### 6 — Capture + analyze `/render-analyze`
`/render-analyze` runs the capture + analysis in one step: `ableton_render`
auto-loads the HallucinoteAnalyzer and runs a WAV capture pass; `ableton_analysis`
builds a **MixReport** from the captures (render integrity — clipping, dropouts,
clicks, phase/polarity, stem-sum reconciliation — plus loudness, master
attribution, reverb verification, per-part timing/feel, masking, soundstage
imaging, energy realization). The integrity family runs over the whole capture
and the imaging one runs per section as well, so together they add roughly a
minute or two to the analysis of a full-length song — the analysis is a
start+poll action already, so this lands as a longer poll, not a blocked call. Both are
realtime / long-running **start + poll** actions (they exceed the 60 s tool-call
timeout — see `ableton://guides/conventions` "Long-running actions = start +
poll"), so `/render-analyze` delegates their poll loops to a subagent and hands
back only the MixReport summary + `report_path` — keeping the plumbing out of
your context. This is the expensive real-time step — it feeds the next checkpoint.

**Capture retention.** Renders are big (~23 MB per surface-minute of per-stem
WAV), so a rolling window keeps a song at **3 takes** on disk; the durable
measurement is the MixReport JSON in `songs/<slug>/analysis/`, which is never
swept. Pin a reference take to exempt it from the sweep. The mechanics — the
`captures list/prune/pin` commands, the env-var knobs, and why they must reach
the server process — are in
[`running-the-engine.md` → Capture retention](running-the-engine.md#capture-retention-render-takes).

### 7 — Read the mix ⭐ `/mix-review`
The single read-side surface over all audio analyses. It reads rendered audio, so
it **needs Max for Live** (Live Suite, or the M4L add-on); `/compose-review` is the
symbolic read, available on Standard too. `/mix-review` recalls the
song's intent, reads the whole MixReport per section, and interprets the
measurements *against* intent — surfacing only the collisions that hurt the
element meant to *win* each section, framed as a producer's question. Masking is
its richest input: masking is the *depth mechanism* of a mix, not a defect — the
question is "is the focal element winning?", not "where do frequencies collide?".
→ [masking-analyzer-goals.md](../.prawduct/artifacts/masking-analyzer-goals.md)

Both review skills **learn revealed intent back** as a markdown annotation, so
they never re-flag a choice you've confirmed.

### 8 — Snapshot + iterate
**The one-bake model (BAK-3M9T).** There is one durable mix bake and one staging
primitive — they write different targets:
- `/song-snapshot` → `captured_session.json` (git-tracked, **durable**). The
  **single mix bake**: params, sends, device chains, and sidechain sources. The
  next `build.py` reproduces your dialed mix from it.
- `/ableton-pull` → the song `.db` (a **regenerable** build artifact). The
  lower-level **build.py-staging** primitive for build.py-owned domains (clip
  notes, automation) you fold into `build.py`. It is NOT a parallel mix bake:
  `replay_capture` re-asserts the snapshot onto the DB every build.

**The contract is enforced (BAK-7D2V).** A mix edit you pull but don't
`/song-snapshot` is no longer silently reverted — as long as the snapshot
carries a `captured_at` stamp, the next `build.py` **refuses to run**
(`StaleSnapshotError`), and `pull_cli` prints a durability notice at pull time.
(A legacy snapshot with no stamp leaves replay no ordering evidence, so it warns
and still reverts; baking once makes the check exact from then on.) So the loop
is **pull → bake → build**: `/ableton-pull` (stage) → `/song-snapshot` (bake,
which writes a fresh capture stamped newer than the pull and so disarms the
guard) → `build.py` (runs clean). `build.py --force-replay` consciously discards
the pulled edits instead. Build.py-owned pulls (notes, envelopes, tempo, cue,
arrangement, tuning) do not themselves arm the guard — that's the sanctioned
staging lane. The exception worth knowing: `score-globals` shares one probe with
master volume/pan ingest, so a "tempo-only" pull arms the guard whenever the
master fader or pan drifted. Arming follows the event kinds a pull actually
emitted, not the domain you asked for — so trust the durability notice.

Then loop back to compose or mix. The hearing offer rides every pass, not just
the first: each loop through compose ends at a unit the user could hear, and the
offer is made again — unless they declined with a scope that has not yet been
reached.

As you loop, keep the **attempt ledger** (`songs/<slug>/attempts/`, `kind: attempt`)
current — log each move you *tried* and how it turned out (`outcome` worked/partial/failed,
`resolution` kept/reverted/superseded), **especially the reverted dead ends**, chaining a
correction with `related:` → the move that worked. The two review checkpoints propose these
entries; `/song-attempts` recalls them. This is the per-song memory that stops the next loop
from re-running a move that already failed — distinct from `annotations/` (revealed intent)
and `decisions/` (what you kept and why). Schema + worked example:
[`.prawduct/artifacts/song-conventions.md`](../.prawduct/artifacts/song-conventions.md)
"The attempt ledger".

---

## Stage exit criteria

**A stage may not emit an unresolved gap.** Under-specifying is the user's
prerogative; *closing* the gap is the stage's job — by deciding it in-stage
(propose, and read the reaction) or by marking it explicitly open. What is
forbidden is passing an unresolved gap downstream **in the clothes of a
decision**.

The failure this exists to stop leaves no trace: the demo song's `_outro`
docstring said the closing octave drop "rides a Shifter device-parameter
envelope", there was no Shifter and no envelope anywhere in the song, the build
ran clean, the push reported OK, and the song ended flat while every document
about it said otherwise. **A documented mechanism with no implementation is
worse than an admitted gap, because every later reader takes it as done.**

### Three states, and a forbidden fourth

| State | Meaning | Blocks stage exit? |
|---|---|---|
| **DECIDED** | a value is chosen **and** the mechanism that realizes it is named | no |
| **UNDECIDED** | the song depends on this and nobody has chosen | **yes** |
| **NOT-APPLICABLE** | the song does not depend on this dimension at all | no |

**DESCRIBED-BUT-UNBUILT** — prose naming a mechanism that does not exist in
`build.py`, the snapshot or the DB — is not a legal state. It is the defect.
UNDECIDED is the honest form of the same situation and is always available.

NOT-APPLICABLE is a **first-class answer**, reached by the agent's own judgement
from the material and never by asking. Record it, then say nothing: silence
about a non-applicable dimension is correct; silence about an undecided one is
the defect. An ambient soundscape has no drum style, no meter argument and
possibly no tempo worth pinning — asking anyway is not thoroughness, it reads as
incompetence, and it is how a mechanism becomes a compliance ritual people route
around.

### Definitions of done

Every one is applicability-gated — read each as *"…for the dimensions this song
depends on."*

| Stage | Done when |
|---|---|
| **0 · `/song-brief`** | `annotations/01-the-brief.md` exists with the prompt verbatim and a resolution table in which every applicable dimension is DECIDED or UNDECIDED-with-an-owner, **and carries the owner column** (*yours* / *offer me options* / *mine*) for each, as the conversation revealed it. NOT-APPLICABLE rows are recorded, not asked about. The time budget is costed if a duration was stated. The user has handed off — the stage does not close identity by inference. |
| **1 · `/song-new`** | Tempo, meter and the section/bar list are **values from the brief**, not invented at the command line. Scaffold builds; shape checks pass (`verify-scaffold`, which runs in-process and needs no test runner). Each brief decision is filed in `decisions/`. If the CLI needs a value the brief lacks, that is an UNDECIDED row — close it before scaffolding, never default it silently. |
| **2 · `/song-pick-instruments`** | Every part the brief names has a resolved **chain** in the snapshot. Where the brief says the sonic worlds differ, that difference exists **as chain differences**. No chain is "TBD at mix time" — sound design is composition. |
| **3 · `/compose-part`** | Every gesture the section needs **exists in `build.py`** — notes, envelope, or device. **The docstring test:** if prose in the song names a device, an envelope or a mechanism, grep the song for it; absent ⇒ the stage is not done. Per-part `feel` is set explicitly, not defaulted by omission. |
| **4 · `/compose-review`** | The composition is read against intent per section. The time budget is **re-costed against actual bar counts** and reconciled with any stated duration. Every brief row this stage owned is now DECIDED or re-stated UNDECIDED with a new owner. ADRs filed for kept bright-line moves; `attempts/` for reverted ones. |
| **5 · `/ableton-push`** | Push reports OK **and** every phase the brief depends on moved something. A phase that pushed zero of a thing the brief requires is a gap, not a clean run. |
| **6 · `/render-analyze`** | A MixReport exists **for the current build** (not a stale take) and the render covered the full arrangement length. |
| **7 · `/mix-review`** | The measurements are read against intent per section, and **every audible gesture the brief names is either confirmed in the measurement or logged as not-yet-landed.** Verified on the render, never asserted. |

Stages 5 and 7 are deliberately redundant with stage 3: the gap that matters is
the one that survives every stage.

**Stage 8 (snapshot + iterate) has no criterion, and that is deliberate** — it is
the loop-back, not a stage handing work downstream. It cannot emit a gap dressed
as a decision because it emits no decisions; the next pass through stages 3–7
re-applies theirs.

**The hearing is not a ninth stage either, and has no row.** It is a property of
the loop — the bound on how much of stages 3–7 is built between moments the user
can hear — not a stage that hands work downstream. Its rule lives with stage 3
above and in the design: never author past one hearable unit without having
offered to play it; never require the listen.

### Meter is a projection concern

The song's meter is a property of the authored work; Live's ability to represent
it is a materialization detail the user should never have to hold. Elicit what
the meter genuinely **is** (*"full 7-rhythm, or 4-then-3?"* is a real musical
question) and never offer "we'll represent it as a global 1/4" as a creative
option.

The model records that meter, within-song changes included, and **places
against it**: declare it on the arrangement (`Arrangement(meter=…)`,
`meter_change(at_bar=…)`, or `section(..., meter=…)`) and every section, clip,
cue and lens read resolves through the song's meter map — the same walk push
uses. **What is still open** is only the projection: Live 12.4's MCP has no
`song_signature` automation target, so only the bar-1 row reaches Live and its
ruler numbers the whole song in one meter. That costs bar numbering and the
metronome, not playback — positions are authored in absolute beats, which is
what Live anchors content in — and the push alert names each change so the
operator can add it by hand if they want the ruler to match. Tracked as
**TMP-4J6Q** / **#321**.

→ Full design, including the worked examples and what is deliberately not built:
[elicitation-and-stage-exit-criteria.md](../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md)
(the three states and stage exit) ·
[collaboration-turn-model.md](../.prawduct/artifacts/collaboration-turn-model.md)
(the conversation, the hearable unit, the status offer)

---

## The expertise behind the tools — five layers

The corpus is a deep, adversarially-verified body of design research. It groups into
five layers; each lens and skill above draws on one or more. Go here when you
want to understand *why*, or to author at a depth the helpers don't reach.

1. **Compositional structure** — what a song is made of and how parts relate;
   form, energy, harmony, motif, recurrence; the dimension taxonomy that decides
   "is X a new axis?". → [arrangement-model.md](../.prawduct/artifacts/arrangement-model.md)
2. **Melodic line** — contour, intervals, expectation, harmonic fit, motivic
   economy; declared-profile-over-universal-substrate.
   → [melody-model.md](../.prawduct/artifacts/melody-model.md)
3. **Performance & feel** — the rendition layer; microtiming, dynamics,
   articulation; the metaperformer pattern; 1/f timing.
   → [performance-model.md](../.prawduct/artifacts/performance-model.md)
4. **Mix & analysis** — masking as a perceptual goal, loudness, reverb, energy
   realization; the producer-question framing.
   → [masking-analyzer-goals.md](../.prawduct/artifacts/masking-analyzer-goals.md)
5. **Intent & collaboration** — the producer stance, the three registers, the
   learn-back loop, and where intent lives (WHAT in build.py / WHY in markdown).
   → [intent-collaboration-model.md](../.prawduct/artifacts/intent-collaboration-model.md),
   [intent-architecture.md](../.prawduct/artifacts/intent-architecture.md)

Orthogonal to these five is **where a song's authorship lives** — generative code
(`build.py`) vs materialized state (`captured_session.json`) vs recorded assets —
and why, plus the LOM read/write walls that bound it.
→ [authorship-model.md](../.prawduct/artifacts/authorship-model.md)

The scope boundaries — what is *deliberately not modeled* (texture-mass music,
unmetered rubato, process-based pieces) and the graceful degradation path to the
raw note floor — are catalogued in
[boundary-patterns.md](../.prawduct/artifacts/boundary-patterns.md).

---

## Going as deep as you want

Depth is a ladder. Most songs live near the top; reach down exactly as far as the
art demands.

1. **Helpers** — `hallucinote.generators` and the skills above. Fast, idiomatic,
   genre-aware. Where most authoring happens.
2. **Review lenses** — `/compose-review` and `/mix-review` apply the framework's
   ear to your work and teach contrast and subtraction by example.
3. **The research** — the five layers above. Read the model when a lens raises a
   question you want to reason about from first principles.
4. **Hand-author** — when a helper doesn't reach far enough, write the notes (or
   the envelope, or the device chain) directly. The toolkit is a convenience, not
   a ceiling; a gap in the helpers is never a reason to scope the art down. Probe
   the platform, then build the capability or hand-build the result.

**Specialized side-paths** (rare; off the mainline so the common case stays
simple):

- **Alternate tunings** (19-EDO, just intonation, Bohlen-Pierce, …) — load the
  `.ascl` in Live, run `/tuning-pull <slug>` to capture it onto the song, then
  author in scale degrees via `hallucinote.tuning.mapper`. The 12-TET path is
  untouched. → [docs/alternate-tunings.md](alternate-tunings.md).

---

## Where things live (the authoring model)

- **WHAT** the song is → `build.py` (note-generating code) → the DB through
  mutators (every write emits an event).
- **WHY** it is that way → git-tracked markdown in `annotations/` and
  `decisions/` (the single authored home for intent; the DB is not an authoring
  surface). → [intent-architecture.md](../.prawduct/artifacts/intent-architecture.md)
- **The sound** → device chains in `captured_session.json` (authorship, per
  phase 2 above).

Operational conventions — directory layout, frontmatter schema, the toolkit
philosophy, drum-kit probing, meter handling — live in
[song-authoring-conventions.md](song-authoring-conventions.md). The skill index
is [skills.md](skills.md); the quick first-song walkthrough is
[quickstart.md](quickstart.md).
