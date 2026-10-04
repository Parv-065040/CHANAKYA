"""Environment-driven configuration. No secrets in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _f(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_f("CHANAKYA_DATA_DIR", "./data/store")))
    groq_api_key: str = field(default_factory=lambda: _f("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: _f("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_base_url: str = field(default_factory=lambda: _f("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    embedding_provider: str = field(default_factory=lambda: _f("EMBEDDING_PROVIDER", "hashing"))
    embedding_model: str = field(default_factory=lambda: _f("EMBEDDING_MODEL", "BAAI/bge-m3"))
    embedding_dimension: int = field(default_factory=lambda: int(_f("EMBEDDING_DIMENSION", "1024")))
    chunk_max_chars: int = field(default_factory=lambda: int(_f("CHUNK_MAX_CHARS", "1200")))
    chunk_min_chars: int = field(default_factory=lambda: int(_f("CHUNK_MIN_CHARS", "250")))
    min_relevance: float = field(default_factory=lambda: float(_f("MIN_RELEVANCE", "0.15")))
    min_coverage: float = field(default_factory=lambda: float(_f("MIN_COVERAGE", "0.6")))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_f("RATE_LIMIT_PER_MINUTE", "30")))
    max_upload_mb: int = field(default_factory=lambda: int(_f("MAX_UPLOAD_MB", "25")))
    storage_backend: str = field(default_factory=lambda: _f("STORAGE_BACKEND", "local"))
    retrieval_backend: str = field(default_factory=lambda: _f("RETRIEVAL_BACKEND", "local"))
    supabase_url: str = field(default_factory=lambda: _f("SUPABASE_URL", ""))
    supabase_service_key: str = field(default_factory=lambda: _f("SUPABASE_SERVICE_ROLE_KEY", ""))
    supabase_bucket: str = field(default_factory=lambda: _f("SUPABASE_BUCKET", "chanakya-docs"))
    hf_token: str = field(default_factory=lambda: _f("HF_API_TOKEN", ""))
    hf_embed_url: str = field(default_factory=lambda: _f("HF_EMBED_URL", ""))
    auth_mode: str = field(default_factory=lambda: _f("AUTH_MODE", "none"))
    admin_token: str = field(default_factory=lambda: _f("ADMIN_TOKEN", ""))
    user_tokens: str = field(default_factory=lambda: _f("USER_TOKENS", "{}"))
    seed_demo_data: bool = field(default_factory=lambda: _f("SEED_DEMO_DATA", "true").lower() == "true")
    cors_origin: str = field(default_factory=lambda: _f("CORS_ORIGIN", "*"))
    host: str = field(default_factory=lambda: _f("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_f("PORT", "8000")))
