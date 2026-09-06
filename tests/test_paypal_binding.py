"""Tests del binding PayPal (bloque E2E): plan_id→level/periodicity, fallback por
subscription_id, fechas reales y vida activa (renovación/recuperación/idempotencia).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from application.use_cases.process_payment_webhook import ProcessPaymentWebhookUseCase
from domain.entities import (
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
    SupportMember,
)
from domain.ports.payment import PaymentProviderEvent
from infrastructure.db.models import Base
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.repositories.donation_repository import SqlAlchemyDonationRepository
from infrastructure.db.repositories.membership_repository import SqlAlchemyMembershipRepository
from infrastructure.db.repositories.payment_event_repository import SqlAlchemyPaymentEventRepository
from infrastructure.db.repositories.support_member_repository import (
    SqlAlchemySupportMemberRepository,
)
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.payment.fake_payment_provider import FakePaymentProvider
from infrastructure.payment.paypal_payment_provider import PayPalPaymentProvider

PLAN_MONTHLY = "P-SUPPORTER-MONTHLY"
USER = "uuid-paypal-1"
SUB_ID = "I-SUB-PAYPAL-1"


def _engine() -> Any:
    return create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


@pytest.fixture
def uc() -> Iterator[tuple[ProcessPaymentWebhookUseCase, Session]]:
    engine = _engine()
    Base.metadata.create_all(engine)
    session = Session(engine)
    uc = ProcessPaymentWebhookUseCase(
        provider=FakePaymentProvider(),
        payment_events=SqlAlchemyPaymentEventRepository(session),
        memberships=SqlAlchemyMembershipRepository(session),
        donations=SqlAlchemyDonationRepository(session),
        communications=SqlAlchemyCommunicationEventRepository(session),
        support_members=SqlAlchemySupportMemberRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    yield uc, session
    session.close()
    engine.dispose()


def _event(
    event_id: str,
    *,
    event_type: str = "payment.succeeded",
    user_id: str | None = None,
    **metadata: object,
) -> PaymentProviderEvent:
    return PaymentProviderEvent(
        provider="paypal",
        provider_event_id=event_id,
        event_type=event_type,
        user_id=user_id,
        received_at=datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC),
        metadata=metadata,
    )


def _pending_membership(session: Session) -> Membership:
    member_repo = SqlAlchemySupportMemberRepository(session)
    member_repo.add(SupportMember(user_id=USER))
    membership = Membership(
        id=None,
        user_id=USER,
        status=MembershipStatus.PENDING,
        level=MembershipLevel.SUPPORTER,
        periodicity=Periodicity.MONTHLY,
        amount_minor=0,
        currency="EUR",
        provider="fake",
        customer_id="",
        subscription_id=SUB_ID,
    )
    SqlAlchemyMembershipRepository(session).add(membership)
    session.commit()
    return membership


# --- provider: plan_id → level/periodicity -------------------------------------


def test_paypal_parse_maps_plan_and_dates() -> None:
    provider = PayPalPaymentProvider(
        mode="sandbox",
        client_id="x",
        client_secret="y",
        plan_ids={("supporter", "monthly"): PLAN_MONTHLY},
    )
    payload = {
        "id": "evt-plan",
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": SUB_ID,
            "plan_id": PLAN_MONTHLY,
            "status": "ACTIVE",
            "start_time": "2026-09-06T10:00:00Z",
            "billing_info": {"next_billing_time": "2026-10-06T10:00:00Z"},
        },
    }
    event = provider.parse_webhook(payload)
    assert event.metadata["plan_id"] == PLAN_MONTHLY
    assert event.metadata["level"] == "supporter"
    assert event.metadata["periodicity"] == "monthly"
    assert event.metadata["subscription_id"] == SUB_ID
    assert event.metadata["start_time"] == "2026-09-06T10:00:00Z"
    assert event.metadata["next_billing_time"] == "2026-10-06T10:00:00Z"


# --- binding: fallback por subscription_id sin custom_id ------------------------


def test_activation_binds_pending_by_subscription_without_custom_id(uc) -> None:
    use_case, session = uc
    _pending_membership(session)

    result = use_case.execute(
        {
            "id": "evt-1",
            "type": "payment.succeeded",
            "user_id": None,
            "metadata": {
                "subscription_id": SUB_ID,
                "next_billing_time": "2026-10-06T10:00:00Z",
            },
        }
    )
    assert result.outcome == "processed"
    memberships = SqlAlchemyMembershipRepository(session).list_by_user(USER)
    assert memberships[0].status is MembershipStatus.ACTIVE
    assert memberships[0].subscription_id == SUB_ID
    # Fecha real de PayPal (next_billing_time) preservada por la máquina.
    assert memberships[0].next_renewal_at == datetime(2026, 10, 6, 10, 0, 0)


def test_duplicate_webhook_is_idempotent_and_keeps_one_payment_event(uc) -> None:
    from sqlalchemy import text

    use_case, session = uc
    _pending_membership(session)
    payload = {
        "id": "evt-dup",
        "type": "payment.succeeded",
        "user_id": None,
        "metadata": {"subscription_id": SUB_ID},
    }
    first = use_case.execute(payload)
    second = use_case.execute(payload)
    assert first.outcome == "processed"
    assert second.outcome == "ignored_duplicate"
    count = session.execute(
        text("SELECT COUNT(*) FROM payment_events WHERE provider_event_id='evt-dup'")
    ).scalar_one()
    assert count == 1
    memberships = SqlAlchemyMembershipRepository(session).list_by_user(USER)
    assert memberships[0].status is MembershipStatus.ACTIVE


def test_recovery_from_past_due_on_successful_payment(uc) -> None:
    use_case, session = uc
    membership = _pending_membership(session)
    repo = SqlAlchemyMembershipRepository(session)
    membership.status = MembershipStatus.PAST_DUE
    repo.add(membership)
    session.commit()

    result = use_case.execute(
        {
            "id": "evt-pay",
            "type": "payment.succeeded",
            "user_id": None,
            "metadata": {"subscription_id": SUB_ID},
        }
    )
    assert result.outcome == "processed"
    memberships = SqlAlchemyMembershipRepository(session).list_by_user(USER)
    assert memberships[0].status is MembershipStatus.ACTIVE


def test_renewal_on_active_refreshes_next_billing_time(uc) -> None:
    use_case, session = uc
    membership = _pending_membership(session)
    repo = SqlAlchemyMembershipRepository(session)
    membership.status = MembershipStatus.ACTIVE
    membership.started_at = datetime(2026, 8, 6, 10, 0, 0)
    repo.add(membership)
    session.commit()

    result = use_case.execute(
        {
            "id": "evt-renew",
            "type": "payment.succeeded",
            "user_id": None,
            "metadata": {
                "subscription_id": SUB_ID,
                "next_billing_time": "2026-11-06T10:00:00Z",
            },
        }
    )
    assert result.outcome == "processed"
    memberships = SqlAlchemyMembershipRepository(session).list_by_user(USER)
    assert memberships[0].status is MembershipStatus.ACTIVE
    assert memberships[0].next_renewal_at == datetime(2026, 11, 6, 10, 0, 0)
    assert memberships[0].renewed_at is not None
