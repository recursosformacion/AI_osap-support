"""Aplicación FastAPI de OSAP Support.

Conexión FastAPI → caso de uso → ports → infraestructura (Fase 5).
La identidad se deriva del token (ADR-008/ADR-002). JWKS productivo queda ABIERTO;
en dev/test se usa DevIdentityResolver (acepta el token real sin validar, con
fallback al token estático). En production el arranque FALLA si no hay
implementaciones reales: es preferible que el servicio no arranque a que parezca
funcional detrás de un fake.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from api.routes.admin_payments import wire_admin_payments_router
from api.routes.admin_recognitions import wire_admin_recognitions_router
from api.routes.checkout import wire_checkout_router
from api.routes.m2m_contributions import wire_m2m_contributions_router
from api.routes.membership import wire_router
from api.routes.public_recognitions import wire_public_recognitions_router
from api.routes.recognitions import wire_recognitions_router
from api.routes.webhooks import wire_webhook_router
from application.use_cases.admin_list_payments import AdminListPaymentsUseCase
from application.use_cases.admin_list_recognitions import AdminListRecognitionsUseCase
from application.use_cases.checkout_donation import CheckoutDonationUseCase
from application.use_cases.checkout_membership import CheckoutMembershipUseCase
from application.use_cases.evaluate_contributor import EvaluateContributorRecognitionUseCase
from application.use_cases.get_my_membership import GetMyMembershipUseCase
from application.use_cases.get_public_recognitions import GetPublicRecognitionsUseCase
from application.use_cases.grant_recognition import GrantRecognitionUseCase
from application.use_cases.ingest_contribution import IngestContributionUseCase
from application.use_cases.list_my_recognitions import ListMyRecognitionsUseCase
from application.use_cases.process_payment_webhook import ProcessPaymentWebhookUseCase
from application.use_cases.revoke_recognition import RevokeRecognitionUseCase
from application.use_cases.set_recognition_consent import SetRecognitionConsentUseCase
from domain.ports.identity import IdentityResolver, ServiceAuthenticator
from domain.ports.payment import PaymentProvider
from infrastructure.clock import SystemClock
from infrastructure.config import (
    Settings,
    load_settings,
    m2m_scope_for_settings,
    recognition_rules_from_settings,
)
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.repositories.contribution_repository import (
    SqlAlchemyContributionRepository,
)
from infrastructure.db.repositories.donation_repository import SqlAlchemyDonationRepository
from infrastructure.db.repositories.membership_repository import SqlAlchemyMembershipRepository
from infrastructure.db.repositories.payment_event_repository import SqlAlchemyPaymentEventRepository
from infrastructure.db.repositories.payments_admin_repository import (
    SqlAlchemyPaymentsAdminRepository,
)
from infrastructure.db.repositories.project_repository import SqlAlchemyProjectRepository
from infrastructure.db.repositories.recognition_event_repository import (
    SqlAlchemyRecognitionEventRepository,
)
from infrastructure.db.repositories.recognition_repository import (
    SqlAlchemyRecognitionRepository,
)
from infrastructure.db.repositories.support_member_repository import (
    SqlAlchemySupportMemberRepository,
)
from infrastructure.db.session import make_session_factory
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.identity.dev_identity_resolver import DevIdentityResolver
from infrastructure.identity.jwks_identity_resolver import JwksIdentityResolver
from infrastructure.identity.jwks_service_authenticator import JwksServiceAuthenticator
from infrastructure.identity.static_service_authenticator import (
    StaticServiceAuthenticator,
)
from infrastructure.payment.fake_payment_provider import FakePaymentProvider

# Entornos en los que los fakes de identidad/pagos están PERMITIDOS (nunca production).
_NON_PRODUCTION = {"development", "test", "dev", "testing"}


class ProductionWiringError(RuntimeError):
    """El entorno es production y falta una implementación real (fail-fast)."""


def _identity_for(settings: Settings) -> IdentityResolver:
    if settings.server.env in _NON_PRODUCTION:
        # Dev: acepta el token REAL del usuario (JWT sin verificar, igual que el bypass de
        # osap-api) para poder probar /support autenticado; fallback al dev-token estático.
        return DevIdentityResolver(
            dev_token=settings.server.dev_token,
            dev_user_id=settings.server.dev_user_id,
        )
    # production: SOLO un resolver real contra el JWKS de osap-auth. Si la integración
    # no está configurada (jwks_uri/issuer/audience), el arranque FALLA explícitamente.
    identity_cfg = settings.identity
    if not (identity_cfg.jwks_uri and identity_cfg.issuer and identity_cfg.audience):
        raise ProductionWiringError(
            "Production identity provider is not configured: "
            "OSAP_SUPPORT_AUTH_JWKS_URI / ISSUER / AUDIENCE required"
        )
    return JwksIdentityResolver(
        jwks_uri=identity_cfg.jwks_uri,
        issuer=identity_cfg.issuer,
        audience=identity_cfg.audience,
        cache_ttl_seconds=identity_cfg.jwks_cache_ttl_seconds,
    )


def _service_authenticator_for(settings: Settings) -> ServiceAuthenticator:
    if settings.server.env in _NON_PRODUCTION:
        return StaticServiceAuthenticator(
            token=settings.server.dev_service_token,
            client_id="dev-service",
            scopes=("support:ingest",),
        )
    identity_cfg = settings.identity
    if not (identity_cfg.jwks_uri and identity_cfg.issuer and identity_cfg.audience):
        raise ProductionWiringError(
            "Production service authenticator is not configured: "
            "OSAP_SUPPORT_AUTH_JWKS_URI / ISSUER / AUDIENCE required"
        )
    return JwksServiceAuthenticator(
        jwks_uri=identity_cfg.jwks_uri,
        issuer=identity_cfg.issuer,
        audience=identity_cfg.service_audience or identity_cfg.audience,
        cache_ttl_seconds=identity_cfg.jwks_cache_ttl_seconds,
    )


def _payment_for(settings: Settings) -> PaymentProvider:
    pcfg = settings.payment
    if settings.server.env in _NON_PRODUCTION:
        # Dev/test: PayPal Sandbox real SOLO con opt-in explícito `[paypal] dev_real`
        # (o env OSAP_SUPPORT_PAYPAL_DEV_REAL=1, p. ej. E2E local). Por defecto: fake.
        if pcfg.dev_real and _sandbox_configured(settings):
            return _paypal_provider(settings)
        return FakePaymentProvider()
    # production: SOLO PayPal real. Sin credenciales/configuración el arranque falla.
    pcfg = settings.payment
    if not (pcfg.mode in ("sandbox", "live") and pcfg.client_id and pcfg.client_secret):
        raise ProductionWiringError(
            "Production payment provider is not configured: "
            "OSAP_SUPPORT_PAYPAL_MODE/CLIENT_ID/CLIENT_SECRET required (PayPal)"
        )
    if not any(pcfg.plan_ids().values()):
        raise ProductionWiringError(
            "Production payment provider is missing PayPal plan_ids: "
            "OSAP_SUPPORT_PAYPAL_PLAN_*_MONTHLY/YEARLY required"
        )
    return _paypal_provider(settings)


def _sandbox_configured(settings: Settings) -> bool:
    pcfg = settings.payment
    return (
        pcfg.mode in ("sandbox", "live")
        and bool(pcfg.client_id)
        and bool(pcfg.client_secret)
        and any(pcfg.plan_ids().values())
    )


def _paypal_provider(settings: Settings) -> PaymentProvider:
    from infrastructure.payment.paypal_payment_provider import PayPalPaymentProvider

    pcfg = settings.payment
    return PayPalPaymentProvider(
        mode=pcfg.mode,
        client_id=pcfg.client_id,
        client_secret=pcfg.client_secret,
        webhook_id=pcfg.webhook_id,
        plan_ids=pcfg.plan_ids(),
    )


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title=settings.server.app_title, version=settings.server.app_version)
    app.state.settings = settings
    origins = settings.server.cors_origins
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    # Wiring (Fase 5/6): FastAPI → use case → ports → infraestructura.
    session = make_session_factory()()
    app.state.db_session = session

    # La sesión es única para toda la app (la comparten todos los repositorios/UoW). Si una
    # petición falla a mitad de transacción, SQLAlchemy la deja inválida y TODAS las
    # siguientes devuelven `PendingRollbackError` → 502 (visto en /checkouts/donation).
    # Este guardián revierte antes de cada petición y ante cualquier excepción, de modo que
    # la sesión siempre parte limpia y una petición rota no tumba el servicio.
    @app.middleware("http")
    async def _db_session_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            if session.in_transaction() or session.in_nested_transaction():
                session.rollback()
        except Exception:  # noqa: BLE001
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        try:
            return await call_next(request)
        except Exception:
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise

    identity = _identity_for(settings)

    @app.get("/")
    def health() -> dict[str, str]:
        return {"service": "osap-support", "version": settings.server.app_version, "status": "ok"}

    @app.get("/health")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def readiness() -> dict[str, str]:
        # Readiness real: comprueba que la BD obligatoria responde. Sin BD, el proceso
        # NO declara estar listo (nunca "healthy" con dependencia obligatoria caída).
        from fastapi import HTTPException
        from sqlalchemy import text

        try:
            session.connection().execute(text("SELECT 1"))
            return {"status": "ready", "database": "ok"}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc

    membership_use_case = GetMyMembershipUseCase(
        identity=identity,
        memberships=SqlAlchemyMembershipRepository(session),
    )
    app.include_router(wire_router(membership_use_case))

    payment = _payment_for(settings)
    donation_uc = CheckoutDonationUseCase(payment)
    membership_uc = CheckoutMembershipUseCase(payment)
    app.include_router(
        wire_checkout_router(
            identity=identity,
            donation_uc=donation_uc,
            membership_uc=membership_uc,
        )
    )

    webhook_use_case = ProcessPaymentWebhookUseCase(
        provider=payment,
        payment_events=SqlAlchemyPaymentEventRepository(session),
        memberships=SqlAlchemyMembershipRepository(session),
        donations=SqlAlchemyDonationRepository(session),
        communications=SqlAlchemyCommunicationEventRepository(session),
        support_members=SqlAlchemySupportMemberRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
        # En production el provider real expone verify_webhook → la ruta verifica la
        # firma antes de procesar. En dev/test (fake) el verificador queda desactivado.
        webhook_verifier=payment if settings.server.env not in _NON_PRODUCTION else None,
    )
    app.include_router(wire_webhook_router(webhook_use_case))

    # --- Reconocimientos y contribuciones (4D, ADR-015/017) -------------------
    rules = recognition_rules_from_settings(settings)
    clock = SystemClock()
    uow = SqlAlchemyUnitOfWork(session)
    projects = SqlAlchemyProjectRepository(session)
    recognitions = SqlAlchemyRecognitionRepository(session)
    recognition_events = SqlAlchemyRecognitionEventRepository(session)
    contributions = SqlAlchemyContributionRepository(session)
    support_members = SqlAlchemySupportMemberRepository(session)

    contributor_eval = EvaluateContributorRecognitionUseCase(
        contributions=contributions,
        projects=projects,
        recognitions=recognitions,
        events=recognition_events,
        support_members=support_members,
        rules=rules,
        clock=clock,
        uow=uow,
    )
    consent_uc = SetRecognitionConsentUseCase(
        recognitions=recognitions,
        events=recognition_events,
        clock=clock,
        uow=uow,
    )
    app.include_router(
        wire_recognitions_router(
            identity=identity,
            list_uc=ListMyRecognitionsUseCase(recognitions=recognitions),
            consent_uc=consent_uc,
        )
    )
    app.include_router(
        wire_public_recognitions_router(
            GetPublicRecognitionsUseCase(recognitions=recognitions, projects=projects)
        )
    )
    app.include_router(
        wire_admin_recognitions_router(
            identity=identity,
            recognitions=recognitions,
            list_uc=AdminListRecognitionsUseCase(recognitions=recognitions),
            grant_uc=GrantRecognitionUseCase(
                recognitions=recognitions,
                events=recognition_events,
                projects=projects,
                support_members=support_members,
                clock=clock,
                uow=uow,
            ),
            revoke_uc=RevokeRecognitionUseCase(
                recognitions=recognitions,
                events=recognition_events,
                clock=clock,
                uow=uow,
            ),
        )
    )
    payments_admin = SqlAlchemyPaymentsAdminRepository(session)
    app.include_router(
        wire_admin_payments_router(
            identity=identity,
            list_uc=AdminListPaymentsUseCase(payments=payments_admin),
        )
    )
    app.include_router(
        wire_m2m_contributions_router(
            service_authenticator=_service_authenticator_for(settings),
            m2m_scope=lambda client_id: m2m_scope_for_settings(settings, client_id),
            ingest_uc=IngestContributionUseCase(
                contributions=contributions,
                projects=projects,
                support_members=support_members,
                contributor_evaluator=contributor_eval,
                clock=clock,
                uow=uow,
            ),
        )
    )

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
