import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schemas import DomainError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS corpus_versions (
                    version TEXT PRIMARY KEY, digest TEXT NOT NULL, loaded_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, version TEXT NOT NULL, title TEXT NOT NULL,
                    category TEXT NOT NULL, text TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, input TEXT NOT NULL, input_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions (
                    case_id TEXT PRIMARY KEY REFERENCES cases(id), decision_id TEXT NOT NULL UNIQUE,
                    body TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(case_id, kind));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ensure_case(self, case_id, expense):
        body = canonical(expense)
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT input_hash FROM cases WHERE id=?", (case_id,)).fetchone()
            if old and old["input_hash"] != digest:
                raise DomainError(
                    "idempotency_conflict", "This request ID was used with another expense."
                )
            db.execute(
                "INSERT OR IGNORE INTO cases VALUES (?, ?, ?, ?)", (case_id, body, digest, now())
            )
            db.execute(
                "INSERT OR IGNORE INTO audit (case_id,kind,detail,created_at) VALUES (?,?,?,?)",
                (case_id, "submitted", canonical({"input_sha256": digest}), now()),
            )

    def case(self, case_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if not row:
                raise DomainError("not_found", "Expense review not found.", 404)
            return dict(row) | {"input": json.loads(row["input"])}

    def decision(self, case_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM decisions WHERE case_id=?", (case_id,)).fetchone()
            return (
                (
                    json.loads(row["body"])
                    | {"reviewer": row["reviewer"], "recorded_at": row["created_at"]}
                )
                if row
                else None
            )

    def record_decision(self, case_id, body, reviewer):
        serialized = canonical(body)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM decisions WHERE case_id=?", (case_id,)).fetchone()
            if old:
                if old["body"] != serialized or old["reviewer"] != reviewer:
                    raise DomainError(
                        "decision_conflict", "A different review decision is already recorded."
                    )
            else:
                try:
                    db.execute(
                        "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
                        (case_id, body["decision_id"], serialized, reviewer, now()),
                    )
                except sqlite3.IntegrityError as exc:
                    raise DomainError("decision_conflict", "Decision ID is already used.") from exc
            db.execute(
                "INSERT OR IGNORE INTO audit (case_id,kind,detail,created_at) VALUES (?,?,?,?)",
                (
                    case_id,
                    "human_decision_recorded",
                    canonical(
                        {
                            "decision_id": body["decision_id"],
                            "reviewer": reviewer,
                            "decision": body["decision"],
                        }
                    ),
                    now(),
                ),
            )
        return self.decision(case_id)

    def audit(self, case_id, kind, detail):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO audit (case_id,kind,detail,created_at) VALUES (?,?,?,?)",
                (case_id, kind, canonical(detail), now()),
            )

    def events(self, case_id):
        with self.connect() as db:
            return [
                dict(r) | {"detail": json.loads(r["detail"])}
                for r in db.execute(
                    "SELECT seq,kind,detail,created_at FROM audit WHERE case_id=? ORDER BY seq",
                    (case_id,),
                )
            ]
