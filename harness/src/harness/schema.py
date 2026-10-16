"""Data structures for evaluation items.

Every item in the evaluation set must validate against `EvalItem`. A malformed
item fails loudly at load time instead of silently skewing a score.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Tier = Literal["T1", "T2", "T3", "T4"]
Category = Literal["factual", "analytical", "retrieval"]
Split = Literal["dev", "holdout"]


class Evidence(BaseModel):
    """Where the answer lives in a source document."""

    model_config = ConfigDict(extra="forbid")

    doc: str  # document id, e.g. "002594_2023_annual"
    page: int = Field(ge=1)
    locator: str | None = None  # e.g. "合并利润表", to find the spot on the page


class CalcInput(BaseModel):
    """One raw number a calculation question depends on."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    unit: str


class NumericAnswer(BaseModel):
    """The reference answer to a numeric question."""

    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
    rel_tol: float = Field(default=1e-3, ge=0)
    formula: str | None = None  # how the value is derived (calculation questions)
    inputs: list[CalcInput] = []  # the raw numbers the formula uses


class EvalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: Category
    tier: Tier
    question: str = Field(min_length=1)
    symbols: list[str]
    as_of_date: date

    answer: NumericAnswer | None = None
    # True when the documents genuinely do not contain the answer;
    # the correct system behaviour is then to say so, not to produce a number.
    not_found: bool = False
    evidence: list[Evidence] = []

    # Items asking about the same underlying fact share a fact_key and must sit
    # in the same split, otherwise tuning on dev leaks into holdout.
    fact_key: str
    split: Split
    tags: dict[str, str | int] = {}

    verified_by: str | None = None
    verified_at: date | None = None

    @property
    def is_verified(self) -> bool:
        return self.verified_by is not None and self.verified_at is not None

    @model_validator(mode="after")
    def _check_consistency(self) -> "EvalItem":
        if self.category == "factual":
            if self.not_found and self.answer is not None:
                raise ValueError("a not_found item must not carry an answer")
            if not self.not_found and self.answer is None:
                raise ValueError("a factual item needs an answer, or not_found=True")
            if not self.not_found and not self.evidence:
                raise ValueError("a factual item with an answer needs evidence")
        if self.category == "retrieval" and not self.evidence:
            raise ValueError("a retrieval item needs at least one relevant page")
        if self.tier == "T2" and self.answer is not None:
            if not self.answer.formula or not self.answer.inputs:
                raise ValueError("a T2 calculation item needs a formula and its inputs")
        return self
