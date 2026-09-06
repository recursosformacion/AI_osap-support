"""Wiring por entorno (ADR: fail-fast en production).

Verifica que:
- en production NINGÚN fake de identidad/pagos se puede wirear (el arranque falla);
- en development/test los fakes siguen disponibles;
- el error de production es explícito (no un fallback silencioso).
"""

from __future__ import annotations

import pytest

from api.main import ProductionWiringError, _identity_for, _payment_for
from infrastructure.config import PROJECT_ROOT, Settings
from infrastructure.identity.jwks_identity_resolver import JwksIdentityResolver
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver
from infrastructure.payment.fake_payment_provider import FakePaymentProvider
from infrastructure.payment.paypal_payment_provider import PayPalPaymentProvider


def _settings(env: str) -> Settings:
    s = Settings(env=env)
    s.server.dev_token = "dev-token"
    s.server.dev_user_id = "dev-user"
    return s


def _settings_without_toml(env: str) -> Settings:
    """Settings sin fichero toml (simula entorno sin configuración obligatoria)."""
    s = Settings(env=env, toml_file=PROJECT_ROOT / "no-such-osap-support.toml")
    s.server.dev_token = "dev-token"
    s.server.dev_user_id = "dev-user"
    return s


class TestProductionFailFast:
    def test_production_identity_fails_fast(self) -> None:
        with pytest.raises(ProductionWiringError) as exc:
            _identity_for(_settings_without_toml("production"))
        assert "Production identity provider is not configured" in str(exc.value)
        assert "OSAP_SUPPORT_AUTH_JWKS_URI" in str(exc.value)

    def test_production_payment_fails_fast(self) -> None:
        with pytest.raises(ProductionWiringError) as exc:
            _payment_for(_settings_without_toml("production"))
        assert "Production payment provider is not configured" in str(exc.value)
        assert "OSAP_SUPPORT_PAYPAL_MODE" in str(exc.value)

    def test_production_identity_requires_real_config(self) -> None:
        # Config parcial (solo jwks_uri, sin issuer) sigue siendo fail-fast.
        s = _settings_without_toml("production")
        s.identity.jwks_uri = "https://auth.osap/auth/.well-known/jwks.json"
        s.identity.issuer = ""
        with pytest.raises(ProductionWiringError):
            _identity_for(s)

    def test_production_identity_uses_jwks_resolver_when_configured(self) -> None:
        s = _settings_without_toml("production")
        s.identity.jwks_uri = "https://auth.osap/auth/.well-known/jwks.json"
        s.identity.issuer = "https://auth.osap"
        s.identity.audience = "osap-support"
        identity = _identity_for(s)
        assert isinstance(identity, JwksIdentityResolver)

    def test_production_payment_requires_paypal_creds(self) -> None:
        s = _settings_without_toml("production")
        s.payment.mode = "sandbox"
        s.payment.client_id = ""
        s.payment.client_secret = ""
        with pytest.raises(ProductionWiringError):
            _payment_for(s)

    def test_production_payment_uses_paypal_when_configured(self) -> None:
        s = _settings_without_toml("production")
        s.payment.mode = "sandbox"
        s.payment.client_id = "cid"
        s.payment.client_secret = "csec"
        s.payment.plan_supporter_monthly = "P-MONTHLY-1"
        provider = _payment_for(s)
        assert isinstance(provider, PayPalPaymentProvider)

    def test_production_payment_requires_plan_ids(self) -> None:
        s = _settings_without_toml("production")
        s.payment.mode = "sandbox"
        s.payment.client_id = "cid"
        s.payment.client_secret = "csec"
        with pytest.raises(ProductionWiringError) as exc:
            _payment_for(s)
        assert "plan_ids" in str(exc.value)


class TestSettingsDependOnOsapToml:
    """Los tests dependen de `osap.toml` (mismo fichero que la app en runtime)."""

    def test_settings_loads_db_from_osap_toml(self) -> None:
        toml = PROJECT_ROOT / "osap.toml"
        if not toml.exists():
            pytest.skip("osap.toml no presente en este entorno")
        s = Settings(env="development", toml_file=toml)
        assert s.database.name == "osap_support"
        assert s.database.host  # presente en osap.toml

    def test_settings_loads_paypal_section_from_osap_toml(self) -> None:
        toml = PROJECT_ROOT / "osap.toml"
        if not toml.exists():
            pytest.skip("osap.toml no presente en este entorno")
        s = Settings(env="production", toml_file=toml)
        # El bloque [paypal] de osap.toml alimenta la config de PayPal.
        assert s.payment.mode in ("sandbox", "live")
        # Si hay credenciales/plan reales, el wiring production produce PayPal real.
        if s.payment.client_id and s.payment.client_secret and any(s.payment.plan_ids().values()):
            assert isinstance(_payment_for(s), PayPalPaymentProvider)

    def test_env_overrides_toml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        toml = PROJECT_ROOT / "osap.toml"
        if not toml.exists():
            pytest.skip("osap.toml no presente en este entorno")
        monkeypatch.setenv("OSAP_SUPPORT_DB_NAME", "override_name")
        s = Settings(env="development", toml_file=toml)
        assert s.database.name == "override_name"


class TestDevAndTestUseFakes:
    def test_development_uses_static_identity(self) -> None:
        identity = _identity_for(_settings("development"))
        assert isinstance(identity, StaticIdentityResolver)
        assert identity.resolve_user_id("Bearer dev-token") == "dev-user"

    def test_test_uses_static_identity(self) -> None:
        identity = _identity_for(_settings("test"))
        assert isinstance(identity, StaticIdentityResolver)

    def test_development_uses_fake_payment(self) -> None:
        provider = _payment_for(_settings("development"))
        assert isinstance(provider, FakePaymentProvider)

    def test_test_uses_fake_payment(self) -> None:
        provider = _payment_for(_settings("test"))
        assert isinstance(provider, FakePaymentProvider)
