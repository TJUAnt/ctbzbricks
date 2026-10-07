$ErrorActionPreference = "Stop"

$script:CtbzScriptDirectory = $PSScriptRoot
$script:CtbzProjectRoot = Split-Path -Parent $script:CtbzScriptDirectory
$script:CtbzSharedEnvFile = if ($env:BACKEND_SHARED_ENV_FILE) {
  $env:BACKEND_SHARED_ENV_FILE
} else {
  Join-Path $script:CtbzProjectRoot "backend/.env"
}
$script:CtbzGoEnvFile = if ($env:GO_BACKEND_ENV_FILE) {
  $env:GO_BACKEND_ENV_FILE
} else {
  Join-Path $script:CtbzProjectRoot "backend-go/.env"
}

function Import-CtbzEnvFile([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }
  foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith("#")) {
      continue
    }
    $separator = $line.IndexOf("=")
    if ($separator -lt 1) {
      throw "Invalid environment entry in $Path"
    }
    $name = $line.Substring(0, $separator).Trim()
    $value = $line.Substring($separator + 1).Trim()
    if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[$value.Length - 1] -eq '"') -or ($value[0] -eq "'" -and $value[$value.Length - 1] -eq "'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
  }
}

function Import-CtbzDevEnvironment {
  $managedNames = @(
    "APP_ENV", "GO_BACKEND_HOST", "GO_BACKEND_PORT", "DATABASE_URL",
    "AUTH_JWT_SECRET", "AUTH_JWKS_URL", "AUTH_JWT_ISSUER", "AUTH_JWT_AUDIENCE",
    "STORAGE_PROVIDER", "STORAGE_BUCKET", "STORAGE_KEY_PREFIX",
    "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_STORAGE_SERVICE_ROLE_KEY",
    "SUPABASE_SECRET_KEY", "COMPONENT_REPO_STORAGE_PROVIDER", "LDRAW_ROOT",
    "COMPONENT_IMPORT_PARSER_VERSION", "COMPONENT_IMPORT_SNAPSHOT_SCHEMA",
    "COMPONENT_IMPORT_MAX_ATTEMPTS", "WORKER_ID", "WORKER_CONCURRENCY",
    "WORKER_TASK_TYPES", "PART_PREVIEW_GLTFPACK_PATH",
    "FEED_RENDER_BLENDER_PATH", "FEED_RENDER_TIMEOUT",
    "WORKER_HEALTH_CHECK_INTERVAL", "WORKER_POLL_INTERVAL", "WORKER_LEASE_DURATION",
    "WORKER_HEARTBEAT_INTERVAL", "WORKER_RETRY_DELAY",
    "WORKER_POLL_INTERVAL_SECONDS", "WORKER_LEASE_DURATION_SECONDS",
    "WORKER_HEARTBEAT_INTERVAL_SECONDS", "WORKER_RETRY_DELAY_SECONDS"
  )
  $callerValues = @{}
  foreach ($name in $managedNames) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ($null -ne $value) {
      $callerValues[$name] = $value
    }
  }

  Import-CtbzEnvFile $script:CtbzSharedEnvFile
  Import-CtbzEnvFile $script:CtbzGoEnvFile

  foreach ($entry in $callerValues.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
  }

  if (-not $env:APP_ENV) { $env:APP_ENV = "development" }
  if (-not $env:GO_BACKEND_HOST) { $env:GO_BACKEND_HOST = "127.0.0.1" }
  if (-not $env:GO_BACKEND_PORT) { $env:GO_BACKEND_PORT = "8080" }
  if (-not $env:STORAGE_PROVIDER) {
    $env:STORAGE_PROVIDER = if ($env:COMPONENT_REPO_STORAGE_PROVIDER) { $env:COMPONENT_REPO_STORAGE_PROVIDER } else { "disabled" }
  }
  if (-not $env:STORAGE_BUCKET) { $env:STORAGE_BUCKET = "component-artifacts" }
  if (-not $env:STORAGE_KEY_PREFIX) { $env:STORAGE_KEY_PREFIX = "component-repo" }
  if (-not $env:FEED_RENDER_BLENDER_PATH) {
    $blenderCommand = Get-Command "blender" -ErrorAction SilentlyContinue
    if ($blenderCommand) {
      $env:FEED_RENDER_BLENDER_PATH = $blenderCommand.Source
    } else {
      $blenderCandidates = @()
      if ($env:ProgramFiles) {
        $blenderCandidates += Join-Path $env:ProgramFiles "Blender Foundation\Blender 4.1\blender.exe"
      }
      if (${env:ProgramFiles(x86)}) {
        $blenderCandidates += Join-Path ${env:ProgramFiles(x86)} "Blender Foundation\Blender 4.1\blender.exe"
      }
      foreach ($candidate in $blenderCandidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
          $env:FEED_RENDER_BLENDER_PATH = $candidate
          break
        }
      }
    }
  }
}

function Assert-CtbzDatabaseUrl {
  if (-not $env:DATABASE_URL) {
    $message = "error: DATABASE_URL is required; configure $script:CtbzGoEnvFile or export it before startup"
    [Console]::Error.WriteLine($message)
    exit 1
  }
}

function Get-CtbzPythonExecutable {
  if ($env:PYTHON_BIN) { return $env:PYTHON_BIN }
  $appPython = Join-Path $script:CtbzProjectRoot ".venv-app/Scripts/python.exe"
  if (Test-Path -LiteralPath $appPython) { return $appPython }
  $venvPython = Join-Path $script:CtbzProjectRoot ".venv/Scripts/python.exe"
  if (Test-Path -LiteralPath $venvPython) { return $venvPython }
  return "python"
}

function Set-CtbzGoCache {
  if (-not $env:GOCACHE) {
    $env:GOCACHE = Join-Path ([System.IO.Path]::GetTempPath()) "ctbzbricks-go-cache"
  }
  New-Item -ItemType Directory -Force -Path $env:GOCACHE | Out-Null
}
