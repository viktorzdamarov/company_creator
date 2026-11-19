"""Editor tests against a stateful fake Keitaro: PUT /streams changes what the next GET returns."""
import json
import re

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import OperationLog
from tests.conftest import API

CAMPAIGN_ID = 500
GEO_STREAM, OFFER_STREAM = 11, 12
OFFERS = {
    3749: "Miaflow [BEAUTY-RO-BE_0009]",
    3717: "Miaflow [BEAUTY-RO-BE_0008]",
    18813: "Flexacil [JOINT-PE]",
}


class FakeKeitaro:
    def __init__(self, offer_ids=(3749,)):
        self.streams = {
            GEO_STREAM: {
                "id": GEO_STREAM, "campaign_id": CAMPAIGN_ID, "type": "regular", "name": "AU → Google",
                "position": 1, "state": "active", "schema": "redirect", "action_type": "http",
                "action_payload": "https://google.com",
                "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}], "offers": [],
            },
            OFFER_STREAM: {
                "id": OFFER_STREAM, "campaign_id": CAMPAIGN_ID, "type": "regular", "name": "Офферы",
                "position": 2, "state": "active", "schema": "landings", "action_type": "do_nothing",
                "filters": [], "offers": [{"offer_id": o, "share": 100 // len(offer_ids), "state": "active"}
                                          for o in offer_ids],
            },
        }
        self.puts: list[dict] = []
        self.ignore_removals = False  # simulate Keitaro keeping offers missing from PUT

    def get_streams(self, request):
        return httpx.Response(200, json=list(self.streams.values()))

    def put_stream(self, request, stream_id):
        body = json.loads(request.content)
        self.puts.append(body)
        stream = self.streams[int(stream_id)]
        if self.ignore_removals:
            kept = {o["offer_id"]: o for o in stream["offers"]}
            kept.update({o["offer_id"]: o for o in body["offers"]})
            stream["offers"] = list(kept.values())
        else:
            stream["offers"] = body["offers"]
        return httpx.Response(200, json=stream)

    def get_offer(self, request, offer_id):
        oid = int(offer_id)
        if oid not in OFFERS:
            return httpx.Response(404, text="<html>404</html>")
        return httpx.Response(200, json={"id": oid, "name": OFFERS[oid], "state": "active"})


@pytest.fixture
def fake():
    return FakeKeitaro()


@pytest.fixture
def keitaro(fake):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{API}/campaigns/{CAMPAIGN_ID}").respond(json={
            "id": CAMPAIGN_ID, "alias": "wVqN1R", "name": "campaign 2", "domain": "https://kylovoa.com/",
            "group": "FORTESTS", "state": "active",
        })
        mock.get(f"{API}/campaigns/999").respond(404, text="<html>404</html>")
        mock.get(f"{API}/campaigns/999/streams").respond(404, text="<html>404</html>")
        mock.get(f"{API}/campaigns").respond(json=[
            {"id": 1, "alias": "a", "name": "other campaign", "group": "X"},
            {"id": CAMPAIGN_ID, "alias": "wVqN1R", "name": "campaign 2", "group": "FORTESTS"},
        ])
        mock.get(f"{API}/campaigns/{CAMPAIGN_ID}/streams").mock(side_effect=fake.get_streams)
        mock.put(url__regex=rf"{re.escape(API)}/streams/(?P<stream_id>\d+)$").mock(side_effect=fake.put_stream)
        mock.get(url__regex=rf"{re.escape(API)}/offers/(?P<offer_id>\d+)$").mock(side_effect=fake.get_offer)
        mock.get(f"{API}/offers").respond(json=[{"id": k, "name": v, "state": "active"} for k, v in OFFERS.items()])
        mock.post(f"{API}/report/build").respond(json={"rows": [
            {"stream_id": GEO_STREAM, "clicks": 10, "campaign_unique_clicks": 8, "bots": 1},
            {"stream_id": OFFER_STREAM, "clicks": 5, "campaign_unique_clicks": 5, "bots": 0},
        ]})
        yield mock


def _shares(view: dict, stream_id: int = OFFER_STREAM) -> list[tuple[int, int]]:
    stream = next(s for s in view["streams"] if s["id"] == stream_id)
    return [(o["offer_id"], o["share"]) for o in stream["offers"]]


def _add(api, offer_id, stream_id=OFFER_STREAM):
    return api.post(f"/api/campaigns/{CAMPAIGN_ID}/streams/{stream_id}/offers", json={"offer_id": offer_id})


def _remove(api, offer_id, stream_id=OFFER_STREAM):
    return api.delete(f"/api/campaigns/{CAMPAIGN_ID}/streams/{stream_id}/offers/{offer_id}")


# ---------------------------------------------------------------- read

