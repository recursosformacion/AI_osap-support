"""Asunto/cuerpo dinámicos y clave de idempotencia en CommunicationEvent.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("communication_events", sa.Column("subject", sa.String(255), nullable=True))
    op.add_column("communication_events", sa.Column("body", sa.Text(), nullable=True))
    op.add_column(
        "communication_events",
        sa.Column("dedupe_key", sa.String(160), nullable=True),
    )
    op.create_index(
        "uq_communication_events_dedupe",
        "communication_events",
        ["dedupe_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_communication_events_dedupe", table_name="communication_events")
    op.drop_column("communication_events", "dedupe_key")
    op.drop_column("communication_events", "body")
    op.drop_column("communication_events", "subject")

