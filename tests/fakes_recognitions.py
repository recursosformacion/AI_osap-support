"""Fakes en memoria para tests de reconocimientos/contribuciones (Fase 3).

Implementan los ports del dominio sin SQLAlchemy ni HTTP: permiten ejecutar los casos de
uso íntegramente desde dominio/application.
"""

from __future__ import annotations

from datetime import UTC, datetime

from domain.entities import (
    CommunicationEvent,
    Contribution,
    ContributionType,
    Donation,
    Membership,
    PaymentEvent,
    Project,
    Recognition,
    RecognitionEvent,
    RecognitionStatus,
    RecognitionType,
    SupportMember,
)
from domain.exceptions import DuplicateContributionError
from domain.ports.clock import Clock
from domain.ports.repositories import (
    CommunicationEventRepository,
    ContributionRepository,
    DonationRepository,
    MembershipRepository,
    PaymentEventRepository,
    ProjectRepository,
    RecognitionEventRepository,
    RecognitionRepository,
    SupportMemberRepository,
)
from domain.ports.unit_of_work import UnitOfWork


class FakeClock(Clock):
    """Reloj determinista; `now` puede mutarse entre llamadas."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def utc_now(self) -> datetime:
        return self.now

    def advance(self, **delta: int) -> None:
        from datetime import timedelta

        self.now += timedelta(**delta)


class FakeUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class FakeSupportMemberRepository(SupportMemberRepository):
    def __init__(self) -> None:
        self._store: dict[str, SupportMember] = {}

    def add(self, member: SupportMember) -> SupportMember:
        self._store[member.user_id] = member
        return member

    def get(self, user_id: str) -> SupportMember | None:
        return self._store.get(user_id)

    def exists(self, user_id: str) -> bool:
        return user_id in self._store


class FakeMembershipRepository(MembershipRepository):
    def __init__(self) -> None:
        self._store: list[Membership] = []

    def add(self, membership: Membership) -> Membership:
        membership.id = len(self._store) + 1
        self._store.append(membership)
        return membership

    def get_by_subscription(self, provider: str, subscription_id: str) -> Membership | None:
        for m in self._store:
            if m.provider == provider and m.subscription_id == subscription_id:
                return m
        return None

    def list_by_user(self, user_id: str) -> list[Membership]:
        return [m for m in self._store if m.user_id == user_id]


class FakeDonationRepository(DonationRepository):
    def __init__(self) -> None:
        self._store: list[Donation] = []

    def add(self, donation: Donation) -> Donation:
        donation.id = len(self._store) + 1
        self._store.append(donation)
        return donation

    def get_by_charge(self, provider: str, charge_id: str) -> Donation | None:
        for d in self._store:
            if d.provider == provider and d.charge_id == charge_id:
                return d
        return None

    def list_by_user(self, user_id: str) -> list[Donation]:
        return [d for d in self._store if d.user_id == user_id]


class FakePaymentEventRepository(PaymentEventRepository):
    def __init__(self) -> None:
        self._store: list[PaymentEvent] = []

    def add(self, event: PaymentEvent) -> PaymentEvent:
        event.id = len(self._store) + 1
        self._store.append(event)
        return event

    def get_by_idempotency_key(self, provider: str, provider_event_id: str) -> PaymentEvent | None:
        for e in self._store:
            if e.provider == provider and e.provider_event_id == provider_event_id:
                return e
        return None


class FakeCommunicationEventRepository(CommunicationEventRepository):
    def __init__(self) -> None:
        self._store: list[CommunicationEvent] = []

    def add(self, event: CommunicationEvent) -> CommunicationEvent:
        event.id = len(self._store) + 1
        self._store.append(event)
        return event

    def get(self, event_id: int) -> CommunicationEvent | None:
        for e in self._store:
            if e.id == event_id:
                return e
        return None

    def list_by_user(self, user_id: str) -> list[CommunicationEvent]:
        return [e for e in self._store if e.user_id == user_id]

    def list_pending(self) -> list[CommunicationEvent]:
        return [e for e in self._store if e.status.value == "pending"]

    def update(self, event: CommunicationEvent) -> CommunicationEvent:
        return event


class FakeProjectRepository(ProjectRepository):
    def __init__(self, *projects: Project) -> None:
        self._store: dict[str, Project] = {p.slug: p for p in projects}

    def get_by_slug(self, slug: str) -> Project | None:
        return self._store.get(slug)

    def add(self, project: Project) -> Project:
        self._store[project.slug] = project
        return project


class FakeRecognitionRepository(RecognitionRepository):
    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], Recognition] = {}
        self._next_id = 1

    def add(self, recognition: Recognition) -> Recognition:
        key = self._key(recognition)
        if key in self._store:
            return self._store[key]
        recognition.id = self._next_id
        self._next_id += 1
        self._store[key] = recognition
        return recognition

    def update(self, recognition: Recognition) -> Recognition:
        self._store[self._key(recognition)] = recognition
        return recognition

    def get_current(
        self, user_id: str, project_slug: str, recognition_type: RecognitionType
    ) -> Recognition | None:
        return self._store.get((user_id, project_slug, recognition_type.value))

    def get_by_id(self, recognition_id: int) -> Recognition | None:
        for recognition in self._store.values():
            if recognition.id == recognition_id:
                return recognition
        return None

    def list_by_user(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]:
        return [
            r
            for (uid, slug, _), r in self._store.items()
            if uid == user_id and (project_slug is None or slug == project_slug)
        ]

    def list_public(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]:
        return [
            r
            for r in self.list_by_user(user_id, project_slug)
            if r.status is RecognitionStatus.ACTIVE and r.public
        ]

    @staticmethod
    def _key(recognition: Recognition) -> tuple[str, str, str]:
        return (
            recognition.user_id,
            recognition.project_slug,
            recognition.recognition_type.value,
        )


class FakeRecognitionEventRepository(RecognitionEventRepository):
    def __init__(self) -> None:
        self._store: list[RecognitionEvent] = []

    def add(self, event: RecognitionEvent) -> RecognitionEvent:
        event.id = len(self._store) + 1
        self._store.append(event)
        return event

    def list_by_user(self, user_id: str) -> list[RecognitionEvent]:
        return [e for e in self._store if e.user_id == user_id]


class FakeContributionRepository(ContributionRepository):
    def __init__(self) -> None:
        self._store: list[Contribution] = []
        self._by_key: dict[tuple[str, str], Contribution] = {}

    def add(self, contribution: Contribution) -> Contribution:
        key = contribution.idempotency_key
        if key in self._by_key:
            raise DuplicateContributionError(f"contribución duplicada: {key}")
        contribution.id = len(self._store) + 1
        self._store.append(contribution)
        self._by_key[key] = contribution
        return contribution

    def get_by_idempotency_key(
        self, source: str, source_reference: str
    ) -> Contribution | None:
        return self._by_key.get((source, source_reference))

    def list_by_user_project(self, user_id: str, project_slug: str) -> list[Contribution]:
        return [
            c
            for c in self._store
            if c.user_id == user_id and c.project_slug == project_slug
        ]

    def sum_amount(
        self,
        user_id: str,
        project_slug: str,
        contribution_types: frozenset[ContributionType],
    ) -> int:
        return sum(
            c.amount or 0
            for c in self.list_by_user_project(user_id, project_slug)
            if c.contribution_type in contribution_types
        )


def seed_projects() -> FakeProjectRepository:
    """Projects whitelisted por defecto (canónico ecosystem + omr)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    return FakeProjectRepository(
        Project(slug="ecosystem", name="OSAP Ecosystem", created_at=now),
        Project(slug="omr", name="Open Music Repository", created_at=now),
    )
