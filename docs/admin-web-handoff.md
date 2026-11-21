# Handoff seguro del panel de reconocimientos

El panel de reconocimientos se abre desde osap-api mediante un formulario POST a
`/api/v1/admin/web/session`. El cuerpo contiene el service token `support:admin` y el
destino relativo `./recognitions`; ninguna credencial se coloca en la URL o en el HTML.

El servicio valida el origen HTTP contra `server.admin_handoff_origins` (TOML) o
`OSAP_SUPPORT_SERVER_ADMIN_HANDOFF_ORIGINS` (entorno). En producción debe incluir
`https://app.openmusicrepository.com`.

Tras validar el service token, Support emite una cookie host-only `osap_support_admin`,
`HttpOnly`, `Secure`, `SameSite=Lax`, con caducidad no superior al `exp` del JWT. La cookie
se limita a la sesión del navegador y autentica la página y sus endpoints admin. Las
operaciones mutables que usan la cookie exigen `Origin` same-origin.

La página conserva el prefijo público del reverse proxy para sus llamadas API. La cookie
usa `Path=/` para funcionar tanto en despliegues en raíz como bajo `/support-api`.

Los tokens en query strings y la inyección del token en JavaScript/HTML ya no forman parte
del contrato aceptado.