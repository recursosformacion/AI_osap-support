# OSAP Support — servicio independiente de apoyo del ecosistema

Servicio real de soporte económico de OSAP: identidad por JWKS de osap-auth, pagos por
**PayPal** (donaciones puntuales y membresías recurrentes), emails por SMTP vía worker,
BD propia `osap_support`, configuración por variables de entorno (`OSAP_SUPPORT_*`).

Es un servicio **independiente** del resto de OSAP: no lee `osap.toml`/`osap.production.toml`
de osap-api; puede desplegarse en otra máquina con su propia configuración externa
(la BD usa el mismo usuario/credenciales del ecosistema).

## Documentación

- [`docs/architecture.md`](docs/architecture.md) — recorridos reales (identity, donation,
  membership, webhook, worker).
- [`docs/configuration.md`](docs/configuration.md) — variables de entorno (env), separadas
  por entorno, y regla de fail-fast.
- [`docs/deployment.md`](docs/deployment.md) — receta: BD → Alembic → procesos web/worker
  → Apache → webhook.
- [`docs/paypal.md`](docs/paypal.md) — sandbox/live, planes, webhook y verificación.
- [`docs/email.md`](docs/email.md) — SMTP y plantillas.

Material de despliegue en [`deploy/`](deploy/): `env.example`, units systemd (web y
worker) y `osap-support-vhost.conf` (Apache, patrón osap-app).

## Stack

FastAPI + uvicorn + Pydantic v2 + pydantic-settings + MySQL/MariaDB + Alembic +
SQLAlchemy 2 + PyJWT + httpx (dev: pytest + ruff + mypy).

## Estructura (hexagonal)

```
domain/ports/          IdentityResolver (ADR-002), PaymentProvider (ADR-005), EmailSender (ADR-006)
domain/entities.py     SupportMember, Membership, Donation, PaymentEvent, CommunicationEvent
application/use_cases  get_my_membership, checkout_donation, checkout_membership,
                       process_payment_webhook, process_communication_events
infrastructure/
  config.py            Settings (OSAP_SUPPORT_*): server/db/identity/payment/smtp
  db/alembic/          0001_create_support_tables
  identity/            Static (dev/test) + JwksIdentityResolver (production)
  payment/             Fake (dev/test) + PayPalPaymentProvider
  email/               Fake (dev/test) + SmtpEmailSender
  worker.py            proceso worker (bucle / --once)
api/main.py            app FastAPI: /health, /ready, membership/me, checkouts, webhook
deploy/                env.example, systemd (web/worker), Apache vhost
tests/                 99 tests (suite verde)
```

## Verificaciones

```bash
python -m ruff check api infrastructure application domain tests
python -m mypy api infrastructure application domain   # salvo stub preexistente de yaml
python -m pytest tests -q
```

## Recorrido mínimo

```text
usuario (osap-auth JWT)
→ osap-support (JWKS)
→ POST /api/v1/checkouts/donation|membership
→ PayPal approval URL
→ PayPal webhook (firma verificada)
→ persistencia
→ CommunicationEvent → worker → SMTP
```
