"""Caso de uso: evaluar y persistir la vigencia del reconocimiento SUPPORTER (ADR-016).

Regla C fijada: SUPPORTER está vigente mientras exista una membresía activa O una donación
completada dentro de la ventana (parámetro de ecosistema, no por proyecto). La regla la
calcula el dominio (`recognitions_rules`); este caso de uso decide cuándo persistir el
estado y qué evento histórico registrar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.entities import (
    Recognition,
    RecognitionEvent,
    RecognitionEventType,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
    SupportMember,
)
from domain.ports.clock import Clock
from domain.ports.repositories import (
    DonationRepository,
    MembershipRepository,
    RecognitionEventRepository,
    RecognitionRepository,
    SupportMemberRepository,
)
from domain.ports.unit_of_work import UnitOfWork
from domain.recognitions_rules import (
    ECOSYSTEM_PROJECT_SLUG,
    SUPPORTER_RULE_ORIGIN,
    RecognitionRules,
    supporter_condition_active,
)


@dataclass(frozen=True)
class SupporterEvaluationResult:
    user_id: str
    active: bool
    changed: bool
    recognition_id: int | None


class EvaluateSupporterRecognitionUseCase:
    def __init__(
        self,
        *,
        memberships: MembershipRepository,
        donations: DonationRepository,
        recognitions: RecognitionRepository,
        events: RecognitionEventRepository,
        support_members: SupportMemberRepository,
        rules: RecognitionRules,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._memberships = memberships
        self._donations = donations
        self._recognitions = recognitions
        self._events = events
        self._support_members = support_members
        self._rules = rules
        self._clock = clock
        self._uow = uow

    def execute(
        self, user_id: str, *, origin_ref: str | None = None
    ) -> SupporterEvaluationResult:
        now = self._clock.utc_now()
        active = supporter_condition_active(
            self._memberships.list_by_user(user_id),
            self._donations.list_by_user(user_id),
            now=now,
            rules=self._rules,
        )
        current = self._recognitions.get_current(
            user_id, ECOSYSTEM_PROJECT_SLUG, RecognitionType.SUPPORTER
        )

        if active:
            return self._activate(user_id, current, now, origin_ref)
        return self._deactivate(user_id, current, now)

    def _activate(
        self,
        user_id: str,
        current: Recognition | None,
        now: datetime,
        origin_ref: str | None,
    ) -> SupporterEvaluationResult:
        if current is None:
            self._ensure_support_member(user_id)
            recognition = Recognition(
                id=None,
                user_id=user_id,
                project_slug=ECOSYSTEM_PROJECT_SLUG,
                recognition_type=RecognitionType.SUPPORTER,
                kind=RecognitionKind.DERIVED,
                status=RecognitionStatus.ACTIVE,
                granted_at=now,
                origin=SUPPORTER_RULE_ORIGIN,
            )
            recognition = self._recognitions.add(recognition)
            self._record(
                user_id,
                RecognitionEventType.ACTIVATED,
                RecognitionStatus.ACTIVE,
                origin=SUPPORTER_RULE_ORIGIN,
                origin_ref=origin_ref,
            )
            self._uow.commit()
            return SupporterEvaluationResult(
                user_id=user_id, active=True, changed=True, recognition_id=recognition.id
            )
        if current.status is RecognitionStatus.INACTIVE:
            current.status = RecognitionStatus.ACTIVE
            self._recognitions.update(current)
            self._record(
                user_id,
                RecognitionEventType.ACTIVATED,
                RecognitionStatus.ACTIVE,
                origin=SUPPORTER_RULE_ORIGIN,
                origin_ref=origin_ref,
            )
            self._uow.commit()
            return SupporterEvaluationResult(
                user_id=user_id, active=True, changed=True, recognition_id=current.id
            )
        return SupporterEvaluationResult(
            user_id=user_id, active=True, changed=False, recognition_id=current.id
        )

    def _deactivate(
        self, user_id: str, current: Recognition | None, now: datetime
    ) -> SupporterEvaluationResult:
        if current is not None and current.status is RecognitionStatus.ACTIVE:
            current.status = RecognitionStatus.INACTIVE
            self._recognitions.update(current)
            self._record(
                user_id,
                RecognitionEventType.DEACTIVATED,
                RecognitionStatus.INACTIVE,
                origin=SUPPORTER_RULE_ORIGIN,
            )
            self._uow.commit()
            return SupporterEvaluationResult(
                user_id=user_id, active=False, changed=True, recognition_id=current.id
            )
        return SupporterEvaluationResult(
            user_id=user_id,
            active=False,
            changed=False,
            recognition_id=current.id if current else None,
        )

    def _ensure_support_member(self, user_id: str) -> None:
        if not self._support_members.exists(user_id):
            self._support_members.add(SupportMember(user_id=user_id))

    def _record(
        self,
        user_id: str,
        event_type: RecognitionEventType,
        status_after: RecognitionStatus,
        *,
        origin: str | None = None,
        origin_ref: str | None = None,
    ) -> None:
        self._events.add(
            RecognitionEvent(
                id=None,
                user_id=user_id,
                project_slug=ECOSYSTEM_PROJECT_SLUG,
                recognition_type=RecognitionType.SUPPORTER,
                event_type=event_type,
                status_after=status_after,
                origin=origin,
                origin_ref=origin_ref,
                occurred_at=self._clock.utc_now(),
            )
        )
