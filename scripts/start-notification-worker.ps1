$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-env.ps1")
Import-CtbzDevEnvironment
Assert-CtbzDatabaseUrl
Set-CtbzGoCache

if (-not $env:NOTIFICATION_WORKER_METRICS_HOST) { $env:NOTIFICATION_WORKER_METRICS_HOST = "127.0.0.1" }
if (-not $env:NOTIFICATION_WORKER_METRICS_PORT) { $env:NOTIFICATION_WORKER_METRICS_PORT = "9091" }
Write-Host "Component Notification Worker"
Write-Host "Environment: $($env:APP_ENV)"
Write-Host "Monitoring: http://$($env:NOTIFICATION_WORKER_METRICS_HOST):$($env:NOTIFICATION_WORKER_METRICS_PORT)"

Set-Location (Join-Path $script:CtbzProjectRoot "backend-go")
& go run ./cmd/notification-worker
exit $LASTEXITCODE
