"""HTML pages. All data is loaded by jQuery from the JSON API (/api/...)."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(include_in_schema=False)


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/create")


@router.get("/create", response_class=HTMLResponse)
def create_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "create.html", {"active": "create"})


@router.get("/edit", response_class=HTMLResponse)
@router.get("/edit/{campaign_id}", response_class=HTMLResponse)
def edit_page(request: Request, campaign_id: int | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "edit.html", {"active": "edit", "campaign_id": campaign_id})
