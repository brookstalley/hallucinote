# Mastering practice for self-released in-the-box music — verified findings (2025–2026)

Gap-fill research for AUD-1M4V discovery (2026-06-10): the producer-practice deep
research produced no surviving mastering claims, so this pass used only checkable
authoritative sources — official platform specs (read in full), standards bodies,
manufacturer education, named engineers. Labels: CONFIRMED-official /
CONFIRMED-expert / CONTESTED.

## Q1. Platform loudness + true peak (and the "-14 LUFS target" trap)

**Spotify (CONFIRMED-official)** — support.spotify.com/us/artists/article/loudness-normalization/
- States "Target the loudness level of your master at -14dB integrated LUFS" BUT see
  contestation. Premium user levels: Loud -11 / Normal -14 / Quiet -19 LUFS.
- True peak: "below -1dB TP max"; "If your master is louder than -14dB integrated
  LUFS, keep True Peak below -2dB."
- Quiet tracks are turned UP ("Positive gain is applied to softer masters").
- Album-aware normalization (whole album, one gain).
- Normalization NOT universal: web player + 3rd-party devices don't normalize.

**Apple (CONFIRMED-official)** — Apple Digital Masters brief (apple.com/apple-music/apple-digital-masters/docs/apple-digital-masters.pdf):
- Sound Check ≈ equal-loudness playback (commonly measured ≈ -16 LUFS; brief names no
  number). "Leave at least 1 dB of headroom" (inter-sample clipping). "Mastered loud
  will be played back at a lower volume which can make tracks actually sound weaker."
- Deliverable: original 24-bit PCM, native rate, no upsampling/bit-padding.

**AES TD1008 (CONFIRMED-standards)** — aes2.org TD1008 v3.13 (Katz co-chair, Shepherd contributor):
- "Maximum True Peak level not exceed -1 dBTP" at lossy-codec input.
- Music: track-normalized -16 LUFS; "-14 applies to the loudest track of an album."
- "Does not provide recommendations for content production" — distribution spec, NOT
  a mastering target. High PLR is "clearer and less fatiguing"; goal: avoid loudness wars.

**YouTube/TIDAL/Amazon (CONFIRMED-expert-measured)** — YouTube ≈ -14 down-only
(productionadvice.co.uk/stats-for-nerds/); **YouTube Music only reduces above ≈ -7 LUFS**
(one concrete reason loud genres stay loud). TIDAL album-normalizes loudest track to
-14 (Grimm/HKU 4.2M-album study). Amazon ≈ -14 down-only, ≈ -2 dBTP observed.

**CONTESTED — "master to -14":** the mastering profession is firmly against treating
platform numbers as targets. Shepherd: "using LUFS as a target just won't work 100%
reliably – as well as being a bad idea… LUFS are the result, not the goal"
(productionadvice.co.uk/no-lufs-targets/). iZotope: "'Should I master to -14 LUFS?'
…no! Make a track sound as good as possible at as high a level as it can handle before
losing impact." Wyner: standards exist "NOT so you can use it as a target."
**True-peak consensus: -1.0 dBTP ceiling; -2.0 dBTP when mastering hot.**

## Q2. Headroom into mastering; mixing into a limiter

