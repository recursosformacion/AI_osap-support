"""Caso de uso: revocación administrativa de un reconocimiento (ADR-015).

El admin revoca un reconocimiento por su id (busca el estado actual), lo pasa a INACTIVE
(histórico: deja de mostrarse, incluido en público aunque tuviera consentimiento) y
registra el evento REVOKED con `granted_by` y `reason` (auditoría). Un CONTRIBUTOR
revocado no se re-deriva automáticamente (ADR-017).
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities import RecognitionEvent, RecognitionEventType, RecognitionStatus
from domain.exceptions import RecognitionNotFoundError
from domain.ports.clock import Clock
from domain.ports.repositories import (
    RecognitionEventRepository,
    RecognitionRepository,
)
from domain.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class RevokeResult:
    recognition_id: int
    changed: bool


class RevokeRecognitionUseCase:
    def __init__(
        self,
        *,
        recognitions: RecognitionRepository,
        events: RecognitionEventRepository,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._recognitions = recognitions
        self._events = events
        self._clock = clock
        self._uow = uow

    def execute(
        self,
        *,
        recognition_id: int,
        granted_by: str,
        reason: str,
    ) -> RevokeResult:
        current = self._recognitions.get_by_id(recognition_id)
        if current is None:
            raise RecognitionNotFoundError(
                f"no existe reconocimiento con id {recognition_id}"
            )
        if not reason or not reason.strip():
            raise ValueError("reason es obligatorio (auditoría)")
        if current.status is RecognitionStatus.INACTIVE:
            return RevokeResult(recognition_id=recognition_id, changed=False)

        current.status = RecognitionStatus.INACTIVE
        self._recognitions.update(current)
        self._events.add(
            RecognitionEvent(
                id=None,
                user_id=current.user_id,
                project_slug=current.project_slug,
                recognition_type=current.recognition_type,
                event_type=RecognitionEventType.REVOKED,
                status_after=RecognitionStatus.INACTIVE,
                reason=reason,
                granted_by=granted_by,
                occurred_at=self._clock.utc_now(),
            )
        )
        self._uow.commit()
        return RevokeResult(recognition_id=recognition_id, changed=True)
