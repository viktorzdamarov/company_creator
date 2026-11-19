"""Campaign creator: name + GEO + offer -> Keitaro campaign with two flows.

Flow 1: country filter "accept GEO" -> HTTP redirect to https://google.com
Flow 2: all other traffic -> the chosen offer (share 100%)
The campaign gets the configured domain, group and traffic source.
"""
from __future__ import annotations

import logging
import secrets
import string
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import CampaignRecord
from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroError
from app.keitaro.schemas import Offer
from app.services.audit import log_operation
from app.services.defaults import CampaignDefaults

log = logging.getLogger(__name__)

GOOGLE_URL = "https://google.com"
ALIAS_ALPHABET = string.ascii_letters + string.digits


class CampaignExistsError(Exception):
    def __init__(self, name: str, campaign_id: int):
        super().__init__(f"Campaign '{name}' already exists in Keitaro (id {campaign_id})")
        self.campaign_id = campaign_id


class CreatedStream(BaseModel):
    id: int | None
    position: int
    name: str
    description: str


class CreateCampaignResult(BaseModel):
    dry_run: bool = False
    campaign_id: int | None
    name: str
    alias: str
    tracking_url: str
    geo: list[str]
    offer_id: int
    offer_name: str
    domain: str
    group: str
    traffic_source: str
    streams: list[CreatedStream]
    elapsed_ms: int
    payloads: dict | None = None  # only in dry-run


# ---------------------------------------------------------------- payload builders (pure)

def generate_alias(length: int = 8) -> str:
    return "".join(secrets.choice(ALIAS_ALPHABET) for _ in range(length))


def build_campaign_payload(name: str, alias: str, defaults: CampaignDefaults) -> dict:
    return {
        "name": name,
        "alias": alias,
        "type": "position",  # «Ротация потоков: По позиции»
        "state": "active",
        "domain_id": defaults.domain.id,
        "group_id": defaults.group.id,
        "traffic_source_id": defaults.traffic_source.id,
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,  # «Из параметра 'cost'»
    }


def build_geo_stream_payload(campaign_id: int | None, geo: list[str]) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": f"{','.join(geo)} → Google",
        "position": 1,
        "state": "active",
        "schema": "redirect",
        "action_type": "http",
        "action_payload": GOOGLE_URL,
        "collect_clicks": True,
        "filter_or": False,
        "filters": [{"name": "country", "mode": "accept", "payload": geo}],
    }


def build_offer_stream_payload(campaign_id: int | None, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Офферы",
        "position": 2,
        "state": "active",
        "schema": "landings",  # direct to offers, no landing pages
        "action_type": "do_nothing",
        "collect_clicks": True,
        "filter_or": False,
        "filters": [],
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


# ---------------------------------------------------------------- service

class CampaignCreator:
    def __init__(self, client: KeitaroClient, db: Session, defaults: CampaignDefaults):
        self.client = client
        self.db = db
        self.defaults = defaults

    def create(self, name: str, geo: list[str], offer_id: int, *, dry_run: bool = False) -> CreateCampaignResult:
        started = time.perf_counter()
        name = name.strip()

        # Independent checks in parallel. Offer 404 -> KeitaroNotFoundError, nothing created.
        with ThreadPoolExecutor(max_workers=2) as pool:
            offer_f = pool.submit(self.client.get_offer, offer_id)
            campaigns_f = pool.submit(self.client.list_campaigns)
            offer = offer_f.result()
            campaigns = campaigns_f.result()
        existing = next((c for c in campaigns if c.name == name), None)
        if existing:
            raise CampaignExistsError(name, existing.id)

        alias = generate_alias()
        campaign_payload = build_campaign_payload(name, alias, self.defaults)
        tracking_url = self.defaults.domain.url + alias

        if dry_run:
            return self._result(
                None, name, alias, tracking_url, geo, offer, [None, None], started, dry_run=True,
                payloads={
                    "campaign": campaign_payload,
                    "flow_1": build_geo_stream_payload(None, geo),
                    "flow_2": build_offer_stream_payload(None, offer.id),
                },
            )

        campaign = self.client.create_campaign(campaign_payload)
        log_operation(self.db, "campaign.create", campaign_id=campaign.id, details=campaign_payload)
        try:
            s1 = self.client.create_stream(build_geo_stream_payload(campaign.id, geo))
            s2 = self.client.create_stream(build_offer_stream_payload(campaign.id, offer.id))
        except KeitaroError as exc:
            self._rollback(campaign.id, exc)
            raise
        log_operation(self.db, "streams.create", campaign_id=campaign.id,
                      details={"flow_1": s1.id, "flow_2": s2.id, "geo": geo, "offer_id": offer.id})

        tracking_url = campaign.tracking_url or tracking_url
        self.db.add(CampaignRecord(
            keitaro_id=campaign.id, name=name, geo=",".join(geo), offer_ids=[offer.id],
            tracking_url=tracking_url, status="created",
        ))
        self.db.commit()
        return self._result(campaign.id, name, campaign.alias, tracking_url, geo, offer, [s1.id, s2.id], started)

    def _rollback(self, campaign_id: int, exc: Exception) -> None:
        log.error("stream creation failed for campaign %s, rolling back: %s", campaign_id, exc)
        log_operation(self.db, "streams.create", status="error", campaign_id=campaign_id, error=str(exc))
        try:
            self.client.delete_campaign(campaign_id)
            log_operation(self.db, "campaign.rollback", campaign_id=campaign_id)
        except KeitaroError as del_exc:
            log_operation(self.db, "campaign.rollback", status="error", campaign_id=campaign_id, error=str(del_exc))

    def _result(self, campaign_id, name, alias, tracking_url, geo, offer: Offer, stream_ids, started,
                *, dry_run=False, payloads=None) -> CreateCampaignResult:
        return CreateCampaignResult(
            dry_run=dry_run,
            campaign_id=campaign_id,
            name=name,
            alias=alias,
            tracking_url=tracking_url,
            geo=geo,
            offer_id=offer.id,
            offer_name=offer.name,
            domain=self.defaults.domain.name,
            group=self.defaults.group.name,
            traffic_source=self.defaults.traffic_source.name,
            streams=[
                CreatedStream(id=stream_ids[0], position=1, name=f"{','.join(geo)} → Google",
                              description=f"Страны принимать {','.join(geo)} → {GOOGLE_URL}"),
                CreatedStream(id=stream_ids[1], position=2, name="Офферы",
                              description=f"Остальной трафик → [{offer.id}] {offer.name} (100%)"),
            ],
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            payloads=payloads,
        )
