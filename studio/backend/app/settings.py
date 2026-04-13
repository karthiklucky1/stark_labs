"""
Mark II Studio — Application Settings
Pydantic BaseSettings for all environment configuration.
"""
from __future__ import annotations

from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


def _default_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _default_database_url() -> str:
    return f"sqlite+aiosqlite:///{(_default_project_root() / 'markii_studio.db').as_posix()}"


class Settings(BaseSettings):
    """Central configuration loaded from environment/.env."""

    # Load .env from current dir or repo root (studio/backend/../../../.env)
    model_config = {
        "env_file": [".env", "../../.env"],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # ── Paths ──────────────────────────────────────────────
    project_root: Path = Field(default_factory=_default_project_root)
    mark_ii_dir: Path = Field(default_factory=lambda: _default_project_root() / "mark_ii")

    # ── API Keys ───────────────────────────────────────────
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    zhipu_api_key: str = ""
    e2b_api_key: str = ""

    # ── Model Selection ────────────────────────────────────
    openai_builder_model: str = "gpt-5.4-2026-03-05"
    deepseek_builder_model: str = "deepseek-reasoner"
    zhipu_builder_model: str = "glm-4-air"
    claude_judge_model: str = "claude-sonnet-4-20250514"
    claude_interviewer_model: str = "claude-sonnet-4-20250514"
    ollama_builder_model: str = "deepseek-coder:6.7b-instruct-q4_K_M"

    # ── DeepSeek ───────────────────────────────────────────
    deepseek_base_url: str = "https://api.deepseek.com"

    # ── Zhipu AI ───────────────────────────────────────────
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    
    # ── Ollama ─────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"

    # ── Database ───────────────────────────────────────────
    database_url: str = Field(default_factory=_default_database_url)

    # ── Redis (optional for V1 dev) ────────────────────────
    redis_url: str = ""

    # ── GitHub OAuth ───────────────────────────────────────
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:3000/auth/callback"

    # ── Session / Build Limits ─────────────────────────────
    max_marks: int = 7
    max_build_timeout_s: int = 300
    max_hardening_timeout_s: int = 600
    max_interview_turns: int = 20

    # ── E2B Sandbox ────────────────────────────────────────
    e2b_sandbox_timeout_s: int = 3600

    # ── Server ─────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:8000",
    ])

    # ── Brand ──────────────────────────────────────────────
    product_name: str = "Mark II Studio"

    # ── Supported Profiles ─────────────────────────────────
    supported_profiles: list[str] = Field(default_factory=lambda: [
        "fastapi_service",
        "nextjs_webapp",
    ])

    # ── Mark names ─────────────────────────────────────────
    mark_names: list[str] = Field(default_factory=lambda: [
        "I", "II", "III", "IV", "V", "VI", "VII",
    ])


    # ── Feature availability checks ────────────────────────
    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_deepseek(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def has_zhipu(self) -> bool:
        return bool(self.zhipu_api_key)

    @property
    def has_e2b(self) -> bool:
        return bool(self.e2b_api_key)

    @property
    def has_github_oauth(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def has_ollama(self) -> bool:
        """Determines if the local personal coder (Ollama) is available."""
        # Simple heuristic: true if model is set. 
        # In runtime, we'll probe it.
        return bool(self.ollama_builder_model)

    @property
    def dual_builder(self) -> bool:
        """True if both OpenAI and DeepSeek are configured for parallel builds."""
        return bool(self.openai_api_key and self.deepseek_api_key)

    @model_validator(mode="after")
    def normalize_database_url(self) -> "Settings":
        """Resolve relative SQLite paths from the repo root for stable local dev."""
        sqlite_prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
        for prefix in sqlite_prefixes:
            if self.database_url.startswith(prefix):
                db_path = self.database_url[len(prefix):]
                if db_path and not db_path.startswith("/"):
                    resolved = (self.project_root / db_path).resolve()
                    self.database_url = f"{prefix}{resolved.as_posix()}"
                break
        return self


settings = Settings()
