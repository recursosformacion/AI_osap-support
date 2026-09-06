"""Puertos de identidad de OSAP Support.

ADR-002 (V-002 FIJADA): Support NO crea usuarios locales. La identidad canónica es
`JWT.sub == Auth.user_id`. `IdentityResolver` expone cómo Support obtiene el `user_id` y
los `roles` a partir de un token de usuario (aud = osap-support, token_use=user).

Contrato de audiencia (4D-1, FIJADA 2026-09-06): osap-support valida EXACTAMENTE
`aud = osap-support` — tanto en tokens de usuario como en service tokens. Los service
tokens (M2M) se resuelven con `ServiceAuthenticator` (token_use=service), nunca con el
resolver de usuario.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


class IdentityError(Exception):
    """Fallo al resolver la identidad (token ausente, inválido o sin autorización)."""


class ServiceScopeError(IdentityError):
    """Service token válido pero sin el scope requerido (403, no 401)."""


@dataclass(frozen=True)
class IdentityPrincipal:
    """Principal de usuario resuelto desde un token (JWT.sub + roles de Auth)."""

    user_id: str
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceIdentity:
    """Principal de servicio resuelto desde un service token (client_id + scopes)."""

    client_id: str
    scopes: tuple[str, ...] = ()


class IdentityResolver(ABC):
    """Resuelve el principal de usuario desde un bearer token de usuario."""

    @abstractmethod
    def resolve_principal(self, bearer_token: str) -> IdentityPrincipal:
        """Devuelve el principal (user_id + roles) del token de usuario.

        Lanza `IdentityError` si el token no es válido, no es de usuario
        (token_use != user/access) o no lleva `aud = osap-support`.
        """

    @abstractmethod
    def resolve_user_id(self, bearer_token: str) -> str:
        """Compatibilidad: resuelve solo el `user_id` (== `Auth.user_id` / `JWT.sub`)."""


class ServiceAuthenticator(ABC):
    """Autentica service tokens M2M (token_use=service, aud=osap-support).

    No confunde servicios con usuarios: los service tokens nunca pasan por
    `IdentityResolver`. `authenticate_service` valida el scope requerido (p. ej.
    `support:ingest`); sin él lanza `IdentityError`.
    """

    @abstractmethod
    def authenticate_service(
        self, bearer_token: str, *, required_scope: str
    ) -> ServiceIdentity:
        """Devuelve la identidad del servicio (client_id + scopes) si el token es válido
        y porta el scope requerido. Lanza `IdentityError` en caso contrario."""


class IdentityProviderProtocol(Protocol):
    """Contrato estable de identidad (para inversión de dependencias en tests)."""

    def resolve_user_id(self, bearer_token: str) -> str: ...


class ServiceAuthenticatorProtocol(Protocol):
    def authenticate_service(
        self, bearer_token: str, *, required_scope: str
    ) -> ServiceIdentity: ...
