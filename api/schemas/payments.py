"""Schemas HTTP del listado administrativo de pagos (support:admin).

Items de `memberships` y `donations` con paginación offset/limit. DTOs de frontera HTTP:
los importes viajan en unidades mínimas enteras (amount_minor, V-021).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminMembershipItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: str
    status: str
    level: str
    periodicity: str
    amount_minor: int
    currency: str
    provider: str
    subscription_id: str
    started_at: datetime | None = None
    renewed_at: datetime | None = None
    next_renewal_at: datetime | None = None
    cancelled_at: datetime | None = None
    expires_at: datetime | None = None
    email_contact: str = ""
    is_founder: bool = False
    created_at: datetime
    updated_at: datetime


class AdminMembershipsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    items: list[AdminMembershipItem]


class AdminDonationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: str
    amount_minor: int
    currency: str
    provider: str
    charge_id: str
    receipt_id: str | None = None
    email_receipt: str = ""
    donated_at: datetime
    created_at: datetime


class AdminDonationsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    items: list[AdminDonationItem]
