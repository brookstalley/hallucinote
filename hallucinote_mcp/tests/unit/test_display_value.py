"""Pure display->raw value inverter.

These tests pin the inverter against synthetic ``str_for_value`` curves shaped
like the real Compressor parameters probed in Live (Threshold dB, Ratio, the
Expansion-Ratio "1 : 1.15" trap), plus a decreasing curve and a nonlinear
dB-like map — so the bisection isn't validated only against an identity fake.
"""
from __future__ import annotations

import math

import pytest

from hallucinote_mcp.handlers.display_value import (
    DisplayValueError,
    canonical_magnitude,
    canonical_unit_echo,
    display_number_for,
    parse_leading_number,
    resolve_continuous_write,
    solve_raw_for_display,
)


# ---------- parse_leading_number ----------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("-8.40 dB", -8.40),
        ("4.00 : 1", 4.00),
        ("100 %", 100.0),
        ("30.0 ms", 30.0),
        ("3:1", 3.0),
        (".71", 0.71),
        ("0.00 dB", 0.0),
        ("+12 dB", 12.0),
        ("80.0 Hz", 80.0),
    ],
)
def test_parse_leading_number(text: str, expected: float) -> None:
    assert parse_leading_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["On", "RMS", "High pass", "", "no digits"])
def test_parse_leading_number_non_numeric(text: str) -> None:
    assert parse_leading_number(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("-inf dB", float("-inf")),
        ("inf", float("inf")),
        ("+inf dB", float("inf")),
        ("-INF dB", float("-inf")),
        ("inf : 1", float("inf")),  # Ratio max — leading inf beats trailing "1"
    ],
)
def test_parse_leading_number_infinity(text: str, expected: float) -> None:
    # Live renders unbounded endpoints with inf ("-inf dB", "inf : 1"); parse the
    # LEFTMOST token so a trailing number doesn't shadow a leading inf.
    assert parse_leading_number(text) == expected


def test_parse_leading_float_wins_over_inf_substring() -> None:
    # A real leading number takes precedence; inf is only the fallback.
    assert parse_leading_number("1.5 (was inf)") == pytest.approx(1.5)


# ---------- canonical_magnitude (DPP-7H2K unit normalisation) ----------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("150 Hz", 150.0),
        ("2 kHz", 2000.0),
        ("1.00 kHz", 1000.0),
        ("120 ms", 120.0),
        ("2.5 s", 2500.0),
        ("3.00 s", 3000.0),
        ("0.1544 Hz", 0.1544),
        # Unrecognised / single-scale units fall back to the bare leading number
        # (unchanged from pre-DPP-7H2K): dB, %, ratio, plain.
        ("-18 dB", -18.0),
        ("100 %", 100.0),
        ("3 : 1", 3.0),
        (".71", 0.71),
        # inf endpoints pass straight through (no scaling).
        ("-inf dB", float("-inf")),
    ],
)
def test_canonical_magnitude(text: str, expected: float) -> None:
    assert canonical_magnitude(text) == pytest.approx(expected)


def test_canonical_magnitude_case_insensitive_units() -> None:
    assert canonical_magnitude("2 KHZ") == pytest.approx(2000.0)
    assert canonical_magnitude("500 MS") == pytest.approx(500.0)


def test_canonical_magnitude_non_numeric() -> None:
    assert canonical_magnitude("On") is None


# ---------- canonical_unit_echo (DPP-7H2K(b) value_real) ----------

@pytest.mark.parametrize(
    "value_display,expected",
    [
        ("0.1544 Hz", (0.1544, "Hz")),
        ("2 kHz", (2000.0, "Hz")),
        ("120 ms", (120.0, "ms")),
        ("2.5 s", (2500.0, "ms")),
    ],
)
def test_canonical_unit_echo_recognised(value_display, expected) -> None:
    mag, unit = canonical_unit_echo(value_display)
    assert mag == pytest.approx(expected[0])
    assert unit == expected[1]


@pytest.mark.parametrize("value_display", ["-18 dB", "100 %", "3 : 1", "On"])
def test_canonical_unit_echo_unrecognised_is_none(value_display: str) -> None:
    # No recognised scale unit → no value_real echo (the raw `value` serves it).
    assert canonical_unit_echo(value_display) is None


