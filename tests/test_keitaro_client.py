import httpx
import pytest
import respx

from app.keitaro import (
    KeitaroAuthError,
    KeitaroClient,
    KeitaroNotFoundError,
    KeitaroRateLimitError,
    KeitaroTimeoutError,
    KeitaroUnavailableError,
    KeitaroValidationError,
)
from app.services.defaults import find_entity, resolve_defaults

BASE = "https://keitaro.test"
API = BASE + "/admin_api/v1"

STREAMS = [
    {
        "id": 2, "type": "default", "name": "Офферы", "campaign_id": 10, "position": 2, "state": "active",
        "action_type": "do_nothing", "action_payload": "", "schema": "landings", "filters": [],
        "offers": [{"id": 7, "stream_id": 2, "offer_id": 3749, "state": "active", "share": 50},
                   {"id": 8, "stream_id": 2, "offer_id": 3717, "state": "active", "share": 50}],
    },
    {
        "id": 1, "type": "regular", "name": "AU → Google", "campaign_id": 10, "position": 1, "state": "active",
        "action_type": "http", "action_payload": "https://google.com", "schema": "redirect",
        "filters": [{"id": 5, "stream_id": 1, "name": "country", "mode": "accept", "payload": ["AU"]}],
        "offers": [],
    },
]


@pytest.fixture
def client():
    c = KeitaroClient(BASE + "/", "secret-key", max_retries=2, retry_backoff=0)
    yield c
    c.close()


@respx.mock
def test_sends_api_key_and_parses_campaign(client):
    route = respx.get(f"{API}/campaigns/10").respond(json={
        "id": 10, "alias": "wVqN1R", "name": "campaign 2", "domain": "https://in.posdk.xyz/",
        "group_id": 1, "traffic_source_id": 2, "domain_id": 3, "unknown_field": "ignored",
    })
    c = client.get_campaign(10)
    assert route.calls.last.request.headers["Api-Key"] == "secret-key"
    assert c.name == "campaign 2"
    assert c.tracking_url == "https://in.posdk.xyz/wVqN1R"


@respx.mock
def test_streams_parsed_and_sorted_by_position(client):
    respx.get(f"{API}/campaigns/10/streams").respond(json=STREAMS)
    streams = client.get_streams(10)
    assert [s.id for s in streams] == [1, 2]
    assert streams[0].schema_ == "redirect"
    assert streams[0].filters[0].payload == ["AU"]
    assert [(o.offer_id, o.share) for o in streams[1].offers] == [(3749, 50), (3717, 50)]


@respx.mock
def test_401_raises_auth_error(client):
    respx.get(f"{API}/campaigns").respond(401, json={"error": "Invalid API key"})
    with pytest.raises(KeitaroAuthError, match="Invalid API key"):
        client.list_campaigns()


@respx.mock
def test_404_html_raises_not_found(client):
    respx.get(f"{API}/campaigns/999").respond(404, text="<html>404 Not Found</html>")
    with pytest.raises(KeitaroNotFoundError):
        client.get_campaign(999)


@respx.mock
def test_400_raises_validation_error(client):
    respx.post(f"{API}/report/build").respond(400, json={"error": "Unknown measure"})
    with pytest.raises(KeitaroValidationError, match="Unknown measure"):
        client.stream_stats(10)


@respx.mock
def test_retries_on_503_then_succeeds(client):
    route = respx.get(f"{API}/offers").mock(side_effect=[
        httpx.Response(503), httpx.Response(200, json=[{"id": 1, "name": "A"}]),
    ])
    assert [o.id for o in client.list_offers()] == [1]
    assert route.call_count == 2


@respx.mock
def test_gives_up_after_max_retries_on_5xx(client):
    route = respx.get(f"{API}/offers").respond(502)
    with pytest.raises(KeitaroUnavailableError):
        client.list_offers()
    assert route.call_count == 3  # 1 + max_retries(2)


@respx.mock
def test_rate_limit_after_retries(client):
    route = respx.get(f"{API}/offers").respond(429)
    with pytest.raises(KeitaroRateLimitError):
        client.list_offers()
    assert route.call_count == 3


@respx.mock
def test_timeout_raises_timeout_error(client):
    route = respx.get(f"{API}/domains").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(KeitaroTimeoutError):
        client.list_domains()
    assert route.call_count == 3


@respx.mock
def test_search_offers_by_id_and_name(client):
    respx.get(f"{API}/offers").respond(json=[
        {"id": 3749, "name": "Miaflow [BEAUTY-RO-BE_0009]", "state": "active"},
        {"id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008]", "state": "active"},
        {"id": 18813, "name": "Flexacil [JOINT-PE]", "state": "active"},
        {"id": 1, "name": "Old miaflow", "state": "deleted"},
    ])
    assert [o.id for o in client.search_offers("miaflow")] == [3749, 3717]
    assert [o.id for o in client.search_offers("18813")] == [18813]
    assert len(client.search_offers("", limit=2)) == 2


@respx.mock
def test_stream_stats_maps_columns(client):
    route = respx.post(f"{API}/report/build").respond(json={"rows": [
        {"stream_id": 1, "clicks": 10, "campaign_unique_clicks": 7, "bots": 2},
        {"stream_id": 2, "clicks": "5", "campaign_unique_clicks": None, "bots": 0},
    ], "total": 2})
    stats = client.stream_stats(10)
    assert (stats[1].clicks, stats[1].unique_clicks, stats[1].bots) == (10, 7, 2)
    assert (stats[2].clicks, stats[2].unique_clicks) == (5, 0)
    sent = route.calls.last.request.content.decode()
    assert '"campaign_id"' in sent and '"stream_id"' in sent


@respx.mock
def test_resolve_defaults_by_name_and_id(client):
    respx.get(f"{API}/domains").respond(json=[{"id": 1813, "name": "kylovoa.com", "is_ssl": True}])
    respx.get(f"{API}/groups").respond(json=[{"id": 10332, "name": "FORTESTS", "type": "campaigns"}])
    respx.get(f"{API}/traffic_sources").respond(json=[{"id": 836, "name": "FORTESTS"}])
    d = resolve_defaults(client, "https://kylovoa.com/", "fortests", "836")
    assert (d.domain.id, d.group.id, d.traffic_source.id) == (1813, 10332, 836)
    assert d.domain.url == "https://kylovoa.com/"


def test_find_entity_unknown_lists_available():
    from app.keitaro.schemas import Domain

    with pytest.raises(KeitaroNotFoundError, match="Available: kylovoa.com"):
        find_entity([Domain(id=1, name="kylovoa.com")], "in.posdk.xyz", "domain")
