"""Campaign editor ("wrapper" over Keitaro): local draft of flows/offers that is published with Push.

Workflow (see TZ 3.2):
- fetch:      load flows from Keitaro into the local DB (flows without offers are kept as a bare flow)
- add/remove: change the LOCAL copy only; the flow becomes "dirty" (yellow) until Push
- push:       send the flow's offers and shares to Keitaro, verify by re-reading
- cancel:     drop unpublished changes of a flow
- bring back: return a removed offer (from the archive or a pending removal)
- pin:        freeze an offer's share; the other offers share the rest evenly

Offer state is two flags (see EditorOffer): ``wanted`` (should be in the flow) and ``published`` (is in Keitaro).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EditorCampaign, EditorOffer, EditorStream
from app.keitaro.client import KeitaroClient
from app.keitaro.errors import KeitaroError, KeitaroNotFoundError
from app.services.audit import log_operation
from app.services.weights import PinnedSharesError, distribute_with_pins

OFFER_SCHEMAS = {"landings"}


class EditorError(Exception):
    http_status = 409

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CampaignNotFetchedError(EditorError):
    http_status = 404


class StreamNotFoundError(EditorError):
    http_status = 404


class OfferNotInStreamError(EditorError):
    http_status = 404


class StreamNotEditableError(EditorError):
    http_status = 422


class InvalidSharesError(EditorError):
    http_status = 422


class DuplicateOfferError(EditorError):
    http_status = 409


class NothingToPushError(EditorError):
    http_status = 409


class SaveVerificationError(EditorError):
    http_status = 502


# ---------------------------------------------------------------- views

class OfferView(BaseModel):
    offer_id: int
    name: str
    share: int
    status: str  # active | new | removing | removed
    pinned: bool


class StreamView(BaseModel):
    id: int
    position: int
    name: str
    has_offers: bool
    dirty: bool  # has unpublished changes ("yellow")
    offers: list[OfferView]
    clicks: int = 0
    unique_clicks: int = 0
    bots: int = 0


class CampaignView(BaseModel):
    id: int
    name: str
    alias: str | None
    tracking_url: str | None
    group: str | None
    fetched_at: datetime
    streams: list[StreamView]
    total_clicks: int
    total_unique_clicks: int
    total_bots: int


class CampaignListItem(BaseModel):
    id: int
    name: str
    group: str | None
    state: str | None


def offer_status(o: EditorOffer) -> str:
    if o.wanted:
        return "active" if o.published else "new"
    return "removing" if o.published else "removed"


def offer_dirty(o: EditorOffer) -> bool:
    return o.wanted != o.published or (o.wanted and o.share != o.published_share)


def stream_dirty(s: EditorStream) -> bool:
    return any(offer_dirty(o) for o in s.offers)


def recalc_shares(stream: EditorStream) -> None:
    """Even split of the unpinned offers; removed offers get 0%."""
    wanted = [o for o in stream.offers if o.wanted]
    try:
        shares = distribute_with_pins([o.share if o.pinned else None for o in wanted])
    except PinnedSharesError as exc:
        raise InvalidSharesError(str(exc)) from exc
    for o, share in zip(wanted, shares):
        o.share = share
    for o in stream.offers:
        if not o.wanted:
            o.share = 0


# ---------------------------------------------------------------- service

class CampaignEditor:
    def __init__(self, client: KeitaroClient, db: Session):
        self.client = client
        self.db = db

    # -------- read

    def list_campaigns(self, query: str = "") -> list[CampaignListItem]:
        q = query.strip().lower()
        items = [
            CampaignListItem(id=c.id, name=c.name, group=c.group, state=c.state)
            for c in self.client.list_campaigns()
            if not q or q == str(c.id) or q in c.name.lower()
        ]
        return sorted(items, key=lambda c: c.id, reverse=True)

    def get(self, campaign_id: int) -> CampaignView:
        campaign = self.db.get(EditorCampaign, campaign_id)
        if campaign is None:
            raise CampaignNotFetchedError(f"Кампания {campaign_id} ещё не загружена: нажмите Fetch streams")
        streams = self._streams(campaign_id)
        views = [self._stream_view(s) for s in streams]
        return CampaignView(
            id=campaign.keitaro_id,
            name=campaign.name,
            alias=campaign.alias,
            tracking_url=campaign.tracking_url,
            group=campaign.group,
            fetched_at=campaign.fetched_at.replace(tzinfo=timezone.utc) if campaign.fetched_at.tzinfo is None else campaign.fetched_at,
            streams=views,
            total_clicks=sum(v.clicks for v in views),
            total_unique_clicks=sum(v.unique_clicks for v in views),
            total_bots=sum(v.bots for v in views),
        )

    # -------- fetch

    def fetch(self, campaign_id: int) -> CampaignView:
        """Load flows from Keitaro and merge them into the local copy (local unpublished changes are kept)."""
        with ThreadPoolExecutor(max_workers=4) as pool:
            campaign_f = pool.submit(self.client.get_campaign, campaign_id)
            streams_f = pool.submit(self.client.get_streams, campaign_id)
            offers_f = pool.submit(self._offer_names)
            stats_f = pool.submit(self.client.stream_stats, campaign_id)
            campaign = campaign_f.result()
            k_streams = streams_f.result()
            names = offers_f.result()
            stats = stats_f.result()

        rec = self.db.get(EditorCampaign, campaign_id) or EditorCampaign(keitaro_id=campaign_id)
        rec.name, rec.alias, rec.tracking_url, rec.group = campaign.name, campaign.alias, campaign.tracking_url, campaign.group
        rec.fetched_at = datetime.now(timezone.utc)
        self.db.add(rec)

        local = {s.id: s for s in self._streams(campaign_id)}
        for ks in k_streams:
            stream = local.pop(ks.id, None) or EditorStream(id=ks.id, campaign_id=campaign_id)
            stream.position = ks.position
            stream.name = ks.name or f"Flow {ks.position}"
            stream.has_offers = ks.schema_ in OFFER_SCHEMAS
            st = stats.get(ks.id)
            stream.clicks, stream.unique_clicks, stream.bots = (st.clicks, st.unique_clicks, st.bots) if st else (0, 0, 0)
            self.db.add(stream)
            if stream.has_offers:
                self._sync_offers(stream, {o.offer_id: o.share for o in ks.offers if o.state == "active"}, names)
        for gone in local.values():  # flow deleted in Keitaro
            self.db.delete(gone)
        self._log_commit("fetch", campaign_id, {"streams": [s.id for s in k_streams]})
        return self.get(campaign_id)

    def _offer_names(self) -> dict[int, str]:
        try:
            return {o.id: o.name for o in self.client.list_offers()}
        except KeitaroError:  # names are cosmetic
            return {}

    def _sync_offers(self, stream: EditorStream, in_keitaro: dict[int, int], names: dict[int, str]) -> None:
        known = {o.offer_id: o for o in stream.offers}
        for rec in stream.offers:
            clean = rec.wanted == rec.published  # no pending local change: follow Keitaro
            if rec.offer_id in in_keitaro:
                rec.published, rec.ever_published = True, True
                rec.published_share = in_keitaro[rec.offer_id]
                if clean:
                    rec.wanted, rec.share = True, rec.published_share
            else:
                rec.published, rec.published_share = False, 0
                if clean:
                    rec.wanted, rec.share = False, 0  # removed in Keitaro -> grey "removed"
            if rec.offer_id in names:
                rec.name = names[rec.offer_id]
        for offer_id, share in in_keitaro.items():
            if offer_id not in known:
                stream.offers.append(EditorOffer(
                    offer_id=offer_id, name=names.get(offer_id, f"Offer #{offer_id}"), wanted=True, published=True,
                    ever_published=True, share=share, published_share=share,
                ))
        if stream_dirty(stream):
            try:
                recalc_shares(stream)
            except InvalidSharesError:
                pass  # keep the shares as they are; Push will report the problem

    # -------- local changes

    def add_offer(self, campaign_id: int, stream_id: int, offer_id: int) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        existing = next((o for o in stream.offers if o.offer_id == offer_id), None)
        if existing and existing.wanted:
            raise DuplicateOfferError(f"Оффер {offer_id} уже есть в потоке")
        if existing:  # in the archive / pending removal: same as "bring back"
            existing.wanted = True
        else:
            offer = self.client.get_offer(offer_id)  # 404 / 403 from Keitaro if unknown or not allowed
            stream.offers.append(EditorOffer(offer_id=offer_id, name=offer.name, wanted=True, published=False))
        self._apply(campaign_id, stream, "offer.add", offer_id)
        return self.get(campaign_id)

    def remove_offer(self, campaign_id: int, stream_id: int, offer_id: int) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        offer = self._offer(stream, offer_id)
        if not offer.wanted:
            raise OfferNotInStreamError(f"Оффер {offer_id} уже удалён из потока")
        if offer.ever_published:
            offer.wanted, offer.pinned = False, False  # grey; stays in the archive after Push
        else:
            self.db.delete(offer)  # never reached Keitaro: nothing to archive
            stream.offers.remove(offer)
        self._apply(campaign_id, stream, "offer.remove", offer_id)
        return self.get(campaign_id)

    def bring_back(self, campaign_id: int, stream_id: int, offer_id: int) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        offer = self._offer(stream, offer_id)
        if offer.wanted:
            raise DuplicateOfferError(f"Оффер {offer_id} уже в потоке")
        offer.wanted = True
        self._apply(campaign_id, stream, "offer.bring_back", offer_id)
        return self.get(campaign_id)

    def set_pin(self, campaign_id: int, stream_id: int, offer_id: int, pinned: bool) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        offer = self._offer(stream, offer_id)
        if not offer.wanted:
            raise OfferNotInStreamError(f"Оффер {offer_id} удалён из потока: закреплять нечего")
        offer.pinned = pinned  # pinning keeps the current share
        self._apply(campaign_id, stream, "offer.pin" if pinned else "offer.unpin", offer_id)
        return self.get(campaign_id)

    def cancel(self, campaign_id: int, stream_id: int) -> CampaignView:
        """Drop unpublished changes: new offers disappear, removals are undone, shares go back."""
        stream = self._editable_stream(campaign_id, stream_id)
        for o in list(stream.offers):
            if o.wanted and not o.published:
                if o.ever_published:
                    o.wanted = False  # back to the archive
                else:
                    stream.offers.remove(o)
                    self.db.delete(o)
            elif not o.wanted and o.published:
                o.wanted = True
        for o in stream.offers:
            o.share = o.published_share if o.wanted else 0
        self._log_commit("stream.cancel", campaign_id, {"stream_id": stream_id})
        return self.get(campaign_id)

    # -------- push

    def push(self, campaign_id: int, stream_id: int) -> CampaignView:
        stream = self._editable_stream(campaign_id, stream_id)
        if not stream_dirty(stream):
            raise NothingToPushError("В потоке нет неопубликованных изменений")
        active = [o for o in stream.offers if o.wanted]
        if not active:
            raise InvalidSharesError("В потоке не осталось офферов: добавьте оффер или нажмите Cancel")
        total = sum(o.share for o in active)
        if total != 100:
            raise InvalidSharesError(f"Доли офферов дают {total}%, нужно 100%: измените закрепление")
        expected = sorted((o.offer_id, o.share) for o in active)
        details = {
            "stream_id": stream.id,
            "before": sorted((o.offer_id, o.published_share) for o in stream.offers if o.published),
            "after": expected,
        }
        payload = {"offers": [{"offer_id": oid, "share": share, "state": "active"} for oid, share in expected]}
        try:
            self.client.update_stream(stream.id, payload)
            saved = next((s for s in self.client.get_streams(campaign_id) if s.id == stream.id), None)
            if saved is None:
                raise KeitaroNotFoundError(f"Поток {stream.id} пропал после сохранения")
            actual = sorted((o.offer_id, o.share) for o in saved.offers if o.state == "active")
            if actual != expected:
                raise SaveVerificationError(f"Keitaro сохранил {actual}, ожидалось {expected}")
        except (KeitaroError, SaveVerificationError) as exc:
            log_operation(self.db, "stream.push", status="error", campaign_id=campaign_id, details=details, error=str(exc))
            raise
        for o in stream.offers:
            if o.wanted:
                o.published, o.ever_published, o.published_share = True, True, o.share
            else:
                o.published, o.published_share = False, 0
        self._log_commit("stream.push", campaign_id, details)
        return self.get(campaign_id)

    # -------- helpers

    def _streams(self, campaign_id: int) -> list[EditorStream]:
        q = select(EditorStream).where(EditorStream.campaign_id == campaign_id).order_by(EditorStream.position, EditorStream.id)
        return list(self.db.scalars(q))

    def _editable_stream(self, campaign_id: int, stream_id: int) -> EditorStream:
        if self.db.get(EditorCampaign, campaign_id) is None:
            raise CampaignNotFetchedError(f"Кампания {campaign_id} ещё не загружена: нажмите Fetch streams")
        stream = self.db.get(EditorStream, stream_id)
        if stream is None or stream.campaign_id != campaign_id:
            raise StreamNotFoundError(f"Поток {stream_id} не найден в кампании {campaign_id}")
        if not stream.has_offers:
            raise StreamNotEditableError(f"В потоке {stream_id} нет офферов: редактировать нечего")
        return stream

    @staticmethod
    def _offer(stream: EditorStream, offer_id: int) -> EditorOffer:
        offer = next((o for o in stream.offers if o.offer_id == offer_id), None)
        if offer is None:
            raise OfferNotInStreamError(f"Оффера {offer_id} нет в потоке {stream.id}")
        return offer

    def _apply(self, campaign_id: int, stream: EditorStream, action: str, offer_id: int) -> None:
        """Recalculate shares and save; on invalid pins nothing is changed."""
        try:
            recalc_shares(stream)
        except InvalidSharesError:
            self.db.rollback()
            raise
        self._log_commit(action, campaign_id, {"stream_id": stream.id, "offer_id": offer_id})

    def _log_commit(self, action: str, campaign_id: int, details: dict) -> None:
        self.db.commit()
        log_operation(self.db, action, campaign_id=campaign_id, details=details)

    @staticmethod
    def _stream_view(s: EditorStream) -> StreamView:
        return StreamView(
            id=s.id, position=s.position, name=s.name, has_offers=s.has_offers, dirty=stream_dirty(s),
            offers=[
                OfferView(offer_id=o.offer_id, name=o.name or f"Offer #{o.offer_id}", share=o.share,
                          status=offer_status(o), pinned=o.pinned)
                for o in s.offers
            ],
            clicks=s.clicks, unique_clicks=s.unique_clicks, bots=s.bots,
        )
