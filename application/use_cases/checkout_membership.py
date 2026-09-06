"""Caso de uso: checkout de membresía (recurrente).

Consume el port `PaymentProvider` (ADR-005). No conoce el proveedor concreto.
ADR-004: la membresía es una relación recurrente.

Regla de seguridad: el importe/plan NO llega del navegador. El backend resuelve
`plan_id` a partir de `level`+`periodicity` (configuración interna del proveedor).
"""

from __future__ import annotations

from domain.ports.payment import CheckoutSession, PaymentMode, PaymentProvider


class CheckoutMembershipUseCase:
    def __init__(self, payment_provider: PaymentProvider) -> None:
        self._provider = payment_provider

    def execute(
        self,
        *,
        user_id: str,
        level: str,
        periodicity: str,
        return_url: str,
    ) -> CheckoutSession:
        return self._provider.create_checkout(
            user_id=user_id,
            mode=PaymentMode.MEMBERSHIP,
            # El importe lo fija el plan del proveedor (level+periodicity), nunca el
            # navegador: se envía 0/"" y PayPalProvider lo ignora en este modo.
            amount_minor=0,
            currency="",
            return_url=return_url,
            level=level,
            periodicity=periodicity,
        )
