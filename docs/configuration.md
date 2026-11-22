# OSAP Support — Configuración

Contrato de configuración: **convención del ecosistema OSAP** (igual que osap-api /
osap-storage): cada servicio tiene su propio fichero TOML en su directorio:

- `osap.toml`            → desarrollo/sandbox (local).
- `osap.production.toml` → producción (se despliega como `osap.toml` en el host).

Precedencia: **variable de entorno `OSAP_SUPPORT_*` > `osap.toml` (secciones) > defaults**.
El fichero está gitignored (contiene secretos) y puede sobreescribir cada valor por env.
`config.yaml` (capa de osap-auth) queda como capa opcional de menor precedencia.

La BD `osap_support` usa el mismo usuario/credenciales del ecosistema (mismos valores de
`osap.toml` de los demás servicios). Plantilla operativa: `deploy/env.example`.

## Secciones del TOML

| Sección | Aplica a | Notas |
|---|---|---|
| `[db]` | `DatabaseConfig` | host/port/name/user/password → `OSAP_SUPPORT_DB_*` |
| `[identity]` | `IdentityConfig` | jwks_uri/issuer/audience → `OSAP_SUPPORT_AUTH_*` |
| `[paypal]` | `PaymentConfig` | mode/client_id/client_secret/webhook_id/plan_* → `OSAP_SUPPORT_PAYPAL_*` |
| `[smtp]` | `SmtpConfig` | host/port/username/password/from_address/tls → `OSAP_SUPPORT_SMTP_*` |
| env `OSAP_SUPPORT_SERVER_*` | `ServerConfig` | host/port/env/debug/cors |

## Entorno / servidor

| Variable | Obligatoria | Descripción |
|---|---|---|
| `OSAP_SUPPORT_ENV` | sí | `development`/`test`/`production`. En `production` los fakes y PayPal Sandbox están prohibidos (fail-fast). |
| `OSAP_SUPPORT_SERVER_HOST` | no | 127.0.0.1 |
| `OSAP_SUPPORT_SERVER_PORT` | no | 8300 |
| `OSAP_SUPPORT_CORS_ORIGINS` | no | Solo si frontend y support son dominios distintos; lista separada por comas. Nunca `*` con credenciales. |

## Base de datos

| Variable | Obligatoria | Descripción |
|---|---|---|
| `OSAP_SUPPORT_DB_HOST` | no | 127.0.0.1 |
| `OSAP_SUPPORT_DB_PORT` | no | 3306 |
| `OSAP_SUPPORT_DB_NAME` | sí | `osap_support` |
| `OSAP_SUPPORT_DB_USER` | sí | p. ej. `osap2027` |
| `OSAP_SUPPORT_DB_PASSWORD` | sí | secreto |

## Identidad (JWKS osap-auth)

| Variable | Obligatoria en production |
|---|---|
| `OSAP_SUPPORT_AUTH_JWKS_URI` | sí |
| `OSAP_SUPPORT_AUTH_ISSUER` | sí |
| `OSAP_SUPPORT_AUTH_AUDIENCE` | sí (`osap-api`, user access tokens) |
| `OSAP_SUPPORT_AUTH_SERVICE_AUDIENCE` | sí (`osap-support`, service/M2M tokens) |
| `OSAP_SUPPORT_AUTH_JWKS_CACHE_TTL_SECONDS` | no (300) |

## PayPal

| Variable | Obligatoria en production |
|---|---|
| `OSAP_SUPPORT_PAYPAL_MODE` | sí (`live` exclusivamente) |
| `OSAP_SUPPORT_PAYPAL_CLIENT_ID` | sí |
| `OSAP_SUPPORT_PAYPAL_CLIENT_SECRET` | sí |
| `OSAP_SUPPORT_PAYPAL_WEBHOOK_ID` | sí (verificación de firma) |
| `OSAP_SUPPORT_PAYPAL_PLAN_<NIVEL>_<PERIODICIDAD>` | sí (8: supporter/contributor/voice/founder × monthly/yearly) |

Detalle y procedimiento: `docs/paypal.md`.

## Email (worker)

| Variable | Obligatoria en production |
|---|---|
| `OSAP_SUPPORT_EMAIL_SENDER` | sí (`smtp`) |
| `OSAP_SUPPORT_SMTP_HOST` | sí |
| `OSAP_SUPPORT_SMTP_PORT` | no (587) |
| `OSAP_SUPPORT_SMTP_USERNAME` | según servidor |
| `OSAP_SUPPORT_SMTP_PASSWORD` | según servidor |
| `OSAP_SUPPORT_SMTP_FROM` | no |
| `OSAP_SUPPORT_SMTP_TLS` | no (1) |

`OSAP_SUPPORT_EMAIL_SENDER=fake` SOLO es válido en dev/test; en production el worker
falla al arrancar.

## Worker

| Variable | Descripción |
|---|---|
| `OSAP_SUPPORT_WORKER_POLL_SECONDS` | poll del bucle (por defecto 30) |

## Fail-fast

En `production` el arranque web falla si falta: JWKS/issuer/audience, credenciales
PayPal Live, webhook verificable y los ocho plan IDs Live reales. El worker falla si falta SMTP real. Ningún fake es seleccionable por
configuración de producción.


En producción, `OSAP_SUPPORT_ENV` debe ser `production` (es el valor por defecto si no hay
marcador de entorno). Un `OSAP_SUPPORT_ENV` explícito prevalece sobre `app.env` de
`config.yaml`. Para desarrollo local, establecer `OSAP_SUPPORT_ENV=development`.


## Contrato M2M con osap-auth y osap-api

Los tokens de usuario y de servicio tienen audiencias distintas:

- Access tokens de usuario enviados por el frontend: `aud=osap-api`.
- Service tokens emitidos para llamadas OSAP API → Support: `aud=osap-support`.

En osap-auth, el service client usado por osap-api debe permitir la audiencia
`osap-support` y los scopes que consume Support: `api:read` para reconocimientos públicos
y `support:admin` para operaciones administrativas. Si se usan credenciales de servicio
separadas, ambos client IDs deben tener su allowlist de audiencia correspondiente.

Los client IDs de `client_credentials` son UUID de registros de service clients de osap-auth,
no el nombre OIDC `osap-api`. El mismo UUID del cliente que solicita `api:read` debe figurar
en la allowlist M2M de este servicio cuando se use la ruta de reconocimientos:

```toml
[[m2m.clients]]
client_id = "<UUID del service client de osap-api>"
source = "osap-api"
projects = ["<slug de proyecto autorizado>"]
```

Sin esa entrada, `GET /api/v1/m2m/recognitions` responde 403 aunque el JWT sea válido.
