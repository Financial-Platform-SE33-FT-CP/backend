# Run all service Alembic migrations against the shared PostgreSQL database.
# Prerequisites: PostgreSQL on DATABASE_URL (see backend/.env).
# Usage (from repo):  .\backend\scripts\dev-migrate.ps1

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path $PSScriptRoot -Parent
Set-Location $BackendRoot

if (-not (Test-Path ".env")) {
    Write-Host "Missing backend/.env — copy .env.example to .env and set DATABASE_URL." -ForegroundColor Red
    exit 1
}

Write-Host "==> Backend root: $BackendRoot" -ForegroundColor Cyan
Write-Host "==> Loading backend/.env into process environment" -ForegroundColor Cyan

Get-Content (Join-Path $BackendRoot ".env") | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if (
        ($val.StartsWith('"') -and $val.EndsWith('"')) -or
        ($val.StartsWith("'") -and $val.EndsWith("'"))
    ) {
        $val = $val.Substring(1, $val.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($key, $val, "Process")
}

if (-not $env:DATABASE_URL) {
    Write-Host "DATABASE_URL is not set in backend/.env" -ForegroundColor Red
    exit 1
}

function Invoke-Migration {
    param(
        [string]$Label,
        [string]$Package,
        [string]$WorkingDir,
        [string[]]$AlembicArgs = @("upgrade", "head")
    )
    Write-Host "`n==> $Label" -ForegroundColor Green
    Push-Location $WorkingDir
    try {
        uv run --package $Package alembic @AlembicArgs
        if ($LASTEXITCODE -ne 0) { throw "alembic failed for $Label (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

Invoke-Migration "auth-service" "auth-service" (Join-Path $BackendRoot "packages\auth-service\alembic")
Invoke-Migration "tenant-service" "tenant-service" (Join-Path $BackendRoot "packages\tenant-service\alembic")
Invoke-Migration "coa-service" "coa-service" (Join-Path $BackendRoot "packages\coa-service") @("-c", "alembic.ini", "upgrade", "head")
Invoke-Migration "ledger-service" "ledger-service" (Join-Path $BackendRoot "packages\ledger-service\alembic")
Invoke-Migration "ar-ap-service" "ar-ap-service" (Join-Path $BackendRoot "packages\ar-ap-service\alembic")
Invoke-Migration "audit-service" "audit-service" (Join-Path $BackendRoot "packages\audit-service\alembic")

Write-Host "`nAll migrations completed." -ForegroundColor Cyan
