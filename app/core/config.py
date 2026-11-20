"""Application settings loaded from environment / .env file."""
from functools import lru_cache

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = ""  # required unless DEMO_MODE
    keitaro_api_key: SecretStr = SecretStr("")  # required unless DEMO_MODE

    # DEMO mode: an in-process fake Keitaro with invented offers (see app/keitaro/demo.py); no real tracker needed.
    demo_mode: bool = False
    demo_state_file: str = "demo_state.json"

    # Name or numeric ID of existing Keitaro entities used for new campaigns.
    keitaro_default_domain: str = "kylovoa.com"
    keitaro_default_group: str = "FORTESTS"
    keitaro_default_source: str = "FORTESTS"

    keitaro_timeout: float = 15.0
    keitaro_max_retries: int = 3
    keitaro_retry_backoff: float = 0.5  # seconds, doubled each retry

    database_url: str = "sqlite:///./adrobot.db"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _keitaro_required_outside_demo(self):
        if not self.demo_mode:
            missing = [n for n, v in (("KEITARO_URL", self.keitaro_url), ("KEITARO_API_KEY", self.keitaro_api_key.get_secret_value())) if not v]
            if missing:
                raise ValueError(", ".join(missing))
        return self


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = ", ".join(
            str(e["loc"][0]).upper() if e["loc"] else str(e["msg"]).removeprefix("Value error, ") for e in exc.errors()
        )
        raise ConfigError(
            f"Invalid or missing configuration: {missing}. "
            "Copy .env.example to .env and fill in the values."
        ) from exc
