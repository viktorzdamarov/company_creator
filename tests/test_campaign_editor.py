"""Editor (draft -> Push) tests against a stateful fake Keitaro: PUT /streams changes what the next GET returns."""
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
    5555: "Fourth offer",
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


URL = f"/api/campaigns/{CAMPAIGN_ID}"


def _stream(view: dict, stream_id: int = OFFER_STREAM) -> dict:
    return next(s for s in view["streams"] if s["id"] == stream_id)


def _shares(view: dict, stream_id: int = OFFER_STREAM) -> dict[int, int]:
    return {o["offer_id"]: o["share"] for o in _stream(view, stream_id)["offers"]}


def _status(view: dict, offer_id: int) -> str:
    return next(o["status"] for o in _stream(view)["offers"] if o["offer_id"] == offer_id)


def _keitaro(fake, stream_id: int = OFFER_STREAM) -> dict[int, int]:
    return {o["offer_id"]: o["share"] for o in fake.streams[stream_id]["offers"]}


def _fetch(api):
    resp = api.post(f"{URL}/fetch")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _add(api, offer_id, stream_id=OFFER_STREAM):
    return api.post(f"{URL}/streams/{stream_id}/offers", json={"offer_id": offer_id})


def _remove(api, offer_id, stream_id=OFFER_STREAM):
    return api.delete(f"{URL}/streams/{stream_id}/offers/{offer_id}")


def _bring_back(api, offer_id, stream_id=OFFER_STREAM):
    return api.post(f"{URL}/streams/{stream_id}/offers/{offer_id}/bring-back")


def _pin(api, offer_id, pinned=True, stream_id=OFFER_STREAM):
    return api.put(f"{URL}/streams/{stream_id}/offers/{offer_id}/pin", json={"pinned": pinned})


def _push(api, stream_id=OFFER_STREAM):
    return api.post(f"{URL}/streams/{stream_id}/push")


def _cancel(api, stream_id=OFFER_STREAM):
    return api.post(f"{URL}/streams/{stream_id}/cancel")


def _publish(api, *offer_ids):
    """Add offers and push, so they exist in Keitaro."""
    for oid in offer_ids:
        assert _add(api, oid).status_code == 200
    resp = _push(api)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- fetch / read

def test_get_before_fetch_is_404(api, keitaro):
    resp = api.get(URL)
    assert resp.status_code == 404
    assert resp.json()["error"] == "CampaignNotFetchedError"


def test_fetch_loads_flows(api, keitaro):
    v = _fetch(api)
    assert v["tracking_url"] == "https://kylovoa.com/wVqN1R"
    s1, s2 = v["streams"]
    # a flow without offers is just a flow: no filters / redirect details
    assert (s1["position"], s1["has_offers"], s1["offers"], s1["dirty"]) == (1, False, [], False)
    assert (s1["clicks"], s1["unique_clicks"], s1["bots"]) == (10, 8, 1)
    assert s2["has_offers"] is True and s2["dirty"] is False
    assert s2["offers"] == [{"offer_id": 3749, "name": OFFERS[3749], "share": 100, "status": "active", "pinned": False}]
    assert (v["total_clicks"], v["total_unique_clicks"], v["total_bots"]) == (15, 13, 1)
    assert api.get(URL).json() == v  # now served from the local DB


def test_fetch_unknown_campaign_404(api, keitaro):
    assert api.post("/api/campaigns/999/fetch").status_code == 404


def test_list_campaigns_search(api, keitaro):
    assert [c["id"] for c in api.get("/api/campaigns").json()] == [CAMPAIGN_ID, 1]
    assert [c["id"] for c in api.get("/api/campaigns", params={"q": "campaign 2"}).json()] == [CAMPAIGN_ID]
    assert [c["id"] for c in api.get("/api/campaigns", params={"q": "1"}).json()] == [1]


# ---------------------------------------------------------------- add -> draft -> push / cancel

def test_add_is_local_until_push(api, keitaro, fake):
    _fetch(api)
    resp = _add(api, 3717)
    assert resp.status_code == 200, resp.text
    v = resp.json()
    assert _shares(v) == {3749: 50, 3717: 50}
    assert _stream(v)["dirty"] is True and _status(v, 3717) == "new"
    assert fake.puts == []  # nothing sent to Keitaro
    assert _keitaro(fake) == {3749: 100}


