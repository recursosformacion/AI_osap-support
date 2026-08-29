"""Puerto de pagos — ADR-005 (V-006 FIJADA).

Support NO queda acoplado a un proveedor de pagos concreto. Este port declara la frontera
necesaria (checkout, resolución de cliente/suscripción) para que el proveedor sea una
infraestructura intercambiable. NO se implementa ningún proveedor en esta fase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckoutSession:
    checkout_url: str
    return_url: str
    provider_session_id: str


@dataclass(frozen=True)
class PaymentReference:
    provider: str
    customer_id: str
    subscription_id: str | None = None


class PaymentProvider(ABC):
    """Frontera conceptual del proveedor de pagos (no implementado todavía)."""

    @abstractmethod
    def create_membership_checkout(self, *, user_id: str, return_url: str) -> CheckoutSession: ...

    @abstractmethod
    def resolve_customer(self, *, user_id: str) -> str:
        """Devuelve el customer_id del proveedor para un user_id (o lo crea)."""

    @abstractmethod
    def get_subscription(self, *, subscription_id: str) -> PaymentReference: ...
