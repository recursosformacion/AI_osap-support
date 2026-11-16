"""Cuerpo HTML opcional para comunicaciones redactadas (boletín).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("communication_events", sa.Column("body_html", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("communication_events", "body_html")
