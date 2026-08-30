"""Ruta del webhook de pagos (Fase 6).

Adaptador HTTP: no contiene lógica de negocio ni SQL. Delega en
ProcessPaymentWebhookUseCase. Responde 2xx siempre que el evento se reconozca o sea
duplicado (ADR-007: el proveedor reintenta ante no-2xx). 400 solo ante payload inválido.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from application.use_cases.process_payment_webhook import (
    InvalidWebhookPayload,
    ProcessPaymentWebhookUseCase,
)

router = APIRouter(prefix="/api/v1", tags=["webhooks"])

_use_case: ProcessPaymentWebhookUseCase


def wire_webhook_router(use_case: ProcessPaymentWebhookUseCase) -> APIRouter:
    global _use_case
    _use_case = use_case
    return router


@router.post("/webhooks/payment")
async def webhook_payment(
    request: Request,
    use_case: ProcessPaymentWebhookUseCase = Depends(lambda: _use_case),
) -> dict[str, str]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="payload JSON inválido") from exc

    try:
        result = use_case.execute(payload)
    except InvalidWebhookPayload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ok",
        "outcome": result.outcome,
        "provider_event_id": result.provider_event_id,
    }
