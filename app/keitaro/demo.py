"""DEMO mode: an in-process stand-in for Keitaro, so the whole app can be tried without a real tracker.

``DemoKeitaroClient`` is a real ``KeitaroClient`` whose ``request`` is answered from memory instead of
over HTTP, so all client logic (parsing, offer search, ...) is the one used with real Keitaro.

- offers come from ``demo_offers.json`` (5 invented offers) and are visible to the "API key" without restrictions;
- on first start two demo campaigns are created (one with 1 offer, one with 3 offers);
- state (campaigns, flows) is saved to ``DEMO_STATE_FILE`` after every change, so it survives restarts;
  delete that file to start from scratch.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroNotFoundError, KeitaroValidationError

OFFERS_FILE = Path(__file__).with_name("demo_offers.json")
FIRST_CAMPAIGN_ID = 900001
FIRST_STREAM_ID = 9000001


class DemoKeitaroClient(KeitaroClient):
    def __init__(self, state_file: str | Path, domain: str, group: str, source: str):
        super().__init__("http://demo.keitaro.local", "demo-key", max_retries=0)
        self._lock = RLock()
        self._file = Path(state_file)
        self._offers: list[dict] = json.loads(OFFERS_FILE.read_text(encoding="utf-8"))
        self._domains = [{"id": 1, "name": domain, "is_ssl": True, "state": "active"}]
        self._groups = [{"id": 1, "name": group, "type": "campaigns"}]
        self._sources = [{"id": 1, "name": source, "state": "active"}]
        self._campaigns: dict[int, dict] = {}
        self._streams: dict[int, dict] = {}
        self._next_campaign = FIRST_CAMPAIGN_ID
        self._next_stream = FIRST_STREAM_ID
        if self._file.exists():
            self._load()
        else:
            self._seed()
            self._save()

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:  # the demo client is shared between requests: nothing to release per request
        pass

    def reset(self) -> None:
        with self._lock:
            self._campaigns, self._streams = {}, {}
            self._next_campaign, self._next_stream = FIRST_CAMPAIGN_ID, FIRST_STREAM_ID
            self._seed()
            self._save()

    # ------------------------------------------------------------------ state

    def _seed(self) -> None:
        self._add_campaign("demo_campaign_001", "AU", [9001])
        self._add_campaign("demo_campaign_multi", "MX,RO", [9002, 9003, 9004])

    def _add_campaign(self, name: str, geo: str, offer_ids: list[int]) -> None:
        campaign = self._create_campaign({
            "name": name, "alias": secrets.token_hex(4), "type": "position", "state": "active",
            "domain_id": 1, "group_id": 1, "traffic_source_id": 1, "cost_type": "CPC",
        })
        codes = geo.split(",")
        self._create_stream({
            "campaign_id": campaign["id"], "type": "regular", "name": f"{geo} → Google", "position": 1,
            "state": "active", "schema": "redirect", "action_type": "http", "action_payload": "https://google.com",
            "filters": [{"name": "country", "mode": "accept", "payload": codes}],
        })
        base, rest = divmod(100, len(offer_ids))
        self._create_stream({
            "campaign_id": campaign["id"], "type": "regular", "name": "Офферы", "position": 2, "state": "active",
            "schema": "landings", "action_type": "do_nothing", "filters": [],
            "offers": [{"offer_id": oid, "share": base + (1 if i < rest else 0), "state": "active"}
                       for i, oid in enumerate(offer_ids)],
        })

    def _load(self) -> None:
        data = json.loads(self._file.read_text(encoding="utf-8"))
        self._campaigns = {int(k): v for k, v in data["campaigns"].items()}
        self._streams = {int(k): v for k, v in data["streams"].items()}
        self._next_campaign, self._next_stream = data["next_campaign"], data["next_stream"]

    def _save(self) -> None:
        data = {"campaigns": self._campaigns, "streams": self._streams,
                "next_campaign": self._next_campaign, "next_stream": self._next_stream}
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _offer(self, offer_id: int) -> dict:
        offer = next((o for o in self._offers if o["id"] == offer_id), None)
        if offer is None:
            raise KeitaroNotFoundError(f"Offer #{offer_id} not found", status_code=404, path=f"/offers/{offer_id}")
        return offer

    def _campaign(self, campaign_id: int) -> dict:
        if campaign_id not in self._campaigns:
            raise KeitaroNotFoundError(f"Campaign #{campaign_id} not found", status_code=404,
                                       path=f"/campaigns/{campaign_id}")
        return self._campaigns[campaign_id]

    def _create_campaign(self, payload: dict) -> dict:
        domain = next((d for d in self._domains if d["id"] == payload.get("domain_id")), self._domains[0])
        group = next((g for g in self._groups if g["id"] == payload.get("group_id")), None)
        campaign = {
            **payload,
            "id": self._next_campaign,
            "domain": f"https://{domain['name']}/",
            "group": group["name"] if group else None,
        }
        self._next_campaign += 1
        self._campaigns[campaign["id"]] = campaign
        return campaign

    def _create_stream(self, payload: dict) -> dict:
        self._campaign(payload["campaign_id"])
        stream = {**payload, "id": self._next_stream, "offers": self._offer_rows(payload.get("offers", []))}
        stream.setdefault("filters", [])
        self._next_stream += 1
        self._streams[stream["id"]] = stream
        return stream

    def _offer_rows(self, offers: list[dict]) -> list[dict]:
        rows = []
        for o in offers:
            self._offer(int(o["offer_id"]))  # unknown offer -> 404 like in Keitaro
            rows.append({"offer_id": int(o["offer_id"]), "share": int(o["share"]), "state": o.get("state", "active")})
        return rows

    # ------------------------------------------------------------------ the fake HTTP layer

    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        with self._lock:
            result = copy.deepcopy(self._route(method.upper(), path, json, params or {}))
            if method.upper() != "GET" and path != "/report/build":
                self._save()
            return result

    def _route(self, method: str, path: str, body: Any, params: dict) -> Any:
        if method == "GET":
            if path == "/domains":
                return self._domains
            if path == "/groups":
                return self._groups
            if path == "/traffic_sources":
                return self._sources
            if path == "/offers":
                return self._offers
            if m := re.fullmatch(r"/offers/(\d+)", path):
                return self._offer(int(m[1]))
            if path == "/campaigns":
                return list(self._campaigns.values())
            if m := re.fullmatch(r"/campaigns/(\d+)", path):
                return self._campaign(int(m[1]))
            if m := re.fullmatch(r"/campaigns/(\d+)/streams", path):
                cid = int(m[1])
                self._campaign(cid)
                return [s for s in self._streams.values() if s["campaign_id"] == cid]
        elif method == "POST":
            if path == "/campaigns":
                if not (body or {}).get("name"):
                    raise KeitaroValidationError("name is required", status_code=422, path=path)
                return self._create_campaign(body)
            if path == "/streams":
                return self._create_stream(body)
            if path == "/report/build":
                return self._report(body)
        elif method == "PUT":
            if m := re.fullmatch(r"/streams/(\d+)", path):
                stream = self._streams.get(int(m[1]))
                if stream is None:
                    raise KeitaroNotFoundError(f"Stream #{m[1]} not found", status_code=404, path=path)
                update = {k: v for k, v in (body or {}).items() if k != "offers"}
                if "offers" in (body or {}):
                    update["offers"] = self._offer_rows(body["offers"])
                stream.update(update)
                return stream
        elif method == "DELETE":
            if m := re.fullmatch(r"/campaigns/(\d+)", path):
                cid = int(m[1])
                self._campaign(cid)
                del self._campaigns[cid]
                self._streams = {k: s for k, s in self._streams.items() if s["campaign_id"] != cid}
                return {}
        raise KeitaroNotFoundError(f"demo: no route {method} {path}", status_code=404, path=path)

    def _report(self, body: dict) -> dict:
        campaign_id = int(body["filters"][0]["expression"])
        rows = []
        for s in self._streams.values():
            if s["campaign_id"] == campaign_id:
                clicks = (s["id"] * 7919) % 300 + 20  # stable fake numbers
                rows.append({"stream_id": s["id"], "clicks": clicks,
                             "campaign_unique_clicks": clicks * 4 // 5, "bots": clicks // 15})
        return {"rows": rows}


@lru_cache
def get_demo_client(state_file: str, domain: str, group: str, source: str) -> DemoKeitaroClient:
    return DemoKeitaroClient(state_file, domain, group, source)
