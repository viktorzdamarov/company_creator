import json

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import CampaignRecord, OperationLog
from app.services.geo import GeoError, parse_geo
from tests.conftest import API


@pytest.fixture
def keitaro():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{API}/domains").respond(json=[{"id": 1813, "name": "kylovoa.com", "is_ssl": True}])
        mock.get(f"{API}/groups").respond(json=[{"id": 10332, "name": "FORTESTS", "type": "campaigns"}])
        mock.get(f"{API}/traffic_sources").respond(json=[{"id": 836, "name": "FORTESTS"}])
        mock.get(f"{API}/offers/18813").respond(json={"id": 18813, "name": "Flexacil [JOINT-PE]", "state": "active"})
        mock.get(f"{API}/offers/404").respond(404, text="<html>404</html>")
        mock.get(f"{API}/campaigns").respond(json=[{"id": 1, "alias": "old", "name": "existing"}])
        mock.post(f"{API}/campaigns").respond(json={
            "id": 500, "alias": "abc12345", "name": "adrobot-test-au",
            "domain": "https://kylovoa.com/", "domain_id": 1813, "group_id": 10332, "traffic_source_id": 836,
        })
        mock.post(f"{API}/streams").mock(side_effect=[
            httpx.Response(200, json={"id": 11, "campaign_id": 500, "type": "regular", "position": 1, "state": "active"}),
            httpx.Response(200, json={"id": 12, "campaign_id": 500, "type": "regular", "position": 2, "state": "active"}),
        ])
        mock.delete(f"{API}/campaigns/500").respond(json={})
        yield mock


def _sent_json(route, i=0):
    return json.loads(route.calls[i].request.content)


# ---------------------------------------------------------------- geo

@pytest.mark.parametrize(("raw", "expected"), [
    ("AU", ["AU"]),
    (" mx, au,RO ", ["MX", "AU", "RO"]),
    ("AU,AU,au", ["AU"]),
    ("MX AU", ["MX", "AU"]),
    (["ro", "AU"], ["RO", "AU"]),
])
def test_parse_geo_ok(raw, expected):
    assert parse_geo(raw) == expected


@pytest.mark.parametrize("raw", ["", " , ", "XX1", "AU,ZZ", "Australia"])
def test_parse_geo_invalid(raw):
    with pytest.raises(GeoError):
        parse_geo(raw)


# ---------------------------------------------------------------- create

def test_create_campaign_payloads(api, keitaro, db_session):
    resp = api.post("/api/campaigns", json={"name": " adrobot-test-au ", "geo": "au,MX", "offer_id": 18813})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["campaign_id"] == 500
    assert data["tracking_url"] == "https://kylovoa.com/abc12345"
    assert data["geo"] == ["AU", "MX"]
    assert [s["id"] for s in data["streams"]] == [11, 12]

    campaign = _sent_json(keitaro.routes[6])  # POST /campaigns
    assert campaign["name"] == "adrobot-test-au"
    assert (campaign["domain_id"], campaign["group_id"], campaign["traffic_source_id"]) == (1813, 10332, 836)
    assert campaign["type"] == "position"

    streams = keitaro.routes[7]
    flow1, flow2 = _sent_json(streams, 0), _sent_json(streams, 1)
    assert flow1["campaign_id"] == 500 and flow1["position"] == 1
    assert flow1["schema"] == "redirect" and flow1["action_type"] == "http"
    assert flow1["action_payload"] == "https://google.com"
    assert flow1["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert flow2["position"] == 2 and flow2["filters"] == []
    assert flow2["offers"] == [{"offer_id": 18813, "share": 100, "state": "active"}]

    record = db_session.scalars(select(CampaignRecord)).one()
    assert (record.keitaro_id, record.geo, record.offer_ids) == (500, "AU,MX", [18813])
    actions = [o.action for o in db_session.scalars(select(OperationLog))]
    assert actions == ["campaign.create", "streams.create"]


def test_dry_run_creates_nothing(api, keitaro, db_session):
    resp = api.post("/api/campaigns?dry_run=true", json={"name": "x", "geo": "AU", "offer_id": 18813})
    assert resp.status_code == 201
    data = resp.json()
    assert data["dry_run"] is True and data["campaign_id"] is None
    assert data["payloads"]["flow_1"]["filters"][0]["payload"] == ["AU"]
    assert not keitaro.routes[6].called and not keitaro.routes[7].called
    assert db_session.scalars(select(OperationLog)).first() is None


@pytest.mark.parametrize("geo", ["", "XX1", "AU,ZZ"])
def test_invalid_geo_422(api, keitaro, geo):
    resp = api.post("/api/campaigns", json={"name": "x", "geo": geo, "offer_id": 18813})
    assert resp.status_code == 422
    assert not keitaro.routes[6].called


def test_empty_name_422(api, keitaro):
    resp = api.post("/api/campaigns", json={"name": "   ", "geo": "AU", "offer_id": 18813})
    assert resp.status_code == 422


def test_unknown_offer_404_nothing_created(api, keitaro):
    resp = api.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 404})
    assert resp.status_code == 404
    assert resp.json()["error"] == "KeitaroNotFoundError"
    assert not keitaro.routes[6].called


def test_duplicate_name_409(api, keitaro):
    resp = api.post("/api/campaigns", json={"name": "existing", "geo": "AU", "offer_id": 18813})
    assert resp.status_code == 409
    assert resp.json()["campaign_id"] == 1
    assert not keitaro.routes[6].called


def test_stream_failure_rolls_back(api, keitaro, db_session):
    keitaro.routes[7].side_effect = [
        httpx.Response(200, json={"id": 11, "campaign_id": 500, "type": "regular", "position": 1, "state": "active"}),
        httpx.Response(422, json={"error": "Invalid offer"}),
    ]
    resp = api.post("/api/campaigns", json={"name": "adrobot-test-au", "geo": "AU", "offer_id": 18813})
    assert resp.status_code == 422
    assert "Invalid offer" in resp.json()["detail"]
    assert keitaro.routes[8].called  # DELETE /campaigns/500
    logs = [(o.action, o.status) for o in db_session.scalars(select(OperationLog))]
    assert logs == [("campaign.create", "ok"), ("streams.create", "error"), ("campaign.rollback", "ok")]
    assert db_session.scalars(select(CampaignRecord)).first() is None


def test_keitaro_auth_error_is_json(api, keitaro):
    keitaro.routes[0].respond(401, json={"error": "Invalid API key"})
    resp = api.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 18813})
    assert resp.status_code == 502
    assert "Invalid API key" in resp.json()["detail"]


def test_offers_autocomplete(api):
    with respx.mock:
        respx.get(f"{API}/offers").respond(json=[
            {"id": 18813, "name": "Flexacil [JOINT-PE]", "state": "active"},
            {"id": 3749, "name": "Miaflow", "state": "active"},
        ])
        resp = api.get("/api/offers", params={"q": "flex"})
    assert resp.status_code == 200
    assert resp.json() == [{"id": 18813, "name": "Flexacil [JOINT-PE]", "label": "[18813] Flexacil [JOINT-PE]"}]
