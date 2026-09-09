# Validation record

## Observed semantic failure in the original candidate

The first real run used source commit `0845b44f8f396bbd20abe684e0d1321fde49fc8f`, local Ollama 0.33.3, and `qwen2.5:0.5b` (Q4_K_M). Its raw results are preserved without edits in [baseline-0845b44-semantic-failure.json](artifacts/baseline-0845b44-semantic-failure.json).

**That candidate failed semantic safety.** Its original automated gate reported 8/8 structural passes because classifications and exact quotes were valid. Manual inspection found a model-written summary claiming a one-million-dollar limit in response to an injected question. Four other summaries contradicted their own classifications or limits. The 8/8 field in the preserved baseline is not a quality-success claim.

The fix restricts model output to evidence selection and exact quotes, requires the complete applicable-rule paragraph, rejects arbitrary narrative fields, and constructs visible explanations from trusted typed policy facts. New tests reproduce the injected million-dollar narrative, benign contradictions, and incomplete applicable-rule quotes. The same frozen input set is being rerun on the fixed source; no input cases were changed.

## Verification

- Original deterministic suite: 29 passed. Final adapter evidence-capture recheck: 2 passed.
- Updated full suite after the semantic fix: **34 passed** in 13.20 seconds on Windows/Python 3.12.2. One upstream Starlette/AnyIO deprecation warning.
- Ruff check and format check: passed for all 17 Python files.
- Dependency compatibility: `pip check` passed; `requirements-lock.txt` records 52 exact pins.
- Actual local model rerun: pending source commit and execution.
- Docker execution and browser visual review: not verified in this environment. API tests verify the UI files are served, not their visual appearance.

The corpus is fictional. This small frozen set is a reproducible acceptance check, not evidence of financial accuracy, general injection immunity, or production readiness.
