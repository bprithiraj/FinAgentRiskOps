import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    submit_token: str
    review_token: str
    reviewer: str = "local-reviewer"
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:1.5b"
    model_timeout: float = 120.0

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.getenv("FINAGENT_DATA_DIR", "data")),
            os.getenv("FINAGENT_SUBMIT_TOKEN", ""),
            os.getenv("FINAGENT_REVIEW_TOKEN", ""),
            os.getenv("FINAGENT_REVIEWER", "local-reviewer"),
            os.getenv("FINAGENT_OLLAMA_URL", "http://127.0.0.1:11434"),
            os.getenv("FINAGENT_MODEL", "qwen2.5:1.5b"),
            float(os.getenv("FINAGENT_MODEL_TIMEOUT", "120")),
        )

    def validate(self):
        if min(len(self.submit_token), len(self.review_token)) < 24:
            raise ValueError("Set separate submitter and reviewer tokens (24+ characters).")
        if self.submit_token == self.review_token:
            raise ValueError("Submitter and reviewer tokens must differ.")
        url = urlparse(self.ollama_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1", "ollama"}:
            raise ValueError("Only a local Ollama endpoint is permitted; no paid/cloud providers.")
        if not self.reviewer or len(self.reviewer) > 80:
            raise ValueError("Reviewer identity must be 1-80 characters.")
        if not 1 <= self.model_timeout <= 600:
            raise ValueError("Model timeout must be between 1 and 600 seconds.")
