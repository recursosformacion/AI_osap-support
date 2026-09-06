"""Maplaceo puro de claims JWT → principals (compartido por resolvers JWKS).

Funciones puras sobre un payload ya descifrado (claims de Auth): permiten testear la
semántica del contrato de audiencia sin necesitar claves JWKS en los tests.
- usuario → `IdentityPrincipal` (token_use/typ = user|access);
- servicio → `ServiceIdentity` (token_use/typ = service) + validación del scope requerido.
"""

from __future__ import annotations

from typing import Any

from domain.ports.identity import (
    IdentityError,
    IdentityPrincipal,
    ServiceIdentity,
    ServiceScopeError,
)

_USER_DISCRIMINATORS = ("user", "access")
_SERVICE_DISCRIMINATORS = ("service",)


def _token_use(payload: dict[str, Any]) -> str:
    return str(payload.get("token_use") or payload.get("typ") or "")


def user_principal_from_payload(payload: dict[str, Any]) -> IdentityPrincipal:
    """Convierte claims de un token de usuario ya verificado en un principal."""
    if _token_use(payload) not in _USER_DISCRIMINATORS:
        raise IdentityError("token no es de acceso de usuario")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise IdentityError("token sin subject")
    raw_roles = payload.get("roles", [])
    roles = tuple(str(r) for r in raw_roles) if isinstance(raw_roles, list) else ()
    return IdentityPrincipal(user_id=sub, roles=roles)


def service_identity_from_payload(
    payload: dict[str, Any], *, required_scope: str
) -> ServiceIdentity:
    """Convierte claims de un service token ya verificado en una identidad de servicio.

    Exige `token_use/typ = service` y la presencia del scope requerido (fail-closed).
    El `sub` es el `client_id` del servicio (Auth `client_credentials`).
    """
    if _token_use(payload) not in _SERVICE_DISCRIMINATORS:
        raise IdentityError("token no es de servicio")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise IdentityError("service token sin subject")
    scope_claim = str(payload.get("scope") or "")
    scopes = tuple(s for s in scope_claim.split() if s)
    if required_scope and required_scope not in scopes:
        raise ServiceScopeError(f"scope requerido no presente: {required_scope}")
    return ServiceIdentity(client_id=sub, scopes=scopes)
