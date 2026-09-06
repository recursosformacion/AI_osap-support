"""Caso de uso: concesión administrativa de un reconocimiento (ADR-015).

Solo CONTRIBUTOR y VOICE son otorgables por administración (kind=GRANTED, granted_by,
reason obligatorios). SUPPORTER es derivado y FOUNDER histórico por criterio congelado:
no se conceden manualmente. Si ya existe un reconocimiento para (user, project, type),
se rechaza (RecognitionConflictError).
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities import (
    Recognition,
    RecognitionEvent,
    RecognitionEventType,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
    SupportMember,
)
from domain.exceptions import (
    InvalidGrantError,
    ProjectNotFoundError,
    RecognitionConflictError,
)
from domain.ports.clock import Clock
from domain.ports.repositories import (
    ProjectRepository,
    RecognitionEventRepository,
    RecognitionRepository,
    SupportMemberRepository,
)
from domain.ports.unit_of_work import UnitOfWork

_MANUAL_GRANTABLE = {RecognitionType.CONTRIBUTOR, RecognitionType.VOICE}


@dataclass(frozen=True)
class GrantResult:
    user_id: str
    project_slug: str
    recognition_type: RecognitionType
    recognition_id: int


class GrantRecognitionUseCase:
    def __init__(
        self,
        *,
        recognitions: RecognitionRepository,
        events: RecognitionEventRepository,
        projects: ProjectRepository,
        support_members: SupportMemberRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._recognitions = recognitions
        self._events = events
        self._projects = projects
        self._support_members = support_members
        self._clock = clock
        self._uow = uow

    def execute(
        self,
        *,
        user_id: str,
        project_slug: str,
        recognition_type: RecognitionType,
        granted_by: str,
        reason: str,
    ) -> GrantResult:
        if recognition_type not in _MANUAL_GRANTABLE:
            raise InvalidGrantError(
                "solo CONTRIBUTOR y VOICE son otorgables manualmente (ADR-015)"
            )
        if not granted_by or not granted_by.strip():
            raise InvalidGrantError("granted_by es obligatorio")
        if not reason or not reason.strip():
            raise InvalidGrantError("reason es obligatorio (auditoría)")
        if self._projects.get_by_slug(project_slug) is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {project_slug}")
        if (
            self._recognitions.get_current(user_id, project_slug, recognition_type)
            is not None
        ):
            raise RecognitionConflictError(
                f"ya existe {recognition_type.value} para {user_id} en {project_slug}"
            )

        now = self._clock.utc_now()
        self._ensure_support_member(user_id)
        recognition = Recognition(
            id=None,
            user_id=user_id,
            project_slug=project_slug,
            recognition_type=recognition_type,
            kind=RecognitionKind.GRANTED,
            status=RecognitionStatus.ACTIVE,
            granted_at=now,
            granted_by=granted_by,
            reason=reason,
        )
        recognition = self._recognitions.add(recognition)
        self._events.add(
            RecognitionEvent(
                id=None,
                user_id=user_id,
                project_slug=project_slug,
                recognition_type=recognition_type,
                event_type=RecognitionEventType.GRANTED,
                status_after=RecognitionStatus.ACTIVE,
                reason=reason,
                granted_by=granted_by,
                occurred_at=now,
            )
        )
        self._uow.commit()
        return GrantResult(
            user_id=user_id,
            project_slug=project_slug,
            recognition_type=recognition_type,
            recognition_id=recognition.id,  # type: ignore[arg-type]
        )

    def _ensure_support_member(self, user_id: str) -> None:
        if not self._support_members.exists(user_id):
            self._support_members.add(SupportMember(user_id=user_id))
