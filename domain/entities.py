"""Entidades del dominio de OSAP Support (arquitectura §3-§4).

- ADR-002: SupportMember referencia `Auth.user_id` (== JWT.sub). No es una identidad.
- ADR-004: Membership (recurrente) y Donation (puntual) son entidades SEPARADAS.
- ADR-007: PaymentEvent tiene clave de idempotencia (provider, provider_event_id).
- V-021: los importes se almacenan en unidades mínimas enteras (amount_minor), nunca float.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class MembershipStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class MembershipLevel(Enum):
    SUPPORTER = "supporter"
    CONTRIBUTOR = "contributor"
    VOICE = "voice"
    FOUNDER = "founder"


class Periodicity(Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class PaymentEventStatus(Enum):
    PROCESSED = "processed"
    IGNORED_DUPLICATE = "ignored_duplicate"
    ERROR = "error"


class CommunicationEventStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Money:
    """Importe en unidades mínimas enteras (V-021). Nunca float (V-020)."""

    amount_minor: int
    currency: str  # ISO 4217

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise ValueError("amount_minor debe ser un entero (unidades mínimas)")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("currency debe ser ISO 4217 (3 caracteres)")


@dataclass
class SupportMember:
    """Relación de apoyo de una identidad OSAP (ADR-002). No es una identidad de usuario."""

    user_id: str  # == Auth.user_id == JWT.sub
    created_at: datetime = field(default_factory=utc_now)
    data_version: int = 0


@dataclass
class Membership:
    """Relación recurrente (suscripción) entre SupportMember y el proyecto."""

    id: int | None  # id interno (autoincremental en BD)
    user_id: str
    status: MembershipStatus
    level: MembershipLevel
    periodicity: Periodicity
    amount_minor: int
    currency: str
    provider: str
    customer_id: str
    subscription_id: str
    started_at: datetime | None = None
    renewed_at: datetime | None = None
    next_renewal_at: datetime | None = None
    cancelled_at: datetime | None = None
    expires_at: datetime | None = None
    email_contact: str = ""
    is_founder: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def money(self) -> Money:
        return Money(amount_minor=self.amount_minor, currency=self.currency)


@dataclass
class Donation:
    """Aportación puntual (no recurrente). ADR-004: separada de Membership."""

    id: int | None
    user_id: str
    amount_minor: int
    currency: str
    provider: str
    charge_id: str
    receipt_id: str | None = None
    email_receipt: str = ""
    donated_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)

    @property
    def money(self) -> Money:
        return Money(amount_minor=self.amount_minor, currency=self.currency)


@dataclass
class PaymentEvent:
    """Evento del proveedor de pagos; registro idempotente (ADR-007)."""

    id: int | None
    provider: str
    provider_event_id: str
    event_type: str  # subscription.created, payment.succeeded, ...
    user_id: str | None = None
    payload_hash: str = ""
    status: PaymentEventStatus = PaymentEventStatus.PROCESSED
    received_at: datetime = field(default_factory=utc_now)
    processed_at: datetime | None = None

    @property
    def idempotency_key(self) -> tuple[str, str]:
        """Clave de idempotencia: UNIQUE(provider, provider_event_id)."""
        return (self.provider, self.provider_event_id)


@dataclass
class CommunicationEvent:
    """Registro de email de la relación económica (ADR-006, flujo con worker)."""

    id: int | None
    user_id: str
    template: str
    recipient_email: str
    status: CommunicationEventStatus = CommunicationEventStatus.PENDING
    attempts: int = 0
    next_attempt_at: datetime | None = None
    origin_event_id: int | None = None  # FK -> PaymentEvent
    created_at: datetime = field(default_factory=utc_now)
    sent_at: datetime | None = None
    last_error: str | None = None
