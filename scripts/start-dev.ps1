$ErrorActionPreference = "Stop"

function Require-ConfigValue($Value, $Name) {
  if ($null -eq $Value -or $Value -eq "") {
    throw "Missing required configuration: $Name"
  }
  return $Value
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $scriptDirectory "dev.config.json"
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$powershell = Require-ConfigValue $config.terminal.powershellExecutable "terminal.powershellExecutable"
$noExit = Require-ConfigValue $config.terminal.noExitArgument "terminal.noExitArgument"
$fileArgument = Require-ConfigValue $config.terminal.fileArgument "terminal.fileArgument"

Start-Process $powershell -ArgumentList $noExit, $fileArgument, (Join-Path $scriptDirectory "start-backend.ps1")
if ($env:START_LEGACY_API -eq "1") {
  Start-Process $powershell -ArgumentList $noExit, $fileArgument, (Join-Path $scriptDirectory "start-legacy-backend.ps1")
}
if ($env:START_COMPONENT_WORKERS -ne "0") {
  Start-Process $powershell -ArgumentList $noExit, $fileArgument, (Join-Path $scriptDirectory "start-go-worker.ps1")
}
if ($env:START_NOTIFICATION_WORKER -ne "0") {
  Start-Process $powershell -ArgumentList $noExit, $fileArgument, (Join-Path $scriptDirectory "start-notification-worker.ps1")
}
Start-Process $powershell -ArgumentList $noExit, $fileArgument, (Join-Path $scriptDirectory "start-frontend.ps1")

Write-Host "Go API: http://127.0.0.1:8080"
if ($env:START_LEGACY_API -eq "1") {
  Write-Host "Legacy API: http://127.0.0.1:8000"
}
if ($env:START_NOTIFICATION_WORKER -ne "0") {
  $notificationPort = if ($env:NOTIFICATION_WORKER_METRICS_PORT) { $env:NOTIFICATION_WORKER_METRICS_PORT } else { "9091" }
  Write-Host "Notification Worker monitoring: http://127.0.0.1:$notificationPort"
}
Write-Host $config.frontend.url
