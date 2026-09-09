import hashlib
import json
import re
from importlib.resources import files

from .schemas import DomainError
from .store import canonical, now

INJECTION = re.compile(
    r"ignore (?:all |the |any )?(?:previous|prior|system) instructions|"
    r"system prompt|submit_payment|transfer_funds|execute (?:this )?code",
    re.I,
)


class Corpus:
    def __init__(self, store, source=None):
        self.store = store
        raw = (source or files("finagent").joinpath("corpus/policy-v1.json")).read_text(
            encoding="utf-8"
        )
        data = json.loads(raw)
        self.version, self.rules = data["version"], data["rules"]
        self.digest = hashlib.sha256(canonical(data).encode()).hexdigest()
        chunks = []
        for doc in data["documents"]:
            for n, paragraph in enumerate(doc["text"].split("\n\n"), 1):
                if INJECTION.search(paragraph):
                    raise DomainError(
                        "unsafe_corpus", "An instruction-like policy source was quarantined.", 422
                    )
                chunks.append(
                    (
                        f"{doc['id']}-{n}",
                        self.version,
                        doc["title"],
                        doc["category"],
                        paragraph,
                        hashlib.sha256(paragraph.encode()).hexdigest(),
                    )
                )
        ids = {c[0] for c in chunks}
        if len(ids) != len(chunks) or any(r["chunk_id"] not in ids for r in self.rules.values()):
            raise ValueError("Corpus chunk references must be unique and complete.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT digest FROM corpus_versions WHERE version=?", (self.version,)
            ).fetchone()
            if old and old[0] != self.digest:
                raise DomainError(
                    "corpus_version_conflict", "Changed corpus content requires a new version."
                )
            db.execute(
                "INSERT OR IGNORE INTO corpus_versions VALUES (?,?,?)",
                (self.version, self.digest, now()),
            )
            db.execute("DELETE FROM chunks_fts")
            db.execute("DELETE FROM chunks")
            db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)", chunks)
            db.executemany("INSERT INTO chunks_fts VALUES (?,?)", [(c[0], c[4]) for c in chunks])

    def search(self, query, category=None, limit=6):
        tokens = list(dict.fromkeys(re.findall(r"[a-zA-Z]{3,30}", query.lower())))[:20]
        if not tokens:
            return []
        match = " OR ".join('"' + t + '"' for t in tokens)
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT c.*, bm25(chunks_fts) AS rank FROM chunks_fts
                JOIN chunks c ON c.id=chunks_fts.id WHERE chunks_fts MATCH ?
                AND (? IS NULL OR c.category IN (?, 'general')) ORDER BY rank, c.id LIMIT ?""",
                (match, category, category, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def assess(self, expense):
        category = expense["category"].strip().lower()
        rule = self.rules.get(category)
        if not rule:
            return {
                "recommendation": "unsupported",
                "reason": "Only meal, hotel, and taxi expenses are supported.",
            }
        recommendation = (
            "missing_receipt"
            if not expense["receipt_present"]
            else "exception_required"
            if expense["amount_cents"] > rule["limit_cents"]
            else "within_policy"
        )
        return {
            "recommendation": recommendation,
            "limit_cents": rule["limit_cents"],
            "required_citation": "receipts-v1-1"
            if recommendation == "missing_receipt"
            else rule["chunk_id"],
            "policy_version": self.version,
            "corpus_sha256": self.digest,
        }
