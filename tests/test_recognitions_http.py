"""4D-5: contrato completo de reconocimientos vía TestClient (sin nueva funcionalidad).

Matriz usuario / público / admin / M2M contra routers reales con SQLite en memoria y
persistencia SQLAlchemy. Incluye el flujo de integración: contribuciones OMR → Support →
suma → CONTRIBUTOR → GET /me (sin consultar memberships/donations).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.routes.admin_recognitions import wire_admin_recognitions_router
from api.routes.m2m_contributions import wire_m2m_contributions_router
from api.routes.public_recognitions import wire_public_recognitions_router
from api.routes.recognitions import wire_recognitions_router
from application.use_cases.admin_list_recognitions import AdminListRecognitionsUseCase
from application.use_cases.evaluate_contributor import EvaluateContributorRecognitionUseCase
from application.use_cases.get_public_recognitions import GetPublicRecognitionsUseCase
from application.use_cases.grant_recognition import GrantRecognitionUseCase
from application.use_cases.ingest_contribution import IngestContributionUseCase
from application.use_cases.list_my_recognitions import ListMyRecognitionsUseCase
from application.use_cases.revoke_recognition import RevokeRecognitionUseCase
from application.use_cases.set_recognition_consent import SetRecognitionConsentUseCase
from domain.entities import (
    Project,
    Recognition,
    RecognitionEventType,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
    SupportMember,
)
from domain.ports.identity import (
    IdentityError,
    ServiceAuthenticator,
    ServiceIdentity,
    ServiceScopeError,
)
from domain.recognitions_rules import ECOSYSTEM_PROJECT_SLUG, RecognitionRules
from infrastructure.clock import SystemClock
from infrastructure.config import M2mClientConfig
from infrastructure.db.models import Base
from infrastructure.db.repositories.contribution_repository import (
    SqlAlchemyContributionRepository,
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
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver

USER = "user-A"
OTHER = "user-B"
ADMIN = "admin-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


class _ServiceAuthTable(ServiceAuthenticator):
    """Service authenticator de tests: token → (client_id, scopes) con fallo 401/403."""

    def __init__(self, principals: dict[str, tuple[str, tuple[str, ...]]]) -> None:
        self._principals = principals

    def authenticate_service(
        self, bearer_token: str, *, required_scope: str
    ) -> ServiceIdentity:
        token = bearer_token
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if token not in self._principals:
            raise IdentityError("token de servicio no válido")
        client_id, scopes = self._principals[token]
        if required_scope and required_scope not in scopes:
            raise ServiceScopeError(f"scope requerido no presente: {required_scope}")
        return ServiceIdentity(client_id=client_id, scopes=scopes)


class _IdentityTable(StaticIdentityResolver):
    """Resolver de usuario de tests: token → (user_id, roles). Los tokens fuera de la
    tabla son inválidos (401); un token válido sin rol admin produce 403."""

    def __init__(self, principals: dict[str, tuple[str, tuple[str, ...]]]) -> None:
        self._principals = principals

    def resolve_principal(self, bearer_token: str) -> object:
        from domain.ports.identity import IdentityPrincipal

        token = bearer_token
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if token not in self._principals:
            raise IdentityError("token no válido")
        user_id, roles = self._principals[token]
        return IdentityPrincipal(user_id=user_id, roles=roles)

    def resolve_user_id(self, bearer_token: str) -> str:
        principal = self.resolve_principal(bearer_token)
        return principal.user_id  # type: ignore[union-attr]


@dataclass
class Harness:
    client: TestClient
    session: Session
    recognitions: SqlAlchemyRecognitionRepository
    events: SqlAlchemyRecognitionEventRepository
    contributions: SqlAlchemyContributionRepository


def _seed_projects(session: Session) -> None:
    repo = SqlAlchemyProjectRepository(session)
    repo.add(Project(slug=ECOSYSTEM_PROJECT_SLUG, name="OSAP Ecosystem"))
    repo.add(Project(slug="omr", name="Open Music Repository"))
    session.commit()


def _ensure_member(session: Session, user_id: str) -> None:
    repo = SqlAlchemySupportMemberRepository(session)
    if not repo.exists(user_id):
        repo.add(SupportMember(user_id=user_id))
        session.commit()


def _add_recognition(
    session: Session,
    *,
    user_id: str = USER,
    project_slug: str = "omr",
    rtype: RecognitionType = RecognitionType.VOICE,
    kind: RecognitionKind = RecognitionKind.GRANTED,
    status: RecognitionStatus = RecognitionStatus.ACTIVE,
    public: bool = False,
    origin: str | None = None,
    granted_by: str | None = ADMIN,
) -> Recognition:
    repo = SqlAlchemyRecognitionRepository(session)
    recognition = Recognition(
        id=None,
        user_id=user_id,
        project_slug=project_slug,
        recognition_type=rtype,
        kind=kind,
        status=status,
        granted_at=NOW,
        granted_by=granted_by,
        origin=origin,
        public=public,
    )
    added = repo.add(recognition)
    if public:
        repo.update(added)
    session.commit()
    return added


@contextmanager
def _make_harness(
    *,
    user_token: str = "user-token",
    admin_token: str = "admin-token",
    service_token: str = "service-token",
) -> Iterator[Harness]:
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    _seed_projects(session)

    projects = SqlAlchemyProjectRepository(session)
    recognitions = SqlAlchemyRecognitionRepository(session)
    events = SqlAlchemyRecognitionEventRepository(session)
    contributions = SqlAlchemyContributionRepository(session)
    support_members = SqlAlchemySupportMemberRepository(session)
    uow = SqlAlchemyUnitOfWork(session)
    rules = RecognitionRules()
    clock = SystemClock()

    identity_user = StaticIdentityResolver(token=user_token, user_id=USER, roles=("user",))
    identity_admin = _IdentityTable(
        {
            admin_token: (ADMIN, ("user", "support:admin")),
            "non-admin-token": ("plain-user", ("user",)),
        }
    )
    service_auth = _ServiceAuthTable(
        {
            service_token: ("omr-backend", ("support:ingest", "api:read")),
            "no-scope-token": ("omr-backend", ("api:read",)),
            "unknown-service-token": ("ghost", ("support:ingest",)),
        }
    )

    def _m2m_scope(client_id: str) -> M2mClientConfig | None:
        if client_id == "omr-backend":
            return M2mClientConfig(client_id=client_id, source="omr", projects=["omr"])
        return None

    app = FastAPI(title="osap-support-4d5")
    app.include_router(
        wire_recognitions_router(
            identity=identity_user,
            list_uc=ListMyRecognitionsUseCase(recognitions=recognitions),
            consent_uc=SetRecognitionConsentUseCase(
                recognitions=recognitions, events=events, clock=clock, uow=uow
            ),
        )
    )
    app.include_router(
        wire_public_recognitions_router(
            GetPublicRecognitionsUseCase(recognitions=recognitions, projects=projects)
        )
    )
    contributor_eval = EvaluateContributorRecognitionUseCase(
        contributions=contributions,
        projects=projects,
        recognitions=recognitions,
        events=events,
        support_members=support_members,
        rules=rules,
        clock=clock,
        uow=uow,
    )
    app.include_router(
        wire_admin_recognitions_router(
            identity=identity_admin,
            recognitions=recognitions,
            list_uc=AdminListRecognitionsUseCase(recognitions=recognitions),
            grant_uc=GrantRecognitionUseCase(
                recognitions=recognitions,
                events=events,
                projects=projects,
                support_members=support_members,
                clock=clock,
                uow=uow,
            ),
            revoke_uc=RevokeRecognitionUseCase(
                recognitions=recognitions, events=events, clock=clock, uow=uow
            ),
        )
    )
    app.include_router(
        wire_m2m_contributions_router(
            service_authenticator=service_auth,
            m2m_scope=_m2m_scope,
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

    yield Harness(
        client=TestClient(app),
        session=session,
        recognitions=recognitions,
        events=events,
        contributions=contributions,
    )
    session.close()
    engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ingest(
    h: Harness,
    *,
    ref: str,
    ctype: str = "review",
    amount: int = 150,
    project: str = "omr",
    user_id: str = OTHER,
    token: str = "service-token",
) -> object:
    body = {
        "project": project,
        "user_id": user_id,
        "type": ctype,
        "summary": f"evidencia {ref}",
        "amount": amount,
        "source_reference": ref,
    }
    return h.client.post("/api/v1/m2m/contributions", json=body, headers=_auth(token))


# --- Usuario -------------------------------------------------------------------


def test_user_me_lists_own_and_consent_grant_and_revoke() -> None:
    with _make_harness() as h:
        _ensure_member(h.session, USER)
        _add_recognition(h.session, user_id=USER)

        me = h.client.get("/api/v1/recognitions/me?project=omr", headers=_auth("user-token"))
        assert me.status_code == 200
        assert [r["type"] for r in me.json()] == ["voice"]

        consent = h.client.put(
            "/api/v1/recognitions/me/consent",
            json={"project": "omr", "type": "voice", "public": True},
            headers=_auth("user-token"),
        )
        assert consent.status_code == 200
        assert consent.json()["changed"] is True
        current = h.recognitions.get_current(USER, "omr", RecognitionType.VOICE)
        assert current is not None and current.public

        revoked = h.client.put(
            "/api/v1/recognitions/me/consent",
            json={"project": "omr", "type": "voice", "public": False},
            headers=_auth("user-token"),
        )
        assert revoked.json()["changed"] is True
        current = h.recognitions.get_current(USER, "omr", RecognitionType.VOICE)
        assert current is not None and not current.public
        assert current.public_revoked_at is not None


def test_user_a_cannot_see_or_modify_user_b() -> None:
    with _make_harness() as h:
        _ensure_member(h.session, OTHER)
        _add_recognition(h.session, user_id=OTHER)

        me = h.client.get("/api/v1/recognitions/me?project=omr", headers=_auth("user-token"))
        assert me.json() == []

        consent = h.client.put(
            "/api/v1/recognitions/me/consent",
            json={"project": "omr", "type": "voice", "public": True},
            headers=_auth("user-token"),
        )
        assert consent.status_code == 404  # A no tiene ese reconocimiento


# --- Público -------------------------------------------------------------------


def test_public_only_active_and_consented_and_lean_fields() -> None:
    with _make_harness() as h:
        _ensure_member(h.session, OTHER)
        _add_recognition(
            h.session,
            user_id=OTHER,
            rtype=RecognitionType.CONTRIBUTOR,
            public=True,
        )
        _add_recognition(h.session, user_id=OTHER, rtype=RecognitionType.VOICE)
        _add_recognition(
            h.session,
            user_id=OTHER,
            project_slug=ECOSYSTEM_PROJECT_SLUG,
            rtype=RecognitionType.SUPPORTER,
            kind=RecognitionKind.DERIVED,
            status=RecognitionStatus.INACTIVE,
            public=True,
            granted_by=None,
            origin="rule:supporter",
        )

        omr = h.client.get(f"/api/v1/public/users/{OTHER}/recognitions?project=omr")
        assert omr.status_code == 200
        items = omr.json()
        assert [r["type"] for r in items] == ["contributor"]
        # Sin origin/reason/granted_by ni economía: solo type y granted_at.
        assert set(items[0].keys()) == {"type", "granted_at"}

        ecosystem = h.client.get(
            f"/api/v1/public/users/{OTHER}/recognitions?project={ECOSYSTEM_PROJECT_SLUG}"
        )
        assert ecosystem.json() == []  # INACTIVE + public=true invisible

        unknown = h.client.get(f"/api/v1/public/users/{OTHER}/recognitions?project=nope")
        assert unknown.status_code == 404


# --- Admin ---------------------------------------------------------------------


def test_admin_requires_role_and_lists() -> None:
    with _make_harness() as h:
        _ensure_member(h.session, OTHER)
        voice = _add_recognition(h.session, user_id=OTHER)

        forbidden = h.client.get(
            f"/api/v1/admin/recognitions?user_id={OTHER}",
            headers=_auth("non-admin-token"),
        )
        assert forbidden.status_code == 403

        ok = h.client.get(
            f"/api/v1/admin/recognitions?user_id={OTHER}", headers=_auth("admin-token")
        )
        assert ok.status_code == 200
        assert ok.json()[0]["id"] == voice.id
        assert ok.json()[0]["granted_by"] == ADMIN


def test_admin_grant_contributor_and_reject_supporter_founder() -> None:
    with _make_harness() as h:
        _ensure_member(h.session, OTHER)
        headers = _auth("admin-token")

        grant = h.client.post(
            "/api/v1/admin/recognitions",
            json={
                "user_id": OTHER,
                "project": "omr",
                "type": "contributor",
                "reason": "150 obras",
            },
            headers=headers,
        )
        assert grant.status_code == 201
        current = h.recognitions.get_current(OTHER, "omr", RecognitionType.CONTRIBUTOR)
        assert current is not None and current.kind is RecognitionKind.GRANTED

        for invalid_type in ("supporter", "founder"):
            resp = h.client.post(
                "/api/v1/admin/recognitions",
                json={
                    "user_id": OTHER,
                    "project": "omr",
                    "type": invalid_type,
                    "reason": "manual",
                },
                headers=headers,
            )
            assert resp.status_code == 422


def test_admin_revoke_marks_inactive_and_records_event() -> None:
    with _make_harness() as h:
        _ensure_member(h.session, OTHER)
        voice = _add_recognition(h.session, user_id=OTHER)

        resp = h.client.post(
            f"/api/v1/admin/recognitions/{voice.id}/revoke",
            json={"reason": "baja de voz"},
            headers=_auth("admin-token"),
        )
        assert resp.status_code == 200
        current = h.recognitions.get_current(OTHER, "omr", RecognitionType.VOICE)
        assert current is not None and current.status is RecognitionStatus.INACTIVE
        event_types = [e.event_type for e in h.events.list_by_user(OTHER)]
        assert RecognitionEventType.REVOKED in event_types

        missing = h.client.post(
            "/api/v1/admin/recognitions/99999/revoke",
            json={"reason": "no existe"},
            headers=_auth("admin-token"),
        )
        assert missing.status_code == 404


# --- M2M -----------------------------------------------------------------------


def test_m2m_user_token_rejected() -> None:
    with _make_harness() as h:
        assert _ingest(h, ref="ref-u1", token="user-token").status_code == 401


def test_m2m_service_without_scope_403() -> None:
    with _make_harness() as h:
        resp = h.client.post(
            "/api/v1/m2m/contributions",
            json={
                "project": "omr",
                "user_id": OTHER,
                "type": "review",
                "summary": "x",
                "amount": 150,
                "source_reference": "ref-s1",
            },
            headers=_auth("no-scope-token"),
        )
        assert resp.status_code == 403


def test_m2m_unknown_client_403() -> None:
    with _make_harness() as h:
        resp = _ingest(h, ref="ref-u2", token="unknown-service-token")
        assert resp.status_code == 403


def test_m2m_project_outside_allowlist_403() -> None:
    with _make_harness() as h:
        resp = _ingest(h, ref="ref-x", project=ECOSYSTEM_PROJECT_SLUG)
        assert resp.status_code == 403


def test_m2m_ingest_201_duplicate_200_and_derived_source() -> None:
    with _make_harness() as h:
        first = _ingest(h, ref="omr/rev/150")
        assert first.status_code == 201
        assert first.json()["status"] == "created"
        assert first.json()["contributor_active"] is True

        second = _ingest(h, ref="omr/rev/150")
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"

        rows = h.contributions.list_by_user_project(OTHER, "omr")
        assert len(rows) == 1
        # source derivado de la allowlist, nunca del cliente.
        assert rows[0].source == "omr"


def test_m2m_cannot_spoof_source_field() -> None:
    with _make_harness() as h:
        body = {
            "project": "omr",
            "user_id": OTHER,
            "type": "review",
            "summary": "x",
            "amount": 150,
            "source_reference": "ref-spoof",
            "source": "otro-sistema",
        }
        resp = h.client.post(
            "/api/v1/m2m/contributions", json=body, headers=_auth("service-token")
        )
        assert resp.status_code == 422  # extra="forbid": source nunca viaja en el body
        assert h.contributions.list_by_user_project(OTHER, "omr") == []


# --- Flujo de integración: OMR → Support → CONTRIBUTOR -------------------------


def test_contributor_derived_without_membership_or_donation_data() -> None:
    """Sin memberships ni donations, solo deltas de OMR: suma 150 → CONTRIBUTOR en /me."""
    with _make_harness() as h:
        for ref, ctype, amount in (
            ("omr/rev/40", "review", 40),
            ("omr/rev/60", "review", 60),
            ("omr/doc/50", "documentation", 50),
        ):
            resp = _ingest(h, ref=ref, ctype=ctype, amount=amount, user_id=USER)
            assert resp.status_code == 201

        me = h.client.get("/api/v1/recognitions/me?project=omr", headers=_auth("user-token"))
        assert me.status_code == 200
        contributor = [r for r in me.json() if r["type"] == "contributor"]
        assert len(contributor) == 1
        assert contributor[0]["status"] == "active"
