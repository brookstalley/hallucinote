# Song-new checklist

**The dimension reference for the elicitation stage.** The skill that *runs* the
pass is [`/hallucinote:song-brief`](../skills/song-brief/SKILL.md); this page is
the catalogue it draws on. `/hallucinote:song-new` consumes what the pass
resolves.

## How to use this

**This is a prompt for thinking, not a form to fill in.** Nothing here is
mandatory. Run each item through the **relevance test** first:

> *Does the song, as described so far, depend on this?*

and assign one of **three states** — never two:

- **DECIDED** — the user pinned it, or it follows unambiguously from what they
  pinned. Restate it so it's correctable; don't re-ask it.
- **UNDECIDED** — the song depends on it and nobody has chosen. **Only this is a
  gap**, and only gaps go into the turn.
- **NOT-APPLICABLE** — the material doesn't imply it. Record it in the brief and
  **say nothing.** This is a real answer you reach by your own judgement; it never
  requires asking the user.

**Silence about a non-applicable dimension is correct. Silence about an
undecided one is the defect.** An ambient soundscape has no drum style to
specify, no meter argument, and possibly no tempo worth pinning — asking anyway
is not thoroughness, it reads as incompetence. Most songs will mark several rows
below NOT-APPLICABLE, and a directed prompt may leave nothing open at all, in
which case the pass is **silent** and the work proceeds.

The must-have / should-have / nice-to-have grouping below is a **rough prior on
how often a dimension turns out to be load-bearing**, not a priority order and
not a required-fields list.

**Proposals, not questions — and one message per turn.** What you raise in a
turn goes into a single message, each item carrying its reasoning and a
recommendation so a one-word reaction settles it — *"I'd propose 132 BPM,
here's the arithmetic"*, never *"what tempo?"*. A blank question is
auto-accompaniment wearing a politeness costume: it looks collaborative and
transfers zero expertise. Cheap, easy-to-revise choices are **shown** rather
than asked; the artifact becomes the next proposal. Sequential Q&A is the
anti-pattern — but so is treating the first turn as the only one. The
conversation runs until the user hands off; what bounds each turn is the
hearable unit (raise what decides it) and the status offer, both defined in
[`collaboration-turn-model.md`](../.prawduct/artifacts/collaboration-turn-model.md).

