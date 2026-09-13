# Go API 与 Worker 单机 Docker 部署设计

> 状态：仓库产物与静态配置已实现；真实服务器部署和联合验收尚未执行  
> 适用阶段：G8 / Feed renderer v4 生产封装  
> 目标平台：Linux x86-64、Docker Engine、Docker Compose v2

## 1. 进程与权限边界

`compose.production.yml` 运行三个长期服务和一个显式运维服务：

| 服务 | 镜像 | 职责 | 关键资源 |
|---|---|---|---|
| `api` | `Dockerfile.api` | Gin HTTP API、Auth、短期 Storage URL；不领取任务、不执行 DDL | 1 CPU / 1 GiB 起步 |
| `worker` | `Dockerfile.worker` | 除 Feed 图片外的 Go 持久任务、上传过期清理、GLB/Import/P2D；只读挂载 LDraw | 4 CPU / 4 GiB 起步 |
| `feed-render-worker` | `Dockerfile.feed-render` | 只领取 `component.feed_render.materialize`，Go 管理 lease/retry，Blender 4.1 Cycles 子进程渲染 | 4 CPU / 4 GiB、并发 1、1 GiB `/tmp` |
| `migrate` | `Dockerfile.api` | `ops` profile 下显式执行 Goose `status/up` | 一次性进程，不随服务启动 |

三个镜像使用 UID/GID 10001、只读根文件系统、`no-new-privileges`、删除 Linux capabilities，并把临时写入限制在 tmpfs。API 只加载公共环境文件；两个 Worker 额外加载独立密钥文件，因此 Supabase server-side Storage 密钥不会进入 API 或 migration 容器。数据库、JWT 与 Storage 凭据不写入镜像层。

通用 Worker 设置 `WORKER_EXCLUDED_TASK_TYPES=component.feed_render.materialize`，仅移交 Feed 重资源任务，并继续运行上传过期清理。Feed Worker 使用 `WORKER_TASK_TYPES` allowlist 且并发固定为 1，不要求 LDraw。两个过滤变量互斥，错误组合会在进程启动前失败。
Compose 不固定 `WORKER_ID`；每个容器由 Go 使用容器 hostname 和 PID 生成唯一 lease owner，因而可以安全增加副本。

## 2. 固定构建输入

- Go builder 固定 `1.26.0-bookworm`，应用二进制以 `CGO_ENABLED=0` 交叉编译。
- 通用 Worker 使用 meshoptimizer 官方 `gltfpack-ubuntu.zip` v1.2，构建时校验 SHA-256 `ebc236f5...17b1`。
- Feed Worker 使用 Blender 官方 `blender-4.1.0-linux-x64.tar.xz`，构建时校验 SHA-256 `d2ac5390...caf1`。
- Compose 固定 `linux/amd64`。当前 Blender 与 gltfpack 生产产物都是 x86-64；ARM 服务器需要另行批准并建立原生依赖、图像一致性和性能基准，不能静默使用模拟执行作为生产方案。

