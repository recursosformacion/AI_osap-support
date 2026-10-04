"""Mantenimiento web de reconocimientos de osap-support (capa propia, ADR-015).

Igual que osap-storage tiene su capa web de mantenimiento, osap-support expone la suya. Esta
página es un shell HTML cuyo JavaScript llama a la API admin JSON ya existente
(`/api/v1/admin/recognitions`, scope `support:admin`); osap-api la abre con un service token.

El token llega por query (`?token=`) desde osap-api y se inyecta en la página. La página NO
contiene lógica de negocio: solo lista y delega en la API admin (los propios endpoints validan
el token/scope).
"""

# ruff: noqa: E501 — la página HTML/CSS/JS embebida tiene líneas largas a propósito.

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from domain.ports.identity import IdentityError, ServiceAuthenticator

router = APIRouter(prefix="/api/v1/admin/web", tags=["admin-web"])

_ADMIN_SCOPE = "support:admin"

_PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Reconocimientos · osap-support</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
  header { padding: 12px 20px; border-bottom: 1px solid #2a2f3a; display: flex; gap: 12px; align-items: baseline; }
  h1 { font-size: 18px; margin: 0; }
  main { padding: 20px; max-width: 960px; }
  .card { border: 1px solid #2a2f3a; border-radius: 8px; padding: 16px; margin-bottom: 16px; background: #161a22; }
  label { display: block; font-size: 12px; color: #9aa4b2; margin-bottom: 2px; }
  input, select { padding: 6px 8px; border: 1px solid #2a2f3a; border-radius: 6px; background: #0f1115; color: #e6e6e6; }
  .row { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
  button { padding: 7px 12px; border-radius: 6px; border: 1px solid #2a2f3a; background: #22303f; color: #e6e6e6; cursor: pointer; }
  button.primary { background: #2f6f4f; border-color: #2f6f4f; }
  button.danger { background: #7a2f2f; border-color: #7a2f2f; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a2f3a; }
  th { color: #9aa4b2; font-weight: 500; }
  code { color: #b8c0cc; }
  .err { color: #ff8a8a; }
  .muted { color: #9aa4b2; font-size: 12px; }
</style>
</head>
<body>
<header><h1>Reconocimientos · osap-support</h1><span class="muted" id="status"></span></header>
<main>
  <div class="card">
    <div class="row">
      <div><label for="user_id">user_id</label><input id="user_id" size="40" placeholder="UUID del usuario" /></div>
      <div><label for="project">proyecto</label><input id="project" size="14" value="omr" /></div>
      <button id="load">Cargar</button>
    </div>
    <p class="muted">Lista los reconocimientos del usuario (todos los estados).</p>
  </div>

  <div class="card">
    <table>
      <thead><tr><th>id</th><th>tipo</th><th>proyecto</th><th>estado</th><th>concedido</th><th>por</th><th></th></tr></thead>
      <tbody id="rows"><tr><td colspan="7" class="muted">Sin datos.</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <div class="row">
      <div><label for="g_type">tipo</label>
        <select id="g_type"><option>contributor</option><option>voice</option><option>founder</option></select>
      </div>
      <div><label for="g_reason">motivo (opcional)</label><input id="g_reason" size="30" /></div>
      <button class="primary" id="grant">Conceder</button>
    </div>
    <p class="muted">Concede al usuario/proyecto de arriba. La visibilidad pública la decide el consentimiento de cuenta en osap-auth.</p>
    <p class="err" id="error"></p>
  </div>
</main>
<script>
const TOKEN = "__TOKEN__";
const api = (path, opts = {}) => fetch(path, { ...opts, headers: { "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json" } });
const el = (id) => document.getElementById(id);
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function setError(msg) { el("error").textContent = msg || ""; }

async function load() {
  const user_id = el("user_id").value.trim();
  const project = el("project").value.trim();
  if (!user_id) { setError("Indica user_id."); return; }
  setError(""); el("status").textContent = "cargando…";
  const qs = new URLSearchParams({ user_id });
  if (project) qs.set("project", project);
  const r = await api("/api/v1/admin/recognitions?" + qs);
  el("status").textContent = "HTTP " + r.status;
  if (!r.ok) { setError("No se pudo listar (" + r.status + ")."); return; }
  const rows = await r.json();
  el("rows").innerHTML = rows.length ? rows.map((x) => `<tr>
    <td>${esc(x.id)}</td><td>${esc(x.type)}</td><td>${esc(x.project)}</td>
    <td>${esc(x.status)}</td><td>${esc(x.granted_at)}</td><td>${esc(x.granted_by)}</td>
    <td>${x.status === "active" ? `<button class="danger" data-revoke="${esc(x.id)}">revocar</button>` : ""}</td>
  </tr>`).join("") : `<tr><td colspan="7" class="muted">Sin reconocimientos.</td></tr>`;
}

async function grant() {
  const user_id = el("user_id").value.trim();
  const project = el("project").value.trim();
  if (!user_id || !project) { setError("Indica user_id y proyecto."); return; }
  setError("");
  const body = { user_id, project, type: el("g_type").value };
  const reason = el("g_reason").value.trim();
  if (reason) body.reason = reason;
  const r = await api("/api/v1/admin/recognitions", { method: "POST", body: JSON.stringify(body) });
  el("status").textContent = "HTTP " + r.status;
  if (!r.ok) { const d = await r.json().catch(() => ({})); setError(d.detail || "No se pudo conceder."); return; }
  await load();
}

async function revoke(id) {
  setError("");
  const r = await api("/api/v1/admin/recognitions/" + encodeURIComponent(id) + "/revoke", { method: "POST", body: "{}" });
  el("status").textContent = "HTTP " + r.status;
  if (!r.ok) { const d = await r.json().catch(() => ({})); setError(d.detail || "No se pudo revocar."); return; }
  await load();
}

el("load").addEventListener("click", load);
el("grant").addEventListener("click", grant);
el("rows").addEventListener("click", (e) => { const b = e.target.closest("[data-revoke]"); if (b) revoke(b.dataset.revoke); });
</script>
</body>
</html>
"""


@router.get("/recognitions", response_class=HTMLResponse)
def recognitions_page(token: str = Query(..., min_length=1)) -> HTMLResponse:
    try:
        _service_authenticator.authenticate_service(token, required_scope=_ADMIN_SCOPE)
    except IdentityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return HTMLResponse(_PAGE.replace("__TOKEN__", token))


_service_authenticator: ServiceAuthenticator


def wire_admin_web_router(*, service_authenticator: ServiceAuthenticator) -> APIRouter:
    global _service_authenticator
    _service_authenticator = service_authenticator
    return router
