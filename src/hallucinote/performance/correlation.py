"""hallucinote.performance.correlation — the structured-vs-white discriminator.

The line between HUMAN feel and SLOPPY jitter (performance-model §4.4, §7): human
microtiming deviation is *correlated* (≈1/f — Keil's "participatory
discrepancies", Hennig 2011); machine-randomized deviation ("quantize, then add
jitter") is *white* — uncorrelated. This module measures that correlation
structure over a part's ordered onset-deviation series. Pure stdlib (no numpy),
matching the rest of the ``performance`` + ``theory`` layers.

**Calibration finding (2026-05-31 — recorded in performance-model.md §7).**
DFA — the textbook 1/f exponent α (≈0.5 white, ≈1.0 pink, ≈1.5 brown) — is
UNRELIABLE on short series: averaged over 12 seeds, white reads α≈0.91 at N=16
and only converges toward 0.5 by N≳64, overlapping pink (≈1.0–1.2) at the short
end. But a part's per-section onset series IS short (often 16–32 onsets). Lag-1
autocorrelation separates cleanly even at N=16 (white≈0.05, pink≈0.37) and is
stable for white across all N (~0). So **lag-1 autocorrelation is the PRIMARY
discriminator**; **DFA α is computed only when the series is long enough to
trust** (``DFA_MIN_POINTS``) — a richer read-out over a whole-part series, never
the classifier's driver. This is the "read the numbers before asserting" DSP
discipline applied: the literal-1/f metric lost to the robust one on the data.
"""
from __future__ import annotations

import math
from typing import Sequence

# Lag-1 autocorrelation at/above which a deviation series reads STRUCTURED
# (correlated → human) rather than WHITE (uncorrelated → sloppy). The tests
# import this constant. Calibrated over 200 seeds per (series, N):
#
#     N    pink mean / p10     white mean      pink frac < 0.20
#     16     0.354 / 0.034       -0.045              24%
#     32     0.499 / 0.278       -0.016               4%
#     48     0.533 / 0.356       -0.007               2%
#     64+    0.558 / 0.430        0.000               0%
#
# 0.20 cleanly separates the population means at every N; white sits at ~0.
STRUCTURED_ACF_MIN = 0.20

# Onset count at/above which a SINGLE lag-1 acf estimate is reliable enough to
# act on (e.g. surface a "sloppy" coaching finding). Below ~32 a single pink
# draw misclassifies too often (24% at N=16) to nag a composer about — the raw
# classification is still reported as a best estimate, just not surfaced. 32 is
# where pink-false-sloppy drops to ~4% (see the table above).
RELIABLE_ACF_ONSETS = 32

# Below this many points DFA α is too unstable to report (white inflates toward
# pink — α≈0.91 at N=16). Calibration: clean separation only emerges at N≳48–64.
DFA_MIN_POINTS = 48


def lag1_autocorr(series: Sequence[float]) -> float | None:
    """Biased lag-1 autocorrelation, bounded in [-1, 1]. ~0 = uncorrelated
    (white / sloppy); positive = correlated (structured / human). ``None`` when
    fewer than 3 points or the series has zero variance (no structure to read)."""
    n = len(series)
    if n < 3:
        return None
    mean = sum(series) / n
    den = sum((x - mean) ** 2 for x in series)
    if den == 0.0:
        return None
    num = sum((series[i] - mean) * (series[i + 1] - mean) for i in range(n - 1))
    return num / den


def dfa_alpha(series: Sequence[float]) -> float | None:
    """Detrended-fluctuation-analysis exponent α (≈0.5 white, ≈1.0 pink/1-f,
    ≈1.5 brown). ``None`` when the series is shorter than ``DFA_MIN_POINTS`` —
    below that α is too unstable to trust (see the module calibration note) — or
    when the integrated series has no fluctuation to fit."""
    n = len(series)
    if n < DFA_MIN_POINTS:
        return None
    mean = sum(series) / n
    # Integrate: cumulative sum of the mean-removed series (the DFA profile).
    profile, acc = [], 0.0
    for x in series:
        acc += x - mean
        profile.append(acc)
    log_s: list[float] = []
    log_f: list[float] = []
    for s in range(4, n // 4 + 1):
        segs = n // s
        mean_x = (s - 1) / 2.0
        s_xx = sum((j - mean_x) ** 2 for j in range(s))
        fluct_sq = 0.0
        for v in range(segs):
            seg = profile[v * s:(v + 1) * s]
            mean_y = sum(seg) / s
            s_xy = sum((j - mean_x) * (seg[j] - mean_y) for j in range(s))
            slope = s_xy / s_xx if s_xx else 0.0
            intercept = mean_y - slope * mean_x
            fluct_sq += sum(
                (seg[j] - (intercept + slope * j)) ** 2 for j in range(s)
            ) / s
        f = math.sqrt(fluct_sq / segs)
        if f > 0:
            log_s.append(math.log(s))
            log_f.append(math.log(f))
    if len(log_s) < 3:
        return None
    mean_ls = sum(log_s) / len(log_s)
    mean_lf = sum(log_f) / len(log_f)
    s_xx = sum((v - mean_ls) ** 2 for v in log_s)
    if s_xx == 0.0:
        return None
    s_xy = sum((log_s[k] - mean_ls) * (log_f[k] - mean_lf) for k in range(len(log_s)))
    return s_xy / s_xx
