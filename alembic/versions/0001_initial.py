"""initial tables: campaign_records, operation_logs

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geo", sa.String(255), nullable=False),
        sa.Column("offer_ids", sa.JSON(), nullable=False),
        sa.Column("tracking_url", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaign_records_keitaro_id", "campaign_records", ["keitaro_id"])
    op.create_index("ix_campaign_records_name", "campaign_records", ["name"])

    op.create_table(
        "operation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("campaign_keitaro_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_operation_logs_action", "operation_logs", ["action"])
    op.create_index("ix_operation_logs_campaign_keitaro_id", "operation_logs", ["campaign_keitaro_id"])


def downgrade() -> None:
    op.drop_index("ix_operation_logs_campaign_keitaro_id", table_name="operation_logs")
    op.drop_index("ix_operation_logs_action", table_name="operation_logs")
    op.drop_table("operation_logs")
    op.drop_index("ix_campaign_records_name", table_name="campaign_records")
    op.drop_index("ix_campaign_records_keitaro_id", table_name="campaign_records")
    op.drop_table("campaign_records")
