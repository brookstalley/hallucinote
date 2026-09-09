---
date: 2026-08-10
kind: attempt
scope: song
tags: [mix, loudness, clipping, masking, bass, sends, reverb]
outcome: kept
resolution: kept
---

First render: **+5.5 dBTP, 257 overshoots**, bass the maskee in 8/8 sections at
−18.7 LUFS-I, returns effectively silent (−62 / −49 LUFS-I).

**Kept:** a full re-balance around the bass (drums −6.2, bass −0.8, guitar −4.9,
voice −12.0, master −4.0), sends raised 2–3×, reverb decay 2.50 s → 1.10 s.
A/B against `db_seq` 727 confirmed **+5.51 → +1.29 dBTP, overshoots 257 → 1**.
Baked into `captured_session.json`, so it survives `build.py --reset` — verified
by rebuilding and re-pushing `mix` (22/22) + `devices` (0 calls, already current).

**The trap worth remembering:** the analyzer captures stems PRE-fader, and this
run's `master_fader_db` came back stale (0.0 vs Live's 0.775). So per-stem LUFS
and per-section masking were byte-identical before and after a real 4.2 dB bus
change — reading those rows as "the fix didn't work" would have been wrong, and
reading them as "the bass is still buried" would also have been wrong. Judge a
level move on the master bus + Live readback, not on the pre-fader stem rows.

**Still open:** whether the bass is genuinely clear of the bed is UNMEASURED for
the reason above. Next pass re-reads it; if still 0.6+, the fix is a
complementary 250–500 Hz cut on the guitar, not more fader.

Filed as [[../decisions/07-the-bass-carries-the-engine]].
