# Canary: `full-band-rock`

## Shape

A 3-minute mid-tempo rock song in E minor. **Eight tracks**: drums (MIDI), bass (MIDI), rhythm guitar (audio placeholder), lead guitar (audio placeholder), keys (MIDI), backing-vocal pad (MIDI), lead vocal (audio placeholder), parallel-comp bus (audio routing target). **Three return tracks**: vocal reverb, drum room, master bus comp send. **Master**. **108 BPM**, **4/4**.

Section shape:

| Section | Bars | Vibe |
|---------|------|------|
| `intro`     | 1–8    | Drums + bass only, building. |
| `verse`     | 9–24   | Add rhythm guitar + lead vocal. |
| `chorus`    | 25–32  | Full band, backing-vocal pad, lead guitar fill. |
| `verse`     | 33–48  | Repeat verse shape with lead vocal lyric variation. |
| `chorus`    | 49–56  | Repeat chorus. |
| `bridge`    | 57–64  | Drop to keys + lead vocal only. |
| `chorus`    | 65–72  | Final chorus, all in. |
| `outro`     | 73–80  | Tag of chorus (original brief: fade via master automation — refused in v1, see below). |

Mixing intent:

- Drum bus → Return A (Drum Room reverb), ~25% send.
- Vocals (lead + backing) → Return B (Vocal Verb), ~30% send.
- Rhythm guitar + bass → bus-comped via Return C (Bus Comp send), ~100% send (parallel).
- ~~Lead vocal sidechained to drum bus via a dummy compressor on the lead-vocal track.~~ Refused in v1 (W10-F D3 — the lead-vocal track is `kind='audio'`, which can't host MIDI session clips in v1, and Hallucinote routes mixer/send/device-parameter envelopes through them). v1.1 sub-bus pattern would route the lead vocal into a kind='midi' group track and host the sidechain envelope on the group's mixer.
- ~~Master automation: -∞ to 0 over 4 bars at `outro` start (fade-out).~~ Refused in v1 (W10-F D2 — Live LOM has no master envelope creation path; master can't host clips). Same v1.1 sub-bus pattern applies (drum + bass + group route into a master sub-bus, fade lives there).
- One third-party VST instrument on **Keys** (Spitfire LABS or whatever the agent guesses — point is to surface the case-B-missing-plugin path).

**Status (2026-05-20):** Wave 0 surfaced the master-fade + lead-vocal-sidechain envelope targets as architectural blockers (bug-triage Group D); W10-F shipped dual-layer (DB + planner) refuse-with-teaching for D2 (master) + D3 (audio-track) hosts. The canary's `build.py::_author_envelopes` is now intentionally empty and documents the v1.1 sub-bus pattern as the working alternative. See `ableton://guides/gaps.md` Group D for the LOM rationale.

**Superseded (2026-06-11):** ENV-7G4K replaced the D2 master refusal with performed automation — master/group/return envelopes are now gesture-recorded into arrangement automation by push. D3 (audio-track hosts) remains refused pending ENV-8H1T. See `docs/song-authoring-conventions.md` "performed automation".

## What this canary exercises

**Third-party plugin path (Wave 13's target).** Keys uses a VST that may not be on the consuming machine. Exercises whether the capture/snapshot records enough identity to round-trip, and whether the push planner refuses gracefully when the plugin is missing. *(W13-A and W13-B aren't built yet; the canary's job is to confirm what happens TODAY — silent failure? confusing error? — so triage knows what shipping W13 actually buys.)*

**Audio-track placeholders.** Four of the eight tracks are "audio" in the sense that they'd hold audio clips in production. The DB doesn't yet model audio clips (`scope.later`). Exercises the "track exists but has no MIDI clips" + "what does the push planner do" path.

**Routing complexity.** Sidechain, parallel comp bus, sends-to-returns at varying levels. Exercises the routing pull/push surface AND surfaces what isn't modeled yet (track routing is `scope.later` per project-state.yaml).

**Many tracks (8 + 3 + 1 = 12).** Stresses any place a planner serializes per-track work — push progress lines, capture probes, mix snapshot rows.

**Repeated sections (verse twice, chorus three times).** Falling-walking has one verse + one chorus + one chorus_twist. Three+ literal-repeats of the same section name exercises whether section identity is `(song_id, name)` or `(song_id, name, occurrence)` and how the arrangement planner places repeats.

**Master automation tail.** ~~Master-fader fade-out at outro is a full-clip-length envelope on the master track. Exercises whether master is treated as a first-class track for envelopes.~~ Wave 0 answer: master is NOT a first-class envelope target (Live LOM constraint — Clip.create_automation_envelope is the only path, and master can't host clips). W10-F now refuses these targets at the DB-mutator layer; the v1.1 sub-bus pattern is the working alternative.

## Out of scope for the canary

- No actual audio recording; "audio" tracks hold empty placeholder clip rows.
- No nested racks beyond the stock Drum Rack on Drums.
- No tempo / signature changes.

## Success criteria for the agent

Same as `solo-piano-ambient.md` — scaffold + build.py + captured_session.json + tests, record every friction, do not push to Live.

Specifically log the following whether or not they fail:

- **What does the capture format do with audio tracks?** Surface whether the schema even supports a track without MIDI clips cleanly.
- **What does the snapshot record about a VST instrument?** Class? FileId? Display name? Manufacturer? (Without the answer, W13-A can't be designed correctly.)
- **How are repeated sections named in build.py?** Does the agent reach for `chorus`, `chorus_2`, `chorus_3` ad-hoc, or does the library offer a pattern? If ad-hoc — *that's a finding*.
- **Sidechain modeling — does it round-trip through the DB at all today, or is it Live-only state?**
