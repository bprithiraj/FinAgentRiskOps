from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expense(StrictModel):
    expense_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    category: str = Field(min_length=1, max_length=60)
    amount_cents: int = Field(ge=1, le=100_000_000, strict=True)
    currency: Literal["USD"] = "USD"
    receipt_present: bool
    business_purpose: str = Field(min_length=5, max_length=500)
    question: str = Field(default="Does this expense require an exception review?", max_length=1000)
    requested_tools: list[str] = Field(default_factory=list, max_length=5)


class Citation(StrictModel):
    chunk_id: str = Field(min_length=1, max_length=150)
    quote: str = Field(min_length=15, max_length=1500)


class Draft(StrictModel):
    recommendation: Literal["within_policy", "exception_required", "missing_receipt"]
    summary: str = Field(min_length=5, max_length=800)
    citations: list[Citation] = Field(min_length=1, max_length=6)


class Review(StrictModel):
    decision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    decision: Literal["approve_exception", "reject", "request_information"]
    note: str = Field(min_length=3, max_length=1000)


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
