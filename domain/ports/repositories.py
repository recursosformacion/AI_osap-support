"""Ports de repositorio del dominio de OSAP Support (Fase 3).

El dominio declara las interfaces de persistencia; la infraestructura las implementa.
El dominio NO conoce SQLAlchemy/MySQL (regla de separación hexagonal).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities import (
    CommunicationEvent,
    Donation,
    Membership,
    PaymentEvent,
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
