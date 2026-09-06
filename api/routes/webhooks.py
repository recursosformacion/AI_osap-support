"""Ruta del webhook de pagos (Fase 6).

Adaptador HTTP: no contiene lógica de negocio ni SQL. Delega en
ProcessPaymentWebhookUseCase. Responde 2xx siempre que el evento se reconozca o sea
duplicado (ADR-007: el proveedor reintenta ante no-2xx). 400 solo ante payload inválido.
"""

from __future__ import annotations

import json

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
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="payload JSON inválido") from exc

    # Production: el wiring inyecta el verificador real (PayPal). Si está presente, la
    # firma se comprueba SIEMPRE antes de procesar (nunca se procesa un webhook sin
    # verificar). En dev/test (fakes, sin verificador) se omite explícitamente.
    if use_case.has_verifier:
        try:
            use_case.verify(raw_body, headers)
        except InvalidWebhookPayload as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = use_case.execute(payload)
    except InvalidWebhookPayload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ok",
        "outcome": result.outcome,
        "provider_event_id": result.provider_event_id,
    }
