from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast with a clear ConfigError if .env is incomplete
    setup_logging(settings.log_level)

    app = FastAPI(title="Adrobot", description="Keitaro campaign creator & editor", version="0.1.0")

    @app.get("/health", tags=["service"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
