"""Resolve default domain / group / traffic source (configured by name or ID) to Keitaro entities."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
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
    # Three independent reads: run them in parallel (httpx.Client is thread-safe).
    with ThreadPoolExecutor(max_workers=3) as pool:
        domains = pool.submit(client.list_domains)
        groups = pool.submit(client.list_campaign_groups)
        sources = pool.submit(client.list_traffic_sources)
        return CampaignDefaults(
            domain=find_entity(domains.result(), domain, "domain"),
            group=find_entity(groups.result(), group, "group"),
            traffic_source=find_entity(sources.result(), source, "traffic source"),
        )


_cache: dict[tuple, tuple[float, CampaignDefaults]] = {}
_cache_lock = Lock()
CACHE_TTL_SECONDS = 300


def resolve_defaults_cached(client: KeitaroClient, domain: str, group: str, source: str) -> CampaignDefaults:
    """Domains/groups/sources rarely change: keep the resolved IDs for a few minutes."""
    key = (client.base_url, domain, group, source)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    value = resolve_defaults(client, domain, group, source)
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def clear_defaults_cache() -> None:
    with _cache_lock:
        _cache.clear()
