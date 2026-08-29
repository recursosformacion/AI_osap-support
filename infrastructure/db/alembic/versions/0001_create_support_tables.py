"""Crear tablas del dominio de osap_support (Fase 3).

Revision ID: 0001
Revises:
Create Date: 2026-08-29

Crea únicamente las tablas del dominio de Support en la BD propia `osap_support`
(ADR-003). No crea identidad local (ADR-002), no toca otras BBDD.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# PK autoincrement: BIGINT en MySQL/MariaDB, INTEGER en SQLite (para tests aislados).
BIG_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "support_members",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
    )

    op.create_table(
        "memberships",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("support_members.user_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("periodicity", sa.String(16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(255), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=False, unique=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("renewed_at", sa.DateTime(), nullable=True),
        sa.Column("next_renewal_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("email_contact", sa.String(255), nullable=False),
        sa.Column("is_founder", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_status", "memberships", ["status"])
    op.create_index("ix_memberships_next_renewal_at", "memberships", ["next_renewal_at"])

    op.create_table(
        "donations",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("support_members.user_id"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("charge_id", sa.String(255), nullable=False),
        sa.Column("receipt_id", sa.String(255), nullable=True),
        sa.Column("email_receipt", sa.String(255), nullable=False),
        sa.Column("donated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_donations_user_id", "donations", ["user_id"])

    op.create_table(
        "payment_events",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_payment_event"),
    )
    op.create_index("ix_payment_events_user_id", "payment_events", ["user_id"])

    op.create_table(
        "communication_events",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column(
            "origin_event_id",
            BIG_PK,
            sa.ForeignKey("payment_events.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_communication_events_user_id", "communication_events", ["user_id"])
    op.create_index("ix_communication_events_status", "communication_events", ["status"])


def downgrade() -> None:
    op.drop_table("communication_events")
    op.drop_table("payment_events")
    op.drop_table("donations")
    op.drop_table("memberships")
    op.drop_table("support_members")
