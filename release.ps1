# release.ps1 — Libera una versión de osap-support a producción (91.134.255.134).
#
# Resumen: corre tests/lint/tipos, sube el código por tar+ssh, asegura el venv,
# despliega `osap.production.toml` como `osap.toml` en el servidor, aplica migraciones
# Alembic y reinicia el servicio systemd verificando /health en 127.0.0.1:8300.
#
# Notas:
#   - `osap.toml` (dev) y `osap.production.toml` (prod) NO se suben al repo.
#   - Producción solo se toca al cerrar una versión.
#
# Uso:
#   pwsh osap-support/release.ps1 [-SkipTests] [-SkipMigrations]

param(
    [string]$Server = "91.134.255.134",
    [string]$User = "ocw",
    [string]$RemoteDir = "/home/ocw/openmusicrepository.com/osap-support",
    [switch]$SkipTests,
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Invoke-Remote($cmd) {
    ssh -o BatchMode=yes "$User@$Server" $cmd
    if ($LASTEXITCODE -ne 0) { throw "Fallo remoto: $cmd" }
}

Write-Host "== Liberación de osap-support ==" -ForegroundColor Cyan

if (-not $SkipTests) {
    Write-Host "[1/7] Tests, lint y tipos..."
    & "$root\.venv\Scripts\python.exe" -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests fallidos" }
    & "$root\.venv\Scripts\ruff.exe" check .
    if ($LASTEXITCODE -ne 0) { throw "Lint fallido" }
    & "$root\.venv\Scripts\python.exe" -m mypy api application domain infrastructure
    if ($LASTEXITCODE -ne 0) { throw "Mypy fallido" }
} else {
    Write-Host "[1/7] Tests omitidos"
}

Write-Host "[2/7] Comprobando osap.production.toml..."
$prodConfig = Join-Path $root "osap.production.toml"
if (-not (Test-Path $prodConfig)) { throw "No existe osap.production.toml" }

Write-Host "[3/7] Subiendo código al servidor..."
tar.exe -czf - `
    --exclude=.venv --exclude=__pycache__ --exclude=.git --exclude=.pytest_cache `
    --exclude=.ruff_cache --exclude=.mypy_cache --exclude=.env --exclude=osap.toml `
    --exclude=osap.production.toml --exclude=config.yaml --exclude=config.production.yaml `
    --exclude=*.egg-info --exclude=dist --exclude=build -C $root . |
    ssh -o BatchMode=yes "$User@$Server" "mkdir -p $RemoteDir && tar -xzf - -C $RemoteDir"
if ($LASTEXITCODE -ne 0) { throw "Fallo al subir el código" }

Write-Host "[4/7] Preparando venv en el servidor (si no existe)..."
Invoke-Remote "cd $RemoteDir && (test -x .venv/bin/python || python3 -m venv .venv) && ./.venv/bin/pip install -e . -q"

Write-Host "[5/7] Desplegando osap.production.toml como osap.toml..."
scp -o BatchMode=yes $prodConfig "${User}@${Server}:/tmp/osap.production.toml"
if ($LASTEXITCODE -ne 0) { throw "Fallo al subir la configuración" }
Invoke-Remote "cp /tmp/osap.production.toml $RemoteDir/osap.toml && rm -f /tmp/osap.production.toml"

if (-not $SkipMigrations) {
    Write-Host "[6/7] Ejecutando migraciones..."
    Invoke-Remote "cd $RemoteDir && ./.venv/bin/python -m alembic upgrade head"
} else {
    Write-Host "[5/6] Migraciones omitidas"
}

Write-Host "[7/7] Reiniciando servicio y verificando..."
Invoke-Remote "sudo systemctl restart osap-support && sleep 4 && curl -s http://127.0.0.1:8300/health"

Write-Host "Liberación completada." -ForegroundColor Green
