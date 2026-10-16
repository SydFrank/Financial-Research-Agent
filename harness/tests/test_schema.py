from datetime import date

import pytest
from pydantic import ValidationError

from harness.schema import EvalItem


def base_item(**overrides) -> dict:
    item = {
        "id": "fact-0001",
        "category": "factual",
        "tier": "T1",
        "question": "示例公司 2023 年合并报表口径的营业收入是多少？",
        "symbols": ["000000"],
        "as_of_date": "2024-06-30",
        "answer": {"value": 123.45, "unit": "亿元"},
        "evidence": [{"doc": "000000_2023_annual", "page": 10, "locator": "合并利润表"}],
        "fact_key": "000000-2023-revenue",
        "split": "dev",
    }
    return item | overrides


def test_valid_item_loads():
    item = EvalItem.model_validate(base_item())
    assert item.as_of_date == date(2024, 6, 30)
    assert not item.is_verified


def test_unknown_tier_is_rejected():
    with pytest.raises(ValidationError):
        EvalItem.model_validate(base_item(tier="T5"))


def test_unknown_field_is_rejected():
    # catches typos such as "evidance" that would otherwise be silently ignored
    with pytest.raises(ValidationError):
        EvalItem.model_validate(base_item(evidance=[]))


def test_factual_item_needs_an_answer_or_not_found():
    with pytest.raises(ValidationError):
        EvalItem.model_validate(base_item(answer=None))
    item = EvalItem.model_validate(base_item(answer=None, evidence=[], not_found=True))
    assert item.not_found


def test_factual_item_with_answer_needs_evidence():
    with pytest.raises(ValidationError):
        EvalItem.model_validate(base_item(evidence=[]))


def test_t2_item_needs_formula_and_inputs():
    with pytest.raises(ValidationError):
        EvalItem.model_validate(base_item(tier="T2"))
