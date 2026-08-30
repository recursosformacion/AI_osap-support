"""Base abstracta para adaptadores de PaymentProvider (Fase 4).

Los futuros proveedores concretos (decisión ABIERTA) extenderán esta base e
implementarán los métodos del port `PaymentProvider`. No hay lógica de negocio aquí;
solo el molde de infraestructura para mantener el dominio limpio (ADR-005).
"""

from __future__ import annotations

from abc import abstractmethod

from domain.ports.payment import (
    CheckoutSession,
    PaymentMode,
    PaymentProvider,
    PaymentProviderEvent,
    PaymentReference,
)


class BasePaymentProvider(PaymentProvider):
    """Molde para adaptadores de pago concretos.

    Provee helpers comunes (no provider-specific) y obliga a implementar el contrato.
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
    ) -> CheckoutSession: ...

    @abstractmethod
    def resolve_customer(self, *, user_id: str) -> str: ...

    @abstractmethod
    def get_subscription(self, *, subscription_id: str) -> PaymentReference: ...

    @abstractmethod
    def parse_webhook(self, payload: object) -> PaymentProviderEvent: ...
