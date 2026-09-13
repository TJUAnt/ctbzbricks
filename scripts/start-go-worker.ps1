$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-env.ps1")
Import-CtbzDevEnvironment
Assert-CtbzDatabaseUrl
Set-CtbzGoCache

Write-Host "Go Worker"
Write-Host "Environment: $($env:APP_ENV)"
Write-Host "Storage provider: $($env:STORAGE_PROVIDER)"
if ($env:FEED_RENDER_BLENDER_PATH) {
  Write-Host "Feed path tracer: Blender Cycles 4.1"
} else {
  Write-Host "Feed path tracer: unavailable (Go raster fallback active)"
}

Set-Location (Join-Path $script:CtbzProjectRoot "backend-go")
& go run ./cmd/worker
exit $LASTEXITCODE
