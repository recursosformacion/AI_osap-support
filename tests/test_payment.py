"""Tests del PaymentProvider (Fase 4).

Cubren: contrato implementable por fake, independencia del dominio/aplicación del
proveedor concreto (ADR-005), checkout vía fake (membership y donation, ADR-004),
dinero en unidades mínimas (V-021), y preservación de (provider, provider_event_id)
(ADR-007).
"""

from __future__ import annotations

from application.use_cases.checkout_donation import CheckoutDonationUseCase
from application.use_cases.checkout_membership import CheckoutMembershipUseCase
from domain.ports.payment import PaymentMode
from infrastructure.payment.fake_payment_provider import FakePaymentProvider


def _fake() -> FakePaymentProvider:
    return FakePaymentProvider()


def test_fake_implements_payment_provider_contract() -> None:
    provider = _fake()
    session = provider.create_checkout(
        user_id="uuid-1",
        mode=PaymentMode.DONATION,
        amount_minor=1000,
        currency="EUR",
        return_url="https://osap-app/return",
    )
    assert session.mode == PaymentMode.DONATION
    assert session.checkout_url.startswith("https://fake-pay/")
    assert session.money.amount_minor == 1000
    assert session.money.currency == "EUR"


def test_application_depends_on_port_not_provider() -> None:
    # Los casos de uso reciben el port; no conocen al proveedor concreto.
    provider = _fake()
    use_case = CheckoutMembershipUseCase(provider)
    session = use_case.execute(
        user_id="uuid-1",
        level="supporter",
        periodicity="monthly",
        return_url="https://osap-app/return",
    )
    assert session.mode == PaymentMode.MEMBERSHIP
    assert session.checkout_url.startswith("https://fake-pay/")

    donation = CheckoutDonationUseCase(provider).execute(
        user_id="uuid-1", amount_minor=500, currency="EUR", return_url="/return"
    )
    assert donation.amount_minor == 500


def test_membership_and_donation_checkouts_are_distinct() -> None:
    # ADR-004: membership (recurrente) y donation (puntual) usan modos distintos.
    provider = _fake()
    membership = CheckoutMembershipUseCase(provider).execute(
        user_id="uuid-1", level="contributor", periodicity="yearly", return_url="/return"
    )
    donation = CheckoutDonationUseCase(provider).execute(
        user_id="uuid-1", amount_minor=500, currency="EUR", return_url="/return"
    )
    assert membership.mode == PaymentMode.MEMBERSHIP
    assert donation.mode == PaymentMode.DONATION
    assert "/contributor/yearly" in membership.checkout_url


def test_resolve_customer_is_stable() -> None:
    provider = _fake()
    assert provider.resolve_customer(user_id="uuid-1") == "cus-uuid-1"
    assert provider.resolve_customer(user_id="uuid-1") == "cus-uuid-1"


def test_get_subscription_returns_reference() -> None:
    provider = _fake()
    ref = provider.get_subscription(subscription_id="sub_1")
    assert ref.subscription_id == "sub_1"
    assert ref.provider == "fake"


def test_money_stays_integer_minor_units() -> None:
    provider = _fake()
    session = provider.create_checkout(
        user_id="uuid-1",
        mode=PaymentMode.DONATION,
        amount_minor=1050,
        currency="EUR",
        return_url="/return",
    )
    assert isinstance(session.amount_minor, int)
    assert not isinstance(session.amount_minor, float)
    assert session.amount_minor == 1050  # 10,50 EUR en céntimos


def test_webhook_parse_preserves_idempotency_key() -> None:
    provider = _fake()
    payload = {"id": "evt_1", "type": "payment.succeeded", "user_id": "uuid-1"}
    event = provider.parse_webhook(payload)
    assert event.idempotency_key == ("fake", "evt_1")
    assert event.event_type == "payment.succeeded"
    assert event.user_id == "uuid-1"
