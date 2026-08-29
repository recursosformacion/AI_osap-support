"""Tests del dominio de OSAP Support (Fase 2).

Cubren entidades, dinero en unidades mínimas (V-021), idempotencia (ADR-007),
Membership/Donation separados (ADR-004) y SupportMember como relación (ADR-002).
"""

from __future__ import annotations

import pytest

from domain.entities import (
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    Money,
    PaymentEvent,
    PaymentEventStatus,
    Periodicity,
    SupportMember,
)


def _membership(**overrides: object) -> Membership:
    base: dict[str, object] = {
        "id": None,
        "user_id": "uuid-1",
        "status": MembershipStatus.PENDING,
        "level": MembershipLevel.SUPPORTER,
        "periodicity": Periodicity.MONTHLY,
        "amount_minor": 1000,
        "currency": "EUR",
        "provider": "stripe",
        "customer_id": "cus_1",
        "subscription_id": "sub_1",
    }
    base.update(overrides)
    return Membership(**base)


def test_money_minor_units_rejects_float() -> None:
    with pytest.raises(ValueError):
        Money(amount_minor=10.5, currency="EUR")  # type: ignore[arg-type]


def test_money_minor_units_accepts_int_and_iso_currency() -> None:
    m = Money(amount_minor=1000, currency="EUR")
    assert m.amount_minor == 1000
    assert m.currency == "EUR"


def test_support_member_is_relationship_not_identity() -> None:
    # ADR-002: SupportMember referencia Auth.user_id; no tiene credenciales.
    member = SupportMember(user_id="uuid-1")
    assert member.user_id == "uuid-1"
    assert not hasattr(member, "password")
    assert not hasattr(member, "email_password")


def test_membership_and_donation_are_separate_entities() -> None:
    # ADR-004: recurrent vs one-off. No existe SupportContribution.
    membership = _membership()
    donation = Donation(
        id=None,
        user_id="uuid-1",
        amount_minor=500,
        currency="EUR",
        provider="stripe",
        charge_id="ch_1",
    )
    assert isinstance(membership, Membership)
    assert isinstance(donation, Donation)
    assert membership.periodicity == Periodicity.MONTHLY
    assert donation.charge_id == "ch_1"


def test_payment_event_idempotency_key() -> None:
    # ADR-007: UNIQUE(provider, provider_event_id).
    ev = PaymentEvent(
        id=None, provider="stripe", provider_event_id="evt_1", event_type="payment.succeeded"
    )
    assert ev.idempotency_key == ("stripe", "evt_1")
    assert ev.status == PaymentEventStatus.PROCESSED
