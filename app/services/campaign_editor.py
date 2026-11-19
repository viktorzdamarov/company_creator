"""Campaign editor: view a campaign's flows and add/remove offers with even share redistribution.

Rules:
- offers can be edited only in offer flows (schema "landings"); a redirect flow (→ google.com) has no offers
- shares are always even: weights.assign_shares (100/N, remainder to the first offers)
- the same offer cannot be added twice to a flow (409)
- the last offer of a flow cannot be removed (409): a flow without offers would send traffic nowhere
- after saving, the flow is re-read from Keitaro and verified (offers set and shares)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroError, KeitaroNotFoundError
from app.keitaro.schemas import Campaign, Stream, StreamStats
from app.services.audit import log_operation
from app.services.weights import assign_shares

OFFER_SCHEMAS = {"landings"}


class EditorError(Exception):
    http_status = 409

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class StreamNotEditableError(EditorError):
    http_status = 422


class DuplicateOfferError(EditorError):
    http_status = 409


class LastOfferError(EditorError):
    http_status = 409


class OfferNotInStreamError(EditorError):
    http_status = 404


class StreamNotFoundError(EditorError):
    http_status = 404


class SaveVerificationError(EditorError):
    http_status = 502


# ---------------------------------------------------------------- views

class OfferView(BaseModel):
    offer_id: int
    name: str
    share: int


class StreamView(BaseModel):
    id: int
    position: int
    name: str
    type: str
    state: str
    schema_: str | None
    action: str  # human readable: "Редирект → https://google.com" / "Офферы"
    filters: list[str]  # e.g. ['Страны принимать "AU"']
    editable: bool  # offers can be added/removed
    offers: list[OfferView]
    clicks: int = 0
    unique_clicks: int = 0
    bots: int = 0


class CampaignView(BaseModel):
    id: int
    name: str
    alias: str
    tracking_url: str | None
    domain: str | None
    group: str | None
    state: str | None
    streams: list[StreamView]
    total_clicks: int
    total_unique_clicks: int
    total_bots: int


class CampaignListItem(BaseModel):
    id: int
    name: str
    group: str | None
    state: str | None


def _describe_filter(f) -> str:
    mode = {"accept": "принимать", "reject": "отклонять"}.get(f.mode, f.mode)
    title = {"country": "Страны"}.get(f.name, f.name)
    payload = ", ".join(map(str, f.payload)) if isinstance(f.payload, list) else (f.payload or "")
    return f'{title} {mode} "{payload}"'


def _describe_action(s: Stream) -> str:
    if s.schema_ == "redirect":
        return f"Редирект → {s.action_payload}"
    if s.schema_ in OFFER_SCHEMAS:
        return "Офферы"
    return f"{s.schema_}: {s.action_type or ''}"


def build_stream_view(s: Stream, offer_names: dict[int, str], stats: StreamStats | None) -> StreamView:
    return StreamView(
        id=s.id,
        position=s.position,
        name=s.name or f"Flow {s.position}",
        type=s.type,
        state=s.state,
        schema_=s.schema_,
        action=_describe_action(s),
        filters=[_describe_filter(f) for f in s.filters],
        editable=s.schema_ in OFFER_SCHEMAS,
        offers=[
            OfferView(offer_id=o.offer_id, name=offer_names.get(o.offer_id, f"Offer #{o.offer_id}"), share=o.share)
            for o in s.offers
        ],
        clicks=stats.clicks if stats else 0,
        unique_clicks=stats.unique_clicks if stats else 0,
        bots=stats.bots if stats else 0,
    )


# ---------------------------------------------------------------- service

class CampaignEditor:
    def __init__(self, client: KeitaroClient, db: Session):
        self.client = client
        self.db = db

    # -------- read

    def list_campaigns(self, query: str = "") -> list[CampaignListItem]:
        q = query.strip().lower()
        items = [
            CampaignListItem(id=c.id, name=c.name, group=c.group, state=c.state)
            for c in self.client.list_campaigns()
            if not q or q == str(c.id) or q in c.name.lower()
        ]
        return sorted(items, key=lambda c: c.id, reverse=True)

    def get(self, campaign_id: int) -> CampaignView:
        with ThreadPoolExecutor(max_workers=4) as pool:
            campaign_f = pool.submit(self.client.get_campaign, campaign_id)
            streams_f = pool.submit(self.client.get_streams, campaign_id)
            offers_f = pool.submit(self.client.list_offers)
            stats_f = pool.submit(self.client.stream_stats, campaign_id)
            campaign: Campaign = campaign_f.result()
            streams = streams_f.result()
            offer_names = {o.id: o.name for o in offers_f.result()}
            stats = stats_f.result()

        views = [build_stream_view(s, offer_names, stats.get(s.id)) for s in streams]
        return CampaignView(
            id=campaign.id,
            name=campaign.name,
            alias=campaign.alias,
            tracking_url=campaign.tracking_url,
            domain=campaign.domain,
            group=campaign.group,
            state=campaign.state,
            streams=views,
            total_clicks=sum(v.clicks for v in views),
            total_unique_clicks=sum(v.unique_clicks for v in views),
            total_bots=sum(v.bots for v in views),
        )

    # -------- write

    def add_offer(self, campaign_id: int, stream_id: int, offer_id: int) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        current = [o.offer_id for o in stream.offers]
        if offer_id in current:
            raise DuplicateOfferError(f"Offer {offer_id} is already in flow {stream_id}")
        self.client.get_offer(offer_id)  # 404 if the offer does not exist
        self._save(campaign_id, stream, current + [offer_id], action="offer.add", offer_id=offer_id)
        return self.get(campaign_id)

    def remove_offer(self, campaign_id: int, stream_id: int, offer_id: int) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        current = [o.offer_id for o in stream.offers]
        if offer_id not in current:
            raise OfferNotInStreamError(f"Offer {offer_id} is not in flow {stream_id}")
        if len(current) == 1:
            raise LastOfferError("Cannot remove the last offer of a flow: traffic would have nowhere to go")
        self._save(campaign_id, stream, [o for o in current if o != offer_id], action="offer.remove", offer_id=offer_id)
        return self.get(campaign_id)

    def _editable_stream(self, campaign_id: int, stream_id: int) -> Stream:
        streams = self.client.get_streams(campaign_id)  # 404 if campaign does not exist
        stream = next((s for s in streams if s.id == stream_id), None)
        if stream is None:
            raise StreamNotFoundError(f"Flow {stream_id} not found in campaign {campaign_id}")
        if stream.schema_ not in OFFER_SCHEMAS:
            raise StreamNotEditableError(
                f"Flow {stream_id} is a '{stream.schema_}' flow ({_describe_action(stream)}); offers can't be edited there"
            )
        return stream

    def _save(self, campaign_id: int, stream: Stream, offer_ids: list[int], *, action: str, offer_id: int) -> None:
        shares = assign_shares(offer_ids)
        payload = {"offers": [{"offer_id": oid, "share": share, "state": "active"} for oid, share in shares]}
        before = [(o.offer_id, o.share) for o in stream.offers]
        details = {"stream_id": stream.id, "offer_id": offer_id, "before": before, "after": shares}
        try:
            self.client.update_stream(stream.id, payload)
            saved = next((s for s in self.client.get_streams(campaign_id) if s.id == stream.id), None)
            if saved is None:
                raise KeitaroNotFoundError(f"Flow {stream.id} disappeared after save")
            actual = sorted((o.offer_id, o.share) for o in saved.offers if o.state == "active")
            if actual != sorted(shares):
                raise SaveVerificationError(f"Keitaro saved {actual}, expected {sorted(shares)}")
        except (KeitaroError, SaveVerificationError) as exc:
            log_operation(self.db, action, status="error", campaign_id=campaign_id, details=details, error=str(exc))
            raise
        log_operation(self.db, action, campaign_id=campaign_id, details=details)
