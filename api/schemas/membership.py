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
