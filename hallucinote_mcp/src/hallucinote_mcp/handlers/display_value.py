"""Resolve a parameter's display value ("-18 dB", "3:1") to a raw value.

Live's ``DeviceParameter`` exposes ``str_for_value(raw) -> display string``
(the *forward* map) but **no inverse** — a real-Live ``dir()`` of a Compressor
parameter shows ``str_for_value`` and ``value`` but no ``str_to_value`` (the
device-handler docstring once claimed one; it does not exist). So to honour a
caller's "set Threshold to -18 dB" we invert ``str_for_value`` numerically.

For a continuous parameter, ``str_for_value`` is monotonic in the raw value, so
bisection over ``[min, max]`` converges on the raw value whose display matches
the target. We parse the *leading signed float* out of both the caller's target
and each ``str_for_value`` probe and compare those numbers — unit text ("dB",
"ms", "Hz", "%") is along for the ride, not matched, because the leading number
already disambiguates within one parameter.

Two display shapes defeat leading-float parsing and MUST be refused rather than
silently mis-converged (verified against a real Compressor):

* Non-numeric displays (enums: "On"/"Off", "RMS") — caught upstream by the
  ``is_quantized`` guard, and here by "endpoints don't parse as numbers".
* Displays whose *leading* number is constant while a *later* number varies —
  e.g. Expansion Ratio renders "1 : 1.15", so the leading float is always 1.0.
  We detect this as "both endpoints parse to the same number" and refuse.

The direction of monotonicity (Threshold rises with raw value; some params
fall) is detected from the endpoints, not assumed.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

# Leading signed float: optional sign, digits with optional decimal, or a bare
# ".5". Matches "-8.40 dB" -> -8.40, "4.00 : 1" -> 4.00, "100 %" -> 100,
# "30.0 ms" -> 30.0, "3:1" -> 3, ".71" -> 0.71.
_LEADING_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")

# Real Live renders unbounded endpoints with "inf": a Compressor Threshold's
# minimum is "-inf dB", and a Ratio's maximum is "inf : 1". Both are legitimate,
# monotonic endpoints — parse the inf token as ±infinity rather than rejecting
# the parameter. Position matters: "inf : 1" has a trailing "1" that the float
# regex would otherwise grab, so parse_leading_number takes whichever of the
# float/inf tokens is LEFTMOST.
_INF_RE = re.compile(r"([-+]?)inf\b", re.IGNORECASE)

# Bisection terminates when the raw interval is this fraction of the full
# range — ~2^-40 with the iteration cap, far below any parameter's display
# resolution.
_RAW_TOL_FRACTION = 1e-7
_MAX_ITER = 60

# Intervals sampled across [min, max] to validate the leading number is a
# monotonic proxy before bisecting. Dense enough to catch a unit-scale reversal
# (e.g. a single Hz->kHz jump shows up as a large drop between adjacent samples);
# the cost is one str_for_value call per sample, all in-process on the Live side.
_MONOTONIC_SAMPLES = 64


class DisplayValueError(ValueError):
    """The display value could not be resolved to a raw parameter value."""


def parse_leading_number(text: str) -> float | None:
    """Return the leading signed number in ``text``, or ``None`` if there is none.

    Reads one number from a Live display string — a signed float, or an
    ``inf`` / ``-inf`` token (Live's rendering of an unbounded endpoint). When
    both a float and an inf token are present, the LEFTMOST wins, so "inf : 1"
    (a Ratio maximum) reads as +inf rather than the trailing "1".

    This is deliberately just "read the number"; whether that number is a
    *usable* proxy for the raw value is decided by the monotonicity check in
    :func:`solve_raw_for_display`, not by special-casing display formats here.
    """
    float_m = _LEADING_FLOAT_RE.search(text)
    inf_m = _INF_RE.search(text)
    if float_m is not None and (inf_m is None or float_m.start() <= inf_m.start()):
        try:
            return float(float_m.group())
        except ValueError:  # pragma: no cover - regex guarantees a float token
            pass
    if inf_m is not None:
        return float("-inf") if inf_m.group(1) == "-" else float("inf")
    return None


def solve_raw_for_display(
    target_display: str,
    *,
    p_min: float,
    p_max: float,
    str_for_value: Callable[[float], str],
    parameter_name: str = "parameter",
) -> float:
    """Resolve a display string ("-18 dB", "3:1") to the raw value whose display
    matches it, by bisecting ``str_for_value`` on the leading number.

    Bisection is only valid when the leading number is a *faithful monotonic
    proxy* for the raw value. Rather than special-casing display formats, we
    sample the curve across ``[p_min, p_max]`` and verify that — refusing
    (:class:`DisplayValueError`) when it isn't. That single check covers, with
    no format-specific code:

    * **constant** displays (Expansion Ratio "1 : x" — leading number never
      varies), and
    * **non-monotonic** displays where the leading number reverses, which is how
      a unit that scales across the range shows up ("999 Hz" -> "1.00 kHz"
      reads as 999 -> 1.0). The magnitude would otherwise resolve silently
      wrong; refusing and pointing at the normalized ``value`` is the honest
      answer.

    Also refuses a non-numeric target or display, and a target outside the
    parameter's displayable range.
    """
    target = parse_leading_number(target_display)
    if target is None:
        raise DisplayValueError(
            f"value_display {target_display!r} for {parameter_name!r} has no "
            "numeric value to resolve"
        )

    # Sample the display curve and read the leading number at each point.
    xs = [
        p_min + (p_max - p_min) * (i / _MONOTONIC_SAMPLES)
        for i in range(_MONOTONIC_SAMPLES + 1)
    ]
    ys = [parse_leading_number(str_for_value(x)) for x in xs]
    if any(y is None for y in ys):
        raise DisplayValueError(
            f"parameter {parameter_name!r} has a non-numeric display "
            f"({str_for_value(p_min)!r}..{str_for_value(p_max)!r}); set it via "
            "the normalized `value` instead of `value_display`"
        )

    # Classify the sampled sequence. NaN diffs (e.g. inf - inf) compare False on
    # both sides, so they neither establish nor break monotonicity.
    diffs = [b - a for a, b in zip(ys, ys[1:])]
    rises = any(d > 0 for d in diffs)
    falls = any(d < 0 for d in diffs)
    if rises and falls:
        raise DisplayValueError(
            f"parameter {parameter_name!r} display isn't monotonic across its "
            f"range ({str_for_value(p_min)!r}..{str_for_value(p_max)!r}) — its "
            "leading number reverses (typically a unit that scales, e.g. "
            "Hz->kHz), so `value_display` can't address it; use the normalized "
            "`value`"
        )
    if not rises and not falls:
        raise DisplayValueError(
            f"parameter {parameter_name!r} display ({str_for_value(p_min)!r}.."
            f"{str_for_value(p_max)!r}) doesn't vary numerically, so "
            "`value_display` can't address it; use the normalized `value`"
        )

    increasing = rises
    lo_bound, hi_bound = sorted((ys[0], ys[-1]))
    if not (lo_bound <= target <= hi_bound):
        raise DisplayValueError(
            f"value_display {target_display!r} is outside {parameter_name!r}'s "
            f"displayable range [{lo_bound:g}, {hi_bound:g}]"
        )

    # Monotonicity verified — bisect raw [min, max] on the leading number.
    lo, hi = p_min, p_max
    raw_tol = abs(p_max - p_min) * _RAW_TOL_FRACTION
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        probe = parse_leading_number(str_for_value(mid))
        if probe is None:  # pragma: no cover - sampling already proved numeric
            raise DisplayValueError(
                f"parameter {parameter_name!r} produced a non-numeric display "
                f"mid-search ({str_for_value(mid)!r})"
            )
        if probe == target or (hi - lo) < raw_tol:
            return mid
        # Move the bound that keeps the target bracketed, respecting direction.
        if (probe < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def resolve_continuous_write(
    param: Any,
    *,
    value: Any,
    value_display: str | None,
    parameter_name: str = "parameter",
) -> float:
    """Resolve a continuous ``DeviceParameter`` write to the raw float to assign.

    Supply EXACTLY ONE of ``value`` (raw, range-checked against
    ``[param.min, param.max]``) or ``value_display`` (display units like "-18 dB",
    inverted via the parameter's ``str_for_value`` curve). Live exposes no
    string->value inverse on ``DeviceParameter``, so the numeric inversion lives
    in :func:`solve_raw_for_display`.

    Shared by the device ``set_parameter`` / ``set_parameter_in_rack`` handlers
    AND the track ``set_property`` mixer-volume path (``mixer_device.volume`` is a
    ``DeviceParameter`` like any other), so the continuous-write contract —
    exactly-one, range-check, display inversion, and the enum refusal — is
    identical across all three call sites.
    """
    if (value is None) == (value_display is None):
        raise ValueError(
            f"set continuous {parameter_name!r} with exactly one of `value` "
            "(raw, in [param.min, param.max]) or `value_display` (display units "
            "like '-18 dB', '3:1')"
        )

    if value_display is not None:
        if bool(getattr(param, "is_quantized", False)):
            raise ValueError(
                f"parameter {parameter_name!r} is an enum (is_quantized=True); "
                "use value_type='enum' with `value`, not `value_display`"
            )
        str_for_value = getattr(param, "str_for_value", None)
        if not callable(str_for_value):
            raise ValueError(
                f"parameter {parameter_name!r} exposes no str_for_value; set it "
                "via the normalized `value`"
            )
        return solve_raw_for_display(
            value_display,
            p_min=float(getattr(param, "min", 0.0)),
            p_max=float(getattr(param, "max", 1.0)),
            str_for_value=str_for_value,
            parameter_name=parameter_name,
        )

    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"value_type='continuous' requires a numeric value, got {value!r}"
        ) from exc
    p_min = float(getattr(param, "min", 0.0))
    p_max = float(getattr(param, "max", 1.0))
    if not (p_min <= coerced <= p_max):
        raise ValueError(
            f"value {coerced} out of range [{p_min}, {p_max}] for "
            f"parameter {parameter_name!r}"
        )
    return coerced


def display_number_for(param: Any) -> float | None:
    """Read a Live ``DeviceParameter``'s current display as a finite number.

    Returns the leading number of ``str_for_value(param.value)`` — for a track
    volume that is the fader's dB. ``None`` when the param exposes no
    ``str_for_value`` (e.g. a minimal test fake) or its display is non-numeric
    or non-finite — a fully-down fader reads "-inf dB", which has no finite dB
    AND is not JSON-encodable, so it is reported as ``None`` (the raw ``volume``
    0.0 already conveys that).
    """
    str_for_value = getattr(param, "str_for_value", None)
    if not callable(str_for_value):
        return None
    number = parse_leading_number(str(str_for_value(param.value)))
    if number is None or not math.isfinite(number):
        return None
    return number
