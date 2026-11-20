from collections.abc import Iterator

from fastapi import Depends

from app.core.config import get_settings
from app.keitaro.client import KeitaroClient
from app.keitaro.demo import get_demo_client
from app.services.defaults import CampaignDefaults, resolve_defaults_cached


def get_keitaro() -> Iterator[KeitaroClient]:
    s = get_settings()
    if s.demo_mode:  # shared in-memory fake Keitaro with invented offers
        yield get_demo_client(s.demo_state_file, s.keitaro_default_domain, s.keitaro_default_group, s.keitaro_default_source)
        return
    client = KeitaroClient.from_settings()
    try:
        yield client
    finally:
        client.close()


def get_campaign_defaults(client: KeitaroClient = Depends(get_keitaro)) -> CampaignDefaults:
    s = get_settings()
    return resolve_defaults_cached(client,s.keitaro_default_domain, s.keitaro_default_group, s.keitaro_default_source)
