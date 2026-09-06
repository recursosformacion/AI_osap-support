"""Tests de las implementaciones reales añadidas para cerrar osap-support.

Cubren (sin red real; JWKS/tokens generados localmente y SMTP/PayPal con stubs):
- JwksIdentityResolver: token firmado RS256 válido/inválido/sin kid/exp y servicio.
- PayPalPaymentProvider: checkout donation/order, subscription sin plan_id, parse de
  webhook normalizado, verify_webhook con fallos explícitos.
- SmtpEmailSender: plantilla inexistente/host ausente rechazados.
- Worker: production exige SMTP real; dev usa fake; runner run_once.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from application.use_cases.process_communication_events import WorkerSummary
from domain.ports.email import EmailMessage
from domain.ports.identity import IdentityError
from domain.ports.payment import PaymentMode
from infrastructure.config import Settings
from infrastructure.email.fake_email_sender import FakeEmailSender
from infrastructure.email.smtp_email_sender import (
    DEFAULT_TEMPLATES,
    EmailSendError,
    SmtpEmailSender,
    SmtpSettings,
)
from infrastructure.identity.jwks_identity_resolver import JwksIdentityResolver
from infrastructure.payment.paypal_payment_provider import PayPalError, PayPalPaymentProvider
from infrastructure.worker import EmailProviderMissing, WorkerRunner, build_email_sender

JWKS_URI = "https://auth.osap/auth/.well-known/jwks.json"
ISSUER = "https://auth.osap"
AUDIENCE = "osap-support"
KID = "test-kid"


class _SigningKeyProvider:
    """Sustituye al PyJWKClient: entrega una PyJWK construida con la clave local."""

    def __init__(self, public_numbers: object, kid: str) -> None:
        numbers = public_numbers
        self._jwk = {
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64(numbers.n),  # type: ignore[attr-defined]
            "e": _b64(numbers.e),  # type: ignore[attr-defined]
        }

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        header = jwt.get_unverified_header(token)
        if header.get("kid") != self._jwk["kid"]:
            raise jwt.InvalidKeyError("kid desconocido")
        return jwt.PyJWK(self._jwk, algorithm="RS256")


def _b64(value: int) -> str:
    length = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


@pytest.fixture
def rsa_key() -> object:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    key: RSAPrivateKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key


def _public_numbers(key: object) -> object:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    if isinstance(key, RSAPrivateKey):
        return key.public_key().public_numbers()
    raise TypeError("clave no RSA")


def _sign(key: object, claims: dict) -> str:
    base = {
        "iss": ISSUER,
        "sub": "uuid-1234",
        "aud": AUDIENCE,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        "token_use": "user",
        "typ": "access",
    }
    base.update(claims)
    return jwt.encode(base, key, algorithm="RS256", headers={"kid": KID})  # type: ignore[arg-type]


def _resolver(rsa_key: object) -> JwksIdentityResolver:
    resolver = JwksIdentityResolver(jwks_uri=JWKS_URI, issuer=ISSUER, audience=AUDIENCE)
    resolver._jwks = _SigningKeyProvider(_public_numbers(rsa_key), KID)  # type: ignore[assignment]
    return resolver


def test_jwks_resolver_requires_configuration() -> None:
    with pytest.raises(IdentityError):
        JwksIdentityResolver(jwks_uri="", issuer="", audience="")


def test_jwks_valid_user_token(rsa_key: object) -> None:
    resolver = _resolver(rsa_key)
    token = _sign(rsa_key, {"sub": "uuid-1234"})
    assert resolver.resolve_user_id(f"Bearer {token}") == "uuid-1234"


def test_jwks_rejects_service_token(rsa_key: object) -> None:
    resolver = _resolver(rsa_key)
    token = _sign(rsa_key, {"token_use": "service", "typ": "service", "sub": "client-1"})
    with pytest.raises(IdentityError):
        resolver.resolve_user_id(token)


def test_jwks_rejects_wrong_audience(rsa_key: object) -> None:
    resolver = _resolver(rsa_key)
    token = _sign(rsa_key, {"aud": "otra-app"})
    with pytest.raises(IdentityError):
        resolver.resolve_user_id(token)


def test_jwks_rejects_unknown_kid(rsa_key: object) -> None:
    resolver = _resolver(rsa_key)
    claims = {
        "iss": ISSUER,
        "sub": "uuid-1",
        "aud": AUDIENCE,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": "otro-kid"})  # type: ignore[arg-type]
    with pytest.raises(IdentityError):
        resolver.resolve_user_id(token)


def test_jwks_rejects_expired(rsa_key: object) -> None:
    resolver = _resolver(rsa_key)
    token = _sign(rsa_key, {"exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp())})
    with pytest.raises(IdentityError):
        resolver.resolve_user_id(token)


def test_paypal_requires_creds_and_mode() -> None:
    with pytest.raises(PayPalError):
        PayPalPaymentProvider(mode="sandbox", client_id="", client_secret="")
    with pytest.raises(PayPalError):
        PayPalPaymentProvider(mode="production", client_id="a", client_secret="b")


def test_paypal_donation_zero_amount_rejected() -> None:
    provider = PayPalPaymentProvider(mode="sandbox", client_id="c", client_secret="s")
    with pytest.raises(PayPalError):
        provider.create_checkout(
            user_id="u1", mode=PaymentMode.DONATION, amount_minor=0, currency="EUR", return_url="/r"
        )


def test_paypal_subscription_requires_plan_id() -> None:
    provider = PayPalPaymentProvider(
        mode="sandbox", client_id="c", client_secret="s", plan_ids={}
    )
    with pytest.raises(PayPalError):
        provider.create_checkout(
            user_id="u1",
            mode=PaymentMode.MEMBERSHIP,
            amount_minor=500,
            currency="EUR",
            return_url="/r",
        )


def test_paypal_verify_webhook_without_webhook_id_fails() -> None:
    provider = PayPalPaymentProvider(mode="sandbox", client_id="c", client_secret="s")
    with pytest.raises(PayPalError):
        provider.verify_webhook(b"{}", {})


def test_paypal_verify_webhook_missing_headers_fails() -> None:
    provider = PayPalPaymentProvider(
        mode="sandbox", client_id="c", client_secret="s", webhook_id="wh_1"
    )
    with pytest.raises(PayPalError):
        provider.verify_webhook(b"{}", {"content-type": "application/json"})


def test_paypal_parse_webhook_normalizes() -> None:
    provider = PayPalPaymentProvider(mode="sandbox", client_id="c", client_secret="s")
    payload = {
        "id": "WH-123",
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "custom_id": "uuid-9",
            "amount": {"currency_code": "EUR", "value": "5.00"},
            "supplementary_data": {"related_ids": {"order_id": "ORD-1"}},
            "id": "CAP-1",
        },
    }
    event = provider.parse_webhook(payload)
    assert event.provider == "paypal"
    assert event.event_type == "payment.succeeded"
    assert event.user_id == "uuid-9"
    assert event.metadata["amount_minor"] == 500
    assert event.metadata["currency"] == "EUR"
    assert event.idempotency_key == ("paypal", "WH-123")


def test_paypal_parse_webhook_invalid() -> None:
    provider = PayPalPaymentProvider(mode="sandbox", client_id="c", client_secret="s")
    with pytest.raises(PayPalError):
        provider.parse_webhook({})


def test_smtp_unknown_template_rejected() -> None:
    sender = SmtpEmailSender(
        SmtpSettings(host="smtp.test", from_address="a@b.c"), templates=DEFAULT_TEMPLATES
    )
    with pytest.raises(EmailSendError):
        sender.send(EmailMessage(template="unknown", recipient_email="x@y.z"))


def test_smtp_missing_host_fails() -> None:
    with pytest.raises(EmailSendError):
        SmtpEmailSender(
            SmtpSettings(host="", from_address="a@b.c"), templates=DEFAULT_TEMPLATES
        )


def test_worker_production_requires_smtp(monkeypatch) -> None:
    monkeypatch.delenv("OSAP_SUPPORT_EMAIL_SENDER", raising=False)
    settings = Settings(env="production")
    with pytest.raises(EmailProviderMissing):
        build_email_sender(settings)


def test_worker_dev_uses_fake(monkeypatch) -> None:
    monkeypatch.delenv("OSAP_SUPPORT_EMAIL_SENDER", raising=False)
    settings = Settings(env="test")
    assert isinstance(build_email_sender(settings), FakeEmailSender)


def test_worker_runner_once() -> None:
    runner = WorkerRunner(process=lambda: WorkerSummary(processed=0, sent=0, failed=0))
    assert runner.run_once().processed == 0
