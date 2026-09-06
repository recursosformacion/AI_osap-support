# OSAP Support — despliegue

Servicio independiente del ecosistema OSAP (puede vivir en otra máquina). NO usa
Docker (el ecosistema OSAP no usa Docker): web y worker son dos procesos uvicorn
independientes bajo Apache/systemd.

## Componentes

| Proceso | Entry point | Puerto | Health |
|---|---|---|---|
| Web (API) | `osap-support-web` | 8300 | `GET /health`, `GET /ready` |
| Worker (emails) | `osap-support-worker` | — | logs + `--once` para comprobar |

## Receta reproducible

### 1. Base de datos

```bash
# Crear BD (mismo user del ecosistema, p. ej. osap2027):
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS osap_support CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL ON osap_support.* TO 'osap2027'@'%';"
```

### 2. Migraciones (Alembic)

```bash
export OSAP_SUPPORT_DB_HOST=127.0.0.1
export OSAP_SUPPORT_DB_PORT=3306
export OSAP_SUPPORT_DB_NAME=osap_support
export OSAP_SUPPORT_DB_USER=osap2027
export OSAP_SUPPORT_DB_PASSWORD=***   # idéntico al del ecosistema

python -m alembic upgrade head    # desde la raíz del repo
# Idempotente: una segunda ejecución no hace cambios.
```

### 3. Variables (configuración externa — support NO lee osap.toml)

Ver `docs/configuration.md`. En producción TODAS las siguientes son obligatorias
(arranque fail-fast si faltan): JWKS/issuer de osap-auth, PayPal (mode/client/webhook/
plan_ids), SMTP, BD. No hay secretos en el repo.

### 4. Procesos

```bash
# Web (proxy Apache → 127.0.0.1:8300)
export OSAP_SUPPORT_ENV=production
osap-support-web

# Worker (proceso separado, reinicio automático con systemd)
osap-support-worker
```

En dev:

```bash
python -m uvicorn --factory api.main:create_app_from_settings --host 127.0.0.1 --port 8300
python -m infrastructure.worker --once
```

### 5. Apache (patrón osap-app, sin Docker)

Ver `deploy/osap-support-vhost.conf`. El navegador habla con Apache (mismo origen que
el resto de OSAP), no con el puerto 8300:

```
Internet → Apache (osap-app / support.openmusicrepository.com)
         → ProxyPass /support-api → http://127.0.0.1:8300
```

`osap-app` (dev) y el vhost de producción publican support bajo un prefijo propio para
no colisionar con `/api` de osap-api.

### 6. Webhook PayPal

Apuntar el webhook de PayPal al endpoint público de support:

```
POST https://<host>/support-api/api/v1/webhooks/payment
```

Firma verificada por PayPal (verify-webhook-signature) antes de procesar (ver
`docs/paypal.md`).