# ---------- synthetic curves mirroring real Compressor params ----------

def threshold_db(raw: float) -> str:
    """Normalized 0..1 -> dB, monotonic increasing. Roughly Live's curve."""
    db = -70.0 + raw * 70.0  # 0 -> -70 dB, 1 -> 0 dB
    return f"{db:.2f} dB"


def ratio_display(raw: float) -> str:
    """Normalized 0..1 -> compression ratio "N : 1", increasing, nonlinear."""
    ratio = 1.0 + (raw ** 2) * 19.0  # 1:1 .. 20:1, leading number varies
    return f"{ratio:.2f} : 1"


def output_db(raw: float) -> str:
    """Value already in dB (min -36, max 36); identity display."""
    return f"{raw:.2f} dB"


def ratio_display_inf_max(raw: float) -> str:
    """Faithful Compressor Ratio: 'N : 1' with 'inf : 1' at the maximum — the
    leading N is the meaningful number AND there's a trailing '1'. Live's real
    shape; the synthetic `ratio_display` never hit inf, hiding the parse bug the
    live test caught."""
    if raw >= 1.0:
        return "inf : 1"
    return f"{1.0 / (1.0 - raw):.2f} : 1"


def freq_hz_khz(raw: float) -> str:
    """Frequency that scales Hz -> kHz across the range (real EQ-freq shape).
    The leading number reverses at the unit boundary (999 -> 1.0), but
    canonical_magnitude normalises kHz -> Hz (DPP-7H2K), so value_display
    resolves it instead of refusing."""
    hz = 20.0 * (1100.0 ** raw)  # 20 Hz .. 22 kHz (distinct endpoint numbers)
    return f"{hz / 1000.0:.2f} kHz" if hz >= 1000.0 else f"{hz:.1f} Hz"


def time_ms_s(raw: float) -> str:
    """Time that scales ms -> s across the range (comp release / LFO rate shape).
    1 ms .. 3000 ms; canonical_magnitude normalises s -> ms (DPP-7H2K)."""
    ms = 1.0 * (3000.0 ** raw)  # 1 ms .. 3 s
    return f"{ms / 1000.0:.2f} s" if ms >= 1000.0 else f"{ms:.2f} ms"


def fold_back_unitless(raw: float) -> str:
    """A genuinely non-monotonic curve with NO recognised scale unit: the
    magnitude rises then falls (V-shaped), so unit normalisation can't rescue
    it and value_display must still refuse (DPP-7H2K only fixes unit-scaling)."""
    return f"{abs(0.5 - raw):.3f} x"


def threshold_db_inf_floor(raw: float) -> str:
    """Faithful Compressor Threshold: logarithmic dB that is genuinely "-inf dB"
    at the minimum (raw 0), finite above. This is what real Live returns — the
    earlier linear `threshold_db` fake hid the -inf endpoint and gave false
    confidence (the live verification caught it)."""
    if raw <= 0.0:
        return "-inf dB"
    return f"{6.0 + 20.0 * math.log10(raw):.2f} dB"


def decreasing_display(raw: float) -> str:
    """Leading number falls as raw rises (direction-detection coverage)."""
    return f"{100.0 - raw * 100.0:.1f} ms"


def expansion_ratio_trap(raw: float) -> str:
    """Real Expansion-Ratio shape: leading number constant, tail varies."""
    return f"1 : {raw:.2f}"


def test_threshold_to_minus_18_db() -> None:
    raw = solve_raw_for_display(
        "-18 dB", p_min=0.0, p_max=1.0, str_for_value=threshold_db
    )
    assert threshold_db(raw) == "-18.00 dB"
    # -18 dB on the -70..0 curve is at raw = (-18+70)/70.
    assert raw == pytest.approx((-18.0 + 70.0) / 70.0, abs=1e-4)


