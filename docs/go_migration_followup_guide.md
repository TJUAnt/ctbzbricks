# Component Repo Go 迁移跟进指南

> Review 快照：2026-08-15
> 当前阶段：G8（前端切换与 Python 公共 API 删除）
> 事实台账：[go_migration_progress.md](./go_migration_progress.md)
> 阶段定义：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 长期原则：[go_backend_migration_principles.md](./go_backend_migration_principles.md)
> Studio Part Library 路线图：[go_part_library_studio_roadmap.md](./go_part_library_studio_roadmap.md)

本文用于日常跟进，不代替阶段验收记录。阅读状态时必须区分三个层次：

1. **代码能力完成**：实现和隔离测试已经通过。
2. **当前环境可运行**：所需 API、Worker、凭据、数据库和 Storage policy 已实际配置并启动。
3. **迁移切换完成**：前端不再依赖旧公共 API，被替代的 Python 路由已经删除。

G5～G7 的代码能力已经完成，但这不自动表示当前开发环境中的异步链路正在运行；G8 只有同时满足运行验收和旧 API 删除门槛后才能完成。

## 1. 运行职责边界

### 1.1 Go API（`cmd/api`）

Go API 是 Component Repo 的公共系统入口，职责是：

- 验证 Supabase JWT，并把认证身份转换为 actor；
- 执行 owner/actor 授权、参数校验和稳定错误映射；
- 完成有界查询和短事务，例如 Component、Version、Group、Artifact、Import、Candidate 和 Task API；
- 原子创建持久化任务及其业务关联，返回 `202 + taskId`；
- 查询任务状态、结果元数据，以及按用户 JWT/RLS 生成短期下载或预览 URL；
- 提供健康检查、trace ID、超时和结构化日志。

Go API **不负责**文件正文解析、复杂几何、关系搜索、长时间校验或 GLB 物化，也不在启动时执行 migration、DDL、修复或数据回填。API 重启不能导致任务丢失，因为 PostgreSQL 任务表才是事实来源。

### 1.2 Go Worker（`cmd/worker`）

Go Worker 是独立进程，负责适合 Go 的异步执行：

| task type | 当前职责 |
|---|---|
| `component.artifact.verify` | 流式读取对象，校验大小与 SHA-256，推进 Artifact 验证状态 |
| `component.validate` | 执行结构化发布校验，写入 ValidationReport |
| `component.preview.materialize` | 使用 ComponentVersion 固定的 SceneSnapshot 与 Studio/LDraw Part Library 生成整体 GLB，写入派生 Artifact 与对象存储 |
| `component.part_preview.materialize` | 从版本固定的只读 LDraw library 生成真实 Part GLB，写入派生 Artifact 与对象存储 |

它还负责 PostgreSQL 队列的通用运行协议：`FOR UPDATE SKIP LOCKED` 领取、lease、heartbeat、attempt fencing、有限重试、协作取消、终态提交、task event/outbox，以及过期上传对象清理。

Go Worker 不提供 HTTP API。Supabase 模式下，它进行服务端对象读取、写入、验证和清理，因此必须使用 `SUPABASE_STORAGE_SERVICE_ROLE_KEY`；缺少该凭据时应在启动前 fail closed。

### 1.3 Python Worker

Python 不再是 Component Repo 的目标公共后端，只保留明确的算法 Worker：

| task type | 当前职责 |
|---|---|
| `component.import.parse` | 解析 LDraw/Studio，物化 SceneSnapshot、BOM、Candidate 和 Draft Version |
| `component.relations.detect` | 复用现有连接识别算法，物化 RelationCandidate、Connector 和 Interface 投影 |

Python Worker 与 Go Worker 使用同一套语言无关任务协议，不能自行建立进程内权威队列，也不能重新承载 Component Repo 公共 HTTP 路由。

### 1.4 一次典型异步调用

```text
Frontend
  -> Go API：认证、短事务、创建 task
  <- 202 Accepted + taskId

Go/Python Worker
  -> PostgreSQL：领取 task + lease
  -> Object Storage / 算法计算
  -> PostgreSQL：业务结果 + task 终态 + event/outbox

Frontend
  -> Go API：轮询 task
  -> Go API：读取 Import/Candidate/Validation/Preview 结果
```

判断某段逻辑归属时使用一个简单规则：能在短请求内确定完成的授权、查询和事务属于 Go API；可能受文件大小、算法复杂度或外部对象存储延迟影响的工作属于 Worker。

## 2. 2026-08-14 客观 Review 结论

### 2.1 已验证的代码事实

