from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_campaign_defaults, get_keitaro
from app.db.session import get_db
from app.keitaro.client import KeitaroClient
from app.services.campaign_creator import CampaignCreator, CreateCampaignResult
from app.services.defaults import CampaignDefaults
from app.services.geo import parse_geo

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, examples=["adrobot-test-au"])
    geo: list[str] = Field(..., description='Country codes: "MX,AU,RO" or ["MX","AU"]', examples=["AU"])
    offer_id: int = Field(..., gt=0, examples=[18813])

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("geo", mode="before")
    @classmethod
    def _parse_geo(cls, v):
        return parse_geo(v)  # GeoError is a ValueError -> 422


@router.post(
    "",
    response_model=CreateCampaignResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create campaign with 2 flows (GEO → Google, rest → offer)",
)
def create_campaign(
    body: CreateCampaignRequest,
    dry_run: bool = Query(False, description="Validate and show payloads without creating anything"),
    client: KeitaroClient = Depends(get_keitaro),
    defaults: CampaignDefaults = Depends(get_campaign_defaults),
    db: Session = Depends(get_db),
) -> CreateCampaignResult:
    return CampaignCreator(client, db, defaults).create(body.name, body.geo, body.offer_id, dry_run=dry_run)
