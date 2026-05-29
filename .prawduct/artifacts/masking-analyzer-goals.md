# Masking analyzer — perceptual & production north star

This is the **why** the technical spec (`masking-analyzer-spec.md`) serves. Read
it first. It is written from the mixing-engineer's chair, not the software
engineer's. Synthesized from research into working-engineer practice (Mike
Senior *Mixing Secrets*; Bobby Owsinski *Mixing Engineer's Handbook*; Hugh
Robjohns / Sound on Sound; iZotope, Sonible, RoEx tool docs + engineer
critiques — sources at the end).

## The core reframe: masking is not a defect to eliminate

Every shipping masking tool (iZotope Neutron's Masking Meter, Sonible smart:EQ,
soothe2) answers one question: **"where do frequencies collide?"** And every
working engineer's critique of those tools is the same: that question produces
mostly *noise*, because **masking is the mechanism a mix uses to create a focal
point and depth — not a bug.**

> "The most important signal is always the strongest signal — and is thus the
> one that tends to mask the others." — Hugh Robjohns, Sound on Sound

A dense, glued mix *relies* on masking. Carve every element into a perfectly
non-overlapping slot and you get something thin, clinical, and disjointed. The
goal is **never zero masking.** iZotope's own docs concede their meter can't
tell desirable masking ("a snare cutting through") from a problem, and ship a
*Sensitivity* slider precisely because it over-reports.

So the right question — the one a score-aware tool can finally answer — is:

> **In this section, is the element that's *supposed* to win actually winning?
> And where it isn't, what's the cheapest *musical* fix?**

That single shift — from *collision detection* to *intent verification* — is the
whole moat. We own the score, the sections, and the composer's declared intent;
no commercial tool does.

## The perceptual goals an engineer is actually chasing

A masking analysis exists to protect these, in roughly this priority:

1. **Intelligibility of the focal element.** Usually the lead vocal; its
   presence/consonant-definition band (~**1–5 kHz**) is the non-negotiable. In a
   given section *something* must be focal — the hook, the lyric, the riff —
   and it must read clearly.
2. **Clarity & separation.** The mix reads as distinct parts, not a blur. Each
   element has its own *perceptual address* = spectral slot **+** stereo
   position **+** dynamic envelope (transient vs sustain). Two parts can share a
   band without masking if they differ in time/dynamics — overlap ≠ masking.
3. **Front-to-back depth.** Masking *is* the depth tool. Foreground = louder,
   brighter, drier, present; background = darker (HF rolled off), quieter,
   wetter. Engineers *deliberately* let background parts be partly masked so the
   foreground reads as close. "Perspective is contrast." (Sound on Sound)
4. **Controlled low-mid buildup.** ~**200–500 Hz** is where most instruments
   overlap — the "mud"/"box" zone. Buildup here is the most common clarity
   killer, and the fix is distributed (small cuts across the secondary parts),
   not one cut on the master.
5. **Translation.** Low end and loudness change masking behavior per system; a
   mix that controls masking survives earbuds, a laptop, and a car. Small
   speakers expose masked midrange that big monitors hid.

## The production / composition context (why section + intent are mandatory)

**"The arrangement is the first EQ."** The cheapest, highest-leverage fix for
masking is almost never a plugin — it's the arrangement: don't have two parts
competing for the same role in the same register at the same time. Robjohns:
*"the best first step is almost always to … fine-tune the orchestration and
arrangement of individual parts to avoid masking clashes in the first place."*
Two quarter-note fuzz guitars leave no room for anything — no EQ rescues that.

**Good balance is section-dependent — there is no song-wide target.** The focal
element and the active parts change section to section:
- **Verse** — sparser; energy low/low-mid; the **lead vocal is focal**, given
  room by *removing* competitors.
- **Chorus** — "opens up"; full spectrum engaged; focus broadens to the hook /
  everything-together; bass owns the lows, vocals + leads own the top.
- **Bridge** — deliberate contrast to reset the ear.

A single full-mix spectrum or song-wide masking score measures an average that
exists in *no actual section* — it flags the chorus's intended density as
"muddy" and the verse's intended sparseness as "thin." **Section scope is
exactly what every meter lacks, and exactly what we have.**

**Role/intent decides whether masking is a problem.** Owsinski's arrangement
roles give the vocabulary — every part is **Foundation** (bass+drums bed),
**Pad**, **Rhythm**, **Lead** (focal), or **Fills**, and ~4 elements at once is
the clarity limit. From this:
- Bass meant to own the low end, kick yielding there → **correct authorship**,
  not a fault. Don't flag it.
- Anything masking the **focal vocal in the chorus** → a real problem. Flag it
  loudly.

The *same* spectral overlap is fine in one place and a defect in another. Only
knowing each part's **declared role and which element is focal in this section**
separates a defect (wrong element winning) from authorship (right element
winning). RoEx exposes manual "Importance" levels for exactly this reason; we
read it from the DB (track roles, composer annotations) for free.

## What this means the tool must output

