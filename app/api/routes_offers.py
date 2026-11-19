from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_keitaro
from app.keitaro.client import KeitaroClient

router = APIRouter(prefix="/api/offers", tags=["offers"])


class OfferItem(BaseModel):
    id: int
    name: str
    label: str  # "[18813] Flexacil ..." — ready for autocomplete


@router.get("", response_model=list[OfferItem], summary="Search offers (autocomplete)")
def search_offers(
    q: str = Query("", description="Offer ID or part of the name"),
    limit: int = Query(20, ge=1, le=100),
    client: KeitaroClient = Depends(get_keitaro),
) -> list[OfferItem]:
    return [OfferItem(id=o.id, name=o.name, label=f"[{o.id}] {o.name}") for o in client.search_offers(q, limit)]
