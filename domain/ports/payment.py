"""Puerto de pagos — ADR-005 (V-006 FIJADA).

Support NO queda acoplado a un proveedor de pagos concreto. Este port declara la frontera
necesaria (checkout, resolución de cliente/suscripción, interpretación de eventos) para
que el proveedor sea una infraestructura intercambiable.

Reglas:
- El dominio/aplicación usan SOLO este port; nunca SDK de un proveedor (V-005 DESCARTADA).
- Contrato pequeño y estable: cada método cubre una necesidad de Support.
- V-021: importes como unidades mínimas enteras (amount_minor int) + currency ISO 4217.
- ADR-007: `PaymentProviderEvent` lleva `(provider, provider_event_id)` para que el
  registro sea idempotente.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from domain.entities import Money


class PaymentMode(Enum):
    """Modalidad del checkout: recurrente (membership) o puntual (donation).

    ADR-004: Membership y Donation son entidades separadas; el port distingue el modo
    de cobro sin acoplarse al proveedor.
    """

    MEMBERSHIP = "membership"
    DONATION = "donation"


@dataclass(frozen=True)
class CheckoutSession:
    """Sesión de pago iniciada en el proveedor (resultado del checkout)."""

    checkout_url: str
    return_url: str
    provider_session_id: str
    mode: PaymentMode
    amount_minor: int
    currency: str

    @property
    def money(self) -> Money:
        return Money(amount_minor=self.amount_minor, currency=self.currency)


@dataclass(frozen=True)
class PaymentReference:
    """Referencia estable de un cliente/suscripción en el proveedor (no datos sensibles)."""

    provider: str
    customer_id: str
    subscription_id: str | None = None


@dataclass(frozen=True)
class PaymentProviderEvent:
    """Evento entrante normalizado (webhook) — compatible con ADR-007.

    `idempotency_key = (provider, provider_event_id)`. No contiene datos sensibles.
    El procesamiento completo del webhook pertenece a la fase de webhooks.
    """

    provider: str
    provider_event_id: str
    event_type: str  # subscription.created, payment.succeeded, ...
    user_id: str | None = None
    payload_hash: str = ""
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def idempotency_key(self) -> tuple[str, str]:
        return (self.provider, self.provider_event_id)


class PaymentProvider(ABC):
    """Frontera del proveedor de pagos (no implementado todavía).

    Implementaciones concretas (Stripe/PayPal/... — decisión ABIERTA) pertenecen a
    infraestructura y deben ser intercambiables sin tocar el dominio/aplicación.
    """

    @abstractmethod
    def create_checkout(
        self,
        *,
        user_id: str,
        mode: PaymentMode,
        amount_minor: int,
        currency: str,
        return_url: str,
    ) -> CheckoutSession:
        """Crea una sesión de checkout (membership recurrente o donation puntual)."""

    @abstractmethod
    def resolve_customer(self, *, user_id: str) -> str:
        """Devuelve el customer_id del proveedor para un user_id (o lo crea)."""

    @abstractmethod
    def get_subscription(self, *, subscription_id: str) -> PaymentReference:
        """Devuelve la referencia de una suscripción del proveedor."""

    @abstractmethod
    def parse_webhook(self, payload: object) -> PaymentProviderEvent:
        """Normaliza el payload entrante del proveedor a PaymentProviderEvent.

        Lanza un error controlado si el payload no es válido o no se reconoce el evento.
        El procesamiento (máquina de estados, emails) NO ocurre aquí; es de la fase de
        webhooks. La idempotencia queda garantizada por `idempotency_key`.
        """
