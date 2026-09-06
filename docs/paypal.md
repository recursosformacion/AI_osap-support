# OSAP Support — PayPal

## Modos

- `OSAP_SUPPORT_PAYPAL_MODE=sandbox` → `https://api-m.sandbox.paypal.com`
- `OSAP_SUPPORT_PAYPAL_MODE=live` → `https://api-m.paypal.com`

Las credenciales (`CLIENT_ID`/`CLIENT_SECRET`) se crean en PayPal Developer
(Apps & Credentials) y se inyectan por entorno. **No versionar secretos.**

## Modelo económico — productos de suscripción actuales (congelados, ADR-013)

> ADR-013: `supporter/contributor/voice/founder` son, hoy, **productos económicos** de
> suscripción con importe, **no** reconocimientos. ADR-013 no aprueba ni descarta estos
> productos: solo fija que la revisión comercial (nombres, importes, periodicidades,
> continuidad) pertenece al dominio económico y no debe confundirse con los
> reconocimientos (dominio distinto, entidad propia según ADR-015). Los reconocimientos
> con esos mismos nombres visuales aún no están implementados.

Los planes de suscripción actuales del dominio económico son 4 productos × 2 periodicidades:

| Producto (plan de suscripción) | Periodicity | Variable de plan_id |
|---|---|---|
| supporter | monthly | `OSAP_SUPPORT_PAYPAL_PLAN_SUPPORTER_MONTHLY` |
| supporter | yearly | `OSAP_SUPPORT_PAYPAL_PLAN_SUPPORTER_YEARLY` |
| contributor | monthly | `OSAP_SUPPORT_PAYPAL_PLAN_CONTRIBUTOR_MONTHLY` |
| contributor | yearly | `OSAP_SUPPORT_PAYPAL_PLAN_CONTRIBUTOR_YEARLY` |
| voice | monthly | `OSAP_SUPPORT_PAYPAL_PLAN_VOICE_MONTHLY` |
| voice | yearly | `OSAP_SUPPORT_PAYPAL_PLAN_VOICE_YEARLY` |
| founder | monthly | `OSAP_SUPPORT_PAYPAL_PLAN_FOUNDER_MONTHLY` |
| founder | yearly | `OSAP_SUPPORT_PAYPAL_PLAN_FOUNDER_YEARLY` |

Los `plan_id` los crea el panel de PayPal (Billing > Plans) — producto + plan con
importe/periodicidad — UNA sola vez por entorno. El checkout envía SOLO `level` +
`periodicity`; el backend resuelve el `plan_id` interno. El navegador nunca elige plan.

## Donación (puntual)

`POST /api/v1/checkouts/donation` → Orders v2 (`intent=CAPTURE`) → approval URL.
La donación solo queda registrada al llegar el webhook de captura.

## Membresía (recurrente)

`POST /api/v1/checkouts/membership` → Subscriptions v2 (`plan_id`) → approval URL.
La membresía solo queda activa al llegar el webhook de suscripción/pago.

## Webhook

Endpoint público:

```
POST /api/v1/webhooks/payment   (publicado por Apache bajo /support-api/...)
```

1. PayPal envía el evento con headers de transmisión (`paypal-transmission-*`).
2. Support verifica la firma con `POST /v1/notifications/verify-webhook-signature`
   usando `OSAP_SUPPORT_PAYPAL_WEBHOOK_ID`.
3. Solo si `verification_status == SUCCESS` se parsea y procesa.
4. Eventos duplicados → `UNIQUE(provider, provider_event_id)` → `ignored_duplicate`
   (sin efectos duplicados).

### Registrar el webhook

- En PayPal Developer → la app → Webhooks → Add webhook.
- URL: el endpoint público de support.
- Eventos: `BILLING.SUBSCRIPTION.*`, `PAYMENT.SALE.*`, `PAYMENT.CAPTURE.*`,
  `CHECKOUT.ORDER.*`.
- PayPal muestra el `Webhook ID` → guardarlo en `OSAP_SUPPORT_PAYPAL_WEBHOOK_ID`.

## Sandbox vs Live

- **Sandbox**: usar credenciales de la app sandbox y cuentas de prueba; no es dinero
  real; verificación completa del circuito (checkout→aprobación→webhook→BD→estado).
- **Live**: mismas credenciales con `MODE=live`; requiere cuenta real, certificado/DNS
  y webhook público con HTTPS válido.

Un E2E contra Sandbox NO se considera "cerrado" si nunca se ejecutó realmente con
credenciales sandbox del administrador.
