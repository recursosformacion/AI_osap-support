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
    SupportMember,
)
from domain.events import DomainEvent, DonationDomainEventType, MembershipDomainEventType
from domain.exceptions import DuplicatePaymentEventError
from domain.ports.payment import PaymentProvider, PaymentProviderEvent
from domain.ports.repositories import (
    CommunicationEventRepository,
    DonationRepository,
    MembershipRepository,
    PaymentEventRepository,
    SupportMemberRepository,
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
        support_members: SupportMemberRepository,
        uow: UnitOfWork,
        webhook_verifier: object | None = None,
    ) -> None:
        self._provider = provider
        self._payment_events = payment_events
        self._memberships = memberships
        self._donations = donations
        self._communications = communications
        self._support_members = support_members
        self._uow = uow
        self._machine = MembershipStateMachine()
        # Verificador de firma del proveedor (p. ej. PayPal verify-webhook-signature).
        # En dev/test suele ser None (fakes); en production SIEMPRE debe estar presente:
        # si falta, el endpoint rechaza el evento (nunca procesa payload sin verificar).
        self._webhook_verifier = webhook_verifier

    def execute(self, payload: object) -> WebhookResult:
        try:
            event = self._provider.parse_webhook(payload)
        except Exception as exc:
            raise InvalidWebhookPayload(str(exc)) from exc

        return self._process(event)

    @property
    def has_verifier(self) -> bool:
        """True si el wiring inyectó un verificador de firma real (production)."""
        return self._webhook_verifier is not None

    def verify(self, raw_body: bytes, headers: dict[str, str]) -> None:
        """Verifica la firma del webhook antes de parsear/procesar.

        En production el wiring inyecta el verificador real (PayPal). Sin verificador
        configurado, el endpoint rechaza (fail-fast) en lugar de procesar payloads
        arbitrarios.
        """
        if self._webhook_verifier is None:
            raise InvalidWebhookPayload("verificador de firma no configurado (webhook rechazado)")
        verifier = self._webhook_verifier
        try:
            verify = getattr(verifier, "verify_webhook", None)
            if verify is None:
                raise InvalidWebhookPayload("verificador sin método verify_webhook")
            verify(raw_body, headers)
        except InvalidWebhookPayload:
            raise
        except Exception as exc:
            raise InvalidWebhookPayload(str(exc)) from exc

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
            if event.user_id is not None:
                # ADR-002/ADR-003: la relación SupportMember debe existir antes de
                # memberships/donations (FK). Creación idempotente.
                self._ensure_support_member(event.user_id)
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

    def _ensure_support_member(self, user_id: str) -> None:
        """Crea la relación SupportMember si no existe (FK memberships/donations)."""
        if self._support_members.exists(user_id):
            return
        self._support_members.add(SupportMember(user_id=user_id, created_at=datetime.now(UTC)))

    # --- efectos de negocio -------------------------------------------------

    def _apply_membership(
        self, event: PaymentProviderEvent, domain_type: MembershipDomainEventType
    ) -> None:
        meta = event.metadata
        subscription_id = _s(meta.get("subscription_id")) or ""

        # Binding robusto (paypal E2E): el evento puede traer custom_id o no.
        # 1) user_id (custom_id) presente → binding directo en la creación.
        if domain_type == MembershipDomainEventType.CREATED:
            if event.user_id is None:
                return  # sin identidad → sin efecto (no inventar, ADR-002)
            self._create_membership_from_subscription(event)
            return

        # 2) Transiciones: buscar la membership por subscription_id (binding real por
        #    PayPal), NO por list_by_user[0] (evita mezclar suscripciones del usuario).
        membership = None
        if subscription_id:
            membership = self._memberships.get_by_subscription(
                event.provider, subscription_id
            )
        if membership is None and event.user_id is not None:
            rows = self._memberships.list_by_user(event.user_id)
            membership = rows[0] if rows else None
        if membership is None:
            return  # sin membership a la que aplicar la transición

        # Fallback de binding: sin custom_id pero con subscription_id + membership
        # PENDING/ACTIVA local → la identidad es la de esa membership (bind indirecto).
        effective_user_id = event.user_id or membership.user_id

        # El mismo webhook de pago significa cosas distintas según el estado actual:
        # - membership ACTIVE + payment.succeeded → RENOVACIÓN (refresca fechas);
        # - membership PAST_DUE + payment.succeeded → RECUPERACIÓN.
        if domain_type == MembershipDomainEventType.ACTIVATED:
            if membership.status is MembershipStatus.ACTIVE:
                domain_type = MembershipDomainEventType.RENEWED
            elif membership.status is MembershipStatus.PAST_DUE:
                domain_type = MembershipDomainEventType.RECOVERED

        # Fechas reales de PayPal (billing_info.next_billing_time / start_time) tienen
        # prioridad; la máquina solo computa cuando no vienen (next_renewal_at None).
        next_at = _parse_iso(_s(meta.get("next_billing_time")))
        if next_at is not None:
            membership.next_renewal_at = next_at
        started = _parse_iso(_s(meta.get("start_time")))
        if started is not None and membership.started_at is None:
            membership.started_at = started

        domain_event = DomainEvent(
            event_type=domain_type,
            user_id=effective_user_id,
            provider_event_id=event.provider_event_id,
            occurred_at=event.received_at,
        )
        self._machine.apply(membership, domain_event)
        self._memberships.add(membership)

    def _create_membership_from_subscription(self, event: PaymentProviderEvent) -> None:
        meta = event.metadata
        subscription_id = _s(meta.get("subscription_id")) or event.provider_event_id
        amount_minor = _i(meta.get("amount_minor"))
        currency = _s(meta.get("currency")) or "EUR"
        # plan_id → level/periodicity resuelto por el provider (nunca defaults si el
        # plan real está configurado).
        periodicity = Periodicity(_s(meta.get("periodicity")) or "monthly")
        level = MembershipLevel(_s(meta.get("level")) or "supporter")
        started = _parse_iso(_s(meta.get("start_time"))) or event.received_at
        next_at = _parse_iso(_s(meta.get("next_billing_time")))
        # PayPal BILLING.SUBSCRIPTION.ACTIVATED = suscripción YA activa (aprobada):
        # se crea la membership en ACTIVE con las fechas reales, no en PENDING a la
        # espera de un cobro (validado con el payload real de Sandbox, 2026-09-06).
        membership = Membership(
            id=None,
            user_id=event.user_id or "",
            status=MembershipStatus.ACTIVE,
            level=level,
            periodicity=periodicity,
            amount_minor=amount_minor,
            currency=currency,
            provider=event.provider,
            customer_id=_s(meta.get("customer_id")) or "",
            subscription_id=subscription_id,
            started_at=started,
            next_renewal_at=next_at,
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


def _parse_iso(value: str) -> datetime | None:
    """ISO8601 (PayPal, con o sin offset) → datetime naive UTC para la BD."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _s(value: object) -> str:
    return str(value) if value is not None else ""


def _i(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
