"""A real child-process exit verifies SQLite WAL recovery, with a labeled model stub."""

import os
import subprocess
import sys
from pathlib import Path

from conftest import EvidenceStub

from finagent.workflow import Service


def test_abrupt_process_exit_preserves_interrupt(tmp_path):
    project = Path(__file__).resolve().parents[1]
    code = """
import os, sys
from pathlib import Path
sys.path.insert(0, "tests")
from conftest import EvidenceStub
from finagent.workflow import Service
service = Service(Path(sys.argv[1]), EvidenceStub())
expense = {"expense_id":"PROC-1", "category":"meal", "amount_cents":6800, "currency":"USD", "receipt_present":True, "business_purpose":"Fictional meal during customer visit.", "question":"Exception review?", "requested_tools":[]}
assert service.submit("process-crash", expense)["status"] == "awaiting_review"
os._exit(23)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 23, completed.stderr
    service = Service(tmp_path, EvidenceStub())
    try:
        result = service.review(
            "process-crash",
            {
                "decision_id": "after-crash",
                "decision": "approve_exception",
                "note": "Reviewed after process crash.",
            },
            "alice",
        )
        assert result["status"] == "review_recorded"
        assert service.model.calls == 0
    finally:
        service.close()
