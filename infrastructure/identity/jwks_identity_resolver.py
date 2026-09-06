"""Resolver de identidad real contra el JWKS de osap-auth (ADR-002, 4D-1).

Valida un Bearer access token de usuario (RS256) contra el JWKS publicado por osap-auth:
- issuer y audience obligatorios (`aud = osap-support` exacto, contrato FIJADA 2026-09-06);
- firma RS256 con el `kid` anunciado (gestión y caché vía PyJWKClient);
- `exp`/`iat` y leeway;
- discriminador de tipo (`token_use=user` / `typ=access`): los service tokens se
  rechazan aquí (se autentican con `ServiceAuthenticator`);
- devuelve el principal (user_id + roles de Auth). Nunca crea usuarios locales.

Errores de red o de validación se traducen a :class:`IdentityError` (401 explícito),
nunca a un usuario falso.
"""

from __future__ import annotations

import jwt
from jwt import PyJWKClient

from domain.ports.identity import (
    IdentityError,
    IdentityPrincipal,
    IdentityResolver,
)
from infrastructure.identity._claims import user_principal_from_payload


class JwksIdentityResolver(IdentityResolver):
    """Resuelve `user_id` (+roles) validando el token contra el JWKS de osap-auth."""

    def __init__(
        self,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str,
        cache_ttl_seconds: int = 300,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not jwks_uri or not issuer or not audience:
            raise IdentityError("JWKS/issuer/audience no configurados")
        self._issuer = issuer
        self._audience = audience
        self._jwks = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            lifespan=cache_ttl_seconds,
            timeout=timeout_seconds,
        )

    def resolve_principal(self, bearer_token: str) -> IdentityPrincipal:
        payload = self._decode_payload(bearer_token)
        return user_principal_from_payload(payload)

    def resolve_user_id(self, bearer_token: str) -> str:
        return self.resolve_principal(bearer_token).user_id

    def _decode_payload(self, bearer_token: str) -> dict[str, object]:
        token = bearer_token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise IdentityError("token ausente")

        header = self._unverified_header(token)
        if header.get("alg") != "RS256":
            raise IdentityError(f"algoritmo no soportado: {header.get('alg')}")

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
        except Exception as exc:
            raise IdentityError(f"JWKS no disponible o kid desconocido: {exc}") from exc

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=30,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise IdentityError("token expirado") from exc
        except jwt.PyJWTError as exc:
            raise IdentityError(f"token inválido: {exc}") from exc

        return payload

    @staticmethod
    def _unverified_header(token: str) -> dict[str, object]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise IdentityError(f"token inválido: {exc}") from exc
        if "kid" not in header:
            raise IdentityError("token sin kid")
        return header
