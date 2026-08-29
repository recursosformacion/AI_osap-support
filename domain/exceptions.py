"""Excepciones del dominio de OSAP Support."""

from __future__ import annotations


class SupportDomainError(Exception):
    """Error base del dominio de OSAP Support."""


class InvalidStateTransition(SupportDomainError):
    """Transición de estado no permitida desde el estado actual.

    Un evento fuera de orden que no puede aplicarse desde el estado actual debe
    registrarse (auditoría) pero no cambiar el estado (ADR-007, idempotencia).
    """


class InvalidMoneyError(SupportDomainError):
    """Representación monetaria inválida (V-021: unidades mínimas enteras)."""


class DuplicatePaymentEventError(SupportDomainError):
    """Evento de pago duplicado.

    ADR-007: `(provider, provider_event_id)` es la clave de idempotencia. Un intento de
    persistir un evento ya registrado debe rechazarse (o tratarse como `ignored_duplicate`).
    """
