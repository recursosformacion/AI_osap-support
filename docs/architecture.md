# OSAP Support — Arquitectura

## Principios

- Servicio **independiente** del resto de OSAP (puede vivir en otra máquina). BD propia
  `osap_support` con el mismo usuario/credenciales de BD del ecosistema (configuración
  externa, nunca en el repo).
- Configuración por la convención del ecosistema: **`osap.toml` (dev) / `osap.production.toml` (prod, desplegado como `osap.toml`) propios del servicio y gitignored**, con precedencia `env OSAP_SUPPORT_* > toml > defaults` (ver `infrastructure/config.py`). No se leen los `osap.toml` de osap-api ni de otros servicios.
- Fail-fast: en production, si falta identity/JWKS, PayPal, SMTP o plan_ids → el
  arranque falla. Nunca degrada a fakes.

## Recorridos reales

### Identidad

```
browser (token Bearer de osap-auth)
→ osap-support HTTP
→ IdentityResolver (production: JWKS de osap-auth; dev/test: estático)
→ user_id = JWT.sub
```

### Donación

```
usuario autenticado
→ POST /api/v1/checkouts/donation {amount_minor, currency, return_url}
→ CheckoutDonationUseCase
→ PayPal Orders v2 → order approval URL (real, del proveedor)
→ PayPal webhook → verificación firma → persistencia Donation
```

### Membresía

```
usuario autenticado
→ POST /api/v1/checkouts/membership {level, periodicity, return_url}
→ CheckoutMembershipUseCase
→ plan_id resuelto en backend (level+periodicity → configuración interna)
→ PayPal Subscriptions v2 → subscription approval URL
→ PayPal webhook → verificación firma → Membership (state machine)
```

### Comunicación (worker)

```
webhook procesado → CommunicationEvent(pending)
→ worker (proceso separado) → EmailSender real (SMTP) → sent/failed + backoff
```

## Puertos y adaptadores

- `domain/ports/identity.py` — IdentityResolver (Static dev, Jwks productivo).
- `domain/ports/payment.py` — PaymentProvider (Fake test, PayPal).
- `domain/ports/email.py` — EmailSender (Fake test, SMTP).
- Repositorios SQLAlchemy + Alembic (tablas: support_members, memberships, donations,
  payment_events, communication_events).

## Seguridad

- user_id SIEMPRE de la identidad (JWT.sub); nunca de la URL ni del navegador.
- plan_id resuelto en backend; no se acepta del cliente (extra=forbid).
- importes en unidades mínimas enteras (amount_minor), currency validada ISO 4217.
- Webhook: firma verificada antes de procesar; eventos duplicados idempotentes.
- Secretos fuera de Git (env de despliegue). No se registran client_secret/password.
