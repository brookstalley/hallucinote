---
date: 2026-08-06
kind: decision
scope: song
tags: [sound-design, chains, production, orchestration]
---

## Context

The brief asks for instrumentation that "varies hugely" across a 46-second piece —
eight distinct sonic worlds, where the instrumentation change IS the content rather
than decoration on it. It also names the production arc precisely: slick throughout
(great stereo, reverb, clever delays, flange/phase on key parts) EXCEPT the 5/8
bridge, which must be raw — "like a punk rocker left alone with a 4 track."

Chains are authorship here, not a mix-time follow-up. A song that traverses this
much ground needs its contrasts built into the signal path, because no amount of
note-writing makes a rock band and an orchestra sound like different ensembles if
they share a reverb.

## Decision

Twelve tracks, three returns, stock Live only. Live Suite confirmed by browser
probe (Analog, Collision, Drift, Electric, Meld, Operator, Sampler, Tension,
Wavetable + 47 audio effects).

    #   track           chain                                          owns
    1   Sub             Operator -> Saturator -> Utility(mono)         the D->Ab->D bass move
    2   Bass            Analog -> Overdrive -> Amp -> Glue Comp        verse rock, reprise
    3   Kit Rock        Kit-BritishVintage -> Drum Buss -> Glue Comp   verse 4/4, reprise
    4   Perc            Percussion Core Kit -> Comp -> EQ Eight        the 3/4 answer + march
    5   Machine         606 Core Kit -> Gate -> Redux -> Overdrive     the bridge, alone
    6   Keys            Electric -> Phaser-Flanger -> Echo             verse stabs
    7   Brass Stab      Brass Ensemble Sforzando -> Saturator          the angry answer
    8   Brass Sustain   Brass Ensemble Legato -> EQ Eight              chorus radiance
    9   Bells           Collision -> Delay                             intro motif
    10  Pad             Wavetable -> Auto Filter -> Utility(wide)      intro layering -> chorus
    11  Lead            Operator -> Saturator -> Echo                  bridge machine lead
    12  FX              Operator -> Auto Filter                        riser, impacts

Returns: **A-Hall** (Hybrid Reverb) · **B-Room** (small Reverb) · **C-Delay** (Echo).

The send matrix carries as much of the authorship as the inserts do:

    track           hall    room    delay
    Sub               -       -       -      subs stay dry; reverb on a sub is mud
    Bass              -     0.08      -
    Kit Rock        0.10    0.15      -      a live-room band, not a hall band
    Perc            0.30    0.10      -      orchestral percussion belongs in a hall
    Machine           -     0.22      -      <- THE POINT
    Keys            0.15    0.10    0.18     the brief's "clever delays"
    Brass Stab      0.22    0.10    0.12     present and angry: close, not distant
    Brass Sustain   0.38    0.05      -      the most hall in the song
    Bells           0.45      -     0.30     intro spookiness = distance
    Pad             0.42      -     0.10
    Lead            0.18    0.08    0.25
    FX              0.35      -     0.20

## Why

**The Machine row is the whole production argument.** Every other track in the song
lives in the same two spaces. The bridge lives somewhere smaller and drier than
anything else — no hall, no delay, a single small room at 0.22 — and its inserts
(Gate, Redux, Overdrive) subtract rather than flatter. That contrast is authored in
the send matrix and cannot be recovered at mix time by turning something down; it
is a different room, not a different level. Pairing it with the bridge's exactly-zero
microtiming (see 03-the-microtiming-arc) means the section is inhuman in *both*
dimensions at once, which is what makes two seconds of 5/8 land as dread rather than
as a dropout.

**Two brass tracks, not one, because articulation cannot be automated into
existence.** `Sforzando` is a sudden accented attack; `Legato` is a sustained line.
One patch cannot be both, and the song needs the same ensemble to be furious in the
verse and radiant in the chorus. Splitting attack from sustain also gives the
section real register spread — a brass section rather than a brass patch.

**Instrument choices trace to a section each, not to a genre default.** Electric
(tine piano) through Phaser-Flanger is the brief's "flange/phase on key parts"
landing on the one instrument that plays in both the rock verse and nowhere else.
Collision for the intro is struck-metal physical modelling: it decays, so a motif
stated in bell tones has silence around it, which is what makes six bars of layering
read as tension rather than as a pad swell.

## Narrative to sound

The orchestration is a SECOND instance of the song's thesis, and this was the
owner's idea rather than the agent's. The 3/4 answer is not a waltz instrument — it
is the brass section of an orchestra, annoyed, responding to these kids' rock and
roll, with orchestral percussion playing a rock 3/4 rather than a polite waltz. The
same brass section that is furious in D minor at the verse is radiant in Ab Lydian
at the chorus. Same ensemble, reframed — exactly what the five-note chord does
harmonically (01-the-tritone-transfiguration), landing on the same bar.

So the ensemble narrative is: the rock band calls; the orchestra answers, irritated;
the machine obliterates both; the orchestra returns transfigured; the rock band
rejoins it for the reprise. The brief's "bring in hints of the verse's
instrumentation" becomes a reconciliation rather than a callback.

## Open — portability, flagged not resolved

The `Brass Ensemble` racks are very likely orchestral **Pack** content, not base
install. The design requires stock-only so a reader can rebuild the song, and a
reader on Live Standard would hit a loud `preset_query` failure at push. Proceeding
with sampled brass because the owner directed the orchestral character and it is
the better music; the strictly-portable fallback is `Poly Synth Brass` / `Saw Pure
Brass` (Analog) or `Prime Brass` (Drift).

**Standing obligation:** run `hallucinote compat check` before the tour ships, and
state the result in the tour rather than letting the reproducibility claim go
unverified. A demo whose job is to prove reproducibility must not itself be
unreproducible.

Decided by: agreed-after-confirm (palette proposed; the owner rejected both offered
forks and supplied the angry-orchestra idea, which is the better one and is what
shipped).
