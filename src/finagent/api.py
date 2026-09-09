import hmac
import re
from contextlib import asynccontextmanager
from importlib.resources import files

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .body_limit import BodyLimitMiddleware
from .config import Settings
from .model import OllamaModel
from .schemas import DomainError, Expense, Review
from .workflow import Service


def create_app(settings=None, model=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        settings.validate()
        app.state.service = Service(
            settings.data_dir,
            model or OllamaModel(settings.ollama_url, settings.model, settings.model_timeout),
        )
        try:
            yield
        finally:
            app.state.service.close()

    app = FastAPI(
        title="FinAgent RiskOps",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        description="Fictional expense policy evidence and durable human reviews. No payments.",
    )

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def role(authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if token and hmac.compare_digest(token.encode(), settings.review_token.encode()):
            return "reviewer"
        if token and hmac.compare_digest(token.encode(), settings.submit_token.encode()):
            return "submitter"
        raise DomainError("unauthorized", "A valid bearer token is required.", 401)

    def reviewer(value=Depends(role)):
        if value != "reviewer":
            raise DomainError("forbidden", "A reviewer token is required.", 403)
        return settings.reviewer

    def case_key(value):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value):
            raise DomainError(
                "invalid_request_id",
                "Request ID must be 8-64 letters, digits, underscores or hyphens.",
                422,
            )
        return value

    @app.get("/health")
    def health():
        return {"status": "ready", "version": "1.0.0", "model_readiness": "checked_on_request"}

    @app.post("/api/reviews")
    def submit(
        expense: Expense, request: Request, idempotency_key: str = Header(), actor=Depends(role)
    ):
        return request.app.state.service.submit(case_key(idempotency_key), expense.model_dump())

    @app.get("/api/reviews/{case_id}")
    def get(case_id: str, request: Request, actor=Depends(role)):
        return request.app.state.service.get(case_key(case_id))

    @app.post("/api/reviews/{case_id}/decision")
    def decide(case_id: str, review: Review, request: Request, actor=Depends(reviewer)):
        return request.app.state.service.review(case_key(case_id), review.model_dump(), actor)

    @app.post("/api/reviews/{case_id}/retry")
    def retry(case_id: str, request: Request, actor=Depends(role)):
        return request.app.state.service.retry(case_key(case_id))

    @app.get("/api/policies/search")
    def search(request: Request, q: str = "expense", actor=Depends(role)):
        if len(q) > 1000:
            raise DomainError(
                "query_too_long", "Search queries are limited to 1000 characters.", 422
            )
        corpus = request.app.state.service.corpus
        return {"version": corpus.version, "sha256": corpus.digest, "chunks": corpus.search(q)}

    web = files("finagent").joinpath("web")
    app.mount("/assets", StaticFiles(directory=str(web)), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(web.joinpath("index.html")))

    app.add_middleware(BodyLimitMiddleware)
    return app
