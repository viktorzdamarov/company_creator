from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CampaignRecord(Base):
    """Campaign created through Adrobot (local mirror of what was sent to Keitaro)."""

    __tablename__ = "campaign_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    geo: Mapped[str] = mapped_column(String(255))
    offer_ids: Mapped[list] = mapped_column(JSON, default=list)
    tracking_url: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OperationLog(Base):
    """Audit log of every operation performed against Keitaro."""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    campaign_keitaro_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16))  # ok | error
    details: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EditorCampaign(Base):
    """Campaign loaded into the editor ("Fetch streams"): local copy of what Keitaro had."""

    __tablename__ = "editor_campaigns"

    keitaro_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(64))
    tracking_url: Mapped[str | None] = mapped_column(String(1024))
    group: Mapped[str | None] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EditorStream(Base):
    """Flow of an editor campaign. Flows without offers are kept only as a name/position."""

    __tablename__ = "editor_streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # Keitaro stream id
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255), default="")
    has_offers: Mapped[bool] = mapped_column(Boolean, default=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    unique_clicks: Mapped[int] = mapped_column(Integer, default=0)
    bots: Mapped[int] = mapped_column(Integer, default=0)

    offers: Mapped[list["EditorOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="EditorOffer.id"
    )


class EditorOffer(Base):
    """Offer binding in a flow.

    ``published`` — the offer is in Keitaro now; ``wanted`` — the user wants it in the flow.
    wanted+published = active; wanted only = new (yellow); published only = pending removal (grey, 0%);
    neither = archive (grey, "removed"), can be brought back.
    """

    __tablename__ = "editor_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_editor_offer_stream_offer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("editor_streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500), default="")
    wanted: Mapped[bool] = mapped_column(Boolean, default=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    ever_published: Mapped[bool] = mapped_column(Boolean, default=False)
    share: Mapped[int] = mapped_column(Integer, default=0)
    published_share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    stream: Mapped[EditorStream] = relationship(back_populates="offers")
