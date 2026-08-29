"""Dominio de OSAP Support (Fase 2): entidades, eventos y máquina de estados."""

from .entities import (
    CommunicationEvent,
    CommunicationEventStatus,
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    Money,
    PaymentEvent,
    PaymentEventStatus,
    Periodicity,
    SupportMember,
)
from .events import (
    DomainEvent,
    DonationDomainEventType,
    MembershipDomainEventType,
)
from .exceptions import (
    InvalidMoneyError,
    InvalidStateTransition,
    SupportDomainError,
)
from .state_machine import MembershipStateMachine, TransitionResult

__all__ = [
    "CommunicationEvent",
    "CommunicationEventStatus",
    "DomainEvent",
    "Donation",
    "DonationDomainEventType",
    "InvalidMoneyError",
    "InvalidStateTransition",
    "Membership",
    "MembershipDomainEventType",
    "MembershipLevel",
    "MembershipStateMachine",
    "MembershipStatus",
    "Money",
    "PaymentEvent",
    "PaymentEventStatus",
    "Periodicity",
    "SupportDomainError",
    "SupportMember",
    "TransitionResult",
]
