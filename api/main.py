"""Aplicación FastAPI de OSAP Support (Fase 1 — esqueleto).

Solo arranque/infraestructura. NO expone endpoints de negocio (ADR-008, API de
membership en fases posteriores). El Stack es el de referencia (ADR-011): FastAPI,
uvicorn, pydantic v2, pydantic-settings.
"""

from __future__ import annotations

from fastapi import FastAPI

from infrastructure.config import Settings, load_settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title=settings.server.app_title, version=settings.server.app_version)
    app.state.settings = settings

    @app.get("/")
    def health() -> dict[str, str]:
        return {"service": "osap-support", "version": settings.server.app_version, "status": "ok"}

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
