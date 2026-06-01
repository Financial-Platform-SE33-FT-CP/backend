# Start backend services required for US-8 (invoices) local development.
# Opens one minimized PowerShell window per service. Stop with Ctrl+C in each window.
#
# Prerequisites:
#   - backend/.env configured (JWT, DATABASE_URL, TENANT_INTERNAL_API_TOKEN)
#   - Migrations applied:  .\scripts\dev-migrate.ps1
#   - Optional: Docker Postgres —  docker compose up -d  (from backend/)
#
# Frontend (.env.local):
#   NEXT_PUBLIC_AR_AP_SERVICE_URL=http://localhost:8005

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path $PSScriptRoot -Parent

$services = @(
    @{ Name = "auth";    Package = "auth-service";   Module = "auth_service.main:app";   Port = 8001 },
    @{ Name = "tenant";  Package = "tenant-service"; Module = "tenant_service.main:app"; Port = 8002 },
    @{ Name = "ledger";  Package = "ledger-service"; Module = "ledger_service.main:app"; Port = 8003 },
    @{ Name = "coa";     Package = "coa-service";    Module = "coa_service.main:app";    Port = 8004 },
    @{ Name = "ar-ap";   Package = "ar-ap-service";  Module = "ar_ap_service.main:app";  Port = 8005 }
)

Write-Host "Starting services from $BackendRoot" -ForegroundColor Cyan
Write-Host "Health checks:" -ForegroundColor Cyan
foreach ($svc in $services) {
    Write-Host "  http://localhost:$($svc.Port)/health  ($($svc.Name))"
}
Write-Host "  http://localhost:8005/ar-ap/health-complete  (ar-ap module)" -ForegroundColor DarkGray

foreach ($svc in $services) {
    $cmd = @"
Set-Location '$BackendRoot'
`$host.UI.RawUI.WindowTitle = '$($svc.Name)-$($svc.Port)'
Write-Host '$($svc.Package) on port $($svc.Port)' -ForegroundColor Green
uv run --package $($svc.Package) uvicorn $($svc.Module) --reload --port $($svc.Port)
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd -WindowStyle Minimized
    Start-Sleep -Milliseconds 400
}

Write-Host "`nStarted $($services.Count) service windows (minimized)." -ForegroundColor Green
Write-Host "Next: npm run dev in frontend/, set NEXT_PUBLIC_AR_AP_SERVICE_URL=http://localhost:8005" -ForegroundColor Yellow
