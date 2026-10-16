from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.1.0"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_dotenv() -> None:
    """Minimal .env reader (no extra dependency). Real environment variables win."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


@dataclass
class Settings:
    host: str = "127.0.0.1"  # never 0.0.0.0 by default
    port: int = 41500
    access_token: str = ""
    allowed_origins: list[str] = field(default_factory=list)
    db_path: str = str(DATA_DIR / "smart_remote.db")
    cert_dir: str = str(DATA_DIR / "certs")
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    use_mock_adapters: bool = False
    trust_proxy: bool = False
    llm_api_key: str = ""
    # Optional allowlist of client networks (CIDR). Empty = anyone with a valid code. Loopback is always allowed.
    allowed_cidrs: list[str] = field(default_factory=list)
    llm_model: str = "claude-opus-5-5"
    token_was_generated: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()
        s = cls(
            host=os.environ.get("BACKEND_HOST", "127.0.0.1"),
            port=int(os.environ.get("BACKEND_PORT", "41500")),
            access_token=os.environ.get("ACCESS_TOKEN", ""),
            allowed_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            allowed_cidrs=[c.strip() for c in os.environ.get("ALLOWED_CIDRS", "").split(",") if c.strip()],
            llm_model=os.environ.get("LLM_MODEL", "claude-opus-5-5"),
            trust_proxy=os.environ.get("TRUST_PROXY", "").lower() in {"1", "true", "yes"},
            ssl_certfile=os.environ.get("SSL_CERTFILE", ""),
            ssl_keyfile=os.environ.get("SSL_KEYFILE", ""),
            use_mock_adapters=os.environ.get("USE_MOCK_ADAPTERS", "").lower() in {"1", "true", "yes"},
        )
        if not s.access_token or s.access_token == "change-me":
            s.access_token = secrets.token_urlsafe(24)
            s.token_was_generated = True
        return s
