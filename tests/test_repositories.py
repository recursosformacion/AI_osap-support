"""Tests de repositorios de osap-support (Fase 3).

Cubren: persistencia/recuperación de cada entidad, rechazo de duplicado de
(provider, provider_event_id) (ADR-007), conservación exacta de amount_minor y currency
(V-021), y mapeo persistencia <-> dominio.
"""

from __future__ import annotations

import pytest

from domain.entities import (
    CommunicationEvent,
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    PaymentEvent,
    Periodicity,
    SupportMember,
)
from domain.exceptions import DuplicatePaymentEventError
from infrastructure.db.repositories import (
    SqlAlchemyCommunicationEventRepository,
    SqlAlchemyDonationRepository,
    SqlAlchemyMembershipRepository,
    SqlAlchemyPaymentEventRepository,
    SqlAlchemySupportMemberRepository,
)


def _member(user_id: str = "uuid-1") -> SupportMember:
    return SupportMember(user_id=user_id)


def _membership(user_id: str = "uuid-1") -> Membership:
    return Membership(
        id=None,
        user_id=user_id,
        status=MembershipStatus.ACTIVE,
        level=MembershipLevel.VOICE,
        periodicity=Periodicity.MONTHLY,
        amount_minor=1000,
        currency="EUR",
        provider="stripe",
        customer_id="cus_1",
        subscription_id="sub_1",
    )


def _donation(user_id: str = "uuid-1") -> Donation:
    return Donation(
        id=None,
        user_id=user_id,
        amount_minor=500,
        currency="EUR",
        provider="stripe",
        charge_id="ch_1",
    )


def _payment_event() -> PaymentEvent:
    return PaymentEvent(
        id=None,
        provider="stripe",
        provider_event_id="evt_1",
        event_type="payment.succeeded",
        user_id="uuid-1",
    )


def _communication() -> CommunicationEvent:
    return CommunicationEvent(
        id=None,
        user_id="uuid-1",
        template="welcome",
        recipient_email="a@b.c",
    )


def test_support_member_persist_and_retrieve(db_session) -> None:
    repo = SqlAlchemySupportMemberRepository(db_session)
    repo.add(_member())
    got = repo.get("uuid-1")
    assert got is not None
    assert got.user_id == "uuid-1"


def test_support_member_does_not_create_identity(db_session) -> None:
    from infrastructure.db.models import SupportMemberModel

    repo = SqlAlchemySupportMemberRepository(db_session)
    repo.add(_member())
    assert not hasattr(repo.get("uuid-1"), "password")
    # Idempotente: añadir de nuevo no duplica la relación
    repo.add(_member())
    assert db_session.query(SupportMemberModel).count() == 1


def test_membership_persist_and_retrieve_by_subscription(db_session) -> None:
    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    repo = SqlAlchemyMembershipRepository(db_session)
    saved = repo.add(_membership())
    got = repo.get_by_subscription("stripe", "sub_1")
    assert got is not None
    assert got.user_id == "uuid-1"
    assert got.status == MembershipStatus.ACTIVE
    assert got.level == MembershipLevel.VOICE
    assert saved.id is not None


def test_membership_preserves_amount_minor_and_currency(db_session) -> None:
    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    repo = SqlAlchemyMembershipRepository(db_session)
    repo.add(_membership())
    got = repo.get_by_subscription("stripe", "sub_1")
    assert got is not None
    assert got.amount_minor == 1000  # V-021: entero exacto
    assert isinstance(got.amount_minor, int)
    assert got.currency == "EUR"


def test_donation_persist_and_retrieve(db_session) -> None:
    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    repo = SqlAlchemyDonationRepository(db_session)
    repo.add(_donation())
    got = repo.get_by_charge("stripe", "ch_1")
    assert got is not None
    assert got.amount_minor == 500
    assert got.currency == "EUR"


def test_donation_and_membership_separate(db_session) -> None:
    # ADR-004: tablas/entidades separadas (persistencia independiente).
    from infrastructure.db.models import DonationModel, MembershipModel

    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    SqlAlchemyMembershipRepository(db_session).add(_membership())
    SqlAlchemyDonationRepository(db_session).add(_donation())
    assert db_session.query(MembershipModel).count() == 1
    assert db_session.query(DonationModel).count() == 1


def test_payment_event_persist_and_idempotency(db_session) -> None:
    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    repo = SqlAlchemyPaymentEventRepository(db_session)
    saved = repo.add(_payment_event())
    assert saved.id is not None
    got = repo.get_by_idempotency_key("stripe", "evt_1")
    assert got is not None
    assert got.event_type == "payment.succeeded"


def test_payment_event_rejects_duplicate(db_session) -> None:
    repo = SqlAlchemyPaymentEventRepository(db_session)
    repo.add(_payment_event())
    with pytest.raises(DuplicatePaymentEventError):
        repo.add(_payment_event())  # (stripe, evt_1) ya existe → ADR-007


def test_communication_event_persist_and_retrieve(db_session) -> None:
    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    repo = SqlAlchemyCommunicationEventRepository(db_session)
    saved = repo.add(_communication())
    got = repo.get(saved.id)
    assert got is not None
    assert got.template == "welcome"
    assert got.status.value == "pending"
    assert got.attempts == 0


def test_mapping_roundtrip_domain(db_session) -> None:
    # Mapeo persistencia -> dominio sin perder campos (fechas incluidas).
    # Nota: SQLite (test) almacena datetime naive; MariaDB (prod) conserva la fecha.
    from datetime import UTC, datetime

    member_repo = SqlAlchemySupportMemberRepository(db_session)
    member_repo.add(_member())
    repo = SqlAlchemyMembershipRepository(db_session)
    m = _membership()
    m.started_at = datetime(2026, 1, 1, tzinfo=UTC)
    repo.add(m)
    got = repo.get_by_subscription("stripe", "sub_1")
    assert got is not None
    # Se conserva la fecha; el tz se normaliza a naive en SQLite (solo tests).
    assert got.started_at.year == 2026
    assert got.started_at.month == 1
    assert got.started_at.day == 1
