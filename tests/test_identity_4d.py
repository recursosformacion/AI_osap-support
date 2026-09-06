"""Tests de la capa de identidad de 4D-1 (osap-support).

Cubren: StaticIdentityResolver (usuario con roles), StaticServiceAuthenticator
(servicio con scope) y el mapeo puro de claims JWKS (usuario → principal+roles; servicio
→ client_id+scopes) que implementa el contrato de audiencia sin necesitar claves.
"""

from __future__ import annotations

import pytest

from domain.ports.identity import IdentityError
from infrastructure.identity._claims import (
    service_identity_from_payload,
    user_principal_from_payload,
)
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver
from infrastructure.identity.static_service_authenticator import (
    StaticServiceAuthenticator,
)


def test_static_user_principal_includes_roles() -> None:
    resolver = StaticIdentityResolver(
        token="user-token", user_id="u-1", roles=("user", "support:admin")
    )
    principal = resolver.resolve_principal("Bearer user-token")
    assert principal.user_id == "u-1"
    assert principal.roles == ("user", "support:admin")
    assert resolver.resolve_user_id("user-token") == "u-1"


def test_static_user_principal_default_roles_empty() -> None:
    resolver = StaticIdentityResolver(token="t", user_id="u-1")
    assert resolver.resolve_principal("t").roles == ()


def test_static_user_principal_rejects_wrong_token() -> None:
    resolver = StaticIdentityResolver(token="t", user_id="u-1")
    with pytest.raises(IdentityError):
        resolver.resolve_principal("Bearer wrong")


# --- servicio (StaticServiceAuthenticator) ---------------------------------------


def test_static_service_authenticates_with_required_scope() -> None:
    auth = StaticServiceAuthenticator(
        token="service-token",
        client_id="omr-dev",
        scopes=("support:ingest", "api:read"),
    )
    identity = auth.authenticate_service("Bearer service-token", required_scope="support:ingest")
    assert identity.client_id == "omr-dev"
    assert identity.scopes == ("support:ingest", "api:read")


def test_static_service_rejects_wrong_token_or_missing_scope() -> None:
    auth = StaticServiceAuthenticator(
        token="service-token", client_id="omr-dev", scopes=("api:read",)
    )
    with pytest.raises(IdentityError):
        auth.authenticate_service("service-token", required_scope="support:ingest")
    with pytest.raises(IdentityError):
        auth.authenticate_service("wrong", required_scope="api:read")


# --- mapeo puro de claims (semántica de los resolvers JWKS) ---------------------


def test_user_claims_map_to_principal_with_roles() -> None:
    principal = user_principal_from_payload(
        {
            "sub": "u-9",
            "token_use": "user",
            "roles": ["user", "support:admin"],
            "aud": "osap-support",
        }
    )
    assert principal.user_id == "u-9"
    assert principal.roles == ("user", "support:admin")


def test_user_claims_accept_typ_access_and_empty_roles() -> None:
    principal = user_principal_from_payload({"sub": "u-9", "typ": "access"})
    assert principal.user_id == "u-9"
    assert principal.roles == ()


def test_user_claims_reject_service_token() -> None:
    with pytest.raises(IdentityError):
        user_principal_from_payload(
            {"sub": "svc-1", "token_use": "service", "scope": "support:ingest"}
        )


def test_service_claims_map_to_client_id_and_scopes() -> None:
    identity = service_identity_from_payload(
        {
            "sub": "omr-backend",
            "token_use": "service",
            "scope": "support:ingest api:read",
            "aud": "osap-support",
        },
        required_scope="support:ingest",
    )
    assert identity.client_id == "omr-backend"
    assert identity.scopes == ("support:ingest", "api:read")


def test_service_claims_fail_closed_on_missing_scope() -> None:
    payload = {
        "sub": "omr-backend",
        "token_use": "service",
        "scope": "api:read",
        "aud": "osap-support",
    }
    with pytest.raises(IdentityError):
        service_identity_from_payload(payload, required_scope="support:ingest")
    with pytest.raises(IdentityError):
        service_identity_from_payload({**payload, "token_use": "user"}, required_scope="api:read")
