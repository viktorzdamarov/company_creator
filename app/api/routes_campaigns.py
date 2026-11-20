from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_campaign_defaults, get_keitaro
from app.db.session import get_db
from app.keitaro.client import KeitaroClient
from app.services.campaign_creator import CampaignCreator, CreateCampaignResult
from app.services.campaign_editor import CampaignEditor, CampaignListItem, CampaignView
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


class AddOfferRequest(BaseModel):
    offer_id: int = Field(..., gt=0, examples=[18813])


class PinRequest(BaseModel):
    pinned: bool


@router.get("", response_model=list[CampaignListItem], summary="List campaigns (search by ID or name)")
def list_campaigns(
    q: str = Query("", description="Campaign ID or part of the name"),
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> list[CampaignListItem]:
    return CampaignEditor(client, db).list_campaigns(q)


@router.get("/{campaign_id}", response_model=CampaignView, summary="Local copy of the campaign (404 if not fetched yet)")
def get_campaign(
    campaign_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).get(campaign_id)


@router.post("/{campaign_id}/fetch", response_model=CampaignView, summary="Fetch streams: load/refresh flows from Keitaro")
def fetch_campaign(
    campaign_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).fetch(campaign_id)


@router.post(
    "/{campaign_id}/streams/{stream_id}/offers",
    response_model=CampaignView,
    summary="Add offer to the local draft of a flow (not published until Push)",
)
def add_offer(
    campaign_id: int,
    stream_id: int,
    body: AddOfferRequest,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).add_offer(campaign_id, stream_id, body.offer_id)


@router.delete(
    "/{campaign_id}/streams/{stream_id}/offers/{offer_id}",
    response_model=CampaignView,
    summary="Remove offer from the local draft (grey, 0%) until Push",
)
def remove_offer(
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).remove_offer(campaign_id, stream_id, offer_id)


@router.post(
    "/{campaign_id}/streams/{stream_id}/offers/{offer_id}/bring-back",
    response_model=CampaignView,
    summary="Bring back a removed offer",
)
def bring_back(
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).bring_back(campaign_id, stream_id, offer_id)


@router.put(
    "/{campaign_id}/streams/{stream_id}/offers/{offer_id}/pin",
    response_model=CampaignView,
    summary="Pin / unpin the share of an offer",
)
def pin_offer(
    campaign_id: int,
    stream_id: int,
    offer_id: int,
    body: PinRequest,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).set_pin(campaign_id, stream_id, offer_id, body.pinned)


@router.post("/{campaign_id}/streams/{stream_id}/push", response_model=CampaignView, summary="Push: publish the flow to Keitaro")
def push_stream(
    campaign_id: int,
    stream_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).push(campaign_id, stream_id)


@router.post("/{campaign_id}/streams/{stream_id}/cancel", response_model=CampaignView, summary="Cancel unpublished changes of the flow")
def cancel_stream(
    campaign_id: int,
    stream_id: int,
    client: KeitaroClient = Depends(get_keitaro),
    db: Session = Depends(get_db),
) -> CampaignView:
    return CampaignEditor(client, db).cancel(campaign_id, stream_id)


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
