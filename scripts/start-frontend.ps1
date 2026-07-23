$ErrorActionPreference = "Stop"

function Require-ConfigValue($Value, $Name) {
  if ($null -eq $Value -or $Value -eq "") {
    throw "Missing required configuration: $Name"
  }
  return $Value
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDirectory
$configPath = Join-Path $scriptDirectory "dev.config.json"
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$frontendDirectory = Join-Path $projectRoot (Require-ConfigValue $config.frontend.workingDirectory "frontend.workingDirectory")

Set-Location $frontendDirectory

& (Require-ConfigValue $config.frontend.command "frontend.command") $config.frontend.arguments
