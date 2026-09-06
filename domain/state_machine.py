"""Máquina de estados de Membership (arquitectura §5).

Diseñada a partir de los eventos reales:
- Cada transición es idempotente (si llega dos veces, no-op).
- Los eventos fuera de orden se "aceptan": se registran (auditoría) pero no cambian el
  estado si la transición no es válida desde el estado actual.
- El scheduler solo dispara comprobaciones (expiry); nunca inventa estados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .entities import Membership, MembershipStatus
from .events import DomainEvent, MembershipDomainEventType

# Eventos que disparan transiciones.
_PAYMENT_SUCCESS = MembershipDomainEventType.ACTIVATED
_PAYMENT_FAILURE = MembershipDomainEventType.PAST_DUE
_RENEWED = MembershipDomainEventType.RENEWED
_RECOVERED = MembershipDomainEventType.RECOVERED
_CANCELLED = MembershipDomainEventType.CANCELLED
_EXPIRED = MembershipDomainEventType.EXPIRED


@dataclass(frozen=True)
class TransitionResult:
    """Resultado de aplicar un evento a la máquina de estados."""

    new_status: MembershipStatus | None
    changed: bool
    note: str = ""


class MembershipStateMachine:
    """Valida y aplica transiciones de estado sobre una Membership."""

    # Transiciones válidas por estado actual.
    _ALLOWED: dict[MembershipStatus, set[MembershipDomainEventType]] = {
        MembershipStatus.PENDING: {_PAYMENT_SUCCESS},
        MembershipStatus.ACTIVE: {_RENEWED, _PAYMENT_FAILURE, _CANCELLED, _EXPIRED},
        MembershipStatus.PAST_DUE: {_RECOVERED, _CANCELLED, _EXPIRED},
        MembershipStatus.CANCELLED: set(),
        MembershipStatus.EXPIRED: set(),
    }

    def apply(self, membership: Membership, event: DomainEvent) -> TransitionResult:
        """Aplica un evento de dominio sobre la membresía.

        Idempotente: si el evento ya produjo el estado, no-op. Fuera de orden: si la
        transición no es válida desde el estado actual, no cambia el estado (el evento
        ya quedó registrado a nivel de PaymentEvent para auditoría).
        """
        event_type = event.event_type
        if not isinstance(event_type, MembershipDomainEventType):
            return TransitionResult(membership.status, False, "evento no de membresía")

        current = membership.status
        allowed = self._ALLOWED.get(current, set())

        # Renovación: válida sobre active, actualiza fechas (active→active, §6).
        # La fecha real de PayPal (next_renewal_at ya fijado por el UC) tiene prioridad.
        if event_type == _RENEWED and current == MembershipStatus.ACTIVE:
            membership.status = MembershipStatus.ACTIVE
            membership.renewed_at = event.occurred_at
            if membership.next_renewal_at is None:
                membership.next_renewal_at = self._next_renewal(membership)
            return TransitionResult(MembershipStatus.ACTIVE, True, "renovada")

        # Eventos que solo son válidos si ya reflejan el estado (idempotencia):
        if event_type == _PAYMENT_SUCCESS and current == MembershipStatus.ACTIVE:
            return TransitionResult(current, False, "ya active (idempotente)")
        if event_type == _RECOVERED and current == MembershipStatus.ACTIVE:
            return TransitionResult(current, False, "ya active (idempotente)")

        if event_type not in allowed:
            msg = f"transición no permitida desde {current.value}"
            return TransitionResult(current, False, msg)

        # Aplicar transición según evento.
        if event_type == _PAYMENT_SUCCESS:
            membership.status = MembershipStatus.ACTIVE
            if membership.started_at is None:
                membership.started_at = event.occurred_at
            if membership.next_renewal_at is None:
                membership.next_renewal_at = self._next_renewal(membership)
            return TransitionResult(MembershipStatus.ACTIVE, True, "activada")

        if event_type == _PAYMENT_FAILURE:
            membership.status = MembershipStatus.PAST_DUE
            return TransitionResult(MembershipStatus.PAST_DUE, True, "pago fallido")

        if event_type == _RECOVERED:
            membership.status = MembershipStatus.ACTIVE
            membership.renewed_at = event.occurred_at
            if membership.next_renewal_at is None:
                membership.next_renewal_at = self._next_renewal(membership)
            return TransitionResult(MembershipStatus.ACTIVE, True, "recuperada")

        if event_type == _CANCELLED:
            membership.status = MembershipStatus.CANCELLED
            membership.cancelled_at = event.occurred_at
            return TransitionResult(MembershipStatus.CANCELLED, True, "cancelada")

        if event_type == _EXPIRED:
            membership.status = MembershipStatus.EXPIRED
            membership.expires_at = event.occurred_at
            return TransitionResult(MembershipStatus.EXPIRED, True, "expirada")

        return TransitionResult(current, False, "sin efecto")

    @staticmethod
    def _next_renewal(membership: Membership) -> datetime:
        """Próxima renovación según periodicidad (scheduler la usará)."""
        base = membership.renewed_at or membership.started_at or membership.created_at
        is_yearly = membership.periodicity.value == "yearly"
        delta = timedelta(days=365) if is_yearly else timedelta(days=30)
        return base + delta
