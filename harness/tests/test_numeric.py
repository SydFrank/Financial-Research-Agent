import pytest

from harness.metrics.numeric import numeric_correct, to_base
from harness.schema import NumericAnswer


def answer(value: float, unit: str, rel_tol: float = 1e-3) -> NumericAnswer:
    return NumericAnswer(value=value, unit=unit, rel_tol=rel_tol)


# --- to_base ---------------------------------------------------------------

def test_to_base_converts_money_to_yuan():
    assert to_base(4009.17, "亿元") == ("money", pytest.approx(400_917_000_000))
    assert to_base(3.5, "万元") == ("money", pytest.approx(35_000))


def test_to_base_keeps_ratios_as_they_are():
    assert to_base(12.5, "%") == ("ratio", 12.5)


def test_to_base_rejects_unknown_unit():
    with pytest.raises(ValueError):
        to_base(1.0, "美元")


# --- numeric_correct -------------------------------------------------------

def test_same_value_same_unit_is_correct():
    assert numeric_correct(answer(4009.17, "亿元"), 4009.17, "亿元")


def test_same_amount_in_another_unit_is_correct():
    assert numeric_correct(answer(4009.17, "亿元"), 400_917_000_000, "元")
    assert numeric_correct(answer(4009.17, "亿元"), 40_091_700, "万元")


def test_within_tolerance_is_correct():
    # 0.05% off, tolerance is 0.1%
    assert numeric_correct(answer(100.0, "亿元"), 100.05, "亿元")


def test_outside_tolerance_is_wrong():
    # 1% off, tolerance is 0.1%
    assert not numeric_correct(answer(100.0, "亿元"), 101.0, "亿元")


def test_negative_values_are_compared_correctly():
    # a net loss
    assert numeric_correct(answer(-12.3, "亿元"), -12.3, "亿元")
    assert not numeric_correct(answer(-12.3, "亿元"), 12.3, "亿元")


def test_different_dimension_is_wrong():
    assert not numeric_correct(answer(40, "%"), 40, "百分点")
    assert not numeric_correct(answer(40, "%"), 40, "亿元")


def test_missing_value_or_unit_is_wrong():
    assert not numeric_correct(answer(1.0, "亿元"), None, "亿元")
    assert not numeric_correct(answer(1.0, "亿元"), 1.0, None)


def test_unknown_unit_in_answer_is_wrong_not_an_error():
    assert not numeric_correct(answer(1.0, "亿元"), 1.0, "美元")


def test_zero_expected_value():
    # e.g. a margin that did not change: 0 百分点
    assert numeric_correct(answer(0.0, "百分点"), 0.0, "百分点")
    assert not numeric_correct(answer(0.0, "百分点"), 0.5, "百分点")
