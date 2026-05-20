---
date: 2026-05-20
kind: decision
scope: song
decided_by: agreed-after-confirm
tags: [instruments, portability-strict, preset-query, mix-time-followups]
---

# Instrument picks (portability=strict)

## Question
Which stock Live devices carry each of the four parts?

## Answer
Written into `captured_session.json` as composer-time `preset_query` selectors so the picks resolve on the consumer's machine at push time:

| Track | Pick | Class | Root + Pattern | Tier |
|-------|------|-------|----------------|------|
| 01 Drums       | Hot Rod Kit          | DrumGroupDevice        | `drums` / `Hot Rod Kit`        | Suite content |
| 02 Bass        | Electric Bass Raw    | InstrumentGroupDevice  | `instruments` / `Electric Bass Raw` (path_prefix `Simpler`) | Standard |
| 03 Lead Guitar | Power Chords Guitar  | Operator               | `instruments` / `Power Chords Guitar` | Suite (Operator) |
| 04 Synth Vox   | Square Dirty Lead    | Operator               | `instruments` / `Square Dirty Lead`   | Suite (Operator) |

All four patterns verified to resolve to exactly **one** match against the local browser at compose time (preset_query is strict — refuses 0 or 2+).

## Rationale
- **Hot Rod Kit** — among Live's ~140 Drum Rack kits, this is the most credibly punk/garage-rock named. None of the stock kits are explicitly "punk"; "Hot Rod" reads garage-rock-adjacent (rockabilly/raw acoustic kit) without leaning electronic (909/808) or hip-hop (Boom Bap, BNYX Boot). Alternates considered: Garage Kit, Dry Session Kit, Stark Kit, Strutter Kit — Hot Rod is the most punchy-rock fit.
- **Electric Bass Raw** — the only stock device that literally says "electric bass" + "raw." Sampled (not synthesized), Standard-tier. Could be wrapped in additional saturation at mix time but the raw character already carries.
- **Power Chords Guitar** — Live's stock catalog has no real distorted-electric-guitar instrument. Sampled clean/muted guitars (`Guitar Electric Muted`) are too polite for punk; Tension's "Hard Picked Guitar" is too polished. The Operator FM preset literally named for power chords is the closest match in spirit. Mix-time follow-up (see below) is mandatory.
- **Square Dirty Lead** — Operator preset with dirty square-wave character. Punk-sneer translated to MIDI. Pairs naturally with the staccato vocal-substitute role: short note events with bite. Mix-time follow-up: tighten envelope release so each "syllable" is clipped.

## Suite-tier dependency
Three of four picks need Live Suite (Hot Rod Kit content is Suite-pack; Operator is Suite-only). Bass is Standard. If a collaborator on Live Standard tries to push this song, three of four loads will fail. The strict-Standard alternates exist but degrade the musical fit — left for a future "low-tier port" if needed.

## Mix-time follow-ups (compose/push doesn't handle these)
- **Lead Guitar** — add Saturator / Amp / Pedal post-instrument on the chain to sell distorted electric guitar. Without it, Operator alone reads "synthy power chord," not "punk guitar."
- **Synth Vox** — dial Operator's amplitude envelope release down (target ~30-60ms) for staccato. The preset's default release is too long for the vocal-syllable feel.
- **Drums** — Drum Buss + Saturator on the bus is mandatory per the punk-energy aesthetic decision; not strictly an "instrument" choice but worth flagging here.
- **No sidechain** anywhere — punk doesn't pump (per `07-energy-aesthetic.md`).

## What this binds
- `/ableton-push punk-fate --new-session` will resolve all four `preset_query` selectors via `ableton_browser(action='search')` and load the picks. If any pattern stops matching exactly one (Live update changed a name, pack uninstalled), push fails fast — that's the strict guarantee.
- Recapture (`tools/capture_cli.py` after push) will replace the `preset_query` with the per-machine `guess_uri` and capture the params actually loaded by Operator. That's the authoritative snapshot going forward.
- The mix-time follow-ups above are NOT in the snapshot today — they happen post-push, manually or via subsequent `/song-snapshot` refresh after the chain is dialed in.
