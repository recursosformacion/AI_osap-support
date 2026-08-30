"""Caso de uso: procesar un webhook de pago (Fase 6).

Flujo (ADR-007): parse_webhook → PaymentProviderEvent → registrar PaymentEvent
(idempotente, UNIQUE(provider, provider_event_id)) → procesar efecto → generar
CommunicationEvent. NO envía email (ADR-006: webhook → CommunicationEvent → worker →
EmailSender; el envío es de fase posterior).

Sin proveedor concreto (ADR-005). La identidad procede del evento normalizado
(ADR-002: user_id = JWT.sub; no se inventa identidad local).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from domain.entities import (
    CommunicationEvent,
    CommunicationEventStatus,
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    PaymentEvent,
    PaymentEventStatus,
    Periodicity,
)
from domain.events import DomainEvent, DonationDomainEventType, MembershipDomainEventType
from domain.exceptions import DuplicatePaymentEventError
from domain.ports.payment import PaymentProvider, PaymentProviderEvent
from domain.ports.repositories import (
    CommunicationEventRepository,
    DonationRepository,
    MembershipRepository,
    PaymentEventRepository,
)
from domain.ports.unit_of_work import UnitOfWork
from domain.state_machine import MembershipStateMachine

# Mapeo event_type del proveedor → evento de dominio (arquitectura §6 / §4.4).
# Solo los eventos suficientemente definidos por las fuentes.
_PROVIDER_TO_DOMAIN: dict[str, MembershipDomainEventType | DonationDomainEventType] = {
    "subscription.created": MembershipDomainEventType.CREATED,
    "payment.succeeded": MembershipDomainEventType.ACTIVATED,
    "subscription.renewed": MembershipDomainEventType.RENEWED,
    "payment.failed": MembershipDomainEventType.PAST_DUE,
    "subscription.cancelled": MembershipDomainEventType.CANCELLED,
    "subscription.expired": MembershipDomainEventType.EXPIRED,
    "donation.succeeded": DonationDomainEventType.RECEIVED,
}

# CommunicationEvent templates (arquitectura §9) por evento de dominio.
_DOMAIN_TO_TEMPLATE: dict[object, str] = {
    MembershipDomainEventType.ACTIVATED: "membership_confirmation",
    MembershipDomainEventType.RENEWED: "renewal_notice",
    MembershipDomainEventType.PAST_DUE: "payment_failed",
    MembershipDomainEventType.RECOVERED: "membership_confirmation",
    MembershipDomainEventType.CANCELLED: "membership_cancelled",
    MembershipDomainEventType.EXPIRED: "membership_expired",
    DonationDomainEventType.RECEIVED: "donation_confirmation",
}


class UnsupportedWebhookEvent(Exception):
    """Evento de proveedor no definido por la arquitectura."""


class InvalidWebhookPayload(Exception):
    """Payload no parseable por el proveedor."""


@dataclass(frozen=True)
class WebhookResult:
    outcome: str  # processed | ignored_duplicate | ignored_unsupported | invalid_payload
    provider: str = ""
    provider_event_id: str = ""
    note: str = ""


class ProcessPaymentWebhookUseCase:
    def __init__(
        self,
        *,
        provider: PaymentProvider,
        payment_events: PaymentEventRepository,
        memberships: MembershipRepository,
        donations: DonationRepository,
        communications: CommunicationEventRepository,
        uow: UnitOfWork,
    ) -> None:
        self._provider = provider
        self._payment_events = payment_events
        self._memberships = memberships
        self._donations = donations
        self._communications = communications
        self._uow = uow
        self._machine = MembershipStateMachine()

    def execute(self, payload: object) -> WebhookResult:
        try:
            event = self._provider.parse_webhook(payload)
        except Exception as exc:
            raise InvalidWebhookPayload(str(exc)) from exc

        return self._process(event)

    def _process(self, event: PaymentProviderEvent) -> WebhookResult:
        provider, event_id = event.provider, event.provider_event_id

        # Idempotencia: si ya existe, no reprocesar (ADR-007) → 2xx.
        existing = self._payment_events.get_by_idempotency_key(provider, event_id)
        if existing is not None:
            return WebhookResult(
                outcome="ignored_duplicate",
                provider=provider,
                provider_event_id=event_id,
                note="evento ya registrado (idempotente)",
            )

        domain_event_type = _PROVIDER_TO_DOMAIN.get(event.event_type)
        if domain_event_type is None:
            # Evento no definido: se registra como ignorado, sin efecto.
            self._register(event, PaymentEventStatus.PROCESSED)
            self._uow.commit()
            return WebhookResult(
                outcome="ignored_unsupported",
                provider=provider,
                provider_event_id=event_id,
                note=f"evento no soportado: {event.event_type}",
            )

        # Registrar el PaymentEvent ANTES de aplicar efectos (ADR-007). En la misma
        # transacción se aplican los efectos; si algo falla, rollback atómico.
        payment_event = self._register(event, PaymentEventStatus.PROCESSED)
        try:
            if isinstance(domain_event_type, DonationDomainEventType):
                self._apply_donation(event, domain_event_type)
            else:
                self._apply_membership(event, domain_event_type)
        except Exception:
            self._uow.rollback()
            raise

        self._enqueue_communication(event, domain_event_type, payment_event)
        self._uow.commit()
        return WebhookResult(
            outcome="processed",
            provider=provider,
            provider_event_id=event_id,
            note=f"procesado ({event.event_type})",
        )

    def _register(self, event: PaymentProviderEvent, status: PaymentEventStatus) -> PaymentEvent:
        payment_event = PaymentEvent(
            id=None,
            provider=event.provider,
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            user_id=event.user_id,
            payload_hash=event.payload_hash,
            status=status,
            received_at=event.received_at,
            processed_at=datetime.now(UTC),
        )
        try:
            self._payment_events.add(payment_event)
        except DuplicatePaymentEventError:
            # Concurrencia: otro request registró el mismo evento.
            raise
        return payment_event

    # --- efectos de negocio -------------------------------------------------

    def _apply_membership(
        self, event: PaymentProviderEvent, domain_type: MembershipDomainEventType
    ) -> None:
        user_id = event.user_id
        if user_id is None:
            return  # sin identidad → sin efecto (ADR-002: no inventar identidad)

        if domain_type == MembershipDomainEventType.CREATED:
            self._create_membership_from_subscription(event)
            return

        # Para transiciones se busca la Membership existente del usuario.
        membership = self._memberships.list_by_user(user_id)
        if not membership:
            return
        current = membership[0]
        domain_event = DomainEvent(
            event_type=domain_type,
            user_id=user_id,
            provider_event_id=event.provider_event_id,
            occurred_at=event.received_at,
        )
        # Re-aplicar en el objeto (los repos devuelven objetos vivos de la sesión).
        self._machine.apply(current, domain_event)
        self._memberships.add(current)

    def _create_membership_from_subscription(self, event: PaymentProviderEvent) -> None:
        meta = event.metadata
        subscription_id = _s(meta.get("subscription_id")) or event.provider_event_id
        amount_minor = _i(meta.get("amount_minor"))
        currency = _s(meta.get("currency")) or "EUR"
        periodicity = Periodicity(_s(meta.get("periodicity")) or "monthly")
        level = MembershipLevel(_s(meta.get("level")) or "supporter")
        membership = Membership(
            id=None,
            user_id=event.user_id or "",
            status=MembershipStatus.PENDING,
            level=level,
            periodicity=periodicity,
            amount_minor=amount_minor,
            currency=currency,
            provider=event.provider,
            customer_id=_s(meta.get("customer_id")) or "",
            subscription_id=subscription_id,
            email_contact=_s(meta.get("email_contact")) or "",
        )
        self._memberships.add(membership)

    def _apply_donation(
        self, event: PaymentProviderEvent, domain_type: DonationDomainEventType
    ) -> None:
        if event.user_id is None:
            return
        meta = event.metadata
        donation = Donation(
            id=None,
            user_id=event.user_id,
            amount_minor=_i(meta.get("amount_minor")) or 0,
            currency=_s(meta.get("currency")) or "EUR",
            provider=event.provider,
            charge_id=_s(meta.get("charge_id")) or event.provider_event_id,
            receipt_id=_s(meta.get("receipt_id")),
            email_receipt=_s(meta.get("email_contact")) or "",
            donated_at=event.received_at,
        )
        self._donations.add(donation)

    # --- comunicación (sin envío; ADR-006) ----------------------------------

    def _enqueue_communication(
        self,
        event: PaymentProviderEvent,
        domain_type: object,
        payment_event: PaymentEvent,
    ) -> None:
        template = _DOMAIN_TO_TEMPLATE.get(domain_type)
        if template is None or event.user_id is None:
            return
        communication = CommunicationEvent(
            id=None,
            user_id=event.user_id,
            template=template,
            recipient_email=_s(event.metadata.get("email_contact")) or "",
            status=CommunicationEventStatus.PENDING,
            attempts=0,
            next_attempt_at=None,
            origin_event_id=payment_event.id,
        )
        self._communications.add(communication)


def _s(value: object) -> str:
    return str(value) if value is not None else ""


def _i(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
