# Song authorship — the source model

**Status:** MODEL (2026-06-16). Basis: design discussion (brooks@tangentry.com)
during the NODE-ADDR doc pass, pressure-tested against five real workflows (below).
Sibling of [`arrangement-model.md`](./arrangement-model.md) (the *musical-dimension*
taxonomy) — this is the orthogonal *authorship-medium* model: **where a song's
authorship lives, and why.**

---

## Thesis

A song's authorship lives in **three source legs** that all converge on **one
truth — the DB + its event stream.** No single artifact is "the source"; each leg
is an *input projection* onto the DB, authoritative for a different *nature* of
state.

1. **Generative code** — `build.py` (Python via `hallucinote.generators` + the
   arrangement model).
2. **Materialized state** — `captured_session.json` (+ the DB rows it and pull
   write): the mix layer and captured gestures.
3. **Recorded assets** — audio takes / samples: files referenced by the song,
   not regenerable from anything.

(The **WHY** corpus — `decisions/`, `annotations/`, `attempts/` markdown — is
orthogonal: it records *why*, never *what*. See
[`song-conventions.md`](./song-conventions.md).)

---

## The reframe: materialized vs generative

This mirrors the DB's own trajectory (materialized state today, event-store seed
for tomorrow): **a store that is simultaneously the source AND the materialized
state is the smell.** Composition doesn't have it — `build.py` *generates*, the DB
*materializes*. The mix layer historically *did*: `captured_session.json` was both
the authored source and the materialized state, with no generative source above it.

The fix isn't "move the mix layer into code." It's to recognize that **most mix
state has no generative source to lift** — and give code a home only for the part
that does.

---

## The decision principle

> **Is there a rule or computation?**
> - **Yes → `build.py`** (generative). A loop, a condition, a value that's a
>   *function* of something (section energy, a cross-chain rule).
> - **No → materialized state.** A fixed value, a *discovered* fact, **or a
>   recorded gesture** — there is nothing to "generate," so the artifact *is* the
>   value. Audio takes go to the **asset** leg.

The earlier crude cut was "static → snapshot, time-varying → code." That's wrong:
a **hand-ridden automation lane is time-varying but recorded, not generated** — so
it's materialized state, not code. The real cut is **generated vs recorded**, not
static vs moving.

---

## The three legs in detail

### 1. Generative code — `build.py`
- **What:** composition (notes, clips, arrangement, cue points, meter) and any
  *computed* mix (a rule across chains, energy-coupled sends, programmatic choke
  grouping). Pure symbolic math — no Live round-trip needed.
- **How it reaches the DB:** generators → mutators → events fall out
  (`feedback_mutator_discipline`).
- **Why code wins here:** only code expresses a rule; JSON can only hold its
  unrolled output, losing the intent.

### 2. Materialized state — `captured_session.json` (+ DB)
- **What:** the mix layer — device chains, `params_dialed` (by-ear scalar knob
  values), sends, mixer state, routing, **per-chain props** (choke/out_note +
  chain mute/solo/volume/pan), nested rack chains; and captured gestures the LOM
  lets us read.
- **Why the snapshot, not code:** this state is either *discovered from Live* (a
  preset URI resolves to a FileId only Live knows; param values normalize against
  Live's display curves; kit pad-notes are probed) or a *by-ear scalar* (the
  number **is** the decision — `comp.threshold(-8)` and `{"Threshold":"-8 dB"}`
  are isomorphic, and code would *discard* the capture-by-ear loop producers
  actually work in). It is fully reproducible: git-tracked, replayed through
  mutators, surviving `build.py --reset` and re-push **without saving the `.als`.**
- **Authored two ways, same shape:** hand/LLM-written into the JSON *composer-time*
  (`/song-pick-instruments` writes it "before Live touches anything"), OR captured
  from manual Live edits (`/song-snapshot`, `capture_cli execute`) — capture is
  *one way to populate it*, not the only way. See
  [`docs/snapshot-schema.md`](../../docs/snapshot-schema.md).

### 3. Recorded assets — audio takes
- **What:** a recorded vocal/instrument take, a one-shot sample. The *source is a
  human performance*; it is not code and not a value.
- **How it persists:** keep the **asset** (the WAV in the repo / sample store) +
  a reference. Reproducibility means *retaining* it, never regenerating it. The
  symbolic layers (`build.py`) are built *around* it.

---

## One source of truth: the DB + event stream

All three legs project onto the DB; both `build.py` and capture write through the
**same mutators**, and the **actor model** arbitrates a contested cell (capture/pull
land as `actor='sync'`; generative writes as a build actor; `_LATEST_ACTOR_EVENTS`
decides). So "code vs snapshot for the same chain" is **not** a new conflict to
invent — it's the existing actor precedence, applied to the mix layer. This is also
the seam the future event-store flip rides on.

