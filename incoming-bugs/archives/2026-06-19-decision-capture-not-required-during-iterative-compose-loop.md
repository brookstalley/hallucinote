# Methodology gap: decision/intent capture is checkpoint-based, but most song decisions are made DURING the iterative compose loop — which has no capture discipline

**Severity:** H (methodology). The `decisions/` corpus is the song's most valuable
and least-recoverable artifact (it's what survives `/clear`, what `/song-context`
serves). Yet on a long, deeply-iterated song almost none of the real decisions
reached it until the user explicitly asked "did we capture all this?" The WHY of
~10 substantial creative/production choices lived only in chat + as terse code,
not in the queryable decision record. The framework should *require* this, not
rely on the agent or the user remembering.

**Engine version:** `0.1.0+b66e0a9b729d`. **Surfaced on:** song `alien` (this session).

## What happened (the evidence)
`/song-new` wrote the initial intent decisions (01–04). Then over a long
compose→push→react→refine collaboration, these decisions were made, applied to
`build.py`/`captured_session.json`, and **never recorded** until the user prompted
a documentation pass at the end:
- the microtiming **feel arc** (verse push / pre-chorus settle / chorus drag) — *authorship*, undocumented
- the chorus **descending line** + the **low-fifth drop** (committed landing)
- the NIN-"Wish" **chaos burst** (a whole sound-design subsystem + a dial knob)
- the intro **reverb deepen-then-snap**
- the **C1→V2 hand-off** + the **V2 re-entry plan** (modulation/fragmentation/infection)
- the **signal chains** (the `/song-pick-instruments` "write a signal-chain decision" step was skipped under delegation)
- the **baked mix levels** (Alien −9 dB, Riff −10 dB + distortion)

Separately, the derived overview went **stale**: `alien.md`'s structure table and
the `build.py` docstring still held the scaffold defaults (8×8-bar sections, "this
session composes Intro + Verse 1 only") long after the form had tripled and three
sections were composed.

## Root cause (the honest introspection)
1. **Capture is front-loaded + checkpoint-bound.** The only places the methodology
   prompts decision/intent capture are `/song-new` (Phase-1 must-haves) and the two
   review skills' LEARN-BACK (`/compose-review`, `/mix-review`). But the *bulk* of a
   song's decisions are made in the **iterate loop** between those checkpoints —
   and `/compose-part` (the author-as-code loop) and the sound-design/automation
   work prompt **no** rationale capture at all. So decisions accumulate in
   conversation + code and silently evaporate from the record.
2. **"Authorship ships in code" masks the WHY-gap.** The norms "sound design is
   composition" / "microtiming feel is authorship" correctly say the moves live in
   `build.py`/the snapshot — but that captures the **WHAT**, not the **WHY** (the
   rationale, and especially the cross-cutting *narrative→sound mapping* that has no
   home in code). The framework implicitly treats "it's in the code" as
   "documented." A reader sees `feel_shift(..., RUN_PUSH)`, not "the human rushes
   ahead of the machine = fear." Comments help but aren't queryable decisions.
3. **Delegation has no capture step.** Sound-design subsystems (chaos burst, reverb)
   were delegated to subagents that authored code + reported — but neither the
   subagent nor the orchestrator was required to record the decision. Delegation
   currently launders the rationale away.
4. **The derived overview isn't regenerated.** `alien.md`'s structure table and the
   `build.py` docstring's section layout are *derivable from the form* (the `FORM`
   list / bar constants) but are hand-maintained, so they rot to the scaffold
   defaults.

A good methodology shouldn't depend on the agent's diligence under
execute-and-react pressure — it should **gate** on capture.

## Proposed fix
1. **Decision-capture in the iterate loop.** `/compose-part` (and the sound-design /
   automation paths) should *end* with a lightweight "record the decision" step —
   an ADR-style `decisions/NN-*.md` for any non-trivial creative/production move
   (a feel choice, a sound-design subsystem, a structural change, a transition).
   Make it part of the required flow the way `/song-new` does, not optional polish.
2. **Pair the "authorship ships in code" norms with "rationale ships in
   `decisions/`."** State explicitly: code is necessary, not sufficient; the WHY +
   the narrative intent belong in the decision record.
3. **Delegation must carry capture.** When sound-design/automation is delegated, the
   decision rationale must be recorded (subagent returns it; orchestrator files it).
4. **Documentation-completeness check.** Fold into the review skills and/or a
   song-level `/janitor`-style sweep: "N significant `build.py`/snapshot changes
   since the last recorded decision — capture them?" and "is `alien.md` / the
   `build.py` docstring current with the `FORM`?"
5. **Regenerate the derived overview.** Generate `alien.md`'s structure table (and
   the docstring's section layout) from the `FORM`/constants instead of letting them
   rot — or have the build emit a staleness warning.

## Repro
Scaffold a song, then iterate on it conversationally for many turns (compose a part,
push, react, tweak feel/sound/structure). Observe that nothing in the workflow
prompts recording the rationale of each move; the `decisions/` folder stays frozen
at the `/song-new` snapshot while the song (and its real reasoning) moves far beyond it.
