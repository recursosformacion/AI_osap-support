"""Schemas HTTP de reconocimientos y contribuciones (4D-4).

extra="forbid" en todas las peticiones: el cliente no puede colar campos desconocidos.
Estos DTOs NO deciden lógica de negocio: solo tipan la frontera HTTP.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RecognitionMeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    kind: str
    status: str
    granted_at: datetime
    active_until: datetime | None = None
    public: bool


class RecognitionConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1)
    type: str
    public: bool


class RecognitionConsentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    type: str
    public: bool
    changed: bool


class PublicRecognitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    granted_at: datetime


class AdminRecognitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: str
    project: str
    type: str
    kind: str
    status: str
    granted_at: datetime
    granted_by: str | None = None
    origin: str | None = None
    reason: str | None = None
    active_until: datetime | None = None
    public: bool


class AdminGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    type: str
    reason: str = Field(min_length=1)


class AdminRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class AdminRevokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recognition_id: int
    changed: bool


class ContributionIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    type: str
    summary: str = Field(min_length=1)
    amount: int | None = Field(default=None, ge=0)
    source_reference: str = Field(min_length=1)


class ContributionIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str  # created | duplicate
    contribution_id: int | None = None
    contributor_active: bool = False
