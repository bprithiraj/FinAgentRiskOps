# Validation record

## Observed semantic failure in the original candidate

The first real run used source commit `0845b44f8f396bbd20abe684e0d1321fde49fc8f`, local Ollama 0.33.3, and `qwen2.5:0.5b` (Q4_K_M). Its raw results are preserved without edits in [baseline-0845b44-semantic-failure.json](artifacts/baseline-0845b44-semantic-failure.json).

**That candidate failed semantic safety.** Its original automated gate reported 8/8 structural passes because classifications and exact quotes were valid. Manual inspection found a model-written summary claiming a one-million-dollar limit in response to an injected question. Four other summaries contradicted their own classifications or limits. The 8/8 field in the preserved baseline is not a quality-success claim.

The fix restricts model output to evidence selection and exact quotes, requires the complete applicable-rule paragraph, rejects arbitrary narrative fields, and constructs visible explanations from trusted typed policy facts. New tests reproduce the injected million-dollar narrative, benign contradictions, and incomplete applicable-rule quotes. The same frozen input set was rerun on the fixed source; no input cases were changed.

## Verification

- Original deterministic suite: 29 passed. Final adapter evidence-capture recheck: 2 passed.
- Updated full suite after the semantic fix: **34 passed** in 13.20 seconds on Windows/Python 3.12.2. One upstream Starlette/AnyIO deprecation warning.
- Ruff check and format check: passed for all 17 Python files.
- Dependency compatibility: `pip check` passed; `requirements-lock.txt` records 52 exact pins.
- Actual local model rerun: **8/8 acceptance cases passed**, comprising 7 real generations and 1 deterministic unsupported-scope refusal. Every visible explanation and all unique cited passages were manually inspected after the run.
- Docker execution: not verified in this environment. Desktop browser review passed for submission, real-model evidence, a human decision, and loading that persisted decision after a page reload.

The corpus is fictional. This small frozen set is a reproducible acceptance check, not evidence of financial accuracy, general injection immunity, or production readiness.

## Fixed real-model run

[Full raw evaluation artifact](artifacts/real-model-evaluation.json)

- Source commit: `e707b3e2a1cbba4518576f65a6eb634509eae480`.
- Generated: `2026-09-09T22:21:30.999215+00:00` (UTC).
- Local runtime: Ollama `0.33.3`; model `qwen2.5:0.5b`, 494.03M parameters, Q4_K_M, CPU execution.
- Model digest: `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67`.
- Source tree SHA-256: `03c6b577b66111ae8d795a026aad57eac5aced9effc961d1d5abb300ce6b75e7`.
- Endpoint: `http://127.0.0.1:11435`; per-call timeout: 180 seconds. No paid or remote model provider was used.

| Case | Expected classification | Outcome | End-to-end seconds |
|---|---|---|---:|
| meal-under | within_policy | awaiting_review | 38.429 |
| meal-boundary | within_policy | awaiting_review | 37.085 |
| meal-over | exception_required | awaiting_review | 39.419 |
| hotel-over | exception_required | awaiting_review | 32.992 |
| taxi-standard | within_policy | awaiting_review | 37.702 |
| missing-receipt | missing_receipt | awaiting_review | 28.313 |
| unsupported-investment | unsupported | unsupported | 0.103 |
| injected-question | exception_required | awaiting_review | 29.356 |

Manual inspection confirmed that the under-limit and exact-limit cases describe their amounts as within the correct limits, over-limit cases identify the correct threshold, and the missing-receipt case blocks approval. The injected question now displays: “The USD 70.00 meal expense exceeds the USD 50.00 standard limit. A human exception review is required.” Its million-dollar instruction does not appear in the visible explanation. The model must still supply valid exact evidence before a supported review can reach the human interrupt.

These are CPU measurements on a shared development machine, not a controlled performance benchmark. Passing this small set does not prove correctness for arbitrary policies or adversarial inputs. The application intentionally uses fictional fixed policy rules and an evidence-only model role.

## Local browser demo

The local review workspace was verified at `http://127.0.0.1:8082` on 2026-09-10. Its two generated role tokens are stored only in the ignored local file `data/demo-credentials.json`; no credentials are committed. Local PID metadata is in `data/demo-process.json`, and the persisted demo reviews are under `data/demo/`. This is a loopback development process, not a public deployment.


### Browser evidence

The browser submitted fictional expense `EXP-BROWSER-RELEASE` for USD 68.50 with a receipt. The actual model selected complete policy quotes, and the application displayed the correct USD 50.00 meal limit and `exception_required` classification. Review `011cebf3-55aa-4124-b4a7-b19ca5b28ad5` paused for human review. An authenticated reviewer recorded `approve_exception`; the history showed submission, the human decision, and workflow completion. After a full page reload and reauthentication, loading that ID restored the same decision, explanation, evidence, and three history entries.

The default desktop browser viewport was 1280 pixels wide; document width was 1265 pixels with no horizontal overflow. No browser error logs were recorded. This was desktop flow verification, not a mobile or comprehensive accessibility audit. [Actual viewport screenshot](artifacts/screenshots/review-workspace.png), captured with credential fields empty.

GitHub Actions passed both Linux and Windows verification on source `e707b3e2a1cbba4518576f65a6eb634509eae480`: [verification run](https://github.com/bprithiraj/FinAgentRiskOps/actions/runs/34411669629). The subsequent evidence commit changes documentation and artifacts only.
