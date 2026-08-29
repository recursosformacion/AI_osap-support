"""Modelos de persistencia de osap-support (SQLAlchemy).

Separación hexagonal: estos son SOLO modelos de persistencia. No son el dominio.
El mapeo persistencia <-> dominio se realiza en `infrastructure/db/repositories/`.

Reglas aplicadas:
- ADR-003: solo tablas de osap_support.
- ADR-002: no existe tabla de usuarios/identidad local; `user_id` es referencia externa (JWT.sub).
- ADR-004: membership y donation son tablas separadas.
- ADR-007: UNIQUE(provider, provider_event_id) en payment_events.
- V-021: importes como enteros (amount_minor) + currency ISO 4217.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
