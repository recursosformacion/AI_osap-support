# OSAP Support — Email (SMTP)

## Modelo

El email NO se envía desde el proceso HTTP. El webhook/pago crea un
`CommunicationEvent` (estado `pending`); el **worker** (`osap-support-worker`,
proceso independiente) lo consume y lo envía con el EmailSender real.

```
CommunicationEvent(pending)
→ worker (bucle o --once)
→ SmtpEmailSender (SMTP real)
→ proveedor acepta → sent
→ proveedor rechaza → failed + backoff (attempts, next_attempt_at)
```

"Enviado" significa **aceptado por el servidor SMTP** (respuesta 2xx a `send_message`),
no "entregado al buzón del destinatario".

## Configuración (production)

| Variable | Descripción |
|---|---|
| `OSAP_SUPPORT_EMAIL_SENDER` | `smtp` (obligatorio en production; `fake` solo dev/test) |
| `OSAP_SUPPORT_SMTP_HOST` | servidor SMTP |
| `OSAP_SUPPORT_SMTP_PORT` | 587 (STARTTLS) |
| `OSAP_SUPPORT_SMTP_USERNAME` | usuario |
| `OSAP_SUPPORT_SMTP_PASSWORD` | contraseña (secreto) |
| `OSAP_SUPPORT_SMTP_FROM` | remitente |
| `OSAP_SUPPORT_SMTP_TLS` | `1` para STARTTLS |

En dev/test, sin `OSAP_SUPPORT_EMAIL_SENDER=smtp`, el worker usa `FakeEmailSender`
(solo tests/manual). En production sin SMTP configurado el worker **falla al arrancar**
(`EmailProviderMissing`).

## Plantillas

`infrastructure/email/smtp_email_sender.py` define `DEFAULT_TEMPLATES`:

- `membership_confirmation`
- `renewal_notice`
- `payment_failed`
- `membership_cancelled`
- `membership_expired`
- `donation_confirmation`

El sender rechaza un `template` desconocido (error explícito; nunca un correo vacío
presentado como enviado). Para producción real, sustituir el texto por plantillas HTML
con los datos del CommunicationEvent.
