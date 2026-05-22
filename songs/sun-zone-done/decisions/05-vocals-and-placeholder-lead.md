# Vocals & Placeholder Lead Strategy

**Question:** The song wants vocals but we won't have them initially. How do we plan for vocals so the instrumental is compelling now AND a vocal-shaped hole is pre-carved?

**Answer:** A dedicated **lead voice track** (single track, channel-switched between clean and dirty tones per section) plays the vocal melody *now*, monophonically, in the **E3–E4 sustained register** (up to G4 for metal-shout emphasis). When real vocals arrive, this track gets muted (or repurposed as a harmony double). A second **counter-melody lead** track lives *above* E4 (B4–E5) and carries hook material that stays even when vocals come in. An empty **vocal bus** is pre-wired with sends and ducking sources so the swap is plug-and-play.

**Decided by:** user (explicit ask: "we won't have vocals to start with, but the song will want them. How do we plan for focal melody and keeping the sonic space?"), strategy proposed and agreed.

**Rationale:**

Two failure modes to avoid:
1. **Filling the hole** — composing as if instrumental, then having to rip stuff out when vocals arrive.
2. **Leaving a vague hole** — leaving the mids empty hoping vocals fill them, but without specific intent, the instrumental sounds thin and you can't tell if the song works.

The placeholder-lead approach addresses both: the instrumental version *has* the tune (sounds complete), and the vocal slot is *specifically shaped* (E3–E4, dry-center, sidechain source ready). When vocals get tracked later, they slot in exactly where the lead voice was, and the lead voice mutes.

**Composition-time rules this generates:**

- **Vocal register reserved.** E3–E4 sustained is for the lead voice / future vocals. No other instrument plays a sustained line in that band.
- **Organ skanks live above** (E4–A5).
- **Bass lives below** (E1–E3).
- **Rhythm guitar comp:** reggae skanks are short/transient (don't sustain through the hole); metal palm-mutes pack energy into 80–250 Hz, leaving 300 Hz–3 kHz mostly clear for vocals.
- **Center channel reserved.** Bass + kick own low center; everything else pans out or goes wet. Center-dry above 200 Hz stays empty — that's the vocal's seat.
- **Counter-melody lead is permanent** — it lives above the vocal register, gets written now, stays when vocals come in.

**Mix pre-wiring (ships in `captured_session.json`):**

- Vocal bus exists as an empty track routed to the vocal slot, sends matching the lead voice's sends.
- Organ and rhythm guitar have sidechain compression triggered by the lead voice track now. When vocals arrive, repoint the sidechain source from lead → vocals. Same ducking, new trigger.
- Lead voice track has reverb sends (medium plate for reggae, short room for metal); the future vocal will inherit these.
