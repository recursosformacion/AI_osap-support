"""Tests de use cases de reconocimientos/contribuciones (Fase 3).

Ejecutan los casos de uso íntegramente desde dominio/application con fakes en memoria
(sin SQLAlchemy ni HTTP), como exige la Fase 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from application.use_cases.evaluate_contributor import (
    EvaluateContributorRecognitionUseCase,
)
from application.use_cases.evaluate_supporter import EvaluateSupporterRecognitionUseCase
from application.use_cases.grant_recognition import GrantRecognitionUseCase
from application.use_cases.ingest_contribution import IngestContributionUseCase
from application.use_cases.list_my_recognitions import ListMyRecognitionsUseCase
from application.use_cases.set_recognition_consent import SetRecognitionConsentUseCase
from domain.entities import (
    ContributionType,
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
    Recognition,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
)
from domain.exceptions import (
    InvalidGrantError,
    ProjectNotFoundError,
    RecognitionConflictError,
    RecognitionNotFoundError,
)
from domain.recognitions_rules import (
    ECOSYSTEM_PROJECT_SLUG,
    RecognitionRules,
)
from tests.fakes_recognitions import (
    FakeClock,
    FakeContributionRepository,
    FakeDonationRepository,
    FakeMembershipRepository,
    FakeProjectRepository,
    FakeRecognitionEventRepository,
    FakeRecognitionRepository,
    FakeSupportMemberRepository,
    FakeUnitOfWork,
    seed_projects,
)

NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


@dataclass
class Harness:
    memberships: FakeMembershipRepository = field(default_factory=FakeMembershipRepository)
    donations: FakeDonationRepository = field(default_factory=FakeDonationRepository)
    recognitions: FakeRecognitionRepository = field(default_factory=FakeRecognitionRepository)
    events: FakeRecognitionEventRepository = field(default_factory=FakeRecognitionEventRepository)
    support_members: FakeSupportMemberRepository = field(
        default_factory=FakeSupportMemberRepository
    )
    contributions: FakeContributionRepository = field(default_factory=FakeContributionRepository)
    projects: FakeProjectRepository = field(default_factory=seed_projects)
    rules: RecognitionRules = field(default_factory=RecognitionRules)
    clock: FakeClock = field(default_factory=lambda: FakeClock(NOW))
    uow: FakeUnitOfWork = field(default_factory=FakeUnitOfWork)

    def supporter_uc(self) -> EvaluateSupporterRecognitionUseCase:
        return EvaluateSupporterRecognitionUseCase(
            memberships=self.memberships,
            donations=self.donations,
            recognitions=self.recognitions,
            events=self.events,
            support_members=self.support_members,
            rules=self.rules,
            clock=self.clock,
            uow=self.uow,
        )

    def contributor_evaluator(self) -> EvaluateContributorRecognitionUseCase:
        return EvaluateContributorRecognitionUseCase(
            contributions=self.contributions,
            projects=self.projects,
            recognitions=self.recognitions,
            events=self.events,
            support_members=self.support_members,
            rules=self.rules,
            clock=self.clock,
            uow=self.uow,
        )

    def ingest_uc(self) -> IngestContributionUseCase:
        return IngestContributionUseCase(
            contributions=self.contributions,
            projects=self.projects,
            support_members=self.support_members,
            contributor_evaluator=self.contributor_evaluator(),
            clock=self.clock,
            uow=self.uow,
        )

    def grant_uc(self) -> GrantRecognitionUseCase:
        return GrantRecognitionUseCase(
            recognitions=self.recognitions,
            events=self.events,
            projects=self.projects,
            support_members=self.support_members,
            clock=self.clock,
            uow=self.uow,
        )

    def consent_uc(self) -> SetRecognitionConsentUseCase:
        return SetRecognitionConsentUseCase(
            recognitions=self.recognitions,
            events=self.events,
            clock=self.clock,
            uow=self.uow,
        )

    def list_uc(self) -> ListMyRecognitionsUseCase:
        return ListMyRecognitionsUseCase(recognitions=self.recognitions)


def _active_membership(user_id: str = "u-1") -> Membership:
    return Membership(
        id=None,
        user_id=user_id,
        status=MembershipStatus.ACTIVE,
        level=MembershipLevel.SUPPORTER,
        periodicity=Periodicity.MONTHLY,
        amount_minor=1000,
        currency="EUR",
        provider="paypal",
        customer_id=f"cus-{user_id}",
        subscription_id=f"sub-{user_id}",
        started_at=NOW,
    )


def _donation(days_ago: int, user_id: str = "u-1") -> Donation:
    return Donation(
        id=None,
        user_id=user_id,
        amount_minor=1000,
        currency="EUR",
        provider="paypal",
        charge_id=f"ch-{user_id}-{days_ago}",
        donated_at=NOW - timedelta(days=days_ago),
    )


def _current(
    h: Harness, user: str, slug: str, rtype: RecognitionType
) -> Recognition | None:
    return h.recognitions.get_current(user, slug, rtype)


# --- SUPPORTER (ADR-016) --------------------------------------------------------


def test_supporter_activates_with_active_membership_and_deactivates_on_cancel() -> None:
    h = Harness()
    membership = _active_membership()
    h.memberships.add(membership)

    result = h.supporter_uc().execute("u-1")
    assert (result.active, result.changed) == (True, True)

    rec = _current(h, "u-1", ECOSYSTEM_PROJECT_SLUG, RecognitionType.SUPPORTER)
    assert rec is not None
    assert rec.kind is RecognitionKind.DERIVED
    assert rec.status is RecognitionStatus.ACTIVE
    assert rec.granted_by is None
    assert rec.origin.startswith("rule:supporter")

    # Consentimiento público, luego cancelación de la membresía → INACTIVE y no visible.
    consent = h.consent_uc().execute(
        user_id="u-1",
        project_slug=ECOSYSTEM_PROJECT_SLUG,
        recognition_type=RecognitionType.SUPPORTER,
        public=True,
    )
    assert consent.changed

    membership.status = MembershipStatus.CANCELLED
    result = h.supporter_uc().execute("u-1")
    assert (result.active, result.changed) == (False, True)
    rec = _current(h, "u-1", ECOSYSTEM_PROJECT_SLUG, RecognitionType.SUPPORTER)
    assert rec is not None
    assert rec.status is RecognitionStatus.INACTIVE
    assert rec.public  # el consentimiento previo permanece registrado
    assert not rec.is_publicly_visible


def test_supporter_activates_from_recent_donation_and_expires_after_window() -> None:
    h = Harness()
    h.donations.add(_donation(days_ago=10))

    first = h.supporter_uc().execute("u-1")
    assert (first.active, first.changed) == (True, True)

    # La ventana (365 días) caduca: nueva evaluación a +400 días → INACTIVE.
    h.clock.advance(days=400)
    second = h.supporter_uc().execute("u-1")
    assert (second.active, second.changed) == (False, True)

    # Re-evaluación sin cambios no escribe nada nuevo.
    third = h.supporter_uc().execute("u-1")
    assert (third.active, third.changed) == (False, False)


def test_supporter_evaluation_creates_support_member() -> None:
    h = Harness()
    h.memberships.add(_active_membership())
    h.supporter_uc().execute("u-1")
    assert h.support_members.exists("u-1")


# --- CONTRIBUTOR / IngestContribution (ADR-017) ---------------------------------


def test_contributor_derives_after_accumulated_bucket_reaches_threshold() -> None:
    h = Harness()
    ingest = h.ingest_uc()

    r1 = ingest.execute(
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="revisión de 40 obras",
        amount=40,
        source="omr",
        source_reference="omr/rev/1",
    )
    assert (r1.outcome, r1.contributor_active) == ("created", False)

    r2 = ingest.execute(
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="revisión de 60 obras",
        amount=60,
        source="omr",
        source_reference="omr/rev/2",
    )
    assert r2.contributor_active is False

    # DOCUMENTATION pertenece al bucket: 40+60+50 = 150 → CONTRIBUTOR.
    r3 = ingest.execute(
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.DOCUMENTATION,
        summary="documentación de 50 obras",
        amount=50,
        source="omr",
        source_reference="omr/doc/1",
    )
    assert (r3.outcome, r3.contributor_active) == ("created", True)

    rec = _current(h, "u-1", "omr", RecognitionType.CONTRIBUTOR)
    assert rec is not None
    assert rec.kind is RecognitionKind.DERIVED
    assert rec.status is RecognitionStatus.ACTIVE
    assert rec.origin.startswith("rule:contributor")
    assert h.contributions.list_by_user_project("u-1", "omr")[-1].summary == (
        "documentación de 50 obras"
    )


def test_contributor_duplicate_ingest_is_idempotent() -> None:
    h = Harness()
    ingest = h.ingest_uc()
    ingest.execute(
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="revisión de 150 obras",
        amount=150,
        source="omr",
        source_reference="omr/rev/150",
    )

    duplicate = ingest.execute(
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="revisión de 150 obras (duplicada)",
        amount=150,
        source="omr",
        source_reference="omr/rev/150",
    )
    assert duplicate.outcome == "duplicate"
    # El delta no se cuenta dos veces (sin contador físico: suma sobre deltas).
    contributions = h.contributions.list_by_user_project("u-1", "omr")
    assert sum(c.amount or 0 for c in contributions) == 150


def test_contributor_ignores_non_bucket_types_and_unknown_project() -> None:
    h = Harness()
    ingest = h.ingest_uc()
    result = ingest.execute(
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.COMMUNITY,
        summary="moderación en comunidad",
        amount=1000,
        source="omr",
        source_reference="omr/com/1",
    )
    assert result.contributor_active is False
    assert _current(h, "u-1", "omr", RecognitionType.CONTRIBUTOR) is None

    with pytest.raises(ProjectNotFoundError):
        ingest.execute(
            user_id="u-1",
            project_slug="no-existe",
            contribution_type=ContributionType.REVIEW,
            summary="x",
            amount=150,
            source="omr",
            source_reference="omr/rev/bad",
        )


# --- GrantRecognition (ADR-015) --------------------------------------------------


def test_grant_voice_by_admin() -> None:
    h = Harness()
    result = h.grant_uc().execute(
        user_id="u-2",
        project_slug="omr",
        recognition_type=RecognitionType.VOICE,
        granted_by="admin-1",
        reason="voz activa en la comunidad",
    )
    assert result.recognition_id is not None
    assert h.support_members.exists("u-2")

    rec = _current(h, "u-2", "omr", RecognitionType.VOICE)
    assert rec is not None
    assert rec.kind is RecognitionKind.GRANTED
    assert rec.granted_by == "admin-1"
    assert rec.status is RecognitionStatus.ACTIVE


def test_grant_rejects_supporter_founder_and_invalid_inputs() -> None:
    h = Harness()
    grant = h.grant_uc()
    with pytest.raises(InvalidGrantError):
        grant.execute(
            user_id="u-2",
            project_slug="omr",
            recognition_type=RecognitionType.SUPPORTER,
            granted_by="admin-1",
            reason="manual",
        )
    with pytest.raises(InvalidGrantError):
        grant.execute(
            user_id="u-2",
            project_slug="omr",
            recognition_type=RecognitionType.VOICE,
            granted_by="admin-1",
            reason="",
        )
    with pytest.raises(InvalidGrantError):
        grant.execute(
            user_id="u-2",
            project_slug="omr",
            recognition_type=RecognitionType.VOICE,
            granted_by="",
            reason="voz",
        )


def test_grant_conflicts_when_recognition_exists() -> None:
    h = Harness()
    grant = h.grant_uc()
    grant.execute(
        user_id="u-2",
        project_slug="omr",
        recognition_type=RecognitionType.VOICE,
        granted_by="admin-1",
        reason="primera voz",
    )
    with pytest.raises(RecognitionConflictError):
        grant.execute(
            user_id="u-2",
            project_slug="omr",
            recognition_type=RecognitionType.VOICE,
            granted_by="admin-1",
            reason="segunda voz",
        )


# --- Consentimiento (ADR-015) ----------------------------------------------------


def test_consent_grant_and_revoke() -> None:
    h = Harness()
    h.grant_uc().execute(
        user_id="u-2",
        project_slug="omr",
        recognition_type=RecognitionType.CONTRIBUTOR,
        granted_by="admin-1",
        reason="revisión de 150 obras",
    )

    consent = h.consent_uc().execute(
        user_id="u-2",
        project_slug="omr",
        recognition_type=RecognitionType.CONTRIBUTOR,
        public=True,
    )
    assert consent.changed
    rec = _current(h, "u-2", "omr", RecognitionType.CONTRIBUTOR)
    assert rec is not None
    assert rec.public and rec.public_since is not None and rec.public_revoked_at is None
    assert rec.is_publicly_visible

    # Repetir el mismo valor no cambia nada.
    unchanged = h.consent_uc().execute(
        user_id="u-2",
        project_slug="omr",
        recognition_type=RecognitionType.CONTRIBUTOR,
        public=True,
    )
    assert not unchanged.changed

    revoked = h.consent_uc().execute(
        user_id="u-2",
        project_slug="omr",
        recognition_type=RecognitionType.CONTRIBUTOR,
        public=False,
    )
    assert revoked.changed
    rec = _current(h, "u-2", "omr", RecognitionType.CONTRIBUTOR)
    assert rec is not None
    assert not rec.public and rec.public_revoked_at is not None


def test_consent_requires_existing_recognition() -> None:
    h = Harness()
    with pytest.raises(RecognitionNotFoundError):
        h.consent_uc().execute(
            user_id="u-2",
            project_slug="omr",
            recognition_type=RecognitionType.VOICE,
            public=True,
        )


# --- ListMyRecognitions (ADR-008) ------------------------------------------------


def test_list_my_recognitions_filters_by_project() -> None:
    h = Harness()
    h.memberships.add(_active_membership())
    h.supporter_uc().execute("u-1")  # project = ecosystem
    h.grant_uc().execute(
        user_id="u-1",
        project_slug="omr",
        recognition_type=RecognitionType.VOICE,
        granted_by="admin-1",
        reason="voz",
    )

    listed = h.list_uc().execute("u-1")
    assert {r.recognition_type for r in listed} == {
        RecognitionType.SUPPORTER,
        RecognitionType.VOICE,
    }
    omr_only = h.list_uc().execute("u-1", project_slug="omr")
    assert [r.recognition_type for r in omr_only] == [RecognitionType.VOICE]
