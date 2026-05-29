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
    parse_leading_number,
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
    The leading number is a non-monotonic proxy across the unit boundary, so
    value_display must refuse rather than resolve to the wrong magnitude."""
    hz = 20.0 * (1100.0 ** raw)  # 20 Hz .. 22 kHz (distinct endpoint numbers)
    return f"{hz / 1000.0:.2f} kHz" if hz >= 1000.0 else f"{hz:.1f} Hz"


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


def test_refuses_non_monotonic_unit_scaling() -> None:
    # Hz -> kHz: the leading number reverses (999 -> 1.0) at the unit boundary,
    # so the monotonicity check refuses rather than resolve to a wrong magnitude.
    # No unit-parsing code — non-monotonicity is the general signal.
    with pytest.raises(DisplayValueError, match="monotonic"):
        solve_raw_for_display(
            "5 kHz", p_min=0.0, p_max=1.0, str_for_value=freq_hz_khz
        )


def test_refuses_non_numeric_display() -> None:
    with pytest.raises(DisplayValueError, match="non-numeric display"):
        solve_raw_for_display(
            "1", p_min=0.0, p_max=2.0, str_for_value=lambda v: "RMS"
        )
