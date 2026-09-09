import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import httpx

from .config import Settings
from .model import OllamaModel
from .schemas import Expense
from .workflow import Service


def evaluate(args):
    settings = Settings.from_env()
    model = OllamaModel(settings.ollama_url, settings.model, settings.model_timeout)
    fixtures = json.loads(files("finagent").joinpath("corpus/evaluation-cases.json").read_text())
    if args.limit:
        fixtures = fixtures[: args.limit]
    rows = []
    with tempfile.TemporaryDirectory(prefix="finagent-eval-") as directory:
        service = Service(Path(directory), model)
        try:
            for fixture in fixtures:
                expected = fixture["expected"]
                expense = Expense.model_validate(
                    {k: v for k, v in fixture.items() if k not in {"id", "expected"}}
                )
                start = time.perf_counter()
                model.last_attempt = None
                result = service.submit("eval-" + uuid.uuid4().hex, expense.model_dump())
                required_status = "unsupported" if expected == "unsupported" else "awaiting_review"
                passed = (
                    result["status"] == required_status
                    and result["assessment"]["recommendation"] == expected
                    and (
                        expected == "unsupported"
                        or result.get("draft", {}).get("summary_origin")
                        == "deterministic_policy_rules"
                    )
                )
                rows.append(
                    {
                        "fixture": fixture["id"],
                        "expected": expected,
                        "passed": passed,
                        "elapsed_seconds": round(time.perf_counter() - start, 3),
                        "result": result,
                        "model_attempt": model.last_attempt,
                    }
                )
                print(f"{fixture['id']}: {result['status']}; pass={passed}", flush=True)
            corpus = {"version": service.corpus.version, "sha256": service.corpus.digest}
        finally:
            service.close()
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            tags = client.get(settings.ollama_url.rstrip("/") + "/api/tags").json()
            server_version = (
                client.get(settings.ollama_url.rstrip("/") + "/api/version").json().get("version")
            )
        tag = next((m for m in tags.get("models", []) if m.get("name") == settings.model), None)
    except (httpx.HTTPError, ValueError):
        tag = None
        server_version = None
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        sha = ""
    source_root = Path(__file__).resolve().parent
    sources = {
        str(path.relative_to(source_root)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(source_root.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".json", ".html", ".css", ".js"}
    }
    source_digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    result = {
        "artifact_type": "real_local_model_acceptance_evaluation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": sha or "uncommitted",
        "model": model.metadata(),
        "model_manifest": tag,
        "ollama_version": server_version,
        "source_tree_sha256": source_digest,
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "processor": platform.processor(),
        },
        "corpus": corpus,
        "cases": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "runs": rows,
        "limitations": "Small frozen synthetic acceptance set. Not financial accuracy, production readiness, or general model safety evidence.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}: {result['passed']}/{result['cases']} acceptance cases passed.")
    return 0 if result["passed"] == result["cases"] else 1


def main():
    parser = argparse.ArgumentParser(description="Local synthetic expense review")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8082)
    evaluation = sub.add_parser(
        "evaluate", help="Call the real configured local Ollama model; never uses a stub"
    )
    evaluation.add_argument("--output", type=Path, default=Path("artifacts/local-evaluation.json"))
    evaluation.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.command == "evaluate" and args.limit < 0:
        parser.error("--limit must be zero (all cases) or a positive number")
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "finagent.api:create_app", factory=True, host="127.0.0.1", port=args.port, workers=1
        )
        return 0
    return evaluate(args)


if __name__ == "__main__":
    raise SystemExit(main())