> **Correction (2026-07-04, BAK-7D2V):** the paragraph above overclaims. Actor
> precedence cannot arbitrate **pull vs snapshot-replay**, because *both* write as
> `actor='sync'` — so a `build.py` re-run's `replay_capture` silently re-asserted
> stale snapshot values over newer pulled live edits (the pull-durability hole).
> The fix (a `captured_at`-anchored replay guard + the enforced pull→bake→build
> staging contract) lives in
> [`plans/BAK-7D2V/design.md`](./plans/BAK-7D2V/design.md).

---

## Pressure test — five real workflows

| Workflow | Nature | Lives in | Round-trips? |
|---|---|---|---|
| Static synth part, then automate a param | by-ear value **+** generated curve | snapshot (`params_dialed`) **+** `build.py` (envelope). Live's own playback semantics let the envelope override the parked value — no conflict | OUT clean; read-back OK if clip-hosted, write-only on the perform route |
| Swap a drum rack (project-time) | discovered device; composition adapts | snapshot (the chain); `build.py` stays kit-agnostic via `Kit.pitch_of("kick")`; pad-notes auto-populate on push | clean |
| Add/change a choke group | relational, **static** wiring (not automatable) | snapshot today; a *rule* ("choke all hats") is the case for the future code hook | clean (re-asserted on push via the `chain` terminal) |
| Hand-ride levels/pan in Live, sync back | **recorded performance** | — | **OUT works; READ-BACK blocked** (open problem #1) |
| Record a vocal, build a song around it | **recorded asset** | external asset + `build.py` around it | audio is an immovable seed (open problem #2) |

The first three confirm the model. The last two exposed the **recorded-performance
leg** — and showed its real limiter is not where the bytes live but **what the LOM
lets us read back.**

---

## Open problems

### 1. Hand-ridden automation read-back (LOM wall)
We *write/perform* automation out cleanly, but a human riding faders writes
**arrangement automation**, which has **no LOM read surface** and **no enumeration**
(`ableton://guides/gaps` — "write-only … no read surface"; `action='list'`
unsupported). So "sync the ride back" is the broken half — no storage choice fixes
it. **Direction (unresolved, needs live tests):** see whether Ableton can be made to
*play the ride out* so it's captured as MIDI/events, or another creative route;
**parsing the `.als` is the worst-case fallback we'd rather avoid.** Until then a
hand-ride lives in the `.als`, or the human re-states the intent and we author it
generatively in `build.py`. Tracked as backlog `ING-9H2T` (with the existing
automation-ingest cluster `ING-1R4C` / `ING-2S7K` / `ING-4P2M` / `ING-5W8H`).

### 2. Recorded audio as a song's origin
The symbolic model has no generative source for a take, so the honest answer is the
asset leg: host the recording, build around it.

**The stated blocker is refuted.** This used to say Live won't let us create session
audio clips. `ClipSlot.create_audio_clip` and `Track.create_audio_clip` landed in the
12.2 cycle, were probe-confirmed on 12.4.1, and the bridge now uses both: an authored
clip places into a slot and the arrangement, and a clip dropped in by hand comes back
on pull. So placement is not the open half.

What is still open is **ergonomics** — where the asset store lives, how a song
references a source, and what a derived file has to record to stay regenerable. That
is SMP-6V2K wave 3's, and the requirements for it are written (R1.6 provenance, R1.7
recipe-regenerability): sources immutable under `assets/sources/`, every derived file
the output of a recorded recipe, because a song that only has the WAV has lost its
source.

### 3. Parametric / computed mix authoring (the `build.py` mix hook)
There is no path today to compute mix state in code (a rule across chains,
energy-coupled sends, programmatic choke groups). It's a clean capability — a
`build.py`-callable mix-authoring surface writing through the mutators, reconciled
by actor — but **speculative until a song needs a computed mix value**
(Proportional Effort). When one does, that's the forcing function to build it.

---

## The kicker

"All authorship in code" *can't* hold — and it's physics, not a design miss: a
performance isn't code (it's a take), and Live barely lets us read one back. So the
deciding constraint for performance-shaped state is **"can we even get it back from
Live,"** a far harder limit than where a value's text lives. The model is three
legs, unified at the DB+events, **bounded by the LOM read surface.**

---

## See also
- [`docs/snapshot-schema.md`](../../docs/snapshot-schema.md) — the materialized-state shape (`captured_session.json`)
- [`docs/song-authoring-conventions.md`](../../docs/song-authoring-conventions.md) — the author-facing "how"
- [`arrangement-model.md`](./arrangement-model.md) — the musical-dimension taxonomy (orthogonal axis)
- [`song-conventions.md`](./song-conventions.md) — the WHY corpus (decisions/annotations/attempts)
- `ableton://guides/gaps` — the LOM read/write walls that bound the recorded-performance leg
