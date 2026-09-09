import pytest

from finagent.workflow import Service


class EvidenceStub:
    """Deterministic contract fixture; not a model or a quality evaluation."""

    def __init__(self):
        self.calls = 0

    def draft(self, expense, assessment, evidence):
        self.calls += 1
        source = next(c for c in evidence if c["id"] == assessment["required_citation"])
        return {
            "recommendation": assessment["recommendation"],
            "citations": [{"chunk_id": source["id"], "quote": source["text"]}],
        }

    def metadata(self):
        return {"provider": "deterministic_contract_stub", "model": "test-only"}


@pytest.fixture
def expense():
    return {
        "expense_id": "EXP-1042",
        "category": "meal",
        "amount_cents": 6800,
        "currency": "USD",
        "receipt_present": True,
        "business_purpose": "A fictional customer workshop meal.",
        "question": "Does this expense need an exception?",
        "requested_tools": [],
    }


@pytest.fixture
def service(tmp_path):
    instance = Service(tmp_path, EvidenceStub())
    yield instance
    instance.close()