[Blender 官方 4.1 发布目录](https://download.blender.org/release/Blender4.1/)列出 Linux x64 归档及校验文件；
[meshoptimizer v1.2 Release](https://github.com/zeux/meshoptimizer/releases/tag/v1.2) 提供 Ubuntu 归档，GitHub Release
资产元数据提供其 digest。升级任一工具都必须同时更新版本、digest、Worker 启动校验、渲染/GLB 基准和本设计文档。

## 3. 服务器准备

在服务器仓库目录创建实际环境文件，它们均已被 `.gitignore` 和 `.dockerignore` 排除：

```bash
cp deploy/docker/production.env.example deploy/docker/production.env
cp deploy/docker/worker.env.example deploy/docker/worker.env
chmod 600 deploy/docker/production.env deploy/docker/worker.env
```

`production.env` 保存数据库、JWT issuer/JWKS、Supabase URL 和 publishable key；`worker.env` 只保存 `SUPABASE_SECRET_KEY` 或旧的 service-role key。把版本固定的 LDraw 库放在服务器只读目录，并通过 `LDRAW_HOST_PATH` 指向它。不要把开发机 `.env`、本机 `.tools` 或 LDraw 数据复制进构建上下文。

先展开配置并构建固定镜像标签：

```bash
export LDRAW_HOST_PATH=/srv/brickbuilder/ldraw/2026-08-14
export BRICKBUILDER_IMAGE_TAG=2026.09.13-feed-v4
docker compose -f compose.production.yml config --quiet
docker compose -f compose.production.yml build
```

当前仓库也兼容独立 `docker-compose` v2 命令；生产应统一一种调用方式并锁定版本。

## 4. 迁移与启动顺序

API/Worker 启动不会执行迁移。发布前先读取目标版本，再由操作者显式执行非破坏性 `up`：

```bash
docker compose -f compose.production.yml --profile ops run --rm migrate status
docker compose -f compose.production.yml --profile ops run --rm migrate up
docker compose -f compose.production.yml --profile ops run --rm migrate status
```

确认数据库已到仓库 head 后启动长期服务：

```bash
docker compose -f compose.production.yml up -d api worker feed-render-worker
docker compose -f compose.production.yml ps
```

renderer 版本升级时，先确认旧版本 `component.feed_render.materialize` 没有 queued/running task，再切换专用
Feed Worker。v4 Handler 严格拒绝旧 payload，避免用新材质逻辑写入旧版本 Artifact 身份；若仍有旧任务，先用上一标签
完成它们，或让既有有限重试进入明确 fallback。Component Preview v6 使 v5 ready 结果返回 stale；需要重建时使用既有
Preview durable backfill/owner materialize 流程，不直接覆盖 v5 Artifact。

API healthcheck 请求 `/health/ready`，同时验证进程和数据库 readiness。Worker healthcheck 只验证 Go 主进程存活；任务领取能力、数据库 lease、Storage、Cycles 成功率和队列年龄必须通过 Worker 安全日志、数据库任务指标和一次真实发布验收确认，不能由进程存活替代。

## 5. Feed 渲染运行契约

Feed Worker 内的 Go 进程是唯一任务消费者。它从对象存储读取已验证 GLB，在隔离临时目录调用 `/opt/blender/blender`，最长运行 `FEED_RENDER_TIMEOUT`，然后校验并上传不可变 PNG。Blender 不连接 PostgreSQL 或 Supabase；子进程环境 allowlist 不继承父进程凭据。Cycles 失败时同一 Attempt 使用 Go raster fallback，任务最终成功或重试终结都不会撤销版本发布。

初始资源值来自本地黄色车辆约 48～51 秒的单次 CPU 结果，只用于第一版容量规划。真实服务器验收至少记录：CPU 型号/核数、峰值 RSS、临时目录峰值、每张耗时、成功/fallback 比例、队列最大年龄，以及并发 1 时连续任务的吞吐。资源不足先横向增加独立 Feed Worker 副本；提高单进程并发前必须重新验证内存峰值和任务 lease。

## 6. 更新与回退

应用更新使用新的 `BRICKBUILDER_IMAGE_TAG` 构建，不覆盖已验收标签。代码回退只切回上一组镜像；数据库回退是独立操作，必须按迁移影响、数据兼容性和恢复点单独批准，不能把 `migrate down/reset` 写入自动发布流程。已生成的源文件和派生 Artifact 保持不可变。

本阶段选择单机 Docker Compose，因为当前只有三个长期进程、规划用户不超过 1,000，且 Feed Worker 已通过 PostgreSQL lease 支持多副本。出现多主机调度、节点故障自动迁移、持续 GPU 资源池或大量弹性扩缩需求时，再以同一镜像和任务协议迁移到 Kubernetes；当前不引入集群控制面。

## 7. 验证状态

仓库验证包括 Compose 普通/`ops` profile 配置展开、Go 配置互斥测试、Worker 能力过滤测试、三个
Linux/amd64 静态二进制本机构建，以及 `make check`。由于本机 Docker daemon 未运行，镜像层下载、容器
启动、官方归档 checksum 和容器内 Blender 冒烟需在下一次服务器/可用 Docker daemon 验收时执行。本阶段
没有连接或修改真实 Supabase。