- G0～G4 已完成。
- G5 的任务状态机、Logical Job / Execution / Attempt、lease/retry/cancel、Go/Python 协议已实现。
- G6 的 `upload -> artifact verify -> parse -> Snapshot/Candidate/Draft` 异步链路已实现。
- G7 的关系检测、发布校验、BOM 与预览物化链路已实现。
- G8 已把 Part preview 代码切换到 `/api/v1`，并删除旧 FastAPI `library-items` preview 路由；真实开发库已执行 Goose v8/v9 与 legacy Rebrickable external ID 交接。后续 Part Library 基准已决定改为 Studio LDraw snapshot，旧 Python Component Repo router 的其他公共能力仍在。

本次 Review 重新执行的代码验证均通过：

```text
backend-go make check          PASS
backend-go go test -race ./... PASS
sqlc generation drift         PASS
isolated PostgreSQL contracts PASS
Python Worker E2E             PASS（7 cases）
frontend i18n check/test/build PASS（13 files / 57 tests）
Python backend pytest         PASS（297 passed / 5 skipped）
```

这些结果证明代码契约和隔离环境成立，不等同于真实 Supabase 开发环境已经具备完整运行条件。

### 2.2 当前未闭环项

| 优先级 | 问题 | 当前影响 | 完成判据 |
|---|---|---|---|
| P1 | 开发启动编排运行收口 | 2026-08-14 已增加 Bash/PowerShell 独立 launcher 和统一 `start-dev`；Bash 真实启动已验证，PowerShell 仅静态核对。legacy API 因真实库 Alembic actual `0021` / expected `0022` fail closed | 明确执行 `0022` 后验证默认完整拓扑；在 Windows 实际运行 PowerShell 拓扑 |
| P1 | Worker Storage 凭据与进程启动 | Resolved 2026-08-14：现代 `SUPABASE_SECRET_KEY` 已接入，Go API 与三个 Worker 真实启动，5 个 queued task 已被领取 | 保持 server-only secret 不进入浏览器、日志、数据库或 task payload |
| P1 | 历史 runnable Task payload 与协议不兼容 | 5 个历史 queued task 含额外 `legacyMigration`；3 个 Verify 严格拒绝，2 个 Parse 由依赖失败传播，当前 queued=0 但业务结果未生成 | 不放宽 Worker 协议；设计可审计数据修复并为可重跑逻辑任务创建 canonical payload 的新 Execution |
| P1 | 非 owner Preview 可见性与 Storage RLS 不一致 | Go SQL 允许 active 非 draft Component 的认证用户读取 Preview。2026-08-16 已通过 Alembic `20260816_0023` 修正 provider-owned Storage preview helper，使其同时识别 legacy `public` preview artifact 与 Go `component_repo` preview artifact；SQL helper 对 smoke owner 已验证通过 | 仍需使用真实 Supabase 登录 access token 通过 Go API GET preview 验证 signed URL；随后补 owner、subscriber、普通认证用户真实 Supabase 测试 |
| P2 | 历史任务缺少 event/outbox | 一次性迁移建立了 29 个历史 task，但 Review 时 `task_events=0`、`outbox_events=0`，与新任务协议的审计语义不一致 | 使用可审计数据 migration 回填初始/终态 event；明确历史 outbox 是否回填、抑制或发布 |
| P2 | Outbox 没有运行时 publisher | service 层已有 claim/retry/ack，但没有持续运行的发布循环；未来 outbox 会积压 | 明确 consumer 目标；若当前不需要外发，记录禁用策略；需要外发时实现独立 publisher 和积压指标 |
| P2 | 工作树不可复现 | Review 时 G5～G8 大量代码仍未提交，当前 HEAD 不能代表已验证系统 | 按 G5、G6、G7、G8/启动与认证等可审查切片提交，提交后重跑关键验证 |
| P2 | Studio Component GLB signed URL 未闭环 | 2026-08-15 已完成 Studio manifest、Studio-based Part Library importer、真实库 metadata 导入和 active 切换；parser hardening 已显式写回真实库，当前 DB-level geometry ready=24,373 / failed=53。Go API + Go Worker + Supabase Storage server-side smoke 已成功物化 ComponentVersion 整体 GLB（artifactId=`2ea5a928-3f0d-5e86-9785-a951b4615352`，magic=`glTF`，generator=`component-preview-studio-ldraw-glb-v1`）。2026-08-16 Alembic `20260816_0023` 已修正 Storage preview helper，SQL helper 对 smoke owner 返回 true；本地 HS256 smoke JWT 仍被 Supabase Storage 拒绝为 `signature verification failed` | 用真实 Supabase 登录 access token 重跑 `GET /api/v1/component-versions/:id/preview`。Part-level GLB 可用 `3001.dat`、`3023.dat`、printed textured part、ready `bl_` 样例做补充 smoke；随后进入 S3 external IDs |
| P2 | G8 仍保留 Python 公共 router | 旧 `library-items` preview 已删除，但 FastAPI 仍挂载 Component Repo router 的其他公共能力 | 完成剩余公共 API 盘点和浏览器网络验收后删除 Python Component Repo router，仅保留两个算法 Worker |
| P2 | PowerShell 运行验收 | PowerShell 已与 Bash 对齐为 Go API、legacy API 和三个独立 Worker launcher，但当前 macOS 环境没有 PowerShell runtime | 在 Windows 真实启动、停止并重启各进程，确认环境覆盖优先级和健康端口 |

