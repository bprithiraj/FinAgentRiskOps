import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .process_lock import ProcessLock
from .retrieval import INJECTION, Corpus
from .schemas import DomainError, Draft
from .store import Store

ALLOWED_TOOLS = {"search_policy", "read_expense"}


class State(TypedDict, total=False):
    case_id: str
    expense: dict
    assessment: dict
    evidence: list[dict]
    draft: dict
    status: str
    error: dict
    review: dict
    model: dict


class Service:
    def __init__(self, data_dir: Path, model, corpus_source=None):
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.process_lock = ProcessLock(data_dir / "service.lock")
        self.store = Store(data_dir / "reviews.sqlite3")
        self.corpus = Corpus(self.store, corpus_source)
        self.model = model
        self.lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(8)
        self.connection = sqlite3.connect(data_dir / "checkpoints.sqlite3", check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.saver = SqliteSaver(
            self.connection, serde=JsonPlusSerializer(allowed_msgpack_modules=[])
        )
        graph = StateGraph(State)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("draft", self._draft)
        graph.add_node("human_review", self._review)
        graph.add_edge(START, "retrieve")
        graph.add_conditional_edges(
            "retrieve", lambda s: END if s["status"] == "unsupported" else "draft"
        )
        graph.add_conditional_edges(
            "draft", lambda s: "human_review" if s["status"] == "awaiting_review" else END
        )
        graph.add_edge("human_review", END)
        self.graph = graph.compile(checkpointer=self.saver)

    def close(self):
        self.connection.close()
        self.process_lock.close()

    @contextmanager
    def admitted(self):
        if not self.capacity.acquire(blocking=False):
            raise DomainError("busy", "Local review capacity is full; retry later.", 429)
        try:
            with self.lock:
                yield
        finally:
            self.capacity.release()

    def _retrieve(self, state):
        expense = state["expense"]
        denied = set(expense.get("requested_tools", [])) - ALLOWED_TOOLS
        if denied:
            raise DomainError(
                "tool_denied", "Only search_policy and read_expense are permitted.", 403
            )
        assessment = self.corpus.assess(expense)
        if assessment["recommendation"] == "unsupported":
            return {"assessment": assessment, "evidence": [], "status": "unsupported"}
        query = expense["category"] + " expense receipt limit human review " + expense["question"]
        evidence = self.corpus.search(query, expense["category"].strip().lower())
        if assessment["required_citation"] not in {c["id"] for c in evidence}:
            raise DomainError(
                "missing_evidence", "The applicable policy evidence could not be retrieved.", 422
            )
        return {"assessment": assessment, "evidence": evidence, "status": "retrieved"}

    def _draft(self, state):
        try:
            draft = Draft.model_validate(
                self.model.draft(state["expense"], state["assessment"], state["evidence"])
            ).model_dump()
            if draft["recommendation"] != state["assessment"]["recommendation"]:
                raise ValueError("Model contradicted the deterministic policy classification")
            sources = {e["id"]: e for e in state["evidence"]}
            cited = set()
            for citation in draft["citations"]:
                source = sources.get(citation["chunk_id"])
                if not source or citation["quote"] not in source["text"]:
                    raise ValueError("Citation must quote a retrieved source verbatim")
                cited.add(citation["chunk_id"])
            if state["assessment"]["required_citation"] not in cited:
                raise ValueError("The applicable rule must be cited")
            if INJECTION.search(draft["summary"]):
                raise ValueError("Instruction-like model output")
            return {"draft": draft, "status": "awaiting_review", "model": self.model.metadata()}
        except (ValueError, DomainError) as exc:
            code = exc.code if isinstance(exc, DomainError) else "invalid_evidence"
            return {
                "status": "model_error",
                "error": {
                    "code": code,
                    "message": "Model output failed validation or the local model was unavailable. No review decision was made.",
                },
                "model": self.model.metadata(),
            }

    def _review(self, state):
        # No side effects before interrupt: LangGraph reruns this node on resume.
        decision = interrupt(
            {
                "case_id": state["case_id"],
                "assessment": state["assessment"],
                "draft": state["draft"],
                "action": "Record a human review only; no payment.",
            }
        )
        return {"review": decision, "status": "review_recorded"}

    def _config(self, case_id):
        return {"configurable": {"thread_id": case_id}, "recursion_limit": 10}

    def _recover(self, case_id):
        case = self.store.case(case_id)
        config = self._config(case_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            self.graph.invoke({"case_id": case_id, "expense": case["input"]}, config)
            snapshot = self.graph.get_state(config)
        elif snapshot.next and not any(task.interrupts for task in snapshot.tasks):
            self.graph.invoke(None, config)
            snapshot = self.graph.get_state(config)
        decision = self.store.decision(case_id)
        if decision:
            self.store.audit(
                case_id,
                "human_decision_recorded",
                {
                    "decision_id": decision["decision_id"],
                    "reviewer": decision["reviewer"],
                    "decision": decision["decision"],
                },
            )
        if decision and snapshot.next:
            self.graph.invoke(Command(resume=decision), config)
            snapshot = self.graph.get_state(config)
        value = dict(snapshot.values)
        if value.get("status") == "review_recorded":
            self.store.audit(
                case_id, "workflow_completed", {"decision_id": value["review"]["decision_id"]}
            )
        value["created_at"] = case["created_at"]
        value["audit"] = self.store.events(case_id)
        return value

    def submit(self, case_id, expense):
        if set(expense.get("requested_tools", [])) - ALLOWED_TOOLS:
            raise DomainError("tool_denied", "Only read-only tools are permitted.", 403)
        with self.admitted():
            self.store.ensure_case(case_id, expense)
            return self._recover(case_id)

    def get(self, case_id):
        with self.admitted():
            return self._recover(case_id)

    def review(self, case_id, review, reviewer):
        with self.admitted():
            state = self._recover(case_id)
            if state["status"] not in {"awaiting_review", "review_recorded"}:
                raise DomainError(
                    "not_reviewable", "This case has no validated draft awaiting review."
                )
            if (
                state["assessment"]["recommendation"] == "missing_receipt"
                and review["decision"] == "approve_exception"
            ):
                raise DomainError(
                    "receipt_required",
                    "A missing receipt cannot be approved; request information or reject.",
                )
            # Commit the decision first. Recovery resumes the graph from this durable record.
            self.store.record_decision(case_id, review, reviewer)
            return self._recover(case_id)

    def retry(self, case_id):
        with self.admitted():
            state = self._recover(case_id)
            if state["status"] != "model_error":
                raise DomainError("not_retryable", "Only a failed model draft can be retried.")
            self.graph.update_state(
                self._config(case_id), {"status": "retrieved", "error": {}}, as_node="retrieve"
            )
            self.graph.invoke(None, self._config(case_id))
            return self._recover(case_id)
