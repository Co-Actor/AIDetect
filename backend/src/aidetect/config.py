from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8010
    api_cors_origins: str = "http://localhost:9000"

    aidetect_internal_token: str = Field(default="dev-token-change-me", min_length=8)

    # ── Persistence (Postgres in prod, SQLite for tests) ─────────────
    database_url: str = "postgresql+asyncpg://aidetect:aidetect@localhost:5432/aidetect"

    # ── User auth (JWT) + Google sign-in + sharing trials ────────────
    auth_jwt_secret: str = Field(default="dev-jwt-secret-change-me-please", min_length=16)
    auth_jwt_expire_minutes: int = 10080  # 7 days
    google_oauth_client_id: str | None = None
    app_base_url: str = "http://localhost:9000"
    trial_check_limit: int = 3

    # ── Invite-only registration ─────────────────────────────────────
    registration_open: bool = False
    resend_api_key: str | None = None
    email_from: str = "AIDetect <onboarding@resend.dev>"
    invite_expire_days: int = 14
    # Comma-separated emails granted the admin role (seeded on startup + on login).
    admin_emails: str = "i.salmova@cccrafts.ai"

    coactor_database_url: str | None = None

    redis_url: str | None = "redis://localhost:6380/0"

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_judge_model_fast: str = "anthropic/claude-haiku-4-5"
    llm_judge_model_balanced: str = "anthropic/claude-haiku-4-5"
    llm_judge_model_thorough: str = "anthropic/claude-sonnet-4-6"
    llm_judge_timeout_sec: float = 20.0

    max_text_length: int = 100_000
    default_mode: Literal["fast", "balanced", "thorough"] = "balanced"

    agg_weight_statistical: float = 0.25
    agg_weight_patterns: float = 0.35
    agg_weight_llm_judge: float = 0.40

    rubric_version: str = "v1"
    model_version: str = "aidetect-0.1.0"

    cache_ttl_result: int = 7 * 24 * 3600
    cache_ttl_idempotency: int = 24 * 3600

    data_dir: str = "data"
    feedback_log_path: str = "data/feedback.jsonl"

    # ── Observability ────────────────────────────────────────────
    # Langfuse — LLM tracing / cost dashboards / prompt versioning.
    # Disabled by default; the client lazy-inits only when both keys are
    # set, otherwise all instrumentation hooks become no-ops.
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_release: str | None = None
    langfuse_environment: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def admin_emails_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def model_for_mode(self, mode: str) -> str:
        return {
            "fast": self.llm_judge_model_fast,
            "balanced": self.llm_judge_model_balanced,
            "thorough": self.llm_judge_model_thorough,
        }.get(mode, self.llm_judge_model_balanced)


@lru_cache
def get_settings() -> Settings:
    return Settings()
