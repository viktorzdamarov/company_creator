"""editor state: editor_campaigns, editor_streams, editor_offers

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editor_campaigns",
        sa.Column("keitaro_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(64), nullable=True),
        sa.Column("tracking_url", sa.String(1024), nullable=True),
        sa.Column("group", sa.String(255), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "editor_streams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("has_offers", sa.Boolean(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("unique_clicks", sa.Integer(), nullable=False),
        sa.Column("bots", sa.Integer(), nullable=False),
    )
    op.create_index("ix_editor_streams_campaign_id", "editor_streams", ["campaign_id"])
    op.create_table(
        "editor_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("editor_streams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("wanted", sa.Boolean(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("ever_published", sa.Boolean(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.Column("published_share", sa.Integer(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("stream_id", "offer_id", name="uq_editor_offer_stream_offer"),
    )
    op.create_index("ix_editor_offers_stream_id", "editor_offers", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_editor_offers_stream_id", table_name="editor_offers")
    op.drop_table("editor_offers")
    op.drop_index("ix_editor_streams_campaign_id", table_name="editor_streams")
    op.drop_table("editor_streams")
    op.drop_table("editor_campaigns")
