---
kind: decision
scope: song
date: 2026-08-10
tags: [mix, balance, loudness, masking, bass, focal, mix-review]
---

# The bass carries the engine, so the mix has to let it

**Question.** The first render came back at **+5.5 dBTP with 257 overshoots** —
hard clipping — and the MixReport named **the bass as the maskee in all eight
sections** (0.56–0.70 buried against the summed bed), while sitting at −18.7
LUFS-I, 9.7 LU below the loudest stem.

**Who decided.** inferred at `/mix-review`, applied. Two of the three fixes are
not taste calls: clipping is a defect, and the bass burial directly contradicts
[[06-the-chorus-has-to-arrive]], which holds the guitar back through the first
half of the verse *specifically so the bass carries the engine*. An inaudible
bass makes that arrangement move do nothing.

**What changed** (fader dB, before → after):

| | before | after | why |
|---|---|---|---|
| 01 Drums | +1.2 | **−6.2** | Loud, but not the loudest — the guitar is the riff |
| 02 Bass | 0.0 | **−0.8** | Barely trimmed, so it rises ~5–11 dB *relative* to everything else. This is the whole fix |
| 03 Guitar | −0.4 | **−4.9** | |
| 04 Voice | −2.0 | **−12.0** | It was the loudest stem in the song by 2 LU. A synth "vocal" that out-shouts the band stops sounding like a band |
| Master | 0.0 | **−4.0** | Headroom |

Sends came up too (the returns were at −62 / −49 LUFS-I — effectively no room at
all): drums 0.12→0.30, guitar 0.08→0.26 + delay 0.05→0.18, voice 0.18→0.38 +
delay 0.22→0.40. And the return reverb's **Decay Time 2.50 s → 1.10 s** — the
brief said *short room*, and 2.5 s is a hall.

**Verified, not assumed.** A/B render against `db_seq` 727:
**true peak +5.51 → +1.29 dBTP on the bus, overshoots 257 → 1.** With the −4 dB
master fader the delivered peak is ≈ −2.7 dBTP.

**One honest limit.** The analyzer captures stems **pre-fader** and this report's
`master_fader_db` came back stale (`0.0` while Live read `0.775`), so the
per-stem LUFS-I and the per-section masking numbers in
`analysis/20260811T051617Z.json` are **pre-fader and do NOT reflect this
rebalance** — they are byte-identical to the before-report. The evidence the
rebalance landed is the master bus (−4.2 dB, 256 fewer overshoots) and Live's own
readback, not the stem rows. **The bass-vs-bed masking figure is therefore still
unconfirmed by measurement** — it should be re-read on the next analysis pass, and
if the bass is still buried at 0.6+ against the bed, the next fix is not another
fader: it is a complementary low-mid cut on the guitar around 250–500 Hz, which is
where the report puts the collision in the verse and break.
