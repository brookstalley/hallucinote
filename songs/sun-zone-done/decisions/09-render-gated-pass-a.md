---
date: 2026-06-03
kind: decision
scope: song
tags: [mix, render, reverb, drums, outro, skank, break-drift, render-gated, handoff]
related: [decisions/08-back-half-reinvention.md, annotations/mix-intent-per-section.md]
---

# Render-gated Pass A — the user's six listen-back notes

**Question (user, 2026-06-02):** Six directed notes from a listen of the back-half song:
1. the SECOND metal section needs the same one-beat-early fix as the first;
2. the break's metal guitars are too loud / too foreground — deep reverb + phasing/flanging;
3. the skank guitars sound too small — maybe a chorus? (research what great reggae uses);
4. add a gradually deepening reverb to the intro that snaps back at verse1;
5. the outro is great but ends abruptly;
6. the development metal drums are too loud / repetitive / jarring — integrate them, don't just play on top.

**Decided by:** Claude (autonomous), against the objective MixReport. The *ear has not yet ruled* on
the subjective items — see "Needs the ear" below.

## What shipped (Pass A — code + tests + render-verified where measurable)

| # | Change | Where | Render-verified? |
|---|---|---|---|
| 4 | Intro Plate send now **RAMPS** (0.12→0.58) across the dawn cloud, snapping back at verse1 (clip-local host). Drums ramp too (0.10→0.40). `_author_atmosphere_envelopes` gained a ramp mode. | `build.py` `_ATMOSPHERE`, `_author_atmosphere_envelopes` | ✅ Plate return −53→−42 dB across the intro |
| 5 | Outro **dub ECHO-OUT** (user-chosen idiom): `_outro_dub_ending` lands a sustained Em9 button + final snare and drops the groove; `_author_outro_throw` swells drums/organ/lead/steel into the DubDelay so the chord rings/echoes out. | `build.py` `_outro_dub_ending`, `_author_outro_throw` | ✅ DubDelay return −inf→−44 dB at the outro; organ −19.8→−18.6 |
| 6 | Development metal drums pulled toward the reggae one-drop bed (kick/snare/**hat** velocities down, crashes thinned to 2 structural hits) so they weave in, not on top. Gallop identity kept. | `build.py` `_dev_collision.metal_bar` | ✅ dev drums −7.1→−8.0 (section avg; metal *bars* much lower) |
| 2 | Break metal-guitar drift washed **DEEP** into the Plate (new clip-spanning gtr send lane) + ghost gain 0.5→0.40. | `build.py` `_author_break_drift_reverb`, `_GTR_BREAK_GHOST` | ⚠️ partial — see "Needs the ear" |
| 1 | The metal-steal (`_interrupt_tail`, "the metal STEALS the reggae's last beat") was already applied to **both** choruses in back-half v4 (`next_metal=chorus1` and `=chorus2`). | already in `build.py` | ⚠️ timing needs the ear |

Master is clean: **−0.87 dBTP, 0 overshoots**. Findings dropped 7→3.

## Two render-pipeline truths discovered (important for every future render-gated pass)

1. **The arrangement is a SNAPSHOT — re-pushing notes/envelopes does NOT refresh it.**
   `duplicate_to_arrangement` copies session clips; the push is idempotent on the
   `arrangement_clip` link, so after a re-push the arrangement phase reports
   "skipped (idempotent)" and the render plays the *old* arrangement. The fix (now the
   standard re-render workflow): **clear the arrangement clips in Live** (`ableton_clip
   action='delete' location='arrangement'`, descending index per track), **drop the
   `arrangement_clip` links** (`M.unlink_db_from_ableton`, actor=`sync`), then re-push —
   the arrangement rebuilds from the updated session clips (`arrangement 38/38 ok`).
2. **Per-stem WAVs are captured PRE-FADER** (post-device-chain, before the mixer fader).
   So `mixer_volume` / `mixer_pan` automation does NOT show in the stems or the
   stem-based **masking** analysis — only `send_level` (via the return stems) and the
   master do. Consequence: the break-drift volume dip (the *reliable* cut, since the
   Heavy-amp distortion floors velocity) is **invisible to the masking metric**. The
   break masking still shows the drift masking steel 0.89 — but that's the pre-fader
   stem; the dip + deep reverb are working in the master. **#2's final level must be set
   by ear.**

## Needs the ear (NOT yet done / not merge-ready without a listen)

- **#1 steal timing** — present in code for both choruses; render can't judge the felt
  "on 4 not 1". Tune `_interrupt_tail` `steal_beats` / `lead_gap` / `groove_gap` by ear.
- **#2 break drift level** — deep reverb + 0.40 gain dip are a reasoned first pass. If
  still too foreground, lower `_GTR_BREAK_GHOST` further (it's the reliable post-fader
  lever) AND add the phaser below.
- **#3 skank too small** — NOT addressed yet; it's device sound-design (see recipe).

## #3 research finding — chorus is the WRONG move

Researched what acclaimed reggae (Studio One, King Tubby, Sly & Robbie) uses to make a
skank big without losing the chop. **Chorus is folklore and the move most likely to make
the chop worse** — it smears the transient. The real recipe, ranked:

1. **Width** — double-track + hard L/R pan (biggest win, no smear). Single-track proxy:
   `Utility` Width ~135% + a haas slap (Echo L 50 / R 70 ms, ~0 feedback).
2. **EQ "chank" carve** — this is where "thin/small" lives: HPF ~130 Hz + **+3–5 dB bell
   at ~3 kHz** + small air shelf ~8 kHz. (The gtr already has an EQ Eight to set.)
3. **Spring/plate reverb** on a send, pre-delay ~20 ms so the dry transient lands first.
4. **Short dub/slap delay** (Echo, dark repeats) — reggae-only; metal stays dry.

## Deferred to the ear-session: the device sound-design (#2 phaser + #3 skank)

Authored as a *recipe*, not blind code, because device params must be tuned by ear and
adding device chains blind risks the device-load. Capability is confirmed: continuous
`device_parameter` automation exists (session-clip-routed like the Amp Type envelope), so
a break-gated Phaser is fully authorable.

- **#2 Phaser/Flanger:** add a stock `Phaser-Flanger` to the `03 Rhythm Gtr` chain (after
  Cabinet). Author a `device_parameter` Dry/Wet envelope bookended 0 except the break
  (~0.6 in [480,544)) so the ghosted drift becomes a distant swirl. Combine with a lower
  `_GTR_BREAK_GHOST`.
- **#3 skank bigger:** add `Utility` (Width ~135%, mono-checked) to the gtr chain; set the
  gtr's existing `EQ Eight` to the chank carve (HPF 130, +4 dB @ 3 kHz Q≈1, +2 dB shelf
  @ 8 kHz); add a reggae-gated gtr send into Plate (space) + DubDelay (slap), ~0 in the
  metal/break/integration cells. Widen via a real doubled take only if width alone isn't
  enough by ear.

## Also noted (pre-existing, not Pass A)

- Reverb RT60 vs declared intent is slightly out of tolerance: Plate 3.23 s vs 3.0
  declared (close); **Room 1.24 s vs 0.8 declared** (the Room preset is not as tight as
  intended). Recalibrate either `_INTENDED_RT60_S` or the Room decay — a small follow-up.
