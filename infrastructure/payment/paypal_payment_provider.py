"""Adaptador PayPal REST (v2) del port PaymentProvider.

Decisión 2026-09: PayPal es el proveedor de pagos de osap-support.
- Donación (PaymentMode.DONATION)  → Orders v2 (capture simple).
- Membresía (PaymentMode.MEMBERSHIP) → Subscriptions v2 (plan_id por nivel/periodicidad).
- Webhook: se verifica la firma contra la API oficial (verify-webhook-signature) con
  transmission headers y el `webhook_id` del panel; NUNCA se confía en el navegador.

La verificación de firma y las llamadas REST usan httpx. Errores de autenticación o de
red se traducen a excepciones controladas; jamás se simula un pago.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from domain.ports.payment import (
    CheckoutSession,
    PaymentMode,
    PaymentProviderEvent,
    PaymentReference,
)
from infrastructure.payment.base import BasePaymentProvider

_API_BASE = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


class PayPalError(RuntimeError):
    """Error controlado del adaptador PayPal (autenticación, API o webhook)."""


def _minor_to_decimal(amount_minor: int, currency: str) -> str:
    """amount_minor (unidades mínimas) → decimal string para PayPal.

    Solo divisas de 2 decimales (EUR/USD/GBP...). JPY y otras de 0 decimales NO se
    soportan: si currency no es 2-decimal se falla explícito (V-021, nunca float).
    """
    if currency in ("JPY", "KRW", "CLP", "VND"):
        raise PayPalError(f"currency sin decimales no soportada: {currency}")
    return f"{amount_minor // 100}.{amount_minor % 100:02d}"


# Mapas de niveles/periodicidad → plan_id configurado por entorno (panel PayPal).
# Se inyectan desde configuración; sin plan_id la membresía falla explícito.
_PLAN_KEYS = {
    ("supporter", "monthly"): "OSAP_SUPPORT_PAYPAL_PLAN_SUPPORTER_MONTHLY",
    ("supporter", "yearly"): "OSAP_SUPPORT_PAYPAL_PLAN_SUPPORTER_YEARLY",
    ("contributor", "monthly"): "OSAP_SUPPORT_PAYPAL_PLAN_CONTRIBUTOR_MONTHLY",
    ("contributor", "yearly"): "OSAP_SUPPORT_PAYPAL_PLAN_CONTRIBUTOR_YEARLY",
    ("voice", "monthly"): "OSAP_SUPPORT_PAYPAL_PLAN_VOICE_MONTHLY",
    ("voice", "yearly"): "OSAP_SUPPORT_PAYPAL_PLAN_VOICE_YEARLY",
    ("founder", "monthly"): "OSAP_SUPPORT_PAYPAL_PLAN_FOUNDER_MONTHLY",
    ("founder", "yearly"): "OSAP_SUPPORT_PAYPAL_PLAN_FOUNDER_YEARLY",
}


class PayPalPaymentProvider(BasePaymentProvider):
    """Proveedor real de pagos vía PayPal REST v2.

    En el constructor valida configuración (modo + credenciales). Sin ellas:
    :class:`PayPalError`, que el wiring convierte en fail-fast en production.
    """

    def __init__(
        self,
        *,
        mode: str,
        client_id: str,
        client_secret: str,
        webhook_id: str = "",
        return_url: str = "https://app.openmusicrepository.com/support/return",
        cancel_url: str = "https://app.openmusicrepository.com/support",
        plan_ids: dict[tuple[str, str], str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if mode not in _API_BASE:
            raise PayPalError(f"modo PayPal inválido: {mode!r} (sandbox|live)")
        if not client_id or not client_secret:
            raise PayPalError("client_id/client_secret de PayPal no configurados")
        self.provider_id = "paypal"
        self._mode = mode
        self._client_id = client_id
        self._client_secret = client_secret
        self._webhook_id = webhook_id
        self._return_url = return_url
        self._cancel_url = cancel_url
        self._plan_ids = dict(plan_ids or {})
        self._base = _API_BASE[mode]
        self._http = http_client or httpx.Client(timeout=20.0)
        self._access_token: str | None = None

    # -- internals ------------------------------------------------------------

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        resp = self._http.post(
            f"{self._base}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise PayPalError(f"oauth token falló ({resp.status_code}): {resp.text[:200]}")
        self._access_token = str(resp.json().get("access_token") or "")
        if not self._access_token:
            raise PayPalError("PayPal no devolvió access_token")
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # -- contrato PaymentProvider ---------------------------------------------

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
        if mode == PaymentMode.DONATION:
            if amount_minor <= 0:
                raise PayPalError("amount_minor debe ser positivo")
            return self._create_order(user_id, amount_minor, currency, return_url)
        if level is None or periodicity is None:
            raise PayPalError("level y periodicity son obligatorios para membresía")
        return self._create_subscription(user_id, level, periodicity, return_url)

    def resolve_customer(self, *, user_id: str) -> str:
        # PayPal no tiene "customer" canónico para Orders/Subscriptions públicas;
        # la trazabilidad es por custom_id/metadata (user_id), no por un customer_id.
        return f"osap-{user_id}"

    def get_subscription(self, *, subscription_id: str) -> PaymentReference:
        resp = self._http.get(
            f"{self._base}/v1/billing/subscriptions/{subscription_id}",
            headers=self._headers(),
        )
        if resp.status_code != 200:
            raise PayPalError(f"get_subscription falló ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        return PaymentReference(
            provider="paypal",
            customer_id="",
            subscription_id=str(data.get("id") or subscription_id),
        )

    def parse_webhook(self, payload: object) -> PaymentProviderEvent:
        """Normaliza un evento PayPal a PaymentProviderEvent (sin verificar firma).

        La verificación de firma se hace ANTES en el endpoint con :meth:`verify_webhook`
        (body crudo + headers). Este método solo parsea el payload ya verificado.
        """
        data = payload if isinstance(payload, dict) else {}
        event_id = str(data.get("id") or "")
        event_type = str(data.get("event_type") or "")
        if not event_id or not event_type:
            raise PayPalError("payload de webhook PayPal inválido")
        raw_resource = data.get("resource")
        resource: dict[Any, Any] = raw_resource if isinstance(raw_resource, dict) else {}
        raw_payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        meta = {
            "resource": resource,
            "amount_minor": _extract_amount_minor(resource),
            "currency": _extract_currency(resource),
            "email_contact": _extract_email(resource),
            "subscription_id": _extract_subscription_id(resource),
            "order_id": _extract_order_id(resource),
            "charge_id": _extract_capture_id(resource),
        }
        return PaymentProviderEvent(
            provider="paypal",
            provider_event_id=event_id,
            event_type=_normalize_event_type(event_type),
            user_id=_extract_custom_id(resource, data),
            payload_hash=hashlib.sha256(raw_payload.encode("utf-8")).hexdigest(),
            received_at=datetime.now(UTC),
            metadata=meta,
        )

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> None:
        """Verifica la firma del webhook PayPal (verify-webhook-signature API).

        Requiere `webhook_id` del panel. Sin él, el endpoint rechaza el evento
        (nunca lo procesa como si fuera válido).
        """
        if not self._webhook_id:
            raise PayPalError("webhook_id de PayPal no configurado (firma no verificable)")
        transmission_id = headers.get("paypal-transmission-id")
        transmission_time = headers.get("paypal-transmission-time")
        transmission_sig = headers.get("paypal-transmission-sig")
        cert_url = headers.get("paypal-cert-url")
        auth_algo = headers.get("paypal-auth-algo")
        if not all((transmission_id, transmission_time, transmission_sig, cert_url, auth_algo)):
            raise PayPalError("headers de transmisión PayPal incompletos")

        body_text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
        verify_payload = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": self._webhook_id,
            "webhook_event": json.loads(body_text),
        }
        resp = self._http.post(
            f"{self._base}/v1/notifications/verify-webhook-signature",
            json=verify_payload,
            headers=self._headers(),
        )
        if resp.status_code != 200:
            raise PayPalError(f"verificación de webhook falló ({resp.status_code})")
        if resp.json().get("verification_status") != "SUCCESS":
            raise PayPalError("firma de webhook PayPal NO verificada")

    # -- operaciones concreto (Orders / Subscriptions) ------------------------

    def _create_order(
        self, user_id: str, amount_minor: int, currency: str, return_url: str
    ) -> CheckoutSession:
        amount = _minor_to_decimal(amount_minor, currency)
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "custom_id": user_id,
                    "amount": {"currency_code": currency, "value": amount},
                }
            ],
            "application_context": {
                "return_url": return_url,
                "cancel_url": self._cancel_url,
                "brand_name": "OpenMusicRepository",
                "user_action": "PAY_NOW",
            },
        }
        resp = self._http.post(
            f"{self._base}/v2/checkout/orders",
            json=body,
            headers=self._headers(),
        )
        if resp.status_code not in (200, 201):
            raise PayPalError(f"crear order falló ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        approve = next(
            (h.get("href") for h in data.get("links", []) if h.get("rel") == "approve"),
            "",
        )
        if not approve:
            raise PayPalError("PayPal no devolvió link de aprobación")
        return CheckoutSession(
            checkout_url=approve,
            return_url=return_url,
            provider_session_id=str(data.get("id") or ""),
            mode=PaymentMode.DONATION,
            amount_minor=amount_minor,
            currency=currency,
        )

    def _create_subscription(
        self, user_id: str, level: str, periodicity: str, return_url: str
    ) -> CheckoutSession:
        plan_key = (level, periodicity)
        plan_id = self._plan_ids.get(plan_key) or ""
        if not plan_id:
            env = _PLAN_KEYS.get(plan_key)
            raise PayPalError(
                f"plan_id PayPal no configurado para {level}/{periodicity}"
                + (f" (env {env})" if env else "")
            )
        body = {
            "plan_id": plan_id,
            "custom_id": user_id,
            "application_context": {
                "return_url": return_url,
                "cancel_url": self._cancel_url,
                "brand_name": "OpenMusicRepository",
                "user_action": "SUBSCRIBE_NOW",
            },
        }
        resp = self._http.post(
            f"{self._base}/v1/billing/subscriptions",
            json=body,
            headers=self._headers(),
        )
        if resp.status_code not in (200, 201):
            raise PayPalError(f"crear subscription falló ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        approve = next(
            (h.get("href") for h in data.get("links", []) if h.get("rel") == "approve"),
            "",
        )
        if not approve:
            raise PayPalError("PayPal no devolvió link de aprobación")
        return CheckoutSession(
            checkout_url=approve,
            return_url=return_url,
            provider_session_id=str(data.get("id") or ""),
            mode=PaymentMode.MEMBERSHIP,
            # El importe lo fija el plan (level+periodicity); aquí 0/"" hasta que el
            # webhook PayPal reporte el cobro real (V-021).
            amount_minor=0,
            currency="",
        )


# --- helpers de extracción ---------------------------------------------------


def _extract_custom_id(resource: dict, envelope: dict) -> str | None:
    for holder in (resource, envelope):
        custom = holder.get("custom_id")
        if isinstance(custom, str) and custom:
            return custom
        po = holder.get("purchase_units")
        if isinstance(po, list):
            for unit in po:
                if isinstance(unit, dict) and isinstance(unit.get("custom_id"), str):
                    return unit["custom_id"]
    return None


def _extract_amount_minor(resource: dict) -> int:
    for holder in (resource, resource.get("amount")):
        if not isinstance(holder, dict):
            continue
        value = holder.get("value")
        if not isinstance(value, str):
            continue
        try:
            whole, _, frac = value.partition(".")
            return int(whole) * 100 + int((frac or "00")[:2].ljust(2, "0"))
        except ValueError:
            return 0
    return 0


def _extract_currency(resource: dict) -> str:
    amount = resource.get("amount")
    if isinstance(amount, dict):
        return str(amount.get("currency_code") or "")
    return str(resource.get("currency_code") or "")


def _extract_email(resource: dict) -> str:
    payer = resource.get("payer")
    if isinstance(payer, dict):
        return str(payer.get("email_address") or "")
    return ""


def _extract_subscription_id(resource: dict) -> str:
    has_plan = "plan_id" in resource
    has_sub_status = "subscription" in str(resource.get("status", "")).lower()
    if has_plan or has_sub_status:
        return str(resource.get("id") or "")
    return ""


def _extract_order_id(resource: dict) -> str:
    return str(resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id") or "")


def _extract_capture_id(resource: dict) -> str:
    return str(resource.get("id") or "")


def _normalize_event_type(event_type: str) -> str:
    """Evento PayPal → tipo normalizado del dominio (arquitectura §4.4)."""
    mapping = {
        "BILLING.SUBSCRIPTION.ACTIVATED": "subscription.created",
        "PAYMENT.SALE.COMPLETED": "payment.succeeded",
        "PAYMENT.CAPTURE.COMPLETED": "payment.succeeded",
        "PAYMENT.SALE.DENIED": "payment.failed",
        "BILLING.SUBSCRIPTION.SUSPENDED": "payment.failed",
        "BILLING.SUBSCRIPTION.CANCELLED": "subscription.cancelled",
        "BILLING.SUBSCRIPTION.EXPIRED": "subscription.expired",
        "CHECKOUT.ORDER.APPROVED": "donation.succeeded",
        "PAYMENT.CAPTURE.DENIED": "payment.failed",
    }
    return mapping.get(event_type, event_type)
