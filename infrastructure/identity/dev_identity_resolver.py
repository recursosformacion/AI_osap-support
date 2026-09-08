"""Resolver de identidad para desarrollo (osap-support).

Solo para entornos no productivos: acepta CUALQUIER Bearer token de osap-auth y extrae
user_id/roles del payload (sin verificar firma, igual que el bypass de dev de osap-api).
Si el token no es un JWT parseable, cae al token estático de desarrollo (dev-token).
NUNCA debe activarse en producción.
"""

from __future__ import annotations

import jwt

from domain.ports.identity import (
    IdentityError,
    IdentityPrincipal,
    IdentityResolver,
)

_BEARER = "Bearer "


def _decode_payload(token: str) -> dict[str, object] | None:
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload if isinstance(payload, dict) else None
    except jwt.PyJWTError:
        return None


class DevIdentityResolver(IdentityResolver):
    """Dev: identidad real desde el JWT sin validar; fallback al usuario estático."""

    def __init__(self, *, dev_token: str, dev_user_id: str) -> None:
        self._dev_token = dev_token
        self._dev_user_id = dev_user_id

    def resolve_principal(self, bearer_token: str) -> IdentityPrincipal:
        token = bearer_token
        if token.startswith(_BEARER):
            token = token[len(_BEARER) :]
        if not token:
            raise IdentityError("token ausente")

        payload = _decode_payload(token)
        if payload is not None:
            sub = payload.get("sub")
            raw_roles = payload.get("roles", [])
            roles = tuple(str(r) for r in raw_roles) if isinstance(raw_roles, list) else ()
            if isinstance(sub, str) and sub:
                return IdentityPrincipal(user_id=sub, roles=roles)

        if token == self._dev_token:
            return IdentityPrincipal(user_id=self._dev_user_id, roles=())
        raise IdentityError("token de desarrollo no válido")

    def resolve_user_id(self, bearer_token: str) -> str:
        return self.resolve_principal(bearer_token).user_id
