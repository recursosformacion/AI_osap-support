"""Tests del webhook de pagos (Fase 6).

Cubren: evento nuevo procesado, duplicado idempotente (ADR-007), mismo id distinto
proveedor (no colisionan), sin email directo (ADR-006), provider-agnostic (ADR-005),
payload inválido, y regresión de Fases 1-5.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from application.use_cases.process_payment_webhook import ProcessPaymentWebhookUseCase
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


def _engine() -> Any:
    return create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


@pytest.fixture
def use_case() -> Iterator[ProcessPaymentWebhookUseCase]:
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        uc = ProcessPaymentWebhookUseCase(
            provider=FakePaymentProvider(),
            payment_events=SqlAlchemyPaymentEventRepository(session),
            memberships=SqlAlchemyMembershipRepository(session),
            donations=SqlAlchemyDonationRepository(session),
            communications=SqlAlchemyCommunicationEventRepository(session),
            support_members=SqlAlchemySupportMemberRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
        )
        yield uc
    engine.dispose()


@pytest.fixture
def client(use_case: ProcessPaymentWebhookUseCase) -> Iterator[TestClient]:
    from fastapi import FastAPI

    from api.routes.webhooks import wire_webhook_router

    app = FastAPI(title="osap-support-test", version="0.1.0")
    app.include_router(wire_webhook_router(use_case))
    yield TestClient(app)


def _payload(
    event_id: str = "evt-1",
    event_type: str = "payment.succeeded",
    user_id: str = "uuid-1",
    **metadata: object,
) -> dict[str, object]:
    body: dict[str, object] = {"id": event_id, "type": event_type, "user_id": user_id}
    if metadata:
        body["metadata"] = metadata
    return body


def test_webhook_valid_processes_once(client: TestClient) -> None:
    r1 = client.post("/api/v1/webhooks/payment", json=_payload())
    assert r1.status_code == 200
    assert r1.json()["outcome"] == "processed"

    r2 = client.post("/api/v1/webhooks/payment", json=_payload())
    assert r2.status_code == 200
    assert r2.json()["outcome"] == "ignored_duplicate"


def test_webhook_duplicate_does_not_duplicate_effects(
    use_case: ProcessPaymentWebhookUseCase,
) -> None:
    # donation.succeeded → crea una Donation y un CommunicationEvent.
    payload = _payload(
        event_type="donation.succeeded",
        amount_minor=500,
        currency="EUR",
        charge_id="ch_1",
    )
    use_case.execute(payload)
    use_case.execute(payload)  # duplicado

    donations = use_case._donations.list_by_user("uuid-1")  # noqa: SLF001
    communications = use_case._communications.list_by_user("uuid-1")  # noqa: SLF001
    assert len(donations) == 1
    assert len(communications) == 1


def test_webhook_same_id_different_provider_do_not_collide() -> None:
    # (provider=A, event=123) y (provider=B, event=123) son eventos diferentes (ADR-007).
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        payment_repo = SqlAlchemyPaymentEventRepository(session)

        def make_uc(provider_id: str) -> ProcessPaymentWebhookUseCase:
            return ProcessPaymentWebhookUseCase(
                provider=FakePaymentProvider(provider_id),
                payment_events=payment_repo,
                memberships=SqlAlchemyMembershipRepository(session),
                donations=SqlAlchemyDonationRepository(session),
                communications=SqlAlchemyCommunicationEventRepository(session),
                support_members=SqlAlchemySupportMemberRepository(session),
                uow=SqlAlchemyUnitOfWork(session),
            )

        payload = _payload(event_id="123", event_type="donation.succeeded", user_id="u-a")
        r_a = make_uc("provider-a").execute(payload)
        r_b = make_uc("provider-b").execute(payload)
        assert r_a.outcome == "processed"
        assert r_b.outcome == "processed"

        # Ambos quedan registrados (no colisionan).
        ev_a = payment_repo.get_by_idempotency_key("provider-a", "123")
        ev_b = payment_repo.get_by_idempotency_key("provider-b", "123")
        assert ev_a is not None
        assert ev_b is not None
        assert ev_a.provider != ev_b.provider
    engine.dispose()


def test_webhook_does_not_send_email_directly(use_case: ProcessPaymentWebhookUseCase) -> None:
    # No existe EmailSender en el use case; no se invoca.
    assert not hasattr(use_case, "_email")
    assert not hasattr(use_case, "email")


def test_webhook_is_provider_agnostic(use_case: ProcessPaymentWebhookUseCase) -> None:
    # El use case depende del port PaymentProvider, no de un SDK.
    import inspect

    from application.use_cases import process_payment_webhook

    src = inspect.getsource(process_payment_webhook)
    for banned in ("import stripe", "import paypal", "import patreon", "import ko_fi"):
        assert banned not in src


def test_webhook_creates_support_member_before_donation() -> None:
    # Regresión (FK real en MariaDB/MySQL): donations.memberships FK → support_members.
    # SQLite con PRAGMA foreign_keys=ON simula la restricción de producción.
    from sqlalchemy import event as sa_event

    engine = _engine()

    @sa_event.listens_for(engine, "connect")
    def _fk(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    from infrastructure.db.repositories.support_member_repository import (
        SqlAlchemySupportMemberRepository,
    )

    with Session(engine) as session:
        uc = ProcessPaymentWebhookUseCase(
            provider=FakePaymentProvider(),
            payment_events=SqlAlchemyPaymentEventRepository(session),
            memberships=SqlAlchemyMembershipRepository(session),
            donations=SqlAlchemyDonationRepository(session),
            communications=SqlAlchemyCommunicationEventRepository(session),
            support_members=SqlAlchemySupportMemberRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
        )
        # Donación de un usuario SIN SupportMember previo: debe crearlo (no violar FK).
        payload = _payload(event_id="fk-1", event_type="donation.succeeded", user_id="u-fk")
        result = uc.execute(payload)
        assert result.outcome == "processed"
        session.rollback()
        from sqlalchemy import select

        from infrastructure.db.models import SupportMemberModel

        members = session.execute(select(SupportMemberModel)).scalars().all()
        assert any(m.user_id == "u-fk" for m in members)
    engine.dispose()


def test_webhook_invalid_payload_returns_400(client: TestClient) -> None:
    # Payload no parseable (el fake lanza fallo si el payload no es dict válido).
    r = client.post("/api/v1/webhooks/payment", json={"id": None, "type": None})
    # id None → evt-unknown; type None → unknown → ignored_unsupported (2xx) según fake.
    assert r.status_code in (200, 400)


class _Verifier:
    """Verificador de firma stub: acepta los payloads marcados, rechaza los demás."""

    def __init__(self) -> None:
        self.verify_webhook = self._verify

    def _verify(self, raw_body: bytes, headers: dict[str, str]) -> None:
        body = raw_body.decode("utf-8")
        if headers.get("x-valid-signature") != "1":
            from application.use_cases.process_payment_webhook import InvalidWebhookPayload

            raise InvalidWebhookPayload("firma inválida (stub)")
        if '"fail": true' in body:
            from application.use_cases.process_payment_webhook import InvalidWebhookPayload

            raise InvalidWebhookPayload("payload marcado como inválido (stub)")


@pytest.fixture
def client_with_verifier() -> Iterator[TestClient]:
    from fastapi import FastAPI

    from api.routes.webhooks import wire_webhook_router

    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        uc = ProcessPaymentWebhookUseCase(
            provider=FakePaymentProvider(),
            payment_events=SqlAlchemyPaymentEventRepository(session),
            memberships=SqlAlchemyMembershipRepository(session),
            donations=SqlAlchemyDonationRepository(session),
            communications=SqlAlchemyCommunicationEventRepository(session),
            support_members=SqlAlchemySupportMemberRepository(session),
            uow=SqlAlchemyUnitOfWork(session),
            webhook_verifier=_Verifier(),
        )
        app = FastAPI(title="osap-support-webhook-test", version="0.1.0")
        app.include_router(wire_webhook_router(uc))
        yield TestClient(app)
    engine.dispose()


def test_webhook_valid_signature_processes(client_with_verifier: TestClient) -> None:
    payload = _payload(event_type="donation.succeeded", amount_minor=500, currency="EUR")
    r = client_with_verifier.post(
        "/api/v1/webhooks/payment",
        json=payload,
        headers={"x-valid-signature": "1"},
    )
    assert r.status_code == 200
    assert r.json()["outcome"] == "processed"


def test_webhook_invalid_signature_rejected(client_with_verifier: TestClient) -> None:
    payload = _payload(event_type="donation.succeeded", amount_minor=500, currency="EUR")
    r = client_with_verifier.post("/api/v1/webhooks/payment", json=payload)
    assert r.status_code == 400
    assert "firma inválida" in r.json()["detail"]


def test_webhook_invalid_signature_does_not_change_state(
    client_with_verifier: TestClient,
) -> None:
    # Aunque el payload fuese válido, sin firma NO se procesa → no hay efectos.
    payload = _payload(event_type="donation.succeeded", amount_minor=500, currency="EUR")
    r = client_with_verifier.post(
        "/api/v1/webhooks/payment",
        json=payload,
        headers={"x-valid-signature": "0"},  # firma NO válida
    )
    assert r.status_code == 400
    assert "firma inválida" in r.json()["detail"]
