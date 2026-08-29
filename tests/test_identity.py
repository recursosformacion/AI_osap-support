"""Tests de identidad (ADR-002 V-002 FIJADA): JWT.sub == Auth.user_id, sin usuarios locales."""

from __future__ import annotations

import pytest

from application.use_cases.resolve_my_user_id import ResolveMyUserIdUseCase
from domain.ports import IdentityError, IdentityResolver
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver


def test_static_resolver_returns_sub_as_user_id() -> None:
    resolver: IdentityResolver = StaticIdentityResolver(token="t-1", user_id="uuid-1234")
    assert resolver.resolve_user_id("Bearer t-1") == "uuid-1234"


def test_static_resolver_rejects_unknown_token() -> None:
    resolver: IdentityResolver = StaticIdentityResolver(token="t-1", user_id="uuid-1234")
    with pytest.raises(IdentityError):
        resolver.resolve_user_id("Bearer nope")


def test_use_case_resolves_my_user_id_without_local_users() -> None:
    resolver: IdentityResolver = StaticIdentityResolver(token="t-1", user_id="uuid-1234")
    use_case = ResolveMyUserIdUseCase(resolver)
    assert use_case.execute("Bearer t-1") == "uuid-1234"
