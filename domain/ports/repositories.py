"""Ports de repositorio del dominio de OSAP Support (Fase 3).

El dominio declara las interfaces de persistencia; la infraestructura las implementa.
El dominio NO conoce SQLAlchemy/MySQL (regla de separación hexagonal).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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
    RecognitionType,
    SupportMember,
)


class SupportMemberRepository(ABC):
    @abstractmethod
    def add(self, member: SupportMember) -> SupportMember: ...

    @abstractmethod
    def get(self, user_id: str) -> SupportMember | None: ...

    @abstractmethod
    def exists(self, user_id: str) -> bool: ...


class MembershipRepository(ABC):
    @abstractmethod
    def add(self, membership: Membership) -> Membership: ...

    @abstractmethod
    def get_by_subscription(self, provider: str, subscription_id: str) -> Membership | None: ...

    @abstractmethod
    def list_by_user(self, user_id: str) -> list[Membership]: ...


class DonationRepository(ABC):
    @abstractmethod
    def add(self, donation: Donation) -> Donation: ...

    @abstractmethod
    def get_by_charge(self, provider: str, charge_id: str) -> Donation | None: ...

    @abstractmethod
    def list_by_user(self, user_id: str) -> list[Donation]: ...


class PaymentEventRepository(ABC):
    @abstractmethod
    def add(self, event: PaymentEvent) -> PaymentEvent:
        """Persiste un evento. Lanza DuplicatePaymentEventError si
        (provider, provider_event_id) ya existe (ADR-007)."""

    @abstractmethod
    def get_by_idempotency_key(
        self, provider: str, provider_event_id: str
    ) -> PaymentEvent | None: ...


class CommunicationEventRepository(ABC):
    @abstractmethod
    def add(self, event: CommunicationEvent) -> CommunicationEvent: ...

    @abstractmethod
    def get(self, event_id: int) -> CommunicationEvent | None: ...

    @abstractmethod
    def list_by_user(self, user_id: str) -> list[CommunicationEvent]: ...

    @abstractmethod
    def list_pending(self) -> list[CommunicationEvent]:
        """Comunicaciones pendientes de envío (worker, ADR-006)."""

    @abstractmethod
    def update(self, event: CommunicationEvent) -> CommunicationEvent:
        """Persiste los cambios de estado del evento (sent/failed/attempts)."""


class ProjectRepository(ABC):
    """Registro whitelisted de proyectos (ADR-015). El slug es el identificador."""

    @abstractmethod
    def get_by_slug(self, slug: str) -> Project | None: ...

    @abstractmethod
    def add(self, project: Project) -> Project: ...


class RecognitionRepository(ABC):
    """Proyección de estado vigente de reconocimientos (ADR-015).

    `get_current` devuelve la fila de estado de (user_id, project_slug, type), si existe
    (una por clave natural; UNIQUE(user_id, project_id, type)).
    """

    @abstractmethod
    def add(self, recognition: Recognition) -> Recognition:
        """Persiste un reconocimiento nuevo (asigna `id`)."""

    @abstractmethod
    def update(self, recognition: Recognition) -> Recognition:
        """Persiste los cambios de estado/consentimiento de un reconocimiento."""

    @abstractmethod
    def get_current(
        self, user_id: str, project_slug: str, recognition_type: RecognitionType
    ) -> Recognition | None: ...

    @abstractmethod
    def get_by_id(self, recognition_id: int) -> Recognition | None: ...

    @abstractmethod
    def list_by_user(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]: ...

    @abstractmethod
    def list_public(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]:
        """Reconocimientos públicamente visibles de un tercero (lectura consentida,
        ADR-015): SOLO status=ACTIVE y public=true. Sin consentimiento no existen."""


class RecognitionEventRepository(ABC):
    """Historial inmutable de cambios de reconocimiento (ADR-016)."""

    @abstractmethod
    def add(self, event: RecognitionEvent) -> RecognitionEvent:
        """Persiste un evento de historial (asigna `id`)."""

    @abstractmethod
    def list_by_user(self, user_id: str) -> list[RecognitionEvent]: ...


class ContributionRepository(ABC):
    """Referencias de contribución agregada emitidas por el sistema fuente (ADR-017)."""

    @abstractmethod
    def add(self, contribution: Contribution) -> Contribution:
        """Persiste una contribución. Lanza DuplicateContributionError si
        (source, source_reference) ya existe (ADR-017)."""

    @abstractmethod
    def get_by_idempotency_key(
        self, source: str, source_reference: str
    ) -> Contribution | None: ...

    @abstractmethod
    def list_by_user_project(self, user_id: str, project_slug: str) -> list[Contribution]: ...

    @abstractmethod
    def sum_amount(
        self,
        user_id: str,
        project_slug: str,
        contribution_types: frozenset[ContributionType],
    ) -> int:
        """Suma de los deltas (`amount`) de los tipos del bucket (ADR-017).

        Sin contador físico: la suma se calcula sobre las contribuciones registradas.
        Espeja `bucket_total` del dominio para consultas escalables.
        """
