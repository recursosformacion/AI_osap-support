"""Provisión del plan de suscripción de apoyo en PayPal (Sandbox o Live).

Modelo económico actual (osap-support): UNA capa económica — un único producto
"Supporter" con periodicidad mensual/anual. Contributor/Voice/Founder son RELACIONES de
reconocimiento (no se crean planes; nunca se compran). free/Amigo (0 €) tampoco.

Idempotente: busca el producto por nombre; si existe, NO crea otro. Busca cada plan por
(nombre exacto dentro de ese producto); si existe ACTIVE, lo reutiliza y guarda su id.

Uso:
  python scripts/provision_paypal_plans.py            # sandbox (osap.toml)
  python scripts/provision_paypal_plans.py --production
  python scripts/provision_paypal_plans.py --dry-run  # solo muestra qué haría
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_API_BASE = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}

_PRODUCT_NAME = "OSAP Support"
_PRODUCT_DESC = "Suscripción de apoyo a OpenMusicRepository (plan Supporter)."

# Niveles de la capa económica → campos de plan en osap.toml. Solo supporter hoy.
_ECONOMIC_PLANS = [("supporter", "monthly"), ("supporter", "yearly")]

_TOML_PLAN_FIELD = {
    ("supporter", "monthly"): "plan_supporter_monthly",
    ("supporter", "yearly"): "plan_supporter_yearly",
}

# Nombre estable de cada plan (el del producto + periodicidad).
def _plan_name(periodicity: str) -> str:
    suffix = "Monthly" if periodicity == "monthly" else "Yearly"
    return f"{_PRODUCT_NAME} - {suffix}"


def _load(cfg_path: Path) -> tuple[dict, dict]:
    with cfg_path.open("rb") as fh:
        data = tomllib.load(fh)
    paypal = data.get("paypal", {})
    if not paypal.get("client_id") or not paypal.get("client_secret"):
        raise SystemExit(
            f"Credenciales PayPal ausentes en {cfg_path} "
            "(rellena [paypal].client_id / client_secret)."
        )
    catalog = data.get("catalog", {})
    return paypal, catalog


def _token(client: httpx.Client, paypal: dict) -> str:
    base = _API_BASE[paypal["mode"]]
    r = client.post(
        f"{base}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(paypal["client_id"], paypal["client_secret"]),
        headers={"Accept": "application/json"},
    )
    if r.status_code != 200:
        raise SystemExit(
            f"Autenticación PayPal fallida ({r.status_code}): "
            f"{r.json().get('error_description') or r.text[:200]}"
        )
    return str(r.json()["access_token"])


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _find_product(client: httpx.Client, headers: dict[str, str], mode: str) -> str | None:
    base = _API_BASE[mode]
    url = f"{base}/v1/catalogs/products?page_size=100&total_required=true"
    data = client.get(url, headers=headers).json()
    for item in data.get("products", []):
        if item.get("name") == _PRODUCT_NAME:
            return str(item["id"])
    return None


def _create_product(client: httpx.Client, headers: dict[str, str], mode: str) -> str:
    base = _API_BASE[mode]
    r = client.post(
        f"{base}/v1/catalogs/products",
        json={"name": _PRODUCT_NAME, "description": _PRODUCT_DESC, "type": "SERVICE"},
        headers=headers,
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"No se pudo crear el producto PayPal: {r.status_code} {r.text[:300]}")
    return str(r.json()["id"])


def _find_plan(
    client: httpx.Client, headers: dict[str, str], mode: str, product_id: str, plan_name: str
) -> str | None:
    base = _API_BASE[mode]
    url = f"{base}/v1/billing/plans?product_id={product_id}&page_size=100&total_required=true"
    data = client.get(url, headers=headers).json()
    for item in data.get("plans", []):
        if item.get("name") == plan_name:
            return str(item["id"])
    return None


def _create_plan(
    client: httpx.Client,
    headers: dict[str, str],
    mode: str,
    product_id: str,
    plan_name: str,
    periodicity: str,
    price: float,
    currency: str,
) -> str:
    base = _API_BASE[mode]
    interval = "MONTH" if periodicity == "monthly" else "YEAR"
    body = {
        "product_id": product_id,
        "name": plan_name,
        "billing_cycles": [
            {
                "frequency": {"interval_unit": interval, "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {
                    "fixed_price": {"value": f"{price:.2f}", "currency_code": currency}
                },
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "payment_failure_threshold": 2,
        },
    }
    r = client.post(f"{base}/v1/billing/plans", json=body, headers=headers)
    if r.status_code not in (200, 201):
        raise SystemExit(f"No se pudo crear el plan {plan_name}: {r.status_code} {r.text[:300]}")
    return str(r.json()["id"])


def _plan_is_active(client: httpx.Client, headers: dict[str, str], mode: str, plan_id: str) -> bool:
    base = _API_BASE[mode]
    r = client.get(f"{base}/v1/billing/plans/{plan_id}", headers=headers)
    return r.status_code == 200 and r.json().get("status") == "ACTIVE"


def _find_or_create_product(client: httpx.Client, headers: dict[str, str], mode: str) -> str:
    product_id = _find_product(client, headers, mode)
    if product_id is not None:
        return product_id
    return _create_product(client, headers, mode)


def _ensure_plan(
    client: httpx.Client,
    headers: dict[str, str],
    mode: str,
    product_id: str,
    plan_name: str,
    periodicity: str,
    price: float,
    currency: str,
    configured_plan_id: str,
) -> str:
    # 1) Si el toml ya apunta a un plan ACTIVE, conservarlo (nunca duplicar).
    if configured_plan_id and _plan_is_active(client, headers, mode, configured_plan_id):
        return configured_plan_id
    # 2) Reutilizar un plan existente con ese nombre en el producto canónico.
    existing = _find_plan(client, headers, mode, product_id, plan_name)
    if existing is not None and _plan_is_active(client, headers, mode, existing):
        return existing
    # 3) Crear.
    return _create_plan(
        client, headers, mode, product_id, plan_name, periodicity, price, currency
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production",
        action="store_true",
        help="Usar osap.production.toml (live) en lugar de osap.toml (sandbox)",
    )
    parser.add_argument("--config", default=None, help="Ruta al toml")
    parser.add_argument("--dry-run", action="store_true", help="Solo imprime el plan de provisión")
    args = parser.parse_args(argv)

    if args.config:
        cfg_path = Path(args.config)
    else:
        cfg_path = PROJECT_ROOT / ("osap.production.toml" if args.production else "osap.toml")
    paypal, catalog = _load(cfg_path)
    mode = paypal["mode"]
    currency = catalog.get("currency", "EUR")
    supporter = catalog.get("supporter", {})
    configured = {
        key: str(paypal.get(key, "") or "")
        for key in ("plan_supporter_monthly", "plan_supporter_yearly")
    }

    print(f"modo={mode} fichero={cfg_path}")
    for _level, period in _ECONOMIC_PLANS:
        price = float(supporter.get(period, 0) or 0)
        print(f"  plan supporter/{period}: {_plan_name(period)} = {price:.2f} {currency}")
    if args.dry_run:
        return

    with httpx.Client(timeout=30.0) as client:
        headers = _headers(_token(client, paypal))
        product_id = _find_or_create_product(client, headers, mode)
        print(f"producto: {product_id}")

        updates = {}
        for _level, period in _ECONOMIC_PLANS:
            field = _TOML_PLAN_FIELD[("supporter", period)]
            plan_id = _ensure_plan(
                client,
                headers,
                mode,
                product_id,
                _plan_name(period),
                period,
                float(supporter.get(period, 0) or 0),
                currency,
                configured.get(field, ""),
            )
            updates[field] = plan_id
            print(f"  {field} = {plan_id}  ({_plan_name(period)})")

        text = cfg_path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if key in updates and stripped.startswith(key):
                out.append(f'{key} = "{updates[key]}"\n')
            else:
                out.append(line)
        cfg_path.write_text("".join(out), encoding="utf-8")
        print("plan_ids guardados en", cfg_path)


if __name__ == "__main__":
    main(sys.argv[1:])