## 3. 推荐执行顺序

后续按以下顺序推进，前一项是后一项的运行前提：

1. **修复历史 runnable Task**：为协议外 legacy payload 制定可审计修复和新 Execution 方案，同时补齐历史 event/outbox 决策；不得把终态行改回 queued。
2. **完成真实 legacy schema 前置**：确认目标后执行 Alembic `20260809_0022`，再验证默认完整启动拓扑；在 Windows 补做 PowerShell smoke。
3. **修正 Preview RLS**：先确定 active Component 的业务可见性，再让数据库查询和 Storage policy 使用同一规则；用真实 Supabase 用户身份验收。
4. **确定 outbox runtime 策略**：若当前不外发则记录禁用与积压策略；需要外发时实现 publisher 和指标。
5. **固化代码基线**：按阶段拆分并提交当前工作树，保证任意开发者能从提交重现测试结果。
6. **闭环 Studio Component preview signed URL**：整体 GLB 物化已通过真实 Go API/Worker + server-side Storage 验证，Storage preview helper 已通过 Alembic 修正并 SQL 验证；下一步用真实 Supabase 登录 access token 重跑 API GET preview。Part-level GLB 用 `3001.dat`、`3023.dat`、一个 printed textured part 和一个 ready `bl_` 样例作为补充 smoke。
7. **进入 S3 external IDs**：从 Studio `elementInfoList.json`、`ldraw_new.xml`、`designid.xml` 补充 BrickLink / LEGO design / LEGO element；Rebrickable 视需要从 legacy 或 CSV 重建。
8. **执行 G8 最终验收**：真实登录态、`zh-CN/en-US`、上传/解析/审核/校验/发布/预览、网络请求只走预期入口。
9. **删除 Python 公共 Component Repo API**：保留两个 Python 算法 Worker，删除 FastAPI router 和只服务于旧公共接口的代码。
10. **再进入部署收口**：Nginx、指标、告警、最小数据库权限和正式进程编排。

## 4. 每次继续迁移时的检查表

开始前：

- [ ] 先看 [go_migration_progress.md](./go_migration_progress.md) 的最新记录，不从 Completed 标签推断进程已启动。
- [ ] 明确本次修改属于 G8 的哪个验收缺口，以及是否影响 i18n、API、任务或 Storage policy。
- [ ] 确认数据库 migration authority：`component_repo` 归 Goose，Supabase `storage` policy 暂归 Alembic。
- [ ] 若操作真实数据库或 Storage，确认目标项目和凭据权限；任何 reset/reseed 仍需再次明确确认。

完成后：

- [ ] 运行与风险相称的 Go、PostgreSQL、Python Worker、前端和 Python backend 验证。
- [ ] 对异步功能同时验证 API 创建任务和 Worker 实际消费，不能只检查 `202`。
- [ ] 检查任务是否产生预期 event/outbox，队列是否残留 queued/running/stale lease。
- [ ] 用真实 Supabase RLS 验证 owner 与非 owner 场景，不能只依赖 fake Storage。
- [ ] 更新 [go_migration_progress.md](./go_migration_progress.md)，记录事实、命令、遗留和下一步。
- [ ] 只有旧 Python 公共路由删除且 G8 验收全部通过后，才能把 G8 标记为 Completed。

## 5. 状态更新规则

本文件中的数量和环境状态是 2026-08-14 的 Review 快照。后续处理完某项后：

1. 在 [go_migration_progress.md](./go_migration_progress.md) 追加带日期的证据记录；
2. 更新本文件的未闭环表和推荐顺序；
3. 不删除历史 Review 事实，但可以将已完成项标为 `Resolved YYYY-MM-DD`；
4. 不以单元测试替代真实 Worker、真实 Supabase RLS 或浏览器切换验收。
