"""Thin synchronous client for Keitaro Admin API v1.

Docs: <KEITARO_URL>/admin_api/v1/docs (link "Документация" in Профиль → API ключи).
Auth: header ``Api-Key``. See docs/keitaro_api_notes.md for verified request/response shapes.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.keitaro.errors import (
    KeitaroAuthError,
    KeitaroError,
    KeitaroForbiddenError,
    KeitaroNotFoundError,
    KeitaroRateLimitError,
    KeitaroTimeoutError,
    KeitaroUnavailableError,
    KeitaroValidationError,
)
from app.keitaro.schemas import (
    Campaign,
    Domain,
    Group,
    Offer,
    Stream,
    StreamStats,
    TrafficSource,
)

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
IDEMPOTENT_METHODS = {"GET", "PUT"}  # PUT /streams sends the full offers list: repeating it changes nothing
API_PREFIX = "/admin_api/v1"


class KeitaroClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._http = httpx.Client(
            base_url=self.base_url + API_PREFIX,
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings=None) -> KeitaroClient:
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
        return cls(
            settings.keitaro_url,
            settings.keitaro_api_key.get_secret_value(),
            timeout=settings.keitaro_timeout,
            max_retries=settings.keitaro_max_retries,
            retry_backoff=settings.keitaro_retry_backoff,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KeitaroClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ transport

    def request(
        self, method: str, path: str, *, json: Any = None, params: dict | None = None, idempotent: bool | None = None
    ) -> Any:
        """Perform a request with retries; return parsed JSON or raise a typed KeitaroError.

        Retry policy (a repeated POST could create a second campaign/stream in Keitaro):
        - the request never reached Keitaro (connect error / connect timeout) or got 429: retried for any method;
        - read timeout, broken connection or 5xx: retried only for idempotent requests
          (GET/PUT by default; read-only POSTs such as reports pass ``idempotent=True``).
        """
        if idempotent is None:
            idempotent = method.upper() in IDEMPOTENT_METHODS
        attempt = 0
        while True:
            attempt += 1
            can_retry = attempt <= self.max_retries
            started = time.perf_counter()
            try:
                resp = self._http.request(method, path, json=json, params=params)
            except httpx.TimeoutException as exc:
                if can_retry and (idempotent or isinstance(exc, httpx.ConnectTimeout)):
                    self._sleep(attempt, method, path, "timeout")
                    continue
                raise KeitaroTimeoutError(f"Keitaro did not respond in time: {method} {path}", path=path) from exc
            except httpx.TransportError as exc:
                if can_retry and (idempotent or isinstance(exc, httpx.ConnectError)):
                    self._sleep(attempt, method, path, type(exc).__name__)
                    continue
                raise KeitaroUnavailableError(f"Cannot connect to Keitaro: {exc}", path=path) from exc

            elapsed_ms = (time.perf_counter() - started) * 1000
            log.info("keitaro %s %s -> %s (%.0f ms)", method, path, resp.status_code, elapsed_ms)

            retryable = resp.status_code == 429 or (idempotent and resp.status_code in RETRY_STATUSES)
            if retryable and can_retry:
                self._sleep(attempt, method, path, str(resp.status_code), resp.headers.get("Retry-After"))
                continue
            return self._handle(resp, path)

    def _sleep(self, attempt: int, method: str, path: str, reason: str, retry_after: str | None = None) -> None:
        delay = self.retry_backoff * (2 ** (attempt - 1))
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning("keitaro %s %s: %s, retry %d/%d in %.2fs", method, path, reason, attempt, self.max_retries, delay)
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _error_text(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.reason_phrase or "error"
        if isinstance(data, dict):
            return str(data.get("error") or data.get("message") or data)
        return str(data)

    def _handle(self, resp: httpx.Response, path: str) -> Any:
        code = resp.status_code
        if code < 400:
            if not resp.content:
                return None
            try:
                return resp.json()
            except ValueError as exc:
                raise KeitaroError("Keitaro returned non-JSON response", status_code=code, path=path) from exc

        text = self._error_text(resp)
        kwargs = {"status_code": code, "path": path}
        if code == 403:
            raise KeitaroForbiddenError(f"У роли API-ключа нет прав на это действие в Keitaro: {text}", detail=text, **kwargs)
        if code == 401:
            raise KeitaroAuthError(f"Keitaro не принял API-ключ (неверный или отозван): {text}", detail=text, **kwargs)
        if code == 404:
            raise KeitaroNotFoundError(f"Not found in Keitaro: {path}", **kwargs)
        if code in (400, 422):
            raise KeitaroValidationError(f"Keitaro rejected the request: {text}", **kwargs)
        if code == 429:
            raise KeitaroRateLimitError("Keitaro rate limit exceeded", **kwargs)
        if code >= 500:
            raise KeitaroUnavailableError(f"Keitaro server error: {text}", **kwargs)
        raise KeitaroError(f"Unexpected Keitaro response: {text}", **kwargs)

    # ------------------------------------------------------------------ dictionaries

    def list_domains(self) -> list[Domain]:
        return [Domain.model_validate(d) for d in self.request("GET", "/domains")]

    def list_campaign_groups(self) -> list[Group]:
        data = self.request("GET", "/groups", params={"type": "campaigns"})
        return [Group.model_validate(g) for g in data]

    def list_traffic_sources(self) -> list[TrafficSource]:
        return [TrafficSource.model_validate(t) for t in self.request("GET", "/traffic_sources")]

    # ------------------------------------------------------------------ offers

    def list_offers(self) -> list[Offer]:
        return [Offer.model_validate(o) for o in self.request("GET", "/offers")]

    def get_offer(self, offer_id: int) -> Offer:
        try:
            return Offer.model_validate(self.request("GET", f"/offers/{offer_id}"))
        except KeitaroForbiddenError as exc:
            # Without rights on Offers Keitaro answers 403 for any ID, even a non-existent one: don't claim it exists.
            raise KeitaroForbiddenError(
                f"Нет доступа к офферу {offer_id}: у роли API-ключа нет прав на офферы или на этот оффер "
                f"(проверьте ID и права роли в Keitaro). Ответ Keitaro: {exc.detail}",
                status_code=exc.status_code, path=exc.path, detail=exc.detail,
            ) from exc

    def search_offers(self, query: str = "", limit: int = 20) -> list[Offer]:
        """Autocomplete: match by exact ID or case-insensitive substring of the name.

        Admin API has no server-side search for offers, so we filter the list locally.
        """
        q = query.strip().lower()
        offers = [o for o in self.list_offers() if o.state != "deleted"]
        if q:
            offers = [o for o in offers if q == str(o.id) or q in o.name.lower()]
        return offers[:limit]

    # ------------------------------------------------------------------ campaigns & streams

    def list_campaigns(self) -> list[Campaign]:
        return [Campaign.model_validate(c) for c in self.request("GET", "/campaigns")]

    def get_campaign(self, campaign_id: int) -> Campaign:
        return Campaign.model_validate(self.request("GET", f"/campaigns/{campaign_id}"))

    def get_streams(self, campaign_id: int) -> list[Stream]:
        data = self.request("GET", f"/campaigns/{campaign_id}/streams")
        streams = [Stream.model_validate(s) for s in data]
        return sorted(streams, key=lambda s: s.position)

    def create_campaign(self, payload: dict) -> Campaign:
        return Campaign.model_validate(self.request("POST", "/campaigns", json=payload))

    def delete_campaign(self, campaign_id: int) -> None:
        """Keitaro moves the campaign to the archive (soft delete)."""
        self.request("DELETE", f"/campaigns/{campaign_id}")

    def create_stream(self, payload: dict) -> Stream:
        return Stream.model_validate(self.request("POST", "/streams", json=payload))

    def update_stream(self, stream_id: int, payload: dict) -> Stream:
        return Stream.model_validate(self.request("PUT", f"/streams/{stream_id}", json=payload))

    # ------------------------------------------------------------------ stats

    def stream_stats(self, campaign_id: int, interval: str = "all_time") -> dict[int, StreamStats]:
        """Clicks / unique clicks / bots per stream of a campaign (columns «Клики / Уник. / Боты»)."""
        body = {
            "range": {"interval": interval, "timezone": "Europe/Moscow"},
            "dimensions": ["stream_id"],
            "measures": ["clicks", "campaign_unique_clicks", "bots"],
            "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
        }
        data = self.request("POST", "/report/build", json=body, idempotent=True) or {}  # read-only report
        result: dict[int, StreamStats] = {}
        for row in data.get("rows", []):
            if row.get("stream_id") in (None, ""):
                continue
            sid = int(row["stream_id"])
            result[sid] = StreamStats(
                stream_id=sid,
                clicks=int(row.get("clicks") or 0),
                unique_clicks=int(row.get("campaign_unique_clicks") or 0),
                bots=int(row.get("bots") or 0),
            )
        return result
