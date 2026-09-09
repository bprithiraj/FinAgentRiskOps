import json
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files

import pytest
from conftest import EvidenceStub

from finagent.schemas import DomainError, Expense
from finagent.workflow import Service

REVIEW = {
    "decision_id": "decision-1042",
    "decision": "approve_exception",
    "note": "Reviewed the synthetic receipt and exception.",
}


def test_supported_and_unsupported_frozen_cases(service):
    fixtures = json.loads(files("finagent").joinpath("corpus/evaluation-cases.json").read_text())
    for fixture in fixtures:
        expense = Expense.model_validate(
            {k: v for k, v in fixture.items() if k not in {"id", "expected"}}
        )
        result = service.submit("test-" + fixture["id"], expense.model_dump())
        assert result["assessment"]["recommendation"] == fixture["expected"]
        assert result["status"] == (
            "unsupported" if fixture["expected"] == "unsupported" else "awaiting_review"
        )
    assert service.model.calls == 7


def test_duplicate_request_and_conflicting_input(service, expense):
    first = service.submit("request-1042", expense)
    second = service.submit("request-1042", expense)
    assert first == second
    assert service.model.calls == 1
    with pytest.raises(DomainError, match="another expense"):
        service.submit("request-1042", expense | {"amount_cents": 4000})


def test_restart_then_resume_human_interrupt(tmp_path, expense):
    first = Service(tmp_path, EvidenceStub())
    result = first.submit("restart-1042", expense)
    assert result["status"] == "awaiting_review"
    first.close()
    second = Service(tmp_path, EvidenceStub())
    try:
        result = second.review("restart-1042", REVIEW, "reviewer-alice")
        assert result["status"] == "review_recorded"
        assert result["review"]["reviewer"] == "reviewer-alice"
        assert second.model.calls == 0
    finally:
        second.close()


def test_crash_after_draft_before_interrupt(tmp_path, expense):
    first = Service(tmp_path, EvidenceStub())
    first.store.ensure_case("boundary-1042", expense)
    first.graph.invoke(
        {"case_id": "boundary-1042", "expense": expense},
        first._config("boundary-1042"),
        interrupt_before=["human_review"],
    )
    snapshot = first.graph.get_state(first._config("boundary-1042"))
    assert snapshot.values["status"] == "awaiting_review"
    assert not any(task.interrupts for task in snapshot.tasks)
    first.close()
    second = Service(tmp_path, EvidenceStub())
    try:
        assert second.review("boundary-1042", REVIEW, "alice")["status"] == "review_recorded"
        assert second.model.calls == 0
    finally:
        second.close()


def test_crash_after_decision_commit_before_resume(tmp_path, expense):
    first = Service(tmp_path, EvidenceStub())
    first.submit("decision-crash", expense)
    first.store.record_decision("decision-crash", REVIEW, "alice")
    first.close()
    second = Service(tmp_path, EvidenceStub())
    try:
        result = second.get("decision-crash")
        assert result["status"] == "review_recorded"
        assert len(result["audit"]) == 3
        assert second.review("decision-crash", REVIEW, "alice") == result
    finally:
        second.close()


def test_repeat_and_conflicting_decisions(service, expense):
    service.submit("review-1042", expense)
    first = service.review("review-1042", REVIEW, "alice")
    assert service.review("review-1042", REVIEW, "alice") == first
    with pytest.raises(DomainError, match="different review"):
        service.review("review-1042", REVIEW | {"decision": "reject"}, "alice")
    with pytest.raises(DomainError, match="different review"):
        service.review("review-1042", REVIEW, "bob")


def test_concurrent_duplicate_review_is_once(service, expense):
    service.submit("concurrent-1042", expense)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: service.review("concurrent-1042", REVIEW, "alice"), range(4))
        )
    assert all(r == results[0] for r in results)
    assert [e["kind"] for e in results[0]["audit"]].count("human_decision_recorded") == 1


def test_missing_receipt_cannot_be_approved(service, expense):
    service.submit("receipt-1042", expense | {"receipt_present": False})
    with pytest.raises(DomainError, match="missing receipt"):
        service.review("receipt-1042", REVIEW, "alice")
    assert service.store.decision("receipt-1042") is None
    assert (
        service.review("receipt-1042", REVIEW | {"decision": "request_information"}, "alice")[
            "status"
        ]
        == "review_recorded"
    )


def test_denied_tool_never_reaches_model(service, expense):
    with pytest.raises(DomainError, match="read-only"):
        service.submit("tools-1042", expense | {"requested_tools": ["submit_payment"]})
    assert service.model.calls == 0


@pytest.mark.parametrize(
    "failure", ["unknown_citation", "wrong_quote", "wrong_classification", "extra_tool"]
)
def test_invalid_model_output_fails_closed(service, expense, failure):
    original = service.model.draft

    def malicious(*args):
        draft = original(*args)
        if failure == "unknown_citation":
            draft["citations"][0]["chunk_id"] = "invented-rule"
        if failure == "wrong_quote":
            draft["citations"][0]["quote"] = "The company pays every expense without any limit."
        if failure == "wrong_classification":
            draft["recommendation"] = "within_policy"
        if failure == "extra_tool":
            draft["tool_call"] = "submit_payment"
        return draft

    service.model.draft = malicious
    result = service.submit("invalid-1042", expense)
    assert result["status"] == "model_error"
    with pytest.raises(DomainError, match="no validated draft"):
        service.review("invalid-1042", REVIEW, "alice")


def test_model_error_can_retry_without_duplicate_case(service, expense):
    original = service.model.draft

    def unavailable(*args):
        raise DomainError("unavailable", "offline", 503)

    service.model.draft = unavailable
    assert service.submit("retry-1042", expense)["status"] == "model_error"
    service.model.draft = original
    result = service.retry("retry-1042")
    assert result["status"] == "awaiting_review"
    assert len(result["audit"]) == 1


def test_second_process_service_is_rejected(service, tmp_path):
    with pytest.raises(RuntimeError, match="one worker"):
        Service(tmp_path, EvidenceStub())
