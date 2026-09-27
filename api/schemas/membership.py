"""Schemas de la API de usuario de OSAP Support (Fase 5).

Contrato documentado (arquitectura §14 + ADR-012):
- Con Membership: { status, level, started_at, next_renewal_at, is_founder }.
- Sin Membership: { status: null, level: null, started_at: null, next_renewal_at: null,
  is_founder: false } (200 OK, estado ausente válido).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class MembershipMeResponse(BaseModel):
    """Respuesta de `GET /api/v1/membership/me`."""

    status: str | None = None
    level: str | None = None
    started_at: datetime | None = None
    next_renewal_at: datetime | None = None
    is_founder: bool = False


class MembershipM2mResponse(BaseModel):
    """Respuesta de `GET /api/v1/m2m/membership?user_id=…` (fase 4.2, M2M).

    Contrato orientado al funnel: `active` indica membresía vigente; `tier` es el nivel de
    funnel (`donor` cuando activa, en 4.2) y `source` el proveedor de origen. Sin membresía:
    todo vacío con `active=false` (200 OK, igual que el estado ausente de ADR-012).
    """

    active: bool = False
    tier: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source: str | None = None