def test_push_publishes_and_clears_dirty(api, keitaro, fake):
    _fetch(api)
    _add(api, 3717)
    _add(api, 18813)
    v = _push(api).json()
    assert _shares(v) == {3749: 34, 3717: 33, 18813: 33}
    assert _stream(v)["dirty"] is False and _status(v, 3717) == "active"
    assert _keitaro(fake) == {3749: 34, 3717: 33, 18813: 33}
    assert len(fake.puts) == 1


def test_four_offers_get_25_each(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717, 18813, 5555)
    assert _keitaro(fake) == {3749: 25, 3717: 25, 18813: 25, 5555: 25}


def test_cancel_drops_new_offers(api, keitaro, fake):
    _fetch(api)
    _add(api, 3717)
    v = _cancel(api).json()
    assert _shares(v) == {3749: 100}
    assert _stream(v)["dirty"] is False
    assert fake.puts == []


def test_add_duplicate_409(api, keitaro):
    _fetch(api)
    assert _add(api, 3749).status_code == 409
    _add(api, 3717)
    assert _add(api, 3717).status_code == 409


def test_add_unknown_offer_404_and_nothing_changed(api, keitaro):
    _fetch(api)
    assert _add(api, 424242).status_code == 404
    assert _shares(api.get(URL).json()) == {3749: 100}


def test_add_to_redirect_flow_422(api, keitaro):
    _fetch(api)
    assert _add(api, 3717, GEO_STREAM).status_code == 422


def test_unknown_flow_404(api, keitaro):
    _fetch(api)
    assert _add(api, 3717, 777).status_code == 404


def test_edit_before_fetch_404(api, keitaro):
    assert _add(api, 3717).status_code == 404


# ---------------------------------------------------------------- remove / bring back

def test_remove_is_grey_zero_until_push(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717)
    v = _remove(api, 3749).json()
    assert _shares(v) == {3749: 0, 3717: 100}
    assert _status(v, 3749) == "removing" and _stream(v)["dirty"] is True
    assert _keitaro(fake) == {3749: 50, 3717: 50}  # still in Keitaro


def test_push_removal_keeps_offer_in_archive(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717)
    _remove(api, 3749)
    v = _push(api).json()
    assert _keitaro(fake) == {3717: 100}
    assert _status(v, 3749) == "removed" and _stream(v)["dirty"] is False


def test_any_offer_can_be_removed_but_push_needs_an_offer(api, keitaro, fake):
    _fetch(api)
    v = _remove(api, 3749).json()  # the only offer
    assert _status(v, 3749) == "removing"
    assert _push(api).status_code == 422
    assert fake.puts == []
    assert _status(_cancel(api).json(), 3749) == "active"


def test_bring_back_from_archive(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717)
    _remove(api, 3749)
    _push(api)
    v = _bring_back(api, 3749).json()
    assert _status(v, 3749) == "new" and _stream(v)["dirty"] is True
    v = _push(api).json()
    assert _status(v, 3749) == "active"
    assert _keitaro(fake) == {3717: 50, 3749: 50}


def test_bring_back_pending_removal_is_undo(api, keitaro):
    _fetch(api)
    _publish(api, 3717)
    _remove(api, 3749)
    v = _bring_back(api, 3749).json()
    assert _status(v, 3749) == "active" and _stream(v)["dirty"] is False
    assert _shares(v) == {3749: 50, 3717: 50}


def test_bring_back_active_offer_409(api, keitaro):
    _fetch(api)
    assert _bring_back(api, 3749).status_code == 409


def test_removing_unpublished_offer_forgets_it(api, keitaro):
    _fetch(api)
    _add(api, 3717)
    v = _remove(api, 3717).json()
    assert list(_shares(v)) == [3749]  # not even in the archive
    assert _stream(v)["dirty"] is False


def test_cancel_sends_brought_back_offer_to_archive(api, keitaro):
    _fetch(api)
    _publish(api, 3717)
    _remove(api, 3749)
    _push(api)  # 3749 archived
    _bring_back(api, 3749)
    v = _cancel(api).json()
    assert _status(v, 3749) == "removed" and _shares(v) == {3749: 0, 3717: 100}


# ---------------------------------------------------------------- fetch again: changes made in Keitaro

def test_offer_deleted_in_keitaro_becomes_removed_on_refetch(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717)
    fake.streams[OFFER_STREAM]["offers"] = [{"offer_id": 3717, "share": 100, "state": "active"}]  # 3749 deleted by hand
    v = _fetch(api)
    assert _status(v, 3749) == "removed"
    assert _shares(v) == {3749: 0, 3717: 100}
    assert _stream(v)["dirty"] is False
    assert _status(_bring_back(api, 3749).json(), 3749) == "new"  # can be brought back


