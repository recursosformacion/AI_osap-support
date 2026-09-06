"""Tests de los repositorios SQLAlchemy de reconocimientos/contribuciones.

Verifican el mapeo persistencia <-> dominio (Fase 4B) sobre SQLite en memoria con los
modelos reales: get_current de Recognition, UNIQUE real, RecognitionEvent inmutable
(append-only), idempotencia de Contribution y resolución de Project por slug.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from domain.entities import (
    Contribution,
    ContributionType,
    Project,
    Recognition,
    RecognitionEvent,
    RecognitionEventType,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
    SupportMember,
)
from domain.exceptions import DuplicateContributionError, ProjectNotFoundError
from domain.recognitions_rules import (
    RecognitionRules,
    bucket_total,
)
from infrastructure.db.repositories.contribution_repository import (
    SqlAlchemyContributionRepository,
)
from infrastructure.db.repositories.project_repository import SqlAlchemyProjectRepository
from infrastructure.db.repositories.recognition_event_repository import (
    SqlAlchemyRecognitionEventRepository,
)
from infrastructure.db.repositories.recognition_repository import (
    SqlAlchemyRecognitionRepository,
)
from infrastructure.db.repositories.support_member_repository import (
    SqlAlchemySupportMemberRepository,
)

NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


def _seed_projects(session: Session) -> None:
    repo = SqlAlchemyProjectRepository(session)
    repo.add(Project(slug="ecosystem", name="OSAP Ecosystem"))
    repo.add(Project(slug="omr", name="Open Music Repository"))


def _ensure_member(session: Session, user_id: str) -> None:
    repo = SqlAlchemySupportMemberRepository(session)
    if not repo.exists(user_id):
        repo.add(SupportMember(user_id=user_id))


def _recognition(project_slug: str = "omr") -> Recognition:
    return Recognition(
        id=None,
        user_id="u-1",
        project_slug=project_slug,
        recognition_type=RecognitionType.VOICE,
        kind=RecognitionKind.GRANTED,
        status=RecognitionStatus.ACTIVE,
        granted_at=NOW,
        granted_by="admin-1",
        reason="voz",
    )


def test_project_get_by_slug_and_unknown(db_session: Session) -> None:
    _seed_projects(db_session)
    repo = SqlAlchemyProjectRepository(db_session)
    omr = repo.get_by_slug("omr")
    assert omr is not None
    assert omr.slug == "omr"
    assert repo.get_by_slug("no-existe") is None


def test_recognition_add_and_get_current(db_session: Session) -> None:
    _seed_projects(db_session)
    _ensure_member(db_session, "u-1")
    repo = SqlAlchemyRecognitionRepository(db_session)
    recognition = repo.add(_recognition())
    assert recognition.id is not None

    current = repo.get_current("u-1", "omr", RecognitionType.VOICE)
    assert current is not None
    assert current.project_slug == "omr"
    assert current.kind is RecognitionKind.GRANTED
    assert current.granted_by == "admin-1"

    other = repo.get_current("u-1", "ecosystem", RecognitionType.VOICE)
    assert other is None
    # Clave natural distinta por proyecto: se puede crear la misma persona+tipo en otro.
    ecosystem = repo.add(
        Recognition(
            id=None,
            user_id="u-1",
            project_slug="ecosystem",
            recognition_type=RecognitionType.VOICE,
            kind=RecognitionKind.GRANTED,
            status=RecognitionStatus.ACTIVE,
            granted_at=NOW,
            granted_by="admin-1",
            reason="voz",
        )
    )
    assert ecosystem.id is not None


def test_recognition_add_rejects_unknown_project(db_session: Session) -> None:
    _seed_projects(db_session)
    _ensure_member(db_session, "u-1")
    repo = SqlAlchemyRecognitionRepository(db_session)
    recognition = _recognition(project_slug="no-existe")
    with pytest.raises(ProjectNotFoundError):
        repo.add(recognition)


def test_recognition_update_changes_status_and_list_filters(db_session: Session) -> None:
    _seed_projects(db_session)
    _ensure_member(db_session, "u-1")
    repo = SqlAlchemyRecognitionRepository(db_session)
    recognition = repo.add(_recognition())
    assert recognition.id is not None

    current = repo.get_current("u-1", "omr", RecognitionType.VOICE)
    assert current is not None
    current.status = RecognitionStatus.INACTIVE
    current.public = True
    current.public_since = NOW
    repo.update(current)

    reloaded = repo.get_current("u-1", "omr", RecognitionType.VOICE)
    assert reloaded is not None
    assert reloaded.status is RecognitionStatus.INACTIVE
    assert reloaded.public
    assert not reloaded.is_publicly_visible

    assert len(repo.list_by_user("u-1", project_slug="omr")) == 1
    assert len(repo.list_by_user("u-1", project_slug="ecosystem")) == 0
    assert len(repo.list_by_user("u-1")) == 1


def test_recognition_event_append_only_with_slug(db_session: Session) -> None:
    _seed_projects(db_session)
    repo = SqlAlchemyRecognitionEventRepository(db_session)
    event = repo.add(
        RecognitionEvent(
            id=None,
            user_id="u-1",
            project_slug="ecosystem",
            recognition_type=RecognitionType.SUPPORTER,
            event_type=RecognitionEventType.ACTIVATED,
            status_after=RecognitionStatus.ACTIVE,
            origin="rule:supporter.active_or_donated_12m",
            occurred_at=NOW,
        )
    )
    assert event.id is not None
    events = repo.list_by_user("u-1")
    assert len(events) == 1
    assert events[0].project_slug == "ecosystem"
    assert events[0].event_type is RecognitionEventType.ACTIVATED


def test_contribution_idempotency_unique_and_list(db_session: Session) -> None:
    _seed_projects(db_session)
    _ensure_member(db_session, "u-1")
    repo = SqlAlchemyContributionRepository(db_session)
    contribution = Contribution(
        id=None,
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="revisión de 40 obras",
        amount=40,
        source="omr",
        source_reference="omr/rev/1",
        created_at=NOW,
    )
    added = repo.add(contribution)
    assert added.id is not None
    db_session.commit()

    duplicate = Contribution(
        id=None,
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="revisión duplicada",
        amount=40,
        source="omr",
        source_reference="omr/rev/1",
        created_at=NOW,
    )
    with pytest.raises(DuplicateContributionError):
        repo.add(duplicate)

    found = repo.get_by_idempotency_key("omr", "omr/rev/1")
    assert found is not None and found.summary == "revisión de 40 obras"
    listed = repo.list_by_user_project("u-1", "omr")
    assert len(listed) == 1
    assert listed[0].project_slug == "omr"
    assert repo.list_by_user_project("u-1", "ecosystem") == []


def test_public_read_returns_only_active_and_consented(db_session: Session) -> None:
    _seed_projects(db_session)
    _ensure_member(db_session, "u-1")
    repo = SqlAlchemyRecognitionRepository(db_session)

    voice = repo.add(_recognition())  # GRANTED ACTIVE, public=False
    contributor = repo.add(
        Recognition(
            id=None,
            user_id="u-1",
            project_slug="omr",
            recognition_type=RecognitionType.CONTRIBUTOR,
            kind=RecognitionKind.GRANTED,
            status=RecognitionStatus.ACTIVE,
            granted_at=NOW,
            granted_by="admin-1",
            reason="contribución",
        )
    )
    assert voice.id is not None and contributor.id is not None
    contributor.public = True
    contributor.public_since = NOW
    repo.update(contributor)

    inactive_with_consent = repo.add(
        Recognition(
            id=None,
            user_id="u-1",
            project_slug="ecosystem",
            recognition_type=RecognitionType.SUPPORTER,
            kind=RecognitionKind.DERIVED,
            status=RecognitionStatus.INACTIVE,
            granted_at=NOW,
            origin="rule:supporter",
            public=True,
            public_since=NOW,
        )
    )
    assert inactive_with_consent.id is not None
    db_session.commit()

    public_omr = repo.list_public("u-1", project_slug="omr")
    assert [r.recognition_type for r in public_omr] == [RecognitionType.CONTRIBUTOR]
    # INACTIVE + public=true NO es visible públicamente (ADR-016).
    public_all = repo.list_public("u-1")
    assert {r.recognition_type for r in public_all} == {RecognitionType.CONTRIBUTOR}


def test_contribution_sum_matches_domain_bucket(db_session: Session) -> None:
    _seed_projects(db_session)
    _ensure_member(db_session, "u-1")
    repo = SqlAlchemyContributionRepository(db_session)
    rules = RecognitionRules()
    for i, (ctype, amount) in enumerate(
        [
            (ContributionType.REVIEW, 40),
            (ContributionType.REVIEW, 60),
            (ContributionType.DOCUMENTATION, 50),
            (ContributionType.COMMUNITY, 1000),  # fuera del bucket
        ]
    ):
        repo.add(
            Contribution(
                id=None,
                user_id="u-1",
                project_slug="omr",
                contribution_type=ctype,
                summary=f"contribución {i}",
                amount=amount,
                source="omr",
                source_reference=f"omr/ref/{i}",
                created_at=NOW,
            )
        )
    db_session.commit()

    total = repo.sum_amount("u-1", "omr", rules.contributor_types)
    assert total == 150
    listed = repo.list_by_user_project("u-1", "omr")
    assert total == bucket_total(listed, types=rules.contributor_types)
