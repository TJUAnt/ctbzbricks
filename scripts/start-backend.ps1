$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-env.ps1")
Import-CtbzDevEnvironment
Assert-CtbzDatabaseUrl
Set-CtbzGoCache

if (-not $env:AUTH_JWT_SECRET -and -not $env:AUTH_JWKS_URL -and -not $env:AUTH_JWT_ISSUER) {
  Write-Warning "JWT verification is not configured; protected /api/v1 routes will fail closed"
}

Write-Host "Go backend: http://$($env:GO_BACKEND_HOST):$($env:GO_BACKEND_PORT)"
Write-Host "Environment: $($env:APP_ENV)"
Write-Host "Storage provider: $($env:STORAGE_PROVIDER)"

Set-Location (Join-Path $script:CtbzProjectRoot "backend-go")
& go run ./cmd/api
exit $LASTEXITCODE
