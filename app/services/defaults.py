"""Resolve default domain / group / traffic source (configured by name or ID) to Keitaro entities."""
from dataclasses import dataclass
from typing import TypeVar

from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroNotFoundError
from app.keitaro.schemas import Domain, Group, TrafficSource

T = TypeVar("T", Domain, Group, TrafficSource)


@dataclass(frozen=True)
class CampaignDefaults:
    domain: Domain
    group: Group
    traffic_source: TrafficSource


def _normalize_domain(value: str) -> str:
    v = value.strip().lower()
    for prefix in ("https://", "http://"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    return v.rstrip("/")


def find_entity(items: list[T], value: str, kind: str) -> T:
    """Find by numeric ID or by name (case-insensitive; for domains scheme and slash are ignored)."""
    raw = value.strip()
    if raw.isdigit():
        for item in items:
            if item.id == int(raw):
                return item
    key = _normalize_domain(raw) if kind == "domain" else raw.lower()
    for item in items:
        name = _normalize_domain(item.name) if kind == "domain" else item.name.lower()
        if name == key:
            return item
    available = ", ".join(i.name for i in items[:20]) or "none"
    raise KeitaroNotFoundError(f"{kind} '{value}' not found in Keitaro. Available: {available}")


def resolve_defaults(client: KeitaroClient, domain: str, group: str, source: str) -> CampaignDefaults:
    return CampaignDefaults(
        domain=find_entity(client.list_domains(), domain, "domain"),
        group=find_entity(client.list_campaign_groups(), group, "group"),
        traffic_source=find_entity(client.list_traffic_sources(), source, "traffic source"),
    )
