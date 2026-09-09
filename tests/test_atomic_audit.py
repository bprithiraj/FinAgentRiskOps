import sqlite3

import pytest
from test_workflow import REVIEW

from finagent.schemas import DomainError


def fail_audit(store, kind):
    with store.connect() as db:
        db.execute(
            f"CREATE TRIGGER test_abort BEFORE INSERT ON audit WHEN NEW.kind='{kind}' BEGIN SELECT RAISE(ABORT, 'injected crash'); END"
        )


def test_submission_and_audit_commit_together(service, expense):
    fail_audit(service.store, "submitted")
    with pytest.raises(sqlite3.IntegrityError, match="injected crash"):
        service.submit("atomic-submit", expense)
    with pytest.raises(DomainError, match="not found"):
        service.store.case("atomic-submit")


def test_decision_and_audit_commit_together(service, expense):
    service.submit("atomic-decision", expense)
    fail_audit(service.store, "human_decision_recorded")
    with pytest.raises(sqlite3.IntegrityError, match="injected crash"):
        service.review("atomic-decision", REVIEW, "alice")
    assert service.store.decision("atomic-decision") is None
    assert service.get("atomic-decision")["status"] == "awaiting_review"
    with service.store.connect() as db:
        db.execute("DROP TRIGGER test_abort")
    assert service.review("atomic-decision", REVIEW, "alice")["status"] == "review_recorded"
