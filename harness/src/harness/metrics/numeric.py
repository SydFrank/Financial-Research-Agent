"""Code-based grading for numeric answers.

Numbers have one correct answer, so they are graded by code: deterministic,
free to run, and never fooled by wording.
"""

import math

from harness.schema import NumericAnswer

# unit -> (dimension, multiplier that converts the unit to the dimension's base unit)
# Two values can only be compared when their dimensions match:
# 40 % (a ratio) and 40 百分点 (a change in a ratio) are different things.
UNITS: dict[str, tuple[str, float]] = {
    "元": ("money", 1),
    "千元": ("money", 1e3),
    "万元": ("money", 1e4),
    "百万元": ("money", 1e6),
    "亿元": ("money", 1e8),
    "股": ("shares", 1),
    "万股": ("shares", 1e4),
    "亿股": ("shares", 1e8),
    "%": ("ratio", 1),
    "百分点": ("ratio_change", 1),
    "倍": ("multiple", 1),
}


def to_base(value: float, unit: str) -> tuple[str, float]:
    """Convert a value to its dimension's base unit.

    to_base(4009.17, "亿元") -> ("money", 400917000000.0)
    to_base(12.5, "%")       -> ("ratio", 12.5)

    Raises ValueError for a unit that is not in UNITS.
    """
    if unit not in UNITS:
        raise ValueError(f"unknown unit: {unit}")
    dimension, scale = UNITS[unit]
    return (dimension, value * scale)


def numeric_correct(
    expected: NumericAnswer,
    actual_value: float | None,
    actual_unit: str | None,
) -> bool:
    """True when the system's number matches the reference answer.

    Rules:
    - a missing value or unit is wrong
    - an unknown unit is wrong (do not raise; the system made a mistake, the grader did not)
    - values in different dimensions are wrong
    - otherwise compare in base units, allowing a relative error of expected.rel_tol

    An unknown unit in the reference answer is a bug in the evaluation set, so
    that case raises instead of being scored.
    """
    if actual_value is None or actual_unit is None:
        return False
    try:
        actual_dim, actual_base = to_base(actual_value, actual_unit)
    except ValueError:
        return False
    expected_dim, expected_base = to_base(expected.value, expected.unit)
    if actual_dim != expected_dim:
        return False
    # rel_tol alone can never match an expected value of 0, because the allowed
    # error is rel_tol * 0 = 0; abs_tol gives a tiny absolute margin for that case
    return math.isclose(actual_base, expected_base, rel_tol=expected.rel_tol, abs_tol=1e-9)
