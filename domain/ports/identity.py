"""Puertos de identidad de OSAP Support.

ADR-002 (V-002 FIJADA): Support NO crea usuarios locales. La identidad canónica es
`JWT.sub == Auth.user_id`. IdentityResolver expone cómo Support obtiene el `user_id`
a partir de un token/contexto, sin tocar las BD de Auth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class IdentityError(Exception):
    """Fallo al resolver la identidad (token ausente, inválido o sin autorización)."""


class IdentityResolver(ABC):
    """Resuelve el `user_id` (== `Auth.user_id` / `JWT.sub`) desde un bearer token."""

    @abstractmethod
    def resolve_user_id(self, bearer_token: str) -> str:
        """Devuelve el `user_id` de Auth correspondiente al token.

        Lanza `IdentityError` si el token no es válido o no corresponde a osap-support.
        """


class IdentityProviderProtocol(Protocol):
    """Contrato estable de identidad (para inversión de dependencias en tests)."""

    def resolve_user_id(self, bearer_token: str) -> str: ...
