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

import re
from typing import Callable

# Leading signed float: optional sign, digits with optional decimal, or a bare
# ".5". Matches "-8.40 dB" -> -8.40, "4.00 : 1" -> 4.00, "100 %" -> 100,
# "30.0 ms" -> 30.0, "3:1" -> 3, ".71" -> 0.71.
_LEADING_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")

# Bisection terminates when the raw interval is this fraction of the full
# range — ~2^-40 with the iteration cap, far below any parameter's display
# resolution.
_RAW_TOL_FRACTION = 1e-7
_MAX_ITER = 60


class DisplayValueError(ValueError):
    """The display value could not be resolved to a raw parameter value."""


def parse_leading_number(text: str) -> float | None:
    """Return the first signed float in ``text``, or ``None`` if there is none."""
    match = _LEADING_FLOAT_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:  # pragma: no cover - regex guarantees a float-parseable token
        return None


def solve_raw_for_display(
    target_display: str,
    *,
    p_min: float,
    p_max: float,
    str_for_value: Callable[[float], str],
    parameter_name: str = "parameter",
) -> float:
    """Bisect ``str_for_value`` to the raw value whose display matches ``target_display``.

    ``target_display`` is the caller's desired display value as a string; only
    its leading signed float is used ("3:1" -> 3, "-18 dB" -> -18). Raises
    :class:`DisplayValueError` when the target is non-numeric, the parameter's
    display is non-numeric or has a non-varying leading number, or the target
    falls outside the parameter's displayable range.
    """
    target = parse_leading_number(target_display)
    if target is None:
        raise DisplayValueError(
            f"value_display {target_display!r} for {parameter_name!r} has no "
            "numeric value to resolve"
        )

    lo_display = parse_leading_number(str_for_value(p_min))
    hi_display = parse_leading_number(str_for_value(p_max))
    if lo_display is None or hi_display is None:
        raise DisplayValueError(
            f"parameter {parameter_name!r} has a non-numeric display "
            f"({str_for_value(p_min)!r}..{str_for_value(p_max)!r}); set it via "
            "the normalized `value` instead of `value_display`"
        )
    if lo_display == hi_display:
        raise DisplayValueError(
            f"parameter {parameter_name!r} display ({str_for_value(p_min)!r}.."
            f"{str_for_value(p_max)!r}) has a constant leading number, so "
            "`value_display` cannot address it; set it via the normalized `value`"
        )

    lo_bound, hi_bound = sorted((lo_display, hi_display))
    if not (lo_bound <= target <= hi_bound):
        raise DisplayValueError(
            f"value_display {target_display!r} is outside {parameter_name!r}'s "
            f"displayable range [{lo_bound:g}, {hi_bound:g}]"
        )

    increasing = hi_display > lo_display
    lo, hi = p_min, p_max
    raw_tol = abs(p_max - p_min) * _RAW_TOL_FRACTION
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        probe = parse_leading_number(str_for_value(mid))
        if probe is None:  # pragma: no cover - endpoints already proved numeric
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
