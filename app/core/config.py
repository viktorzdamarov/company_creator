"""Application settings loaded from environment / .env file."""
from functools import lru_cache

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = Field(..., description="Base URL of the Keitaro tracker")
    keitaro_api_key: SecretStr = Field(..., description="Keitaro Admin API key")

    # Name or numeric ID of existing Keitaro entities used for new campaigns.
    keitaro_default_domain: str = "kylovoa.com"
    keitaro_default_group: str = "FORTESTS"
    keitaro_default_source: str = "FORTESTS"

    keitaro_timeout: float = 15.0
    keitaro_max_retries: int = 3
    keitaro_retry_backoff: float = 0.5  # seconds, doubled each retry

    database_url: str = "sqlite:///./adrobot.db"
    log_level: str = "INFO"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = ", ".join(str(e["loc"][0]).upper() for e in exc.errors())
        raise ConfigError(
            f"Invalid or missing configuration: {missing}. "
            "Copy .env.example to .env and fill in the values."
        ) from exc
