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


# --- Reconocimientos y contribuciones (ADR-015/016/017, Fase 3) ----------------


class RecognitionType(Enum):
    SUPPORTER = "supporter"
    CONTRIBUTOR = "contributor"
    VOICE = "voice"
    FOUNDER = "founder"


class RecognitionKind(Enum):
    HISTORICAL = "historical"
    DERIVED = "derived"
    GRANTED = "granted"


class RecognitionStatus(Enum):
    ACTIVE = "active"  # vigente: se muestra (en público solo con consentimiento)
    INACTIVE = "inactive"  # histórico: permanece en auditoría, no se muestra


class RecognitionEventType(Enum):
    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    GRANTED = "granted"
    REVOKED = "revoked"
    CONSENT_GRANTED = "consent_granted"
    CONSENT_REVOKED = "consent_revoked"
    UPDATED = "updated"


class ContributionType(Enum):
    CONTENT = "content"
    REVIEW = "review"
    TRANSLATION = "translation"
    DEVELOPMENT = "development"
    DOCUMENTATION = "documentation"
    COMMUNITY = "community"
    PROMOTION = "promotion"
    OTHER = "other"


@dataclass
class Project:
    """Registro whitelisted de un proyecto del ecosistema (ADR-015).

    `slug` es el identificador canónico y no puede ser vacío. El proyecto `ecosystem`
    es el ámbito de los reconocimientos derivados de la relación económica global.
    """

    slug: str
    name: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.slug or not self.slug.strip():
            raise ValueError("slug no puede ser vacío")
        if not self.name or not self.name.strip():
            raise ValueError("name no puede ser vacío")


@dataclass
class Recognition:
    """Proyección de estado VIGENTE de un reconocimiento (ADR-015).

    Semántica de la pareja estado/histórico:
    - `Recognition` representa SOLO el estado actual (ACTIVE/INACTIVE); el historial
      inmutable vive en `RecognitionEvent`.
    - `status=INACTIVE` significa "no vigente en este momento" (histórico a efectos de
      ADR-016): permanece en la proyección y en auditoría, pero no se muestra.
    - FOUNDER (kind=HISTORICAL, active_until=None) NO es contradictorio: es un
      reconocimiento de origen histórico/criterio congelado que permanece
      **permanentemente vigente** (status=ACTIVE) como sello histórico. "Histórico" se
      refiere a su origen (criterion), no a que esté inactivo.

    Invariantes:
    - kind=GRANTED exige `granted_by`; kind=HISTORICAL/DERIVED no lo admite (el origen
      se documenta en `origin`: criterio o regla).
    - `public` y `public_revoked_at` son incompatibles (revocado => no público).
    - `is_publicly_visible` exige status=ACTIVE y consentimiento: el consentimiento
      previo no hace visible un reconocimiento no vigente.
    """

    id: int | None
    user_id: str
    project_slug: str
    recognition_type: RecognitionType
    kind: RecognitionKind
    status: RecognitionStatus
    granted_at: datetime
    granted_by: str | None = None
    origin: str | None = None
    reason: str | None = None
    active_until: datetime | None = None
    public: bool = False
    public_since: datetime | None = None
    public_revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def is_publicly_visible(self) -> bool:
        return self.status is RecognitionStatus.ACTIVE and self.public

    def __post_init__(self) -> None:
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id no puede ser vacío")
        if not self.project_slug or not self.project_slug.strip():
            raise ValueError("project_slug no puede ser vacío")
        if not isinstance(self.recognition_type, RecognitionType):
            raise TypeError("recognition_type debe ser RecognitionType")
        if not isinstance(self.kind, RecognitionKind):
            raise TypeError("kind debe ser RecognitionKind")
        if not isinstance(self.status, RecognitionStatus):
            raise TypeError("status debe ser RecognitionStatus")
        if self.kind is RecognitionKind.GRANTED:
            if not self.granted_by:
                raise ValueError("kind=GRANTED requiere granted_by")
        elif self.granted_by is not None:
            raise ValueError("granted_by solo aplica a kind=GRANTED")
        if self.public and self.public_revoked_at is not None:
            raise ValueError("public y public_revoked_at son incompatibles")


@dataclass
class RecognitionEvent:
    """Historial inmutable de un cambio de reconocimiento (ADR-016).

    Registra activaciones/desactivaciones (SUPPORTER derivado), concesiones/revocaciones
    (granted) y cambios de consentimiento. Complementa a `Recognition`: responde "por qué
    y cuándo" sin contaminar el estado vigente.
    """

    id: int | None
    user_id: str
    project_slug: str
    recognition_type: RecognitionType
    event_type: RecognitionEventType
    status_after: RecognitionStatus
    reason: str | None = None
    origin: str | None = None
    origin_ref: str | None = None
    granted_by: str | None = None
    occurred_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id no puede ser vacío")
        if not self.project_slug or not self.project_slug.strip():
            raise ValueError("project_slug no puede ser vacío")
        if not isinstance(self.recognition_type, RecognitionType):
            raise TypeError("recognition_type debe ser RecognitionType")
        if not isinstance(self.event_type, RecognitionEventType):
            raise TypeError("event_type debe ser RecognitionEventType")
        if not isinstance(self.status_after, RecognitionStatus):
            raise TypeError("status_after debe ser RecognitionStatus")


@dataclass
class Contribution:
    """Referencia agregada de contribución emitida por el sistema fuente (ADR-017).

    `amount` es un delta ADITIVO de unidades homogéneas del bucket; la semántica de la
    unidad la decide el emisor (p. ej. OMR: obras revisadas). Support no la interpreta y
    nunca confía en un total acumulado enviado por el emisor: el acumulado se calcula
    desde los deltas.
    """

    id: int | None
    user_id: str
    project_slug: str
    contribution_type: ContributionType
    summary: str
    source: str
    source_reference: str
    amount: int | None = None
    created_at: datetime = field(default_factory=utc_now)

    @property
    def idempotency_key(self) -> tuple[str, str]:
        """Clave de idempotencia: UNIQUE(source, source_reference) (ADR-017)."""
        return (self.source, self.source_reference)

    def __post_init__(self) -> None:
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id no puede ser vacío")
        if not self.project_slug or not self.project_slug.strip():
            raise ValueError("project_slug no puede ser vacío")
        if not isinstance(self.contribution_type, ContributionType):
            raise TypeError("contribution_type debe ser ContributionType")
        if not self.summary or not self.summary.strip():
            raise ValueError("summary no puede ser vacío")
        if not self.source or not self.source.strip():
            raise ValueError("source no puede ser vacío")
        if not self.source_reference or not self.source_reference.strip():
            raise ValueError("source_reference no puede ser vacío")
        if self.amount is not None and (
            isinstance(self.amount, bool) or not isinstance(self.amount, int) or self.amount < 0
        ):
            raise ValueError("amount debe ser un entero >= 0 o None")
