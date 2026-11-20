"""DEMO mode: fake in-process Keitaro with invented offers; the full editor flow works without a real tracker."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import ConfigError, get_settings

DEMO_OFFER_IDS = [9001, 9002, 9003, 9004, 9005]


@pytest.fixture
def demo(monkeypatch, db_session, tmp_path):
    from app.db.session import get_db
    from app.keitaro.demo import get_demo_client
    from app.main import create_app

    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_STATE_FILE", str(tmp_path / "demo_state.json"))
    monkeypatch.setenv("KEITARO_URL", "")
    monkeypatch.setenv("KEITARO_API_KEY", "")
    monkeypatch.setenv("KEITARO_DEFAULT_DOMAIN", "demo.test")
    get_settings.cache_clear()
    get_demo_client.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    get_demo_client.cache_clear()


def _campaign(demo, name):
    return next(c for c in demo.get("/api/campaigns").json() if c["name"] == name)


def test_keitaro_settings_required_outside_demo(monkeypatch):
    monkeypatch.setenv("KEITARO_URL", "")
    monkeypatch.setenv("KEITARO_API_KEY", "")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match="KEITARO_URL, KEITARO_API_KEY"):
        get_settings()


def test_demo_has_five_invented_offers(demo):
    offers = demo.get("/api/offers", params={"limit": 100}).json()
    assert [o["id"] for o in offers] == DEMO_OFFER_IDS
    assert [o["id"] for o in demo.get("/api/offers", params={"q": "tea"}).json()] == [9004]
    assert [o["id"] for o in demo.get("/api/offers", params={"q": "9002"}).json()] == [9002]


def test_demo_campaigns_are_seeded(demo):
    names = {c["name"] for c in demo.get("/api/campaigns").json()}
    assert {"demo_campaign_001", "demo_campaign_multi"} <= names


def test_demo_banner_in_pages(demo):
    assert "DEMO" in demo.get("/edit").text


def test_editor_full_flow_in_demo(demo):
    cid = _campaign(demo, "demo_campaign_001")["id"]
    url = f"/api/campaigns/{cid}"
    view = demo.post(f"{url}/fetch").json()
    flow = next(s for s in view["streams"] if s["has_offers"])
    sid = flow["id"]
    assert [(o["offer_id"], o["share"]) for o in flow["offers"]] == [(9001, 100)]
    assert (view["total_clicks"], view["total_bots"]) != (0, 0)  # fake stats

    for oid in (9002, 9003, 9004):  # add three offers -> yellow draft, 25% each
        assert demo.post(f"{url}/streams/{sid}/offers", json={"offer_id": oid}).status_code == 200
    flow = next(s for s in demo.get(url).json()["streams"] if s["id"] == sid)
    assert flow["dirty"] is True and [o["share"] for o in flow["offers"]] == [25, 25, 25, 25]

    assert demo.post(f"{url}/streams/{sid}/push").status_code == 200
    # what the "API" returns now matches
    k = demo.post(f"{url}/fetch").json()
    flow = next(s for s in k["streams"] if s["id"] == sid)
    assert flow["dirty"] is False and sorted(o["offer_id"] for o in flow["offers"]) == [9001, 9002, 9003, 9004]

    demo.put(f"{url}/streams/{sid}/offers/9001/pin", json={"pinned": True})
    demo.delete(f"{url}/streams/{sid}/offers/9004")
    flow = next(s for s in demo.get(url).json()["streams"] if s["id"] == sid)
    assert {o["offer_id"]: o["share"] for o in flow["offers"]} == {9001: 25, 9002: 38, 9003: 37, 9004: 0}
    assert demo.post(f"{url}/streams/{sid}/push").status_code == 200
    flow = next(s for s in demo.post(f"{url}/fetch").json()["streams"] if s["id"] == sid)
    statuses = {o["offer_id"]: o["status"] for o in flow["offers"]}
    assert statuses == {9001: "active", 9002: "active", 9003: "active", 9004: "removed"}

    demo.post(f"{url}/streams/{sid}/offers/9004/bring-back")
    assert demo.post(f"{url}/streams/{sid}/cancel").status_code == 200
    flow = next(s for s in demo.get(url).json()["streams"] if s["id"] == sid)
    assert {o["offer_id"]: o["status"] for o in flow["offers"]}[9004] == "removed"


def test_create_campaign_in_demo_then_edit_it(demo):
    resp = demo.post("/api/campaigns", json={"name": "demo-created", "geo": "AU", "offer_id": 9005})
    assert resp.status_code == 201, resp.text
    cid = resp.json()["campaign_id"]
    assert demo.post("/api/campaigns", json={"name": "demo-created", "geo": "AU", "offer_id": 9005}).status_code == 409
    view = demo.post(f"/api/campaigns/{cid}/fetch").json()
    assert [s["has_offers"] for s in view["streams"]] == [False, True]
    sid = view["streams"][1]["id"]
    assert demo.post(f"/api/campaigns/{cid}/streams/{sid}/offers", json={"offer_id": 9001}).status_code == 200
    assert demo.post(f"/api/campaigns/{cid}/streams/{sid}/push").status_code == 200


def test_unknown_offer_404_in_demo(demo):
    cid = _campaign(demo, "demo_campaign_001")["id"]
    view = demo.post(f"/api/campaigns/{cid}/fetch").json()
    sid = next(s["id"] for s in view["streams"] if s["has_offers"])
    assert demo.post(f"/api/campaigns/{cid}/streams/{sid}/offers", json={"offer_id": 1}).status_code == 404


def test_demo_state_survives_restart(monkeypatch, demo, tmp_path):
    from app.keitaro.demo import get_demo_client

    demo.post("/api/campaigns", json={"name": "persisted", "geo": "RO", "offer_id": 9005})
    get_demo_client.cache_clear()  # "restart": a new client reads the state file
    assert any(c["name"] == "persisted" for c in demo.get("/api/campaigns").json())