def test_get_campaign_view(api, keitaro):
    resp = api.get(f"/api/campaigns/{CAMPAIGN_ID}")
    assert resp.status_code == 200, resp.text
    v = resp.json()
    assert v["tracking_url"] == "https://kylovoa.com/wVqN1R"
    s1, s2 = v["streams"]
    assert (s1["position"], s1["editable"], s1["action"]) == (1, False, "Редирект → https://google.com")
    assert s1["filters"] == ['Страны принимать "AU"']
    assert (s1["clicks"], s1["unique_clicks"], s1["bots"]) == (10, 8, 1)
    assert s2["editable"] is True
    assert s2["offers"] == [{"offer_id": 3749, "name": OFFERS[3749], "share": 100}]
    assert (v["total_clicks"], v["total_unique_clicks"], v["total_bots"]) == (15, 13, 1)


def test_unknown_campaign_404(api, keitaro):
    assert api.get("/api/campaigns/999").status_code == 404


def test_list_campaigns_search(api, keitaro):
    assert [c["id"] for c in api.get("/api/campaigns").json()] == [CAMPAIGN_ID, 1]
    assert [c["id"] for c in api.get("/api/campaigns", params={"q": "campaign 2"}).json()] == [CAMPAIGN_ID]
    assert [c["id"] for c in api.get("/api/campaigns", params={"q": "1"}).json()] == [1]


# ---------------------------------------------------------------- add / remove

def test_add_remove_scenario_shares(api, keitaro, fake, db_session):
    resp = _add(api, 3717)
    assert resp.status_code == 200, resp.text
    assert _shares(resp.json()) == [(3749, 50), (3717, 50)]

    resp = _add(api, 18813)
    assert _shares(resp.json()) == [(3749, 34), (3717, 33), (18813, 33)]

    resp = _remove(api, 3749)
    assert resp.status_code == 200, resp.text
    assert _shares(resp.json()) == [(3717, 50), (18813, 50)]

    # what was actually sent to Keitaro
    assert fake.puts[-1] == {"offers": [
        {"offer_id": 3717, "share": 50, "state": "active"},
        {"offer_id": 18813, "share": 50, "state": "active"},
    ]}
    for body in fake.puts:
        assert sum(o["share"] for o in body["offers"]) == 100

    logs = [(o.action, o.status) for o in db_session.scalars(select(OperationLog))]
    assert logs == [("offer.add", "ok"), ("offer.add", "ok"), ("offer.remove", "ok")]
    last = db_session.scalars(select(OperationLog).order_by(OperationLog.id.desc())).first()
    assert last.details["before"] == [[3749, 34], [3717, 33], [18813, 33]]


def test_add_duplicate_409(api, keitaro, fake):
    resp = _add(api, 3749)
    assert resp.status_code == 409
    assert resp.json()["error"] == "DuplicateOfferError"
    assert fake.puts == []


def test_add_unknown_offer_404(api, keitaro, fake):
    resp = _add(api, 777)
    assert resp.status_code == 404
    assert fake.puts == []


def test_add_to_redirect_flow_422(api, keitaro, fake):
    resp = _add(api, 3717, stream_id=GEO_STREAM)
    assert resp.status_code == 422
    assert resp.json()["error"] == "StreamNotEditableError"
    assert fake.puts == []


def test_unknown_stream_404(api, keitaro):
    resp = _add(api, 3717, stream_id=12345)
    assert resp.status_code == 404
    assert resp.json()["error"] == "StreamNotFoundError"


def test_remove_missing_offer_404(api, keitaro, fake):
    resp = _remove(api, 3717)
    assert resp.status_code == 404
    assert resp.json()["error"] == "OfferNotInStreamError"
    assert fake.puts == []


def test_remove_last_offer_409(api, keitaro, fake):
    resp = _remove(api, 3749)
    assert resp.status_code == 409
    assert resp.json()["error"] == "LastOfferError"
    assert fake.puts == []


def test_keitaro_error_on_save_is_logged(api, keitaro, db_session):
    keitaro.routes[5].side_effect = None
    keitaro.routes[5].respond(422, json={"error": "Invalid share"})
    resp = _add(api, 3717)
    assert resp.status_code == 422
    log = db_session.scalars(select(OperationLog)).one()
    assert (log.action, log.status) == ("offer.add", "error")
    assert "Invalid share" in log.error


def test_save_verification_detects_mismatch(api, keitaro, fake, db_session):
    """If Keitaro does not apply the change as sent, the editor reports it instead of showing wrong numbers."""
    fake.streams[OFFER_STREAM]["offers"] = [
        {"offer_id": 3749, "share": 50, "state": "active"},
        {"offer_id": 3717, "share": 50, "state": "active"},
    ]
    fake.ignore_removals = True
    resp = _remove(api, 3749)
    assert resp.status_code == 502
    assert resp.json()["error"] == "SaveVerificationError"
    log = db_session.scalars(select(OperationLog)).one()
    assert log.status == "error"
