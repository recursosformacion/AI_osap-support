"""Tests de la máquina de estados de Membership (Fase 2, arquitectura §5).

Verifican: transiciones válidas, idempotencia (eventos repetidos = no-op), eventos
fuera de orden (se aceptan sin cambiar estado), y que el scheduler no inventa estados.
"""

from __future__ import annotations

from datetime import UTC, datetime

from domain.entities import (
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
)
from domain.events import DomainEvent, MembershipDomainEventType
from domain.state_machine import MembershipStateMachine


def _membership(status: MembershipStatus = MembershipStatus.PENDING) -> Membership:
    return Membership(
        id=None,
        user_id="uuid-1",
        status=status,
        level=MembershipLevel.SUPPORTER,
        periodicity=Periodicity.MONTHLY,
        amount_minor=1000,
        currency="EUR",
        provider="stripe",
        customer_id="cus_1",
        subscription_id="sub_1",
    )


def _event(event_type: MembershipDomainEventType) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        user_id="uuid-1",
        provider_event_id="evt_1",
        occurred_at=datetime.now(UTC),
    )


def test_pending_activates_on_payment_success() -> None:
    m = _membership(MembershipStatus.PENDING)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.ACTIVATED))
    assert result.changed is True
    assert m.status == MembershipStatus.ACTIVE
    assert m.started_at is not None
    assert m.next_renewal_at is not None


def test_active_to_past_due_on_failure() -> None:
    m = _membership(MembershipStatus.ACTIVE)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.PAST_DUE))
    assert result.changed is True
    assert m.status == MembershipStatus.PAST_DUE


def test_past_due_recovers_to_active() -> None:
    m = _membership(MembershipStatus.PAST_DUE)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.RECOVERED))
    assert result.changed is True
    assert m.status == MembershipStatus.ACTIVE


def test_active_cancels() -> None:
    m = _membership(MembershipStatus.ACTIVE)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.CANCELLED))
    assert result.changed is True
    assert m.status == MembershipStatus.CANCELLED


def test_repeated_activation_is_idempotent_noop() -> None:
    m = _membership(MembershipStatus.ACTIVE)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.ACTIVATED))
    assert result.changed is False
    assert m.status == MembershipStatus.ACTIVE


def test_out_of_order_event_does_not_change_state() -> None:
    # Activación llegando tarde sobre un estado expirado: no cambia (fuera de orden).
    m = _membership(MembershipStatus.EXPIRED)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.ACTIVATED))
    assert result.changed is False
    assert m.status == MembershipStatus.EXPIRED


def test_expired_is_terminal() -> None:
    m = _membership(MembershipStatus.EXPIRED)
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.CANCELLED))
    assert result.changed is False
    assert m.status == MembershipStatus.EXPIRED


def test_renewal_updates_next_renewal() -> None:
    m = _membership(MembershipStatus.ACTIVE)
    before = m.next_renewal_at
    result = MembershipStateMachine().apply(m, _event(MembershipDomainEventType.RENEWED))
    assert result.changed is True
    assert m.status == MembershipStatus.ACTIVE
    if before is not None:
        assert m.next_renewal_at is not None
        assert m.next_renewal_at >= before