def test_ratio_with_inf_max_resolves_interior_target() -> None:
    # Regression for the second live-caught bug: an "inf : 1" maximum (leading
    # inf + trailing "1") must not be mis-read as a constant leading number.
    raw = solve_raw_for_display(
        "3:1", p_min=0.0, p_max=1.0, str_for_value=ratio_display_inf_max
    )
    assert ratio_display_inf_max(raw) == "3.00 : 1"
    # 1/(1-raw) = 3  ->  raw = 2/3.
    assert raw == pytest.approx(2.0 / 3.0, rel=1e-3)


def test_threshold_with_inf_floor_resolves_interior_target() -> None:
    # Regression for the live-caught bug: a "-inf dB" minimum endpoint must NOT
    # disqualify the parameter — a target inside the finite range still resolves.
    raw = solve_raw_for_display(
        "-18 dB", p_min=0.0, p_max=1.0, str_for_value=threshold_db_inf_floor
    )
    assert threshold_db_inf_floor(raw) == "-18.00 dB"
    # 6 + 20*log10(raw) = -18  ->  raw = 10**(-24/20).
    assert raw == pytest.approx(10.0 ** (-24.0 / 20.0), rel=1e-3)


def test_ratio_three_to_one_nonlinear() -> None:
    raw = solve_raw_for_display(
        "3:1", p_min=0.0, p_max=1.0, str_for_value=ratio_display
    )
    assert parse_leading_number(ratio_display(raw)) == pytest.approx(3.0, abs=0.01)
    # ratio = 1 + 19*raw^2 = 3 -> raw = sqrt(2/19).
    assert raw == pytest.approx(math.sqrt(2.0 / 19.0), abs=1e-3)


def test_value_already_in_db_non_unit_range() -> None:
    raw = solve_raw_for_display(
        "-12 dB", p_min=-36.0, p_max=36.0, str_for_value=output_db
    )
    # The contract is display resolution, not infinite raw precision: the
    # resolved raw must *render* as the target (here the 0.01 dB display bucket).
    assert output_db(raw) == "-12.00 dB"


def test_decreasing_curve_direction_detected() -> None:
    raw = solve_raw_for_display(
        "25 ms", p_min=0.0, p_max=1.0, str_for_value=decreasing_display
    )
    # 100 - 100*raw = 25 -> raw = 0.75.
    assert raw == pytest.approx(0.75, abs=1e-3)


def test_target_at_endpoint() -> None:
    raw = solve_raw_for_display(
        "0 dB", p_min=0.0, p_max=1.0, str_for_value=threshold_db
    )
    assert raw == pytest.approx(1.0, abs=1e-4)


# ---------- refusals ----------

def test_refuses_non_numeric_target() -> None:
    with pytest.raises(DisplayValueError, match="no numeric value"):
        solve_raw_for_display(
            "loud", p_min=0.0, p_max=1.0, str_for_value=threshold_db
        )


def test_refuses_out_of_displayable_range() -> None:
    with pytest.raises(DisplayValueError, match="outside"):
        solve_raw_for_display(
            "10 dB", p_min=0.0, p_max=1.0, str_for_value=threshold_db
        )


def test_refuses_constant_display_trap() -> None:
    # Expansion Ratio "1 : x" — leading number is always 1.0, so it doesn't vary
    # and value_display can't address it. Caught by the monotonicity check
    # (doesn't-vary branch), not a format special-case.
    with pytest.raises(DisplayValueError, match="doesn't vary"):
        solve_raw_for_display(
            "1.5", p_min=1.0, p_max=2.0, str_for_value=expansion_ratio_trap
        )


def test_refuses_non_monotonic_after_unit_normalisation() -> None:
    # A V-shaped curve in an unrecognised unit ("x") stays non-monotonic after
    # canonical_magnitude (no scale to apply), so it still refuses — DPP-7H2K
    # only rescues displays whose reversal is a pure unit-scale switch.
    with pytest.raises(DisplayValueError, match="monotonic"):
        solve_raw_for_display(
            "0.1 x", p_min=0.0, p_max=1.0, str_for_value=fold_back_unitless
        )


# ---------- DPP-7H2K: explicit-unit non-monotonic resolution ----------

