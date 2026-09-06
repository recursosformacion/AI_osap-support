"""Caso de uso: evaluar y persistir el reconocimiento CONTRIBUTOR (ADR-017).

Regla fijada en Fase 1: el acumulado (suma de `amount` de los tipos del bucket sobre
`contributions`) >= umbral deriva un único CONTRIBUTOR (kind=DERIVED). No se persiste
contador físico: la regla agrega bajo demanda. Un CONTRIBUTOR revocado (INACTIVE) no se
re-deriva automáticamente: respeta la revocación administrativa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.entities import (
    Contribution,
    Recognition,
    RecognitionEvent,
    RecognitionEventType,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
    SupportMember,
)
from domain.exceptions import ProjectNotFoundError
from domain.ports.clock import Clock
from domain.ports.repositories import (
    ContributionRepository,
    ProjectRepository,
    RecognitionEventRepository,
    RecognitionRepository,
    SupportMemberRepository,
)
from domain.ports.unit_of_work import UnitOfWork
from domain.recognitions_rules import (
    CONTRIBUTOR_RULE_ORIGIN,
    RecognitionRules,
    contributor_condition_reached,
)


@dataclass(frozen=True)
class ContributorEvaluationResult:
    user_id: str
    project_slug: str
    active: bool
    total: int
    changed: bool
    recognition_id: int | None


class EvaluateContributorRecognitionUseCase:
    def __init__(
        self,
        *,
        contributions: ContributionRepository,
        projects: ProjectRepository,
        recognitions: RecognitionRepository,
        events: RecognitionEventRepository,
        support_members: SupportMemberRepository,
        rules: RecognitionRules,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._contributions = contributions
        self._projects = projects
        self._recognitions = recognitions
        self._events = events
        self._support_members = support_members
        self._rules = rules
        self._clock = clock
        self._uow = uow

    def execute(
        self,
        user_id: str,
        project_slug: str,
        *,
        commit: bool = True,
        origin_ref: str | None = None,
    ) -> ContributorEvaluationResult:
        now = self._clock.utc_now()
        contributions = self._contributions.list_by_user_project(user_id, project_slug)
        reached, total = contributor_condition_reached(contributions, rules=self._rules)
        current = self._recognitions.get_current(
            user_id, project_slug, RecognitionType.CONTRIBUTOR
        )

        if not reached:
            return ContributorEvaluationResult(
                user_id=user_id,
                project_slug=project_slug,
                active=False,
                total=total,
                changed=False,
                recognition_id=current.id if current else None,
            )

        if current is None:
            return self._create(
                user_id, project_slug, contributions, total, now, origin_ref, commit
            )
        if current.status is RecognitionStatus.ACTIVE:
            return ContributorEvaluationResult(
                user_id=user_id,
                project_slug=project_slug,
                active=True,
                total=total,
                changed=False,
                recognition_id=current.id,
            )
        # INACTIVE (revocado por administración): no se re-deriva automáticamente.
        return ContributorEvaluationResult(
            user_id=user_id,
            project_slug=project_slug,
            active=False,
            total=total,
            changed=False,
            recognition_id=current.id,
        )

    def _create(
        self,
        user_id: str,
        project_slug: str,
        contributions: list[Contribution],
        total: int,
        now: datetime,
        origin_ref: str | None,
        commit: bool,
    ) -> ContributorEvaluationResult:
        if self._projects.get_by_slug(project_slug) is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {project_slug}")
        self._ensure_support_member(user_id)
        reason = _latest_summary(contributions)
        recognition = Recognition(
            id=None,
            user_id=user_id,
            project_slug=project_slug,
            recognition_type=RecognitionType.CONTRIBUTOR,
            kind=RecognitionKind.DERIVED,
            status=RecognitionStatus.ACTIVE,
            granted_at=now,
            origin=CONTRIBUTOR_RULE_ORIGIN,
            reason=reason,
        )
        recognition = self._recognitions.add(recognition)
        self._events.add(
            RecognitionEvent(
                id=None,
                user_id=user_id,
                project_slug=project_slug,
                recognition_type=RecognitionType.CONTRIBUTOR,
                event_type=RecognitionEventType.ACTIVATED,
                status_after=RecognitionStatus.ACTIVE,
                reason=reason,
                origin=CONTRIBUTOR_RULE_ORIGIN,
                origin_ref=origin_ref,
                occurred_at=now,
            )
        )
        if commit:
            self._uow.commit()
        return ContributorEvaluationResult(
            user_id=user_id,
            project_slug=project_slug,
            active=True,
            total=total,
            changed=True,
            recognition_id=recognition.id,
        )

    def _ensure_support_member(self, user_id: str) -> None:
        if not self._support_members.exists(user_id):
            self._support_members.add(SupportMember(user_id=user_id))


def _latest_summary(contributions: list[Contribution]) -> str | None:
    """Resumen de la contribución más reciente (evidencia que completa el umbral)."""
    if not contributions:
        return None
    latest = max(contributions, key=lambda c: c.created_at)
    return latest.summary