def test_refetch_keeps_unpublished_local_changes(api, keitaro):
    _fetch(api)
    _add(api, 3717)
    v = _fetch(api)
    assert _status(v, 3717) == "new" and _stream(v)["dirty"] is True
    assert _shares(v) == {3749: 50, 3717: 50}


def test_refetch_picks_up_offer_added_in_keitaro(api, keitaro, fake):
    _fetch(api)
    fake.streams[OFFER_STREAM]["offers"] = [
        {"offer_id": 3749, "share": 50, "state": "active"}, {"offer_id": 18813, "share": 50, "state": "active"}]
    v = _fetch(api)
    assert _shares(v) == {3749: 50, 18813: 50} and _stream(v)["dirty"] is False


# ---------------------------------------------------------------- pin

def test_pin_is_local_metadata(api, keitaro):
    _fetch(api)
    _publish(api, 3717)
    v = _pin(api, 3749).json()
    assert next(o for o in _stream(v)["offers"] if o["offer_id"] == 3749)["pinned"] is True
    assert _shares(v) == {3749: 50, 3717: 50}
    assert _stream(v)["dirty"] is False  # not a Keitaro change


def test_video_scenario_pin_25_percent(api, keitaro, fake):
    """4 offers x 25%; pin one; remove another and bring it back: pinned stays 25%."""
    _fetch(api)
    _publish(api, 3717, 18813, 5555)
    _pin(api, 3749)
    v = _remove(api, 5555).json()
    assert _shares(v) == {3749: 25, 3717: 38, 18813: 37, 5555: 0}  # pinned 25, the rest share 75
    v = _bring_back(api, 5555).json()
    assert _shares(v) == {3749: 25, 3717: 25, 18813: 25, 5555: 25}
    _remove(api, 5555)
    v = _push(api).json()
    assert _shares(v) == {3749: 25, 3717: 38, 18813: 37, 5555: 0}
    assert _keitaro(fake) == {3749: 25, 3717: 38, 18813: 37}


def test_unpin_redistributes_evenly(api, keitaro):
    _fetch(api)
    _publish(api, 3717)
    _pin(api, 3749)
    _add(api, 18813)  # pinned 50, the rest 50 -> 25/25
    v = _pin(api, 3749, False).json()
    assert _shares(v) == {3749: 34, 3717: 33, 18813: 33}


def test_pins_leaving_no_room_rejected_and_nothing_changes(api, keitaro):
    _fetch(api)
    _publish(api, 3717)  # 50/50
    _pin(api, 3749)
    _pin(api, 3717)
    resp = _add(api, 18813)  # 50 + 50 pinned: no room for a new unpinned offer
    assert resp.status_code == 422
    v = api.get(URL).json()
    assert _shares(v) == {3749: 50, 3717: 50} and _stream(v)["dirty"] is False


def test_all_pinned_not_summing_to_100_cannot_be_pushed(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717)
    _pin(api, 3749)
    _pin(api, 3717)
    _remove(api, 3717)  # only 3749 left, pinned at 50
    resp = _push(api)
    assert resp.status_code == 422
    assert "100" in resp.json()["detail"]
    assert len(fake.puts) == 1  # just the first push


def test_pin_removed_offer_404(api, keitaro):
    _fetch(api)
    _publish(api, 3717)
    _remove(api, 3717)
    assert _pin(api, 3717).status_code == 404


# ---------------------------------------------------------------- push errors and logging

def test_push_nothing_to_publish_409(api, keitaro, fake):
    _fetch(api)
    assert _push(api).status_code == 409
    assert fake.puts == []


def test_push_detects_keitaro_not_saving(api, keitaro, fake):
    _fetch(api)
    _publish(api, 3717)
    _remove(api, 3749)
    fake.ignore_removals = True
    resp = _push(api)
    assert resp.status_code == 502
    assert resp.json()["error"] == "SaveVerificationError"


def test_operations_are_logged(api, keitaro, db_session):
    _fetch(api)
    _add(api, 3717)
    _push(api)
    _remove(api, 3749)
    logs = list(db_session.scalars(select(OperationLog).order_by(OperationLog.id)))
    assert [r.action for r in logs] == ["fetch", "offer.add", "stream.push", "offer.remove"]
    push = logs[2]
    assert push.details["before"] == [[3749, 100]] and push.details["after"] == [[3717, 50], [3749, 50]]
    assert push.campaign_keitaro_id == CAMPAIGN_ID