**Clear direction always wins.** Questions are for genuine gaps, never for
choices the user already made. When open questions stop yielding direction ("you
decide," repeated vagueness), switch from asking to **proposing** a concrete,
redirectable option — never assume-and-go.

**Persist the answers.** The states land in `songs/<slug>/annotations/01-the-brief.md`
(the resolution table); each substantive *why* lands as a markdown file under
`songs/<slug>/decisions/`, recording the question, the answer, who decided (user
/ inferred / agreed-after-confirm), and the rationale. Future sessions read these
via `/hallucinote:song-context` so the song's intent survives `/clear`.

**No dimension may be left DESCRIBED-BUT-UNBUILT** — written as settled prose
with nothing behind it. If you can't decide it, mark it open. See
[`docs/song-workflow.md`](song-workflow.md#stage-exit-criteria).

---

## Must-have — can't compose without these

### 1. Intent / meaning / purpose

What does the song evoke? What does it explore? What's it FOR (background music vs centerpiece vs DJ tool vs portfolio piece vs commission vs sketch)? Mood, function, audience.

*Why it's must-have:* function shapes production decisions (a DJ tool wants loud-and-flat mastering; a centerpiece wants dynamic range). Mood shapes everything else.

### 2. Genre / style anchor

At least one named reference; hybridization is fine. "Disco prog-metal," "lo-fi hip-hop," "ambient drone with field recordings."

*Why it's must-have:* anchors a thousand other defaults — drum kit choices, harmonic vocabulary, mix density, swing/groove pocket, instrumentation. Without an anchor the agent has to ask everything else explicitly.

*A named genre is a **loaded prompt** — it opens its domain rather than closing it.* "Make a rap song" implies a beat and a tempo range, a flow, lyrical content, sampled versus synthesized production, an era and a region. The move is to unpack what the word implies, state which implications you are taking as read so they are correctable in a word, and ask about the two or three whose answer would change the song most — not the whole list, and not a form. See [`collaboration-turn-model.md`](../.prawduct/artifacts/collaboration-turn-model.md).

### 3. Length and high-level structure

Total bars + section breakdown (`intro 8, verse 16, chorus 16, bridge 8, outro 8`). Sections can have non-uniform bar counts.

*Why it's must-have:* without this the agent can't pace anything. Generators need bar counts; arrangement needs section boundaries.

### 4. Vocals?

Three options, not binary:

- **No vocals.** Instrumental piece.
- **Leave 1-vocal-line of space.** Compose around a future vocal melody; leave a placeholder MIDI track or no melody in the lead role.
- **Instrumental-as-vocal-substitute.** A lead line (synth, guitar, sax) carries the melodic role vocals would.

*Why it's must-have:* each option leads to different arrangement decisions. A song-with-vocals needs space in the midrange; an instrumental fills that space with melodic instruments.

### 5. Instrumentation / timbres

The palette. Doesn't need exact device picks at this stage — "vintage analog poly + acoustic drums + electric bass + tape-saturated guitar" is enough.

*Why it's must-have:* shapes the snapshot's track structure and feeds `/hallucinote:song-pick-instruments` (the post-scaffold skill that resolves these descriptions to real devices via `ableton_browser`).

---

## Should-have — defaults exist but worth confirming

### 6. Tempo and feel

BPM range, swing/groove pocket, energy level. Often inferable from genre but worth stating. "120 BPM, slight humanization, no swing" vs "92 BPM, heavy MPC swing, dragged behind the beat."

### 7. Time signature / meter

4/4 default; flag and confirm anything else. Critical when the song wants meter changes — the DB records them, but only the bar-1 meter reaches Live, so the rest must be carried as felt groove (see `docs/song-authoring-conventions.md` → *Meter (4/4 vs. other)*). **The agent needs to know early whether to attempt non-4/4** (generators are 4/4-shaped within bars; non-4/4 sections need hand-authored patterns).

### 8. Harmonic strategy

Key (Cmaj / Dm / etc.). Modal vs tonal. Harmonic rhythm pace (one chord per bar? Per 4 bars? Per beat?). Key changes y/n. Modal interchange y/n.

→ These answers become an authored `theory.Progression` per section (the **harmony axis**) that the chord-aware generators voice and the conformance lint verifies — see `docs/song-authoring-conventions.md` § *Harmony is a modeled substrate*.

### 9. Production style

Reverb tail (dry / club / cathedral). Stereo width (mono compatibility needed?). Vintage vs modern. Dynamic-range target (loud-and-flat vs dynamic). Mastering intent (in-DAW finish vs separate mastering pass).

### 10. Arrangement curve / energy arc

Where's the peak? Slow build vs immediate engagement? Breakdown placement? Where do we lose layers to give the peak somewhere to come back from? This is the macro-shape; sections (item 3) are the bones.

→ This is the authored **energy curve** of the arrangement model (a structure intent) — see `.prawduct/artifacts/arrangement-model.md` (the dimension taxonomy).

---

## Nice-to-have — often emerge during composition

### 11. References / inspiration

"Like X but with Y." Worth asking explicitly because users often have a reference but don't volunteer it. A reference **opens** a domain rather than compressing it: naming an artist implies an era, a writing stance and a production world, and which of those the user actually means is the thing to find out. Unpack it, say what you're taking as read, and ask about the two or three that would change the song most — the same move as any [loaded prompt](../.prawduct/artifacts/collaboration-turn-model.md). Reading it as a shortcut that settles five other answers is what produces a build the user never asked for.

### 12. Hard constraints

What NOT to do. "No vocals." "Acoustic only." "Under 3 minutes." "Must loop seamlessly." "Mono-compatible (mobile playback)." Constraints are as load-bearing as preferences and easy to forget to ask.

### 13. Hooks / focal points

What's the memorable bit — the riff, drop, chord change, vocal line? Often emerges during composition, but flagging it early sharpens the build.

### 14. Density / complexity per section

Sparse vs busy. Layer count at each moment. Affects how the agent picks generators and decides what to leave silent. Verses often want fewer layers than choruses; intros often want the fewest.

---

## Gap-closers — applicable exactly when the prompt names one

These three aren't preferences to elicit; they're **holes to close**. Each is
NOT-APPLICABLE unless the prompt itself creates it, and each caused a real defect
in the first demo song. They are the reason this page exists as more than a
questionnaire.

### 15. Named narrative turns

A turn the prompt names but doesn't give a musical mechanism for: *"the ominous
notes are suddenly major **somehow**"*, *"the two are finally **integrated**"*.
A destination with no route.

*Applicable when:* the prompt names a turn. *Closing it* means proposing what the
turn **is** musically — same five pitches with only the bass moving; the same
melody at two rates. Both examples above came from one brief; one got answered
in-stage and became the best thing in the song, and one didn't.

### 16. Mechanism for every named gesture

The prompt names an audible event — a pitch bend, a riser, a drop, a crash, a
fade. **A gesture is not decided until the thing that produces it is named**: a
generator call, an envelope, a device, or hand-authored notes.

*Applicable when:* the prompt names an audible event. This is the row that
catches the failure with no symptoms — the demo song's `_outro` docstring said
the closing octave drop "rides a Shifter device-parameter envelope"; no Shifter
and no envelope existed anywhere; the build ran clean, the push reported OK, and
the song ended flat while every document about it said otherwise.

### 17. Section time budget

*Applicable when:* the prompt states a duration **and** names sections. Cost the
structure at the chosen tempo and compare it to the stated length. Under-budget
and a hinge reads as an edit; over-budget and something has to give. The first
demo song under-budgeted three of its own best moments against its own stated
45–60 s floor — caught late, by arithmetic someone happened to run, not by a
gate. This is a **statement to the user, not a question**: show the numbers and
the proposed adjustment, ending with "say if you want the shape different".

---

## What this becomes

Once the applicable dimensions are settled (or confidently inferred + confirmed):

1. **Scaffold** with `/hallucinote:song-new <slug> ...` — gets you `songs/<slug>/build.py` + synthetic snapshot.
2. **Pick instruments** via `/hallucinote:song-pick-instruments` — translates "vintage analog poly + acoustic drums" into device picks. Use `portability=strict` for cross-machine portability (stock Live content); switch to `relaxed` or `unrestricted` if the style demands third-party plugins. Picks land in the snapshot via `preset_query` (composer-time, portable) or via load-then-recapture.
3. **Push the scaffold to a fresh Live set** so the device chains materialize.
4. **Recapture** with `"$PY" -m hallucinote.cli capture` so device URIs / params land in `captured_session.json`.
5. **Compose** — open `build.py`'s `=== Compose-half ===` and author clips/notes/arrangement against the now-realistic snapshot.

The decisions you recorded here are durable — re-opening this song in a future session, the agent reads `decisions/` and picks up where you left off without re-eliciting.

---

## Reference

- Implementation: `skills/song-brief/SKILL.md` runs the pass; `skills/song-new/SKILL.md` consumes it. Sibling workflow skills under `skills/` include `song-pick-instruments`, `track-new-with-instrument`, `return-new`, `mix-sidechain`, `clip-humanize`, `compose-part`.
- The model behind the three states, the relevance test, and each stage's definition of done: [`docs/song-workflow.md`](song-workflow.md#stage-exit-criteria) and [`.prawduct/artifacts/elicitation-and-stage-exit-criteria.md`](../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md).
- Adjacent docs: `docs/snapshot-schema.md` for the snapshot shape; `docs/song-authoring-conventions.md` for compose-half conventions; `skills/hallucinote:ableton-push/SKILL.md` for the push flow.
- Decision retrieval: `/hallucinote:song-context` skill (queries `decisions/` + `annotations/`).
