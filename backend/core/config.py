"""
Central configuration — all values from environment variables.
Import `settings` from core everywhere. Never read os.environ directly.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────────
    POSTGRES_DB: str = "cost_intelligence"
    POSTGRES_USER: str = "ci_user"
    POSTGRES_PASSWORD: str = "ci_pass"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # ── Ollama ────────────────────────────────────────────────────────────────
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_CONTEXT_WINDOW: int = 4096
    MODEL_DEFAULT: str = "qwen2.5:7b"
    MODEL_REASONING: str = "deepseek-r1:7b"
    MODEL_FALLBACK: str = "llama3.2:3b"

    # ── Model routing thresholds ──────────────────────────────────────────────
    # DeepSeek is invoked for ALL HIGH/CRITICAL — see blueprint §3 UPDATE note.
    DEEPSEEK_TRIGGER_SEVERITY: str = "HIGH"
    DEEPSEEK_CONFIDENCE_THRESHOLD: float = 0.80   # kept for legacy gate logic
    FALLBACK_TIMEOUT_MS: int = 120000  # 2 minutes for CPU-based 7B model inference
    MAX_DEEPSEEK_CALLS_PER_HOUR: int = 10
    MAX_OLLAMA_WORKERS: int = 5

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    EMAIL_FROM: str = "costbot@enterprise.local"
    ALERT_EMAIL: str = "finance@company.local"

    # ── App ───────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Business thresholds ────────────────────────────────────────────────────
    AUTO_APPROVE_LIMIT: float = 50000.0      # ₹ — above this needs human approval
    SLA_ESCALATION_THRESHOLD: float = 0.70   # P(breach) >= 0.70 triggers escalation
    DUPLICATE_WINDOW_DAYS: int = 30
    UNUSED_LICENSE_DAYS: int = 60
    PRICING_ANOMALY_PCT: float = 0.15        # >15% above benchmark = anomaly
    INFRA_WASTE_CPU_PCT: float = 5.0         # CPU < 5% for N days
    INFRA_WASTE_DAYS: int = 7

    # ── Approval auto-release ─────────────────────────────────────────────────
    PAYMENT_HOLD_AUTO_RELEASE_HOURS: int = 48  # release held payments if not confirmed

    class Config:
        env_file = "../.env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

# ── Routing config dict (mirrors blueprint §3 pseudocode) ─────────────────────
ROUTING_CONFIG: dict = {
    "deepseek_trigger_severity": settings.DEEPSEEK_TRIGGER_SEVERITY,
    "deepseek_confidence_threshold": settings.DEEPSEEK_CONFIDENCE_THRESHOLD,
    "fallback_on_timeout_ms": settings.FALLBACK_TIMEOUT_MS,
    "max_deepseek_calls_per_hour": settings.MAX_DEEPSEEK_CALLS_PER_HOUR,
    "ollama_context_window": settings.OLLAMA_CONTEXT_WINDOW,
}