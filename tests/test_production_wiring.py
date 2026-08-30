"""Wiring por entorno (ADR: fail-fast en production).

Verifica que:
- en production NINGÚN fake de identidad/pagos se puede wirear (el arranque falla);
- en development/test los fakes siguen disponibles;
- el error de production es explícito (no un fallback silencioso).
"""

from __future__ import annotations

import pytest

from api.main import ProductionWiringError, _identity_for, _payment_for
from infrastructure.config import Settings
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver
from infrastructure.payment.fake_payment_provider import FakePaymentProvider


def _settings(env: str) -> Settings:
    s = Settings(env=env)
    s.server.dev_token = "dev-token"
    s.server.dev_user_id = "dev-user"
    return s


class TestProductionFailFast:
    def test_production_identity_fails_fast(self) -> None:
        with pytest.raises(ProductionWiringError) as exc:
            _identity_for(_settings("production"))
        assert "Production identity provider is not configured/implemented" in str(exc.value)

    def test_production_payment_fails_fast(self) -> None:
        with pytest.raises(ProductionWiringError) as exc:
            _payment_for(_settings("production"))
        assert "Production payment provider is not configured/implemented" in str(exc.value)


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
