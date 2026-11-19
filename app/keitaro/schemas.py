"""Pydantic models for Keitaro Admin API v1 responses (only the fields Adrobot uses).

Unknown fields are ignored so the models survive minor API changes.
"""
from pydantic import BaseModel, ConfigDict, Field


class _KModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Domain(_KModel):
    id: int
    name: str
    is_ssl: bool = False
    state: str | None = None

    @property
    def url(self) -> str:
        return f"{'https' if self.is_ssl else 'http'}://{self.name}/"


class Group(_KModel):
    id: int
    name: str
    type: str | None = None


class TrafficSource(_KModel):
    id: int
    name: str
    state: str | None = None


class Offer(_KModel):
    id: int
    name: str
    state: str | None = None
    country: list[str] = []
    group: str | None = None


class StreamFilter(_KModel):
    id: int | None = None
    name: str  # e.g. "country"
    mode: str  # "accept" | "reject"
    payload: list | str | None = None


class StreamOffer(_KModel):
    id: int | None = None
    offer_id: int
    share: int
    state: str = "active"


class Stream(_KModel):
    """Keitaro "stream" == "flow" in the UI."""

    id: int
    campaign_id: int
    name: str | None = None
    type: str  # regular | forced | default
    position: int
    state: str
    schema_: str | None = Field(None, alias="schema")  # redirect | landings | action
    action_type: str | None = None
    action_payload: str | None = None
    filters: list[StreamFilter] = []
    offers: list[StreamOffer] = []

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Campaign(_KModel):
    id: int
    alias: str
    name: str
    type: str | None = None  # position | weight
    state: str | None = None
    domain_id: int | None = None
    domain: str | None = None  # e.g. "https://kylovoa.com/"
    group_id: int | None = None
    group: str | None = None
    traffic_source_id: int | None = None
    cost_type: str | None = None

    @property
    def tracking_url(self) -> str | None:
        if not self.domain:
            return None
        return self.domain.rstrip("/") + "/" + self.alias


class StreamStats(_KModel):
    stream_id: int
    clicks: int = 0
    unique_clicks: int = 0
    bots: int = 0
