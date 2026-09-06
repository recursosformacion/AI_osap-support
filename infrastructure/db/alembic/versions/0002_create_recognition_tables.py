"""Crear tablas de reconocimientos y contribuciones (ADR-015/ADR-017, migración 0002).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06

Añade a la BD `osap_support` (ADR-003):
- `projects`: registro whitelisted (proyecto canónico `ecosystem` + `omr` sembrados).
- `recognitions`: proyección de estado vigente; UNIQUE(user_id, project_id, type).
- `recognition_events`: historial inmutable (libro mayor de reconocimientos).
- `contributions`: deltas de evidencia; UNIQUE(source, source_reference).

No toca la economía existente (memberships/donations/payment_events, ADR-004/ADR-007).
El seed de `projects` se ejecuta una sola vez por base (controlado por la revisión
Alembic), por lo que es idempotente a efectos de migración.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# PK/refs autoincrement: BIGINT en MySQL/MariaDB, INTEGER en SQLite (para tests).
BIG_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def _seed_projects() -> None:
    from datetime import UTC, datetime

    projects = sa.table(
        "projects",
        sa.column("id", BIG_PK),
        sa.column("slug", sa.String(32)),
        sa.column("name", sa.String(120)),
        sa.column("created_at", sa.DateTime()),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        projects,
        [
            {"slug": "ecosystem", "name": "OSAP Ecosystem", "created_at": now},
            {"slug": "omr", "name": "Open Music Repository", "created_at": now},
        ],
    )


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "recognitions",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("support_members.user_id"),
            nullable=False,
        ),
        sa.Column("project_id", BIG_PK, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by", sa.String(64), nullable=True),
        sa.Column("origin", sa.String(120), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("active_until", sa.DateTime(), nullable=True),
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_since", sa.DateTime(), nullable=True),
        sa.Column("public_revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "project_id", "type", name="uq_recognition_current"
        ),
    )
    op.create_index(
        "ix_recognitions_project_status_public",
        "recognitions",
        ["project_id", "status", "public"],
    )
    op.create_index("ix_recognitions_user_id", "recognitions", ["user_id"])

    op.create_table(
        "recognition_events",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("project_id", BIG_PK, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("status_after", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("origin", sa.String(120), nullable=True),
        sa.Column("origin_ref", sa.String(255), nullable=True),
        sa.Column("granted_by", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recognition_events_user", "recognition_events", ["user_id"])
    op.create_index(
        "ix_recognition_events_user_project",
        "recognition_events",
        ["user_id", "project_id"],
    )

    op.create_table(
        "contributions",
        sa.Column("id", BIG_PK, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("support_members.user_id"),
            nullable=False,
        ),
        sa.Column("project_id", BIG_PK, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("summary", sa.String(255), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source", "source_reference", name="uq_contribution_source"),
    )
    op.create_index("ix_contributions_user_id", "contributions", ["user_id"])
    op.create_index(
        "ix_contributions_user_project", "contributions", ["user_id", "project_id"]
    )

    _seed_projects()


def downgrade() -> None:
    op.drop_table("contributions")
    op.drop_table("recognition_events")
    op.drop_table("recognitions")
    op.drop_table("projects")
