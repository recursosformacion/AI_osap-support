"""Fake PaymentProvider para tests (Fase 4).

Solo para verificar que `application → PaymentProvider` funciona sin depender de un
proveedor externo. NO es una implementación productiva (la decisión de proveedor está
ABIERTA). No debe usarse fuera de tests.
"""

from __future__ import annotations

from domain.ports.payment import (
    CheckoutSession,
    PaymentMode,
    PaymentProviderEvent,
    PaymentReference,
)
from infrastructure.payment.base import BasePaymentProvider


class FakePaymentProvider(BasePaymentProvider):
    """Proveedor ficticio determinista para tests."""

    def __init__(self, provider: str = "fake") -> None:
        self.provider_id = provider
        self.checkouts: list[CheckoutSession] = []
        self.customers: dict[str, str] = {}

    def create_checkout(
        self,
        *,
        user_id: str,
        mode: PaymentMode,
        amount_minor: int,
        currency: str,
        return_url: str,
        level: str | None = None,
        periodicity: str | None = None,
    ) -> CheckoutSession:
        session = CheckoutSession(
            checkout_url=(
                f"https://{self.provider_id}-pay/{user_id}/{mode.value}/{level}/{periodicity}"
                if mode == PaymentMode.MEMBERSHIP
                else f"https://{self.provider_id}-pay/{user_id}/{mode.value}"
            ),
            return_url=return_url,
            provider_session_id=f"sess-{user_id}-{len(self.checkouts)}",
            mode=mode,
            amount_minor=amount_minor,
            currency=currency,
        )
        self.checkouts.append(session)
        return session

    def resolve_customer(self, *, user_id: str) -> str:
        if user_id not in self.customers:
            self.customers[user_id] = f"cus-{user_id}"
        return self.customers[user_id]

    def get_subscription(self, *, subscription_id: str) -> PaymentReference:
        return PaymentReference(
            provider=self.provider_id,
            customer_id="cus-1",
            subscription_id=subscription_id,
        )

    def parse_webhook(self, payload: object) -> PaymentProviderEvent:
        data = payload if isinstance(payload, dict) else {}
        metadata = data.get("metadata")
        return PaymentProviderEvent(
            provider=self.provider_id,
            provider_event_id=str(data.get("id") or "evt-unknown"),
            event_type=str(data.get("type") or "unknown"),
            user_id=data.get("user_id"),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
