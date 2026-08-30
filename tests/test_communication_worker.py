"""Tests del worker de CommunicationEvent (Fase 7).

Cubren: pendiente se envía y marca procesado, ya procesado no se reenvía, fallo del
EmailSender no marca falsamente enviado (reintentable), varios eventos (un fallo no
pierde los demás), templates definidos, y preservación de origin_event_id.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from application.use_cases.process_communication_events import (
    ProcessCommunicationEventsUseCase,
)
from domain.entities import CommunicationEvent, CommunicationEventStatus
from infrastructure.db.models import Base
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.email.fake_email_sender import FakeEmailSender


@pytest.fixture
def env() -> Iterator[tuple[SqlAlchemyCommunicationEventRepository, FakeEmailSender]]:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repo = SqlAlchemyCommunicationEventRepository(session)
        sender = FakeEmailSender()
        yield repo, sender
    engine.dispose()


def _make_worker(
    repo: SqlAlchemyCommunicationEventRepository, sender: FakeEmailSender
) -> ProcessCommunicationEventsUseCase:
    return ProcessCommunicationEventsUseCase(
        communications=repo,
        email_sender=sender,
        uow=SqlAlchemyUnitOfWork(repo._session),  # noqa: SLF001
    )


def _event(**overrides: object) -> CommunicationEvent:
    base: dict[str, object] = {
        "id": None,
        "user_id": "uuid-1",
        "template": "donation_confirmation",
        "recipient_email": "a@b.c",
    }
    base.update(overrides)
    return CommunicationEvent(**base)


def test_pending_event_sent_once_and_marked(
    env: tuple[SqlAlchemyCommunicationEventRepository, FakeEmailSender],
) -> None:
    repo, sender = env
    saved = repo.add(_event())
    worker = _make_worker(repo, sender)

    summary = worker.execute()
    assert summary.sent == 1
    assert summary.failed == 0
    assert len(sender.sent) == 1
    assert sender.sent[0].template == "donation_confirmation"
    assert sender.sent[0].recipient_email == "a@b.c"

    after = repo.get(saved.id)
    assert after is not None
    assert after.status == CommunicationEventStatus.SENT
    assert after.sent_at is not None


def test_already_processed_not_resent(
    env: tuple[SqlAlchemyCommunicationEventRepository, FakeEmailSender],
) -> None:
    repo, sender = env
    repo.add(_event(status=CommunicationEventStatus.SENT))
    worker = _make_worker(repo, sender)

    summary = worker.execute()
    assert summary.sent == 0
    assert len(sender.sent) == 0


def test_failed_send_not_marked_sent_and_retryable(
    env: tuple[SqlAlchemyCommunicationEventRepository, FakeEmailSender],
) -> None:
    repo, sender = env
    saved = repo.add(_event())
    sender.fail_next = 1
    worker = _make_worker(repo, sender)

    summary = worker.execute()
    assert summary.failed == 1
    assert len(sender.sent) == 0

    after = repo.get(saved.id)
    assert after is not None
    assert after.status == CommunicationEventStatus.FAILED
    assert after.attempts == 1
    assert after.next_attempt_at is not None
    assert after.sent_at is None

    # Reintento posterior (vencido el backoff) con éxito.
    from datetime import UTC, datetime, timedelta

    assert after.id is not None
    after.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
    repo.update(after)
    summary2 = worker.execute()
    assert summary2.sent == 1
    after2 = repo.get(saved.id)
    assert after2 is not None
    assert after2.status == CommunicationEventStatus.SENT


def test_multiple_events_one_failure_does_not_lose_others(
    env: tuple[SqlAlchemyCommunicationEventRepository, FakeEmailSender],
) -> None:
    repo, sender = env
    repo.add(_event(recipient_email="ok1@x.y", template="donation_confirmation"))
    repo.add(_event(recipient_email="ok2@x.y", template="membership_confirmation"))
    repo.add(_event(recipient_email="fail@x.y", template="renewal_notice"))
    sender.fail_next = 1  # fallará el primero procesado
    worker = _make_worker(repo, sender)

    summary = worker.execute()
    assert summary.sent == 2
    assert summary.failed == 1
    assert len(sender.sent) == 2


def test_origin_event_id_preserved(
    env: tuple[SqlAlchemyCommunicationEventRepository, FakeEmailSender],
) -> None:
    repo, sender = env
    repo.add(_event(origin_event_id=42))
    worker = _make_worker(repo, sender)
    worker.execute()
    assert len(sender.sent) == 1
    assert sender.sent[0].origin_event_ref == "1"
