"""Eventos de dominio de OSAP Support (arquitectura §6).

Todos los cambios de estado se derivan de eventos de pago registrados. Los eventos de
dominio representan el efecto semántico; el origen externo es un `PaymentEvent`
identificado por `(provider, provider_event_id)` (ADR-007). La clave de idempotencia
completa vive en `PaymentEvent.idempotency_key`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class MembershipDomainEventType(Enum):
    CREATED = "membership.created"
    ACTIVATED = "membership.activated"
    RENEWED = "membership.renewed"
    PAST_DUE = "membership.past_due"
    RECOVERED = "membership.recovered"
    CANCELLED = "membership.cancelled"
    EXPIRED = "membership.expired"


class DonationDomainEventType(Enum):
    RECEIVED = "donation.received"


@dataclass(frozen=True)
class DomainEvent:
    """Evento de dominio: efecto derivado de un PaymentEvent procesado."""

    event_type: MembershipDomainEventType | DonationDomainEventType
    user_id: str
    provider_event_id: str  # id del evento origen en el proveedor
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
