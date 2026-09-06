"""Caso de uso: consentimiento público de un reconocimiento (ADR-015).

El consentimiento es opt-in y revocable, y lo cambia SOLO el propio usuario. `public=True`
otorga consentimiento (public_since); `public=False` lo revoca (public_revoked_at) y oculta
el badge de las lecturas públicas. El consentimiento no hace visible un reconocimiento no
vigente (status=INACTIVE): la visibilidad exige status=ACTIVE y public (ADR-016).
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities import (
    RecognitionEvent,
    RecognitionEventType,
    RecognitionType,
)
from domain.exceptions import RecognitionNotFoundError
from domain.ports.clock import Clock
from domain.ports.repositories import (
    RecognitionEventRepository,
    RecognitionRepository,
)
from domain.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class ConsentResult:
    user_id: str
    project_slug: str
    recognition_type: RecognitionType
    public: bool
    changed: bool


class SetRecognitionConsentUseCase:
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
        user_id: str,
        project_slug: str,
        recognition_type: RecognitionType,
        public: bool,
    ) -> ConsentResult:
        current = self._recognitions.get_current(user_id, project_slug, recognition_type)
        if current is None:
            raise RecognitionNotFoundError(
                f"no existe {recognition_type.value} para {user_id} en {project_slug}"
            )
        if current.public == public:
            return ConsentResult(
                user_id=user_id,
                project_slug=project_slug,
                recognition_type=recognition_type,
                public=public,
                changed=False,
            )

        now = self._clock.utc_now()
        if public:
            current.public = True
            current.public_since = now
            current.public_revoked_at = None
            event_type = RecognitionEventType.CONSENT_GRANTED
        else:
            current.public = False
            current.public_revoked_at = now
            event_type = RecognitionEventType.CONSENT_REVOKED
        self._recognitions.update(current)
        self._events.add(
            RecognitionEvent(
                id=None,
                user_id=user_id,
                project_slug=project_slug,
                recognition_type=recognition_type,
                event_type=event_type,
                status_after=current.status,
                occurred_at=now,
            )
        )
        self._uow.commit()
        return ConsentResult(
            user_id=user_id,
            project_slug=project_slug,
            recognition_type=recognition_type,
            public=public,
            changed=True,
        )
