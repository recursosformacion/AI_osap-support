"""Aplicación FastAPI de OSAP Support.

Conexión FastAPI → caso de uso → ports → infraestructura (Fase 5).
La identidad se deriva del token (ADR-008/ADR-002). JWKS productivo queda ABIERTO;
en dev/test se usa StaticIdentityResolver. En production el arranque FALLA si no hay
implementaciones reales: es preferible que el servicio no arranque a que parezca
funcional detrás de un fake.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes.membership import wire_router
from api.routes.webhooks import wire_webhook_router
from application.use_cases.get_my_membership import GetMyMembershipUseCase
from application.use_cases.process_payment_webhook import ProcessPaymentWebhookUseCase
from domain.ports.identity import IdentityResolver
from domain.ports.payment import PaymentProvider
from infrastructure.config import Settings, load_settings
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.repositories.donation_repository import SqlAlchemyDonationRepository
from infrastructure.db.repositories.membership_repository import SqlAlchemyMembershipRepository
from infrastructure.db.repositories.payment_event_repository import SqlAlchemyPaymentEventRepository
from infrastructure.db.session import make_session_factory
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver
from infrastructure.payment.fake_payment_provider import FakePaymentProvider

# Entornos en los que los fakes de identidad/pagos están PERMITIDOS (nunca production).
_NON_PRODUCTION = {"development", "test", "dev", "testing"}


class ProductionWiringError(RuntimeError):
    """El entorno es production y falta una implementación real (fail-fast)."""


def _identity_for(settings: Settings) -> IdentityResolver:
    if settings.server.env in _NON_PRODUCTION:
        return StaticIdentityResolver(
            token=settings.server.dev_token,
            user_id=settings.server.dev_user_id,
        )
    # production: SOLO un resolver real. No existe implementación JWKS todavía, por lo
    # que es preferible no arrancar a servir 401 a todos los usuarios con un fake.
    raise ProductionWiringError(
        "Production identity provider is not configured/implemented"
    )


def _payment_for(settings: Settings) -> PaymentProvider:
    if settings.server.env in _NON_PRODUCTION:
        return FakePaymentProvider()
    # production: SOLO un proveedor real. No existe (Stripe/... decisión ABIERTA), por
    # lo que es preferible no arrancar a aceptar webhooks arbitrarios o checkouts fake.
    raise ProductionWiringError(
        "Production payment provider is not configured/implemented"
    )


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title=settings.server.app_title, version=settings.server.app_version)
    app.state.settings = settings

    @app.get("/")
    def health() -> dict[str, str]:
        return {"service": "osap-support", "version": settings.server.app_version, "status": "ok"}

    # Wiring (Fase 5/6): FastAPI → use case → ports → infraestructura.
    # Resolver estático y provider fake SOLO en dev/test; en production el arranque
    # falla con error explícito si las implementaciones reales no existen.
    session = make_session_factory()()
    identity = _identity_for(settings)
    membership_use_case = GetMyMembershipUseCase(
        identity=identity,
        memberships=SqlAlchemyMembershipRepository(session),
    )
    app.include_router(wire_router(membership_use_case))

    webhook_use_case = ProcessPaymentWebhookUseCase(
        provider=_payment_for(settings),
        payment_events=SqlAlchemyPaymentEventRepository(session),
        memberships=SqlAlchemyMembershipRepository(session),
        donations=SqlAlchemyDonationRepository(session),
        communications=SqlAlchemyCommunicationEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    app.include_router(wire_webhook_router(webhook_use_case))

    return app


def create_app_from_settings(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or load_settings())


def run() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "api.main:create_app_from_settings",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
    )