def test_resolves_hz_khz_by_unit_normalisation() -> None:
    # "5 kHz" -> 5000 Hz; freq_hz_khz maps 20*1100**raw, so raw solves to
    # log(5000/20)/log(1100). The display at that raw rounds to "5.00 kHz".
    raw = solve_raw_for_display(
        "5 kHz", p_min=0.0, p_max=1.0, str_for_value=freq_hz_khz
    )
    assert freq_hz_khz(raw) == "5.00 kHz"


def test_resolves_hz_form_on_same_unit_scaling_param() -> None:
    # A target in the OTHER unit of the same family ("150 Hz") resolves too —
    # the canonical magnitude (150 Hz) bisects the normalised curve.
    raw = solve_raw_for_display(
        "150 Hz", p_min=0.0, p_max=1.0, str_for_value=freq_hz_khz
    )
    assert freq_hz_khz(raw) == "150.0 Hz"


def test_resolves_ms_s_by_unit_normalisation() -> None:
    raw = solve_raw_for_display(
        "1.5 s", p_min=0.0, p_max=1.0, str_for_value=time_ms_s
    )
    assert time_ms_s(raw) == "1.50 s"


def test_resolves_ms_form_on_same_time_scaling_param() -> None:
    raw = solve_raw_for_display(
        "120 ms", p_min=0.0, p_max=1.0, str_for_value=time_ms_s
    )
    assert time_ms_s(raw) == "120.00 ms"


def test_refuses_non_numeric_display() -> None:
    with pytest.raises(DisplayValueError, match="non-numeric display"):
        solve_raw_for_display(
            "1", p_min=0.0, p_max=2.0, str_for_value=lambda v: "RMS"
        )


# ---------- resolve_continuous_write (shared continuous-write contract) ----------


class _Param:
    """Minimal DeviceParameter stand-in for the shared write contract."""

    def __init__(self, value=0.0, *, min=0.0, max=1.0, str_for_value=None,
                 is_quantized=False):
        self.value = value
        self.min = min
        self.max = max
        self.is_quantized = is_quantized
        if str_for_value is not None:
            self.str_for_value = str_for_value


def test_resolve_continuous_raw_value_in_range() -> None:
    assert resolve_continuous_write(
        _Param(min=0.0, max=1.0), value=0.7, value_display=None
    ) == pytest.approx(0.7)


def test_resolve_continuous_raw_value_out_of_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        resolve_continuous_write(_Param(min=0.0, max=1.0), value=1.5, value_display=None)


def test_resolve_continuous_value_display_inverts_curve() -> None:
    # threshold_db: 0->-70 dB, 1->0 dB; -35 dB sits at raw 0.5.
    raw = resolve_continuous_write(
        _Param(min=0.0, max=1.0, str_for_value=threshold_db),
        value=None,
        value_display="-35 dB",
    )
    assert raw == pytest.approx(0.5, abs=1e-3)


def test_resolve_continuous_requires_exactly_one() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        resolve_continuous_write(_Param(), value=0.5, value_display="-35 dB")
    with pytest.raises(ValueError, match="exactly one"):
        resolve_continuous_write(_Param(), value=None, value_display=None)


def test_resolve_continuous_refuses_value_display_on_enum() -> None:
    with pytest.raises(ValueError, match="enum"):
        resolve_continuous_write(
            _Param(is_quantized=True, str_for_value=threshold_db),
            value=None,
            value_display="-35 dB",
        )


def test_resolve_continuous_refuses_value_display_without_str_for_value() -> None:
    with pytest.raises(ValueError, match="no str_for_value"):
        resolve_continuous_write(_Param(), value=None, value_display="-35 dB")


# ---------- display_number_for ----------


def test_display_number_for_reads_db() -> None:
    p = _Param(value=0.85, str_for_value=lambda v: f"{40.0 * (v - 0.85):.1f} dB")
    assert display_number_for(p) == pytest.approx(0.0)


def test_display_number_for_none_when_infinite() -> None:
    assert display_number_for(_Param(value=0.0, str_for_value=lambda v: "-inf dB")) is None


def test_display_number_for_none_without_str_for_value() -> None:
    assert display_number_for(_Param(value=0.5)) is None


def test_display_number_for_none_when_non_numeric() -> None:
    assert display_number_for(_Param(value=0.5, str_for_value=lambda v: "RMS")) is None
