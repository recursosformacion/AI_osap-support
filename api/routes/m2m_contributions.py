"""Ruta M2M de ingesta de contribuciones (ADR-017, 4D).

Fronteras (todas en la ruta o en los ports, nunca en el dominio):
1. Service token válido (token_use=service, aud=osap-support) con scope `support:ingest`;
2. El client autenticado está en la allowlist `[m2m]` (client_id → source + proyectos);
3. El `project` del body está entre los permitidos para ese client;
4. `source` se deriva de la allowlist (nunca del body).
La lógica de ingesta/idempotencia/derivación vive en IngestContributionUseCase.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from api.schemas.recognitions import ContributionIngestRequest, ContributionIngestResponse
from application.use_cases.ingest_contribution import IngestContributionUseCase
from domain.entities import ContributionType
from domain.exceptions import ProjectNotFoundError
from domain.ports.identity import (
    IdentityError,
    ServiceAuthenticator,
    ServiceScopeError,
)
from infrastructure.config import M2mClientConfig

router = APIRouter(prefix="/api/v1/m2m", tags=["m2m-contributions"])

_REQUIRED_SCOPE = "support:ingest"


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


def _parse_type(raw: str) -> ContributionType:
    try:
        return ContributionType(raw.strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"tipo desconocido: {raw}") from None


@router.post(
    "/contributions",
    response_model=ContributionIngestResponse,
    status_code=201,
)
def ingest_contribution(
    body: ContributionIngestRequest,
    response: Response,
    bearer: str = Depends(_bearer_token),
) -> ContributionIngestResponse:
    try:
        service = _service_authenticator.authenticate_service(
            bearer, required_scope=_REQUIRED_SCOPE
        )
    except ServiceScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    scope = _m2m_scope(service.client_id)
    if scope is None:
        raise HTTPException(status_code=403, detail="client M2M no permitido")
    if body.project not in scope.projects:
        raise HTTPException(
            status_code=403,
            detail=f"proyecto no permitido para este client: {body.project}",
        )
    # `source` se deriva de la allowlist; el body nunca puede falsearlo.
    source = scope.source
    ctype = _parse_type(body.type)

    try:
        result = _ingest_uc.execute(
            user_id=body.user_id,
            project_slug=body.project,
            contribution_type=ctype,
            summary=body.summary,
            amount=body.amount,
            source=source,
            source_reference=body.source_reference,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Idempotencia por contrato: reemisión del mismo source_reference → 200 duplicate.
    response.status_code = 200 if result.outcome == "duplicate" else 201
    return ContributionIngestResponse(
        status=result.outcome,
        contribution_id=result.contribution_id,
        contributor_active=result.contributor_active,
    )


# Wiring: service authenticator real/estático + allowlist m2m desde config.
_service_authenticator: ServiceAuthenticator
_m2m_scope: Callable[[str], M2mClientConfig | None]
_ingest_uc: IngestContributionUseCase


def wire_m2m_contributions_router(
    *,
    service_authenticator: ServiceAuthenticator,
    m2m_scope: Callable[[str], M2mClientConfig | None],
    ingest_uc: IngestContributionUseCase,
) -> APIRouter:
    global _service_authenticator, _m2m_scope, _ingest_uc
    _service_authenticator = service_authenticator
    _m2m_scope = m2m_scope
    _ingest_uc = ingest_uc
    return router