- Commonly requested pre-master headroom: peaks ≈ -6 to -3 dBFS, but pros call the
  number arbitrary ("the amount of headroom that a mastering engineer needs is zero,
  as long as it's not clipping" — theproaudiofiles.com). The REAL universal contract:
  **no brickwall limiting / loudness processing on the mix sent to mastering**
  (iZotope: bypass before bouncing). 32-bit float bounce makes over-0 peaks
  recoverable — "no clipping at the rendered bit depth" is the actual rule.
- **Mixing INTO a limiter: genuinely CONTESTED.** Con (SOS/Mike Senior): preview in a
  separate pseudo-mastering project; limiting "adds to the already considerable
  complication of creating a decent mix." Pro (working mixers): hear the mix at
  competitive loudness, "you're driving the limiter the same way the mastering guy
  will." Common reconciliation: monitor through it, bounce without it, or deliver both.

## Q3. In-the-box chain + ordering

- iZotope (CONFIRMED-expert, explicitly anti-dogma): "slightly more conventional to
  have the EQ first, and then the compressor" but "there are no wrong answers."
  Representative chain: corrective EQ → saturation/exciter → (multiband) dynamics →
  dynamic EQ → imager → maximizer/limiter LAST (dither after, absolute last).
- **Consensus**: limiter last; corrective EQ early; width before limiter.
  **Contested**: saturation placement; whether multiband compression belongs at all;
  comp-before-vs-after-EQ.
- Width cautions (Ozone Imager docs): "Excessive widening can reduce impact, weaken
  the center image, and cause phase cancellation when summed to mono"; artificial
  widening "best avoided unless there is a very specific and controlled reason."
- **Mono bass convention** (vinyl/club lineage): narrow from ~300 Hz, mono by
  ~150–120 Hz (masterdisk.com); driving cases are vinyl + single-sub club systems.
  Club-destined: keep low end mono below ~100–150 Hz, verify in mono.

## Q4. Never-dos (sourced)

1. Over-limiting: >~3–4 dB average GR on the final limiter → pumping; >6 dB "will only
   destroy the dynamic content" (Splice/Ozone education); AES: excessive limiting =
   less clear, more fatiguing.
2. Excessive stereo widening (mono-collapse, phase cancellation); never widen low end.
3. Skipping the mono check (phase problems, disappearing instruments, weak bass).
4. Mastering from a clipped bounce (Apple: clipped sources worsen on oversampling DACs
   and AAC; afclip catches inter-sample clipping).
5. Double-limiting (pre-limited mix into another limiter); platform-side: hot masters
   with hot true peaks risk "extra distortion… in the transcoding process" (Spotify).
6. Dither errors: dither ONLY at bit-depth reduction, ONCE, absolute last ("Any effect
   applied after dithering, even a slight gain adjustment… can undermine the positive
   effects" — iZotope). 32-bit float: no dither while staying in float.

## Q5. Release-ready checklist (each item sourced)

- Integrated LUFS (BS.1770) MEASURED and known (→ per-platform normalization offset),
  not targeted.
- True peak ≤ -1.0 dBTP (≤ -2.0 if hotter than -14 LUFS).
- Inter-sample peaks checked post-limiter; codec audition (encode and listen).
- Mono compatibility verified; mono bass below ~100–150 Hz for club material.
- Heads/tails clean, fades intentional (quiet moments expose export errors).
- Deliverable 24-bit PCM, native rate, no upsampling. Dither once, iff reducing depth,
  last. (Metadata/ISRC out of scope.)

## Q6. Genre dependence

- Wyner: classic rock PLR ≈ 8–12 dB; pop ≈ 2 dB tighter; acoustic jazz ≈ -14 RMS;
  classical 18–20 dB range; "no ONE recipe."
- Shepherd: "it makes no sense to master a folk tune at -14 and a metal track at -14";
  loudest-material enjoyment ceiling ≈ -10 LUFS.
- Community consensus (softer label): EDM ≈ -10 to -6, hip-hop ≈ -10 to -7, rock
  ≈ -9 to -8, dynamic acoustic ≈ -14 to -13 integrated LUFS.

## Requirements a production system must enable (music needs, not features)

1. Measure loudness the way platforms do (BS.1770 LUFS-I + loudest-section short-term)
   so the normalization offset per platform is KNOWN, never chased.
2. Measure TRUE peak (not sample peak) post-limiter; declarable ceiling -1.0 dBTP
   default / -2.0 hot.
3. Detect inter-sample/post-codec clipping.
4. Loudness is GENRE-DECLARED, not universal — verify against the song's declared
   presentation, never a hardcoded -14. (Same declared-profile-over-universal shape as
   the melody lens.)
5. Stage deliverables: pre-master mix bounce = real headroom + no brickwall limiting;
   mastered render = separate artifact; 24-bit PCM native rate; dither once/iff/last.
6. Mono-fold verification; mono bass below ~100–150 Hz for club-destined songs.
7. Limiter restraint is MEASURABLE — expose final-limiter gain-reduction depth
   (>~4 dB average GR = checkable pumping territory).
8. Chain ordering = convention with escape hatches (corrective EQ → glue → tone/sat →
   width → limiter → dither as scaffold, never a cap).
9. Heads/tails inspection as part of release-readiness.
10. Album-aware loudness for multi-track releases (loudest track anchors; relative
    levels preserved, measured as a set).
