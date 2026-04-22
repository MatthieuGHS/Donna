"""Configuration module using pydantic-settings.

All secrets are loaded from environment variables only.
Never hardcode any secret value in this file.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Environment
    environment: str = "dev"
    timezone: str = "Europe/Paris"

    # Telegram
    telegram_bot_token: str
    allowed_chat_ids: str  # comma-separated

    # Anthropic
    anthropic_api_key: str

    # Google Calendar
    google_calendar_id: str
    google_service_account_json: str  # JSON string

    # Zimbra (EDT école + IMAP mails)
    zimbra_ics_url: str = ""
    zimbra_user: str = ""
    zimbra_password: str = ""
    zimbra_cache_ttl_seconds: int = 86400
    zimbra_imap_host: str = ""
    zimbra_imap_port: int = 993
    zimbra_emails_cache_size: int = 30

    # Supabase
    supabase_url: str
    supabase_service_role_key: str

    # API FastAPI
    api_url: str = "http://localhost:8000"
    api_key: str

    # Scheduler
    recap_morning_hour: int = 7
    recap_afternoon_hour: int = 13

    # Pending actions
    pending_expiration_minutes: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @property
    def allowed_chat_ids_list(self) -> list[int]:
        return [int(cid.strip()) for cid in self.allowed_chat_ids.split(",") if cid.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in ("dev", "prod"):
            raise ValueError("ENVIRONMENT must be 'dev' or 'prod'")
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key_strength(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("API_KEY must be at least 32 characters")
        return v


settings = Settings()