Existing meters output spectral blobs the engineer then has to interpret. A
score-aware analyzer should do the interpretation and speak the engineer's
language:

- **Relationship-framed findings, not band numbers.** *"Chorus: the pad is
  masking the lead vocal in the presence region (2–4 kHz)"* — not "−2.3 dB in
  critical band 14." Frame by the known conflict pairs engineers already think
  in: **kick↔bass, bass↔guitar, vocal↔everything, backing-vocals↔pads,
  guitars↔piano**.
- **Musical region language** (with Hz under the hood): *sub* (20–60), *lows*
  (60–250), *mud/box* (200–500), *body/mids* (500–2k), *presence/intelligibility*
  (2–5k), *brilliance* (5–8k), *air* (8k+).
- **Per-section context.** The same overlap judged against *that section's*
  intent; fixes may be section-conditional ("duck the guitars under the vocal in
  the chorus only").
- **Intent-graded severity.** Masking *of* a high-priority/focal element = high
  severity. Masking *by* the focal element over a deliberately-supporting part =
  "encouraged," downgraded or suppressed. This is the noise filter the meters
  lack.
- **Cheapest-fix-first recommendations, never auto-applied.** In the pro order
  of preference:
  1. **Re-arrange / thin / mute** — when the collision is structural (redundant
     parts, same register, same time). The highest-leverage fix, and the one no
     meter can suggest because it can't see the arrangement. *We can.*
  2. **Complementary subtractive carve** on the *lesser* element (cut the
     competitor, don't boost the hero) — for steady tonal clashes (mud, box).
  3. **Sidechain / dynamic duck** — for intermittent collisions where both parts
     must coexist (vocal-ducks-guitars, kick-ducks-bass); section-conditional.
  4. **Pan / depth** — partial separation; flagged as weakest and mono-fragile.

  Diagnose, propose ranked options with rationale, **get out of the way.** The
  industry consensus is unanimous that auto-applying produces "generic,
  formulaic" mixes and tempts "mixing with your eyes over your ears."

## Intent taxonomy & applicability boundaries (stress-tested across styles)

The default framing above — *protect the focal element's clarity* — is **one
intent among several.** Run real music through it and it's clear the tool must
model intent explicitly or it will confidently fight the art. The axes below are
derived from mentally applying this doc to a deliberately wide set of works. We
aim to be exhaustive about **intent**, not genre.

**Element-level intent (per part, per section):**

1. **Focal** — must be intelligible / must win. Flag anything masking it.
   *Rap (the lyric is the form), a Beatles lead vocal, the AC/DC vocal over the
   riff, a Depeche Mode hook, the verse vocal in early Bowie.* This is the
   highest-value, least-ambiguous case — and the largest swath of music.
2. **Support / bed** — present, in its lane, below focal (rhythm parts, pads,
   kick/bass foundation). Masking *among* the bed is usually fine; the bed
   masking the focal is not.
3. **Blend group** — two-plus parts *meant to fuse into one composite timbre*,
   where separation would be **wrong**. Intra-group masking *is the instrument*
   — never flag it; treat the group as a single element for inter-group
   analysis. *Ravel's Boléro (the climactic horn+celesta+piccolo parallel-
   harmony doubling that fakes an organ/“new instrument”), AC/DC's doubled
   rhythm guitars as one wall, a gospel/Tallis choir, Philip Glass's interlocking
   arpeggios, an octave-doubled synth lead.* Without a blend-group concept the
   tool screams "guitar L masks guitar R" — exactly the false positive engineers
   hate.
4. **Textural / submerged** — deliberately buried as atmosphere; intelligibility
   knowingly traded for mood. Don't flag *its* being masked. Instead **invert**:
   verify the one element meant to *pierce* the wall still pierces, and flag a
   submerged part only if it's unintentionally burying the focal. *My Bloody
   Valentine's Loveless (guitars + vocal as a glorious wash), Skinny Puppy's
   Too Dark Park — "Tormentor"/"Grave Wisdom" (vocals as menace-texture in the
   murk by design), late Bowie's Blackstar unease, Phil Spector's Wall of Sound.*

**Section/song-level intent:**

- **Clarity-intended** (default) — full analysis as written.
- **Density / wash-intended** — don't chase separation; analysis collapses to
  "does the intended-to-pierce element pierce, where one is declared?"
- **Diffuse / no single focal** — ambient & evolving-texture music has no hook to
  protect; the masking-of-focal question is weak and the tool should soften to
  "is the intended space/texture-contrast present?" *Aphex Twin's Selected
  Ambient Works 85–92 (warm, spacious — the consensus "best," though his drill-
  'n'-bass like Drukqs is the opposite: intended chaos where density IS the
  aesthetic and nothing should be "separated").*
- **Saturation / no discrete elements** — **decline.** The model has no purchase:
  no focal, no roles, no separation goal. *Merzbow (harsh noise — the wall of
  spectral saturation IS the work).* The tool should *detect* this (near-flat
  inter-stem separability / one-or-no-stems / extreme broadband density) and say
  so — offer a loudness/spectral description if anything, never a list of
  masking "problems." This is the clearest "not our tool, and we know it."

**The blind spot we must state honestly — spectral ≠ perceptual masking.** The
DSP measures *spectral overlap*. The ear *also* separates sources by **pitch
streaming, common onset, and timbral familiarity** — cues the spectral model
doesn't see. So **same-timbre material over-reports**: a cappella (every part is
"voice," from a solo to Tallis's 40-part *Spem in Alium*), unison string
sections, Glass's same-patch interlock. The masked-tile ratio will read high
while the listener separates the lines effortlessly by pitch and melody.
Mitigation: when parts share an instrument class / register, weight by
melodic-line role rather than frequency band, and caveat (or down-rank) the
finding. We do not auto-flag a choir as "muddy."

**Out of scope — performance/acoustic balance.** Where the "mix" is orchestration
+ room + mic placement and there are no clean stems (a live orchestra playing
Boléro, a bleeding jazz combo), balance is a performance/arrangement act we don't
observe per-stem. Boléro is *in* scope only as an in-DAW stemmed mockup — which
is exactly how Hallucinote would build it; the acoustic recording is not.

**Validation read:** the home turf (focal/clarity — rap, Beatles, AC/DC, early
Bowie/DM, most song-based music) is enormous and high-value, and on already-clean
material (AC/DC, Beatles) the tool's *correct* behavior is to stay nearly silent.
The boundary cases tell us the required intent inputs are richer than "track
role": we need **blend-group** membership, a per-element **submerged/textural**
flag, a section/song **density-vs-clarity** intent, and a **decline detector**.
These come from the composer's declared intent — authored in the git-tracked
markdown corpus (mix-intent tags + `songs/<slug>/annotations/`, surfaced via
`/song-context`; see `intent-architecture.md`) — which is precisely the
score-awareness no meter has.

## The one-line thesis

> Commercial meters answer *"where do frequencies collide?"* Hallucinote should
> answer *"which collisions hurt the part that's supposed to win this section —
> and what's the cheapest musical fix?"* — then get out of the way.

## How this reshapes the technical spec

The DSP in `masking-analyzer-spec.md` (Bark bands → spreading function →
masked-tile ratio) is correct and stays — but it is the **measurement layer**,
not the product. It feeds an **intent layer** that the spec must now add:

1. **Inputs gain intent.** Beyond stems + sections, the analyzer needs each
   track's **role** (lead/pad/rhythm/foundation/fills) and the **focal element
   per section** — read from the markdown intent corpus (mix-intent tags +
   `songs/<slug>/annotations/`; see `intent-architecture.md`). Masked-fraction
   alone is necessary, not sufficient.
2. **Output is a `MaskingFinding`, not a raw `MaskingPair`** — carrying the
   musical region label, the role-relationship, an intent-graded severity, and a
   ranked fix list (arrangement-first). The raw masked-fraction stays as
   evidence under the finding.
3. **Severity = f(masked_fraction, maskee_role, is_maskee_focal_here).** A high
   masked-fraction on a backing pad in a dense chorus may be *fine*; a moderate
   one on the chorus vocal is *severe*.
4. **Arrangement-first recommendations require the clip schedule after all** —
   to say "both parts play here, and one is redundant" we read which parts are
   active in the section (it moves from an optional perf prune to a real input).
5. **Reporting floor + honest confidence.** Suppress sub-threshold and
   "encouraged" masking by default so the report is signal, not a wall of red.

A follow-on revision of the spec will fold these in; the DSP chunking still
holds, with an added intent-layer chunk and the role/annotation inputs wired
through the MCP handler.

## Sources

- Hugh Robjohns, Sound on Sound — *"Can static EQ tackle masking effectively?"*
  (arrangement-first; strongest signal masks others) and *"Creating a Sense of
  Depth in Your Mix."*
- Mike Senior, *Mixing Secrets for the Small Studio* — masking, mix prep,
  arrangement density; cymbals-mask-vocal example.
- Bobby Owsinski, *Mixing Engineer's Handbook* — six elements of a mix; five
  arrangement roles (Foundation/Pad/Rhythm/Lead/Fills); ~4-element limit;
  balance starts with arrangement.
- iZotope — Neutron Masking Meter / Histogram / Sensitivity docs ("encouraged
  masking," snare caveat); *"What Is Frequency Masking?"* (overlap ≠ masking);
  *"What Is Mix Depth?"* (foreground/midground/background).
- Sonible smart:EQ 3 (priority groups), soothe2 (dynamic resonance), Gullfoss
  (spectral balancer), iZotope Tonal Balance Control (bus referencing) — tool
  framings + critiques (Bedroom Producers Blog, Sound on Sound, weraveyou).
- RoEx Automix — per-track Importance levels; explicit admission AI can't infer
  narrative/emotional intent ("Use the Machine, Keep the Music").
- foxmusicproduction, Production Expert — conflict-pair framing, region
  vocabulary + Hz, arrangement-first fix order.
