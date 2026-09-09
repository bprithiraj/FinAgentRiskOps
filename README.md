# FinAgent RiskOps

A runnable local assistant for **fictional expense-policy exceptions**. It retrieves versioned policy evidence, asks a local Ollama model to select exact policy quotes, validates that evidence, constructs an explanation from typed policy facts, and pauses in a durable LangGraph workflow for an authenticated human decision.

The assistant never pays an expense. Its supported scope is one USD meal, taxi journey, or hotel night, using synthetic policy limits. No company data, paid model API, cloud database, or external tracing is required.

## What this release implements

- Actual paragraph ingestion and SQLite FTS5 retrieval with document/version IDs and SHA-256 provenance.
- Deterministic policy limits and missing-receipt checks. A language model cannot change these rules.
- Real Ollama JSON-schema evidence selection; arbitrary model narrative is rejected, with no runtime fake-model fallback.
- Exact quote and citation membership validation, a complete quote of the applicable rule, and rejection of extra output fields.
- LangGraph `interrupt()` and SQLite checkpoints that survive service restart.
- Separate submitter/reviewer bearer roles, immutable reviewer identity from configuration, request idempotency, and conflicting-decision rejection.
- A durable decision ledger and audit entries committed atomically; interrupted graph delivery recovers from that ledger.
- A browser workspace to submit, inspect citations, resume a saved review, and record a decision.

## Run locally

Use Python 3.11 or 3.12 and [Ollama](https://docs.ollama.com/quickstart). Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
ollama pull qwen2.5:0.5b
$env:FINAGENT_MODEL = 'qwen2.5:0.5b'
$env:FINAGENT_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:FINAGENT_SUBMIT_TOKEN = (.\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(32))')
$env:FINAGENT_REVIEW_TOKEN = (.\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(32))')
$env:FINAGENT_REVIEWER = 'local-reviewer'
.\.venv\Scripts\python.exe -m finagent.cli serve --port 8082
```

Open [localhost:8082](http://127.0.0.1:8082). Enter the two tokens you configured in the UI. Tokens are held only in page memory. Ollama must be running; on a manual installation start `ollama serve` first. A 0.5B model is a free CPU smoke-test choice, not a quality guarantee; a larger local instruction model may select evidence more reliably. Changing the model does not weaken validation.

Linux/macOS use `python3 -m venv .venv`, `.venv/bin/python`, and `export NAME=value`. The `.env.example` file documents configuration; the Python service does not load `.env` automatically.

If your Ollama server uses another loopback port, set `FINAGENT_OLLAMA_URL`. The adapter accepts only loopback hosts and the Compose `ollama` service name. Model errors remain visible and retryable. They never turn into fabricated answers.

## Walk through a recovery

1. Submit the default USD 68.50 meal with a receipt. The standard synthetic meal limit is USD 50.00; a valid model draft pauses as `awaiting_review`.
2. Copy the review ID. Stop and restart the Python process with the same `FINAGENT_DATA_DIR` (default `./data`).
3. Enter the tokens again and load the saved ID. The draft and evidence are unchanged; the model is not called again.
4. Use the reviewer token to record a decision. A repeated identical decision is idempotent; a changed decision returns `409`.
5. Try a missing receipt. `approve_exception` is rejected; the reviewer can request information or reject.

The app records a review outcome only. `request_information` is a terminal record for that submission; submit corrected facts under a new idempotency key for a new review.

## API

Every `/api/` route requires `Authorization: Bearer <token>`. These are local demonstration roles, not organization-wide identity management.

| Endpoint | Behavior |
|---|---|
| `POST /api/reviews` | Submit an `Expense`; include a unique `Idempotency-Key` of 8-64 letters, digits, hyphens or underscores. |
| `GET /api/reviews/{id}` | Read persisted state and recover interrupted delivery. |
| `POST /api/reviews/{id}/decision` | Reviewer only; body contains `decision_id`, `decision`, `note`. |
| `POST /api/reviews/{id}/retry` | Retry a failed local-model draft for the same immutable input. |
| `GET /api/policies/search?q=receipt` | Read-only FTS evidence search. |
| `GET /health` | Service readiness; model availability is checked on generation. |

Example expense body:

```json
{"expense_id":"EXP-1042","category":"meal","amount_cents":6850,"currency":"USD","receipt_present":true,"business_purpose":"Fictional customer workshop meal."}
```

## Verify

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m finagent.cli evaluate --output artifacts\local-evaluation.json
```

Unit/contract tests use an explicitly named `EvidenceStub` confined to `tests/`. They prove deterministic workflow behavior and failure boundaries; they do **not** measure model quality. The evaluation command calls the actual configured Ollama model over HTTP for eight frozen synthetic acceptance cases, requires a deterministic visible explanation, writes raw outputs, timing, corpus hash and model metadata, and exits nonzero on failed acceptance. Unsupported cases are rejected deterministically without a model call. `--limit 1` runs a small smoke test.

See [VALIDATION.md](VALIDATION.md) for the current verified results and their limits. Dependency versions used for validation are captured in `requirements-lock.txt`; install the lock before `pip install --no-deps -e .` to reproduce that environment. CI uses this lock and runs the deterministic tests on Linux and Windows.

## Containers

Create a `.env` containing distinct 24+ character `FINAGENT_SUBMIT_TOKEN` and `FINAGENT_REVIEW_TOKEN` values, then:

```sh
docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:0.5b
```

Only `127.0.0.1:8082` is published. Model and workflow volumes persist across restarts. The model download uses disk and bandwidth; inference is local and free. The container route is an additional packaging option; validation status is recorded separately from local Python tests.

## Boundaries

This is a complete bounded local v1, not a production financial platform. It uses one service process, one SQLite data directory, eight admitted requests at most, and serialized graph execution. An OS lock rejects a second process sharing that directory. Do not run multiple Uvicorn workers. Stop the service before copying both SQLite databases and their WAL files for a backup.

Receipt presence and business purpose are caller-supplied synthetic facts; there is no receipt OCR or fraud verification. There are no embeddings, bank/payment integrations, multi-currency rules, multi-tenant authorization, or distributed job workers. The first real evaluation demonstrated that a model can produce false narrative even beside correct quotes. This release therefore accepts only evidence selection from the model and computes the visible explanation from typed amount, receipt, category, and policy facts. Prompt-injection pattern checks are only an extra filter; the enforced boundaries are no model-selected executable tools, no model narrative fields, schema validation, complete applicable-rule quotes, deterministic rules, and human review. Do not treat this small evaluation set as general prompt-injection immunity.

Policies are administrator-controlled source files, not user uploads. Editing existing content requires a new policy version. Existing reviews retain their original evidence snapshots; they are not silently migrated to new policies. Shared local role tokens permit reading any known review ID; use real identity, ownership checks, HTTPS, key rotation, storage encryption and a deployment threat model before any multi-user deployment.

## Architecture and source references

See [docs/architecture.md](docs/architecture.md). The workflow follows the official [LangGraph interrupt](https://docs.langchain.com/oss/python/langgraph/interrupts) and [SQLite checkpointer](https://docs.langchain.com/oss/python/integrations/checkpointers/index) contracts. The local model adapter uses [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Retrieval is [SQLite FTS5](https://www.sqlite.org/fts5.html), not a simulated retrieval function.
