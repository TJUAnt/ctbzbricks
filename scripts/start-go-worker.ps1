$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-env.ps1")
Import-CtbzDevEnvironment
Assert-CtbzDatabaseUrl
Set-CtbzGoCache

Write-Host "Go Worker"
Write-Host "Environment: $($env:APP_ENV)"
Write-Host "Storage provider: $($env:STORAGE_PROVIDER)"

Set-Location (Join-Path $script:CtbzProjectRoot "backend-go")
& go run ./cmd/worker
exit $LASTEXITCODE
