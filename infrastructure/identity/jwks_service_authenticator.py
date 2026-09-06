"""Autenticador real de service tokens M2M contra el JWKS de osap-auth (4D-1).

Valida un Bearer service token (RS256): issuer + `aud = osap-support` exacto, firma con
`kid`, exp/iat, `token_use/typ = service`, y devuelve la identidad del servicio
(client_id en `sub` + scopes) exigiendo el scope requerido (p. ej. `support:ingest`).
Fail-closed: un service token sin scope/audience válidos se rechaza, nunca degrada.
"""

from __future__ import annotations

import jwt
from jwt import PyJWKClient

from domain.ports.identity import IdentityError, ServiceAuthenticator, ServiceIdentity
from infrastructure.identity._claims import service_identity_from_payload


class JwksServiceAuthenticator(ServiceAuthenticator):
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

    def authenticate_service(
        self, bearer_token: str, *, required_scope: str
    ) -> ServiceIdentity:
        payload = self._decode_payload(bearer_token)
        return service_identity_from_payload(payload, required_scope=required_scope)

    def _decode_payload(self, bearer_token: str) -> dict[str, object]:
        token = bearer_token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise IdentityError("service token ausente")

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
                options={"require": ["iss", "sub", "aud", "exp", "iat", "jti"]},
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
