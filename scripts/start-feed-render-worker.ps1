$ErrorActionPreference = "Stop"

# 离线路径追踪属于 CPU/内存重负载；专用进程默认串行，避免与 GLB 计算任务争抢资源。
if (-not $env:WORKER_ID) { $env:WORKER_ID = "feed-render" }
$env:WORKER_TASK_TYPES = "component.feed_render.materialize"
if (-not $env:WORKER_CONCURRENCY) { $env:WORKER_CONCURRENCY = "1" }
if (-not $env:WORKER_LEASE_DURATION) { $env:WORKER_LEASE_DURATION = "10m" }
if (-not $env:WORKER_HEARTBEAT_INTERVAL) { $env:WORKER_HEARTBEAT_INTERVAL = "30s" }
if (-not $env:FEED_RENDER_TIMEOUT) { $env:FEED_RENDER_TIMEOUT = "5m" }

& (Join-Path $PSScriptRoot "start-go-worker.ps1")
exit $LASTEXITCODE
