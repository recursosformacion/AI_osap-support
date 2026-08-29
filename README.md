# OSAP Support — servicio independiente de apoyo del ecosistema

**Fase 1 — esqueleto del servicio.** Stack de referencia (ADR-011): FastAPI + uvicorn +
Pydantic v2 + pydantic-settings + MySQL + Alembic + PyJWT + httpx (dev: pytest-asyncio + ruff + mypy).

## ADR aplicados (ver `docs/../support-decisions.md`)

- ADR-001 — Support es propietario de la relación de apoyo (no de identidad ni datos de pago).
- ADR-002 — Identidad canónica `JWT.sub == Auth.user_id`; sin usuarios locales.
- ADR-003 — BD propia `osap_support` (config por entorno, Alembic).
- ADR-011 — Stack del servicio pequeño de referencia (osap-auth), Python ≥ 3.12.

## Estructura (hexagonal, como osap-auth)

```
domain/ports/         ports estables: IdentityResolver (ADR-002), PaymentProvider (ADR-005), EmailSender (ADR-006)
application/use_cases caso de uso mínimo: ResolveMyUserIdUseCase (ADR-002)
infrastructure/
  config.py           Settings/database/identity (OSAP_SUPPORT_*)
  db/alembic/         migraciones (base; sin tablas de negocio en esta fase)
  identity/           StaticIdentityResolver (dev/tests; JWKS real queda abierto)
api/main.py           app FastAPI mínima (solo liveness; sin endpoints de negocio)
config.example.yaml
tests/                pruebas de config, imports, identidad, aislamiento
```

## Límites

- **No** creados en esta fase: proveedor de pagos/email, endpoints de negocio, tablas de
  Memberships/Donations/PaymentEvents, extracción física de Chorus, Social.
- Decisiones **ABIERTAS** (no decididas): proveedor concreto, hosting/Docker, frecuencia de
  scheduler, JWKS real, `SupportApiClient`, comunidad, niveles/recompensas, panel admin.
