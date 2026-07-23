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
Start-Process $powershell -ArgumentList $noExit, $fileArgument, (Join-Path $scriptDirectory "start-frontend.ps1")

Write-Host $config.frontend.url
