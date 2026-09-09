import json

import pytest
from conftest import EvidenceStub
from fastapi.testclient import TestClient

from finagent.api import create_app
from finagent.config import Settings
from finagent.model import OllamaModel
from finagent.schemas import DomainError

SUBMIT = "submitter-token-for-tests-0000000"
REVIEW = "reviewer-token-for-tests-00000000"


@pytest.fixture
def client(tmp_path):
    settings = Settings(tmp_path, SUBMIT, REVIEW)
    with TestClient(create_app(settings, EvidenceStub())) as value:
        yield value


def test_auth_roles_and_review_flow(client, expense):
    assert client.post("/api/reviews", json=expense).status_code == 401
    headers = {"Authorization": f"Bearer {SUBMIT}", "Idempotency-Key": "api-test-1042"}
    response = client.post("/api/reviews", headers=headers, json=expense)
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_review"
    review = {
        "decision_id": "api-decision",
        "decision": "approve_exception",
        "note": "Reviewed synthetic evidence.",
    }
    path = "/api/reviews/api-test-1042/decision"
    assert client.post(path, headers=headers, json=review).status_code == 403
    response = client.post(path, headers={"Authorization": f"Bearer {REVIEW}"}, json=review)
    assert response.status_code == 200
    assert response.json()["status"] == "review_recorded"
    assert response.json()["review"]["reviewer"] == "local-reviewer"


def test_schema_bounds_and_role_identity(client, expense):
    headers = {"Authorization": f"Bearer {SUBMIT}", "Idempotency-Key": "api-test-1042"}
    for changed in [
        {"amount_cents": -1},
        {"amount_cents": 1.5},
        {"currency": "INR"},
        {"reviewer": "admin"},
    ]:
        assert (
            client.post("/api/reviews", headers=headers, json=expense | changed).status_code == 422
        )
    assert client.get("/api/policies/search").status_code == 401
    assert client.get("/api/policies/search?q=receipt", headers=headers).json()["chunks"]


def test_ui_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "FinAgent RiskOps" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/assets/app.js").status_code == 200
    assert client.post("/api/reviews", content="x" * 33000).status_code == 413


def test_invalid_configuration_fails_startup(tmp_path):
    with pytest.raises(ValueError, match="separate"):
        with TestClient(create_app(Settings(tmp_path, "", ""), EvidenceStub())):
            pass
    with pytest.raises(ValueError, match="local Ollama"):
        Settings(tmp_path, SUBMIT, REVIEW, ollama_url="https://paid-provider.example").validate()


def test_ollama_adapter_contract(monkeypatch):
    import httpx

    captured = []
    original = httpx.Client
    draft = {
        "recommendation": "exception_required",
        "summary": "A human exception review is required.",
        "citations": [
            {
                "chunk_id": "meals-v1-1",
                "quote": "A meal expense above USD 50.00 requires a human exception review.",
            }
        ],
    }

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(draft)}})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    model = OllamaModel("http://127.0.0.1:11434", "contract-model")
    result = model.draft({}, {"recommendation": "exception_required"}, [])
    assert result == draft
    assert json.loads(model.last_attempt["raw_response"])["message"]["content"] == json.dumps(draft)
    assert captured[0]["format"]["additionalProperties"] is False
    assert captured[0]["stream"] is False
    assert captured[0]["options"]["temperature"] == 0
    assert "untrusted" in captured[0]["messages"][0]["content"]


def test_ollama_malformed_response_is_fail_closed(monkeypatch):
    import httpx

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"message": {"content": "not JSON"}})
            ),
            **kw,
        ),
    )
    with pytest.raises(DomainError, match="output invalid"):
        OllamaModel("http://localhost:11434", "contract-model").draft({}, {}, [])


def test_chunked_body_cap(client):
    def chunks():
        yield b"x" * 20000
        yield b"y" * 20000

    response = client.post("/api/reviews", content=chunks())
    assert response.status_code == 413


def test_non_ascii_token_rejected(client):
    response = client.get("/api/policies/search", headers={b"Authorization": b"Bearer \xc3\xa9"})
    assert response.status_code == 401
