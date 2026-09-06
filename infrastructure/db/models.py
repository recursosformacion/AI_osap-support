"""Modelos de persistencia de osap-support (SQLAlchemy).

Separación hexagonal: estos son SOLO modelos de persistencia. No son el dominio.
El mapeo persistencia <-> dominio se realiza en `infrastructure/db/repositories/`.

Reglas aplicadas:
- ADR-003: solo tablas de osap_support.
- ADR-002: no existe tabla de usuarios/identidad local; `user_id` es referencia externa (JWT.sub).
- ADR-004: membership y donation son tablas separadas.
- ADR-007: UNIQUE(provider, provider_event_id) en payment_events.
- V-021: importes como enteros (amount_minor) + currency ISO 4217.
- ADR-015/ADR-017: projects/recognitions/recognition_events/contributions (migración 0002).
  `projects.slug` es el registro whitelisted (canónico `ecosystem`); `recognitions` es la
  proyección de estado vigente y `recognition_events` el historial inmutable; `contributions`
  guarda deltas con UNIQUE(source, source_reference).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# PK autoincrement: BIGINT en MySQL/MariaDB, INTEGER en SQLite (tests). En SQLite
# solo `INTEGER PRIMARY KEY` autoincrementa; BIGINT no (causa NOT NULL en tests).
BIG_PK = BigInteger().with_variant(Integer, "sqlite")


def _utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SupportMemberModel(Base):
    __tablename__ = "support_members"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # JWT.sub (Auth)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc)
    data_version: Mapped[int] = mapped_column(Integer, default=0)


class MembershipModel(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("support_members.user_id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)  # MembershipStatus.value
    level: Mapped[str] = mapped_column(String(32))  # MembershipLevel.value
    periodicity: Mapped[str] = mapped_column(String(16))  # Periodicity.value
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # V-021: enteros
    currency: Mapped[str] = mapped_column(String(3))  # ISO 4217
    provider: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[str] = mapped_column(String(255))
    subscription_id: Mapped[str] = mapped_column(String(255), unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_renewal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_contact: Mapped[str] = mapped_column(String(255), default="")
    is_founder: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc, onupdate=_utc)


class DonationModel(Base):
    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("support_members.user_id"), index=True
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # V-021
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(64))
    charge_id: Mapped[str] = mapped_column(String(255))
    receipt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_receipt: Mapped[str] = mapped_column(String(255), default="")
    donated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc)


class PaymentEventModel(Base):
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_payment_event"),)

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64))
    provider_event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="processed")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utc)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommunicationEventModel(Base):
    __tablename__ = "communication_events"

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    template: Mapped[str] = mapped_column(String(64))
    recipient_email: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    origin_event_id: Mapped[int | None] = mapped_column(
        BIG_PK, ForeignKey("payment_events.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectModel(Base):
    """Registro whitelisted de proyectos del ecosistema (ADR-015).

    `slug='ecosystem'` es el proyecto canónico de los reconocimientos derivados de la
    relación económica global (SUPPORTER/FOUNDER). Otros slugs (p. ej. `omr`) se añaden
    por migración/operación; nunca desde el cliente.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc, nullable=False)


class RecognitionModel(Base):
    """Proyección de estado vigente de un reconocimiento (ADR-015).

    Una fila por (user_id, project_id, type); `status` distingue vigente (ACTIVE) de
    histórico (INACTIVE, no se muestra). El historial inmutable vive en
    `recognition_events`. project_id siempre poblado (canónico `ecosystem` para
    SUPPORTER/FOUNDER); sin NULL semántico.
    """

    __tablename__ = "recognitions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "project_id", "type", name="uq_recognition_current"
        ),
        Index("ix_recognitions_project_status_public", "project_id", "status", "public"),
    )

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("support_members.user_id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BIG_PK, ForeignKey("projects.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # RecognitionType.value
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # RecognitionKind.value
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # RecognitionStatus.value
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    public_revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utc, onupdate=_utc, nullable=False
    )

    project: Mapped[ProjectModel] = relationship()


class RecognitionEventModel(Base):
    """Historial inmutable de cambios de reconocimiento (ADR-016).

    Permite responder por qué/cuándo se activó, desactivó, concedió o revocó un
    reconocimiento (incluidas las sucesivas activaciones/desactivaciones de SUPPORTER)
    sin contaminar la proyección `recognitions`.
    """

    __tablename__ = "recognition_events"
    __table_args__ = (
        Index("ix_recognition_events_user", "user_id"),
        Index("ix_recognition_events_user_project", "user_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[int] = mapped_column(
        BIG_PK, ForeignKey("projects.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status_after: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(120), nullable=True)
    origin_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_utc, nullable=False)

    project: Mapped[ProjectModel] = relationship()


class ContributionModel(Base):
    """Referencia agregada de contribución emitida por el sistema fuente (ADR-017).

    `amount` es un delta aditivo de unidades homogéneas del bucket (la semántica de la
    unidad la decide el emisor, p. ej. OMR). El detalle granular vive en el emisor; aquí
    solo el agregado y la referencia idempotente UNIQUE(source, source_reference).
    """

    __tablename__ = "contributions"
    __table_args__ = (
        UniqueConstraint("source", "source_reference", name="uq_contribution_source"),
        Index("ix_contributions_user_project", "user_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("support_members.user_id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        BIG_PK, ForeignKey("projects.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)  # ContributionType.value
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc, nullable=False)

    project: Mapped[ProjectModel] = relationship()
