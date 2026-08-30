"""Caso de uso: checkout de donación (puntual).

Consume el port `PaymentProvider` (ADR-005). No conoce el proveedor concreto.
ADR-004: la donación es una aportación puntual, separada de la membresía.
"""

from __future__ import annotations

from domain.ports.payment import CheckoutSession, PaymentMode, PaymentProvider


class CheckoutDonationUseCase:
    def __init__(self, payment_provider: PaymentProvider) -> None:
        self._provider = payment_provider

    def execute(
        self,
        *,
        user_id: str,
        amount_minor: int,
        currency: str,
        return_url: str,
    ) -> CheckoutSession:
        return self._provider.create_checkout(
            user_id=user_id,
            mode=PaymentMode.DONATION,
            amount_minor=amount_minor,
            currency=currency,
            return_url=return_url,
        )
