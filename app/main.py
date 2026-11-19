import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import routes_campaigns, routes_offers
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.keitaro.errors import KeitaroError
from app.services.campaign_creator import CampaignExistsError
from app.services.campaign_editor import EditorError

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast with a clear ConfigError if .env is incomplete
    setup_logging(settings.log_level)

    app = FastAPI(title="Adrobot", description="Keitaro campaign creator & editor", version="0.3.0")

    @app.exception_handler(KeitaroError)
    async def keitaro_error_handler(request: Request, exc: KeitaroError) -> JSONResponse:
        log.warning("%s %s -> %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.message, "error": type(exc).__name__, "keitaro_status": exc.status_code},
        )

    @app.exception_handler(CampaignExistsError)
    async def campaign_exists_handler(request: Request, exc: CampaignExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc), "campaign_id": exc.campaign_id})

    @app.exception_handler(EditorError)
    async def editor_error_handler(request: Request, exc: EditorError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.message, "error": type(exc).__name__})

    @app.get("/health", tags=["service"])
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_offers.router)
    app.include_router(routes_campaigns.router)
    return app


app = create_app()
