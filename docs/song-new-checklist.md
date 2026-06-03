# Song-new checklist

**Authoritative pre-composition checklist.** Use this when starting a new song. The `/song-new` skill cross-links here — one source of truth.

## How to use this

This is **guidance, not a script.** The agent reads the user's prompt, infers everything it can, and **states inferences explicitly** ("you said disco prog-metal so I'm assuming 120 BPM, 4/4, electric bass + acoustic drums, modal interchange in the bridge — say if you want different"). Then it asks 2-3 targeted questions for the must-haves it genuinely can't infer. Should-haves get defaults with a "I'll go with N — say if you want different." Nice-to-haves are emergent unless the user volunteers them. **Freeform exploration is allowed** — this is the list of things the user would want to fix later if the model guessed wrong, so the agent surfaces its guesses early.

Apply with judgment, scaled to the work. A quick sketch song deserves 2-3 questions; a serious centerpiece deserves the full pass.

**This is collaborate-by-default, with precedence** (see `/song-new`'s "Read the request, not the requester"): elicit only the *load-bearing* unknowns, and when open questions stop yielding direction ("you decide," repeated vagueness), switch from asking to **proposing** a concrete, redirectable option — never assume-and-go. Clear direction always wins; questions are for genuine gaps, not choices the user already made.

**Persist the answers.** Each non-trivial decision (especially must-haves) lands as a markdown file under `songs/<slug>/decisions/`, recording the question, the answer, who decided (user / inferred / agreed-after-confirm), and the rationale. Future sessions read these via `/song-context` so the song's intent survives `/clear`.

---

## Must-have — can't compose without these

### 1. Intent / meaning / purpose

What does the song evoke? What does it explore? What's it FOR (background music vs centerpiece vs DJ tool vs portfolio piece vs commission vs sketch)? Mood, function, audience.

*Why it's must-have:* function shapes production decisions (a DJ tool wants loud-and-flat mastering; a centerpiece wants dynamic range). Mood shapes everything else.

### 2. Genre / style anchor

At least one named reference; hybridization is fine. "Disco prog-metal," "lo-fi hip-hop," "ambient drone with field recordings."

*Why it's must-have:* anchors a thousand other defaults — drum kit choices, harmonic vocabulary, mix density, swing/groove pocket, instrumentation. Without an anchor the agent has to ask everything else explicitly.

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

*Why it's must-have:* shapes the snapshot's track structure and feeds `/song-pick-instruments` (the post-scaffold skill that resolves these descriptions to real devices via `ableton_browser`).

---

## Should-have — defaults exist but worth confirming

### 6. Tempo and feel

BPM range, swing/groove pocket, energy level. Often inferable from genre but worth stating. "120 BPM, slight humanization, no swing" vs "92 BPM, heavy MPC swing, dragged behind the beat."

### 7. Time signature / meter

4/4 default; flag and confirm anything else. Critical when the song wants meter changes — neon-feedback's 5/8 bridge-twist exposed Hallucinote's meter-ratchet refusal path. **The agent needs to know early whether to attempt non-4/4** (generators are 4/4-shaped within bars; non-4/4 sections need hand-authored patterns).

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

"Like X but with Y." A 1-line shortcut that often collapses 5 other answers into one. Worth asking explicitly because users often have a reference but don't volunteer it.

### 12. Hard constraints

What NOT to do. "No vocals." "Acoustic only." "Under 3 minutes." "Must loop seamlessly." "Mono-compatible (mobile playback)." Constraints are as load-bearing as preferences and easy to forget to ask.

### 13. Hooks / focal points

What's the memorable bit — the riff, drop, chord change, vocal line? Often emerges during composition, but flagging it early sharpens the build.

### 14. Density / complexity per section

Sparse vs busy. Layer count at each moment. Affects how the agent picks generators and decides what to leave silent. Verses often want fewer layers than choruses; intros often want the fewest.

---

## What this becomes

Once the must-haves are settled (or confidently inferred + confirmed):

1. **Scaffold** with `/song-new <slug> ...` — gets you `songs/<slug>/build.py` + synthetic snapshot.
2. **Pick instruments** via `/song-pick-instruments` — translates "vintage analog poly + acoustic drums" into device picks. Use `portability=strict` for cross-machine portability (stock Live content); switch to `relaxed` or `unrestricted` if the style demands third-party plugins. Picks land in the snapshot via `preset_query` (composer-time, portable) or via load-then-recapture.
3. **Push the scaffold to a fresh Live set** so the device chains materialize.
4. **Recapture** with `python -m hallucinote.tools.capture_cli` so device URIs / params land in `captured_session.json`.
5. **Compose** — open `build.py`'s `=== Compose-half ===` and author clips/notes/arrangement against the now-realistic snapshot.

The decisions you recorded here are durable — re-opening this song in a future session, the agent reads `decisions/` and picks up where you left off without re-eliciting.

---

## Reference

- Implementation: `skills/song-new/SKILL.md`. Sibling workflow skills under `skills/` include `song-pick-instruments`, `track-new-with-instrument`, `return-new`, `mix-sidechain`, `clip-humanize`, `compose-part`.
- Adjacent docs: `docs/snapshot-schema.md` for the snapshot shape; `docs/song-authoring-conventions.md` for compose-half conventions; `skills/ableton-push/SKILL.md` for the push flow.
- Decision retrieval: `/song-context` skill (queries `decisions/` + `annotations/`).
