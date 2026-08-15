# Go 后端迁移进度

> 最后更新：2026-08-14（G8 当前职责与跟进基线）
> 状态依据：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 跟进指南：[go_migration_followup_guide.md](./go_migration_followup_guide.md)
> 更新规则：只记录已经由代码、测试或文档证据证明的事实。

## 1. 当前摘要

| 阶段 | 状态 | 说明 |
|---|---|---|
| G0 原则、路线与工程决策 | Completed | 目标架构、迁移原则、阶段和完成定义已入库 |
| G1 Go 工程骨架 | Completed | API、Worker、migration、sqlc/pgxpool 与测试骨架已验收 |
| G2 PostgreSQL schema baseline | Completed | `component_repo` baseline、authority、sqlc 与 PostgreSQL contract 已验收 |
| G3 组件目录、版本和分组 | Completed | GET 只读与 Candidate 来源链约束已完成 hardening 并通过 PostgreSQL contract |
| G4 Artifact 与上传会话 | Completed | source Artifact 数据库不可变边界、直传 RLS 与服务端清理权限均已通过 contract |
| G5 持久化任务系统 | Completed | Logical Job / Execution / Attempt、PostgreSQL 状态机、attempt-fenced lease/retry/cancel、event/outbox 与 Go/Python Worker 已验收 |
| G6 导入、解析与候选流程 | Completed | upload -> verify dependency -> Python parse -> Snapshot/Candidate/Draft 异步闭环已验收 |
| G7 关系、接口、校验和预览 | Completed | Python 关系检测、Go 关系审核/真实发布校验/预览与 PostgreSQL 不变量已验收 |
| G8 前端切换与 Python API 删除 | In progress | 主要 Component Repo 前端能力已切换；Part/Library preview、真实浏览器/RLS 验收与 Python 公共 router 删除尚未完成 |

当前 Go 后端已经覆盖 Component Repo 的目录、版本、分组、订阅、Artifact、上传、持久任务、导入、Candidate、关系审核、connector/interface、验证、发布门禁、BOM 和预览闭环。Python 的目标保留边界只有 `component.import.parse` 与 `component.relations.detect` 两个独立算法 Worker。G8 已切换 Component Repo 的主要前端调用；Part/Library preview 仍访问旧 FastAPI，真实 Supabase 非 owner Preview RLS、Worker 启动与队列消费、浏览器双语言网络流量和旧 Python router 删除仍需完成。代码阶段状态与当前环境运行状态必须分开判断，详见[跟进指南](./go_migration_followup_guide.md)。

## 2. 已确认决策

- [x] Go 作为后端系统主体，Python 作为算法插件。
- [x] 技术栈采用 Gin、PostgreSQL、sqlc、pgx/v5、pgxpool。
- [x] 增加 Goose 作为 Go 目标 schema migration 工具。
- [x] 当前开发阶段不承担旧 API、在线流量、MySQL 或开发数据兼容义务。
- [x] 采用模块化单体 API，不开发 Go 业务网关。
- [x] 组件长任务通过 PostgreSQL 持久化队列异步执行。
- [x] Gin 不同步执行文件解析、复杂几何和长时间计算。
- [x] 新组件 API 使用 `/api/v1`，不要求复刻旧 FastAPI DTO。
- [x] migration authority 按 PostgreSQL schema/domain 分配：Goose 独占 `component_repo`；Alembic 暂时管理未迁移的 legacy `public` 域及 provider-owned Supabase `storage` policy，双方不得跨边界管理同一对象。
- [x] Go API 继承现有 i18n、领域内容和结构化错误不变量。

## 3. G0 完成记录

日期：2026-08-06

完成内容：

- 新增 `docs/go_backend_migration_principles.md`。
- 新增 `docs/go_component_migration_plan.md`。
- 新增本进度台账。
- 在仓库级 `AGENTS.md` 增加 Go 迁移必读入口和不可变执行规则。
- 在 `README.md` 增加 Go 迁移文档入口。

验证：

- 文档职责已拆分为“长期原则 / 执行路线 / 完成事实”。
- 本次没有修改 UI 文案、API runtime、任务、领域数据、导出资源或数据库。
- 未执行前后端测试；本次仅文档和代理指令变更。

## 4. G1 完成记录

日期：2026-08-06

完成内容：

- [x] 创建 `backend-go/go.mod`，固定 Gin、pgx/v5、pgxpool 和 Goose 依赖。
- [x] 创建 `cmd/api`、`cmd/worker`、`cmd/migrate` 三个独立入口。
- [x] 增加环境配置解析、PostgreSQL-only URL 校验、连接池和 HTTP/Worker 参数边界。
- [x] 增加 JSON 结构化日志、trace ID、panic recovery、request context timeout、server timeout、正文大小限制和优雅关闭。
- [x] 实现统一 `code + params + traceId` 错误响应，未知 panic 只返回 `common.internal_error`。
- [x] 初始化 pgxpool，增加有界连接池配置、Ping/readiness 和关闭流程。
- [x] 增加 `/health/live` 与 `/health/ready`；数据库不可用时 readiness 返回机器状态且不泄露连接错误。
- [x] 增加 `sqlc.yaml`、固定版本生成命令、G1 health query 和 sqlc 生成代码。
- [x] 增加 Goose migration 入口与嵌入式 migration 目录；G1 不包含 DDL，Alembic 仍是 authority。
- [x] 通过 `go.mod` tool directive 固定 sqlc v1.31.1，并增加 Makefile 的 format、generate、sqlc vet、test、go vet、API/Worker 和 migration help 命令。
- [x] 增加配置、连接池、API 错误、middleware、health、Worker 停止和 migration embed 测试。

验证结果：

```text
go test ./...        PASS
go test -race ./...  PASS
go vet ./...         PASS
make check            PASS（含 sqlc vet，离线模块缓存验证）
sqlc v1.31.1 generate PASS
cmd/migrate --help   PASS（无数据库、无 DDL）
API smoke            /health/live = 200
API smoke            /health/ready = 503（故意使用不可用数据库）
Worker smoke         启动、数据库不可用结构化日志、SIGINT 停止通过
frontend i18n check  PASS（2 locales / 10 namespaces）
frontend test         PASS（12 files / 50 tests）
frontend build        PASS
Python backend pytest PASS（294 tests；沙箱外重跑多进程用例）
```

未执行真实数据库 migration；G1 没有 schema SQL，符合 G2 交接前 Alembic 继续作为 authority 的原则。

## 5. G2 完成记录

日期：2026-08-06

完成内容：

- [x] 清点 Python Component Repo 22 张领域表及其 Alembic revisions，并记录保留、重命名、拆分和新增决策。
- [x] 建立独立 PostgreSQL `component_repo` schema，明确 Goose 对其独占 authority；Alembic 只能继续管理未迁移的 legacy `public` 域。
- [x] 新增 Goose baseline：26 张表、关系、索引、check/unique/foreign-key 约束、权限收紧和全表 RLS enable。
- [x] 将 `component_artifacts` 整理为域内 `artifacts`，将上传期望文件 JSON 拆分为 `upload_session_files`。
- [x] 增加发布版本结构不可变 trigger，以及“官方 Component 才允许 translation”的数据库保护。
- [x] 为任务和导入显式保存 locale/timezone；进度、验证和错误字段采用稳定 `code + params` 结构。
- [x] 增加 `tasks`、`task_events`、`outbox_events` 的持久化结构，为 G5 提供 schema，不提前实现 Worker 领取逻辑。
- [x] `sqlc.yaml` 直接读取 Goose migrations，删除第二份 scaffold schema，并重新生成全部数据库类型。
- [x] 增加 PostgreSQL integration contract tests、API/Worker 禁止 DDL 的静态 contract，以及隔离本机 PostgreSQL 验收脚本。
- [x] 增加开发 reset/reseed runbook；没有连接、重置或修改现有数据库。

验证结果：

```text
go tool sqlc generate PASS
go tool sqlc vet      PASS
make check             PASS
go test -race ./...    PASS
go vet ./...           PASS
isolated PostgreSQL    PASS（空库 -> Goose v1；再次 up 为 no-op）
schema contract        PASS（26 tables / RLS / constraints / immutable version）
startup DDL contract   PASS（API/Worker 启动前后 schema dump 一致）
frontend i18n check    PASS（2 locales / 10 namespaces）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS
Python backend pytest  PASS（294 tests；6 个既有 warning）
```

隔离 PostgreSQL cluster 位于系统临时目录，验证结束后已停止并删除。未对现有开发数据库执行 Goose、drop、reset 或 reseed。

## 6. G3 完成记录

日期：2026-08-07

完成内容：

- [x] 增加 `/api/v1` 下 Component CRUD、版本查询/草稿创建/发布/弃用/归档/删除、分组树/移动/成员关系和订阅接口。
- [x] 增加 HS256 Bearer JWT 验证；只接受已验证 UUID `sub` 作为 actor，签名、过期时间、issuer 和 audience 均可校验，未配置时 fail closed。
- [x] 所有业务 SQL 由 sqlc 生成并显式携带 actor/owner 条件；跨用户草稿读取、修改、分组操作和版本输入引用均被拒绝。
- [x] 所有 mutation 通过 serializable pgx transaction 执行，serialization/deadlock 最多重试三次；版本发布在一个事务中弃用旧版本并更新 current version。
- [x] Component 列表支持 query/category/status、稳定 `updated_at DESC, id` 页码分页；版本和分组成员列表也使用稳定排序。
- [x] ComponentGroup 在首次分组 mutation 中自动创建无名称 root；GET 只读；支持最大深度 5、循环检测、同级规范化名称唯一性、sort order 和并发写保护。
- [x] 用户 Component/Group 内容原文保存并返回规范化 `contentLocale`；官方 Component 只选择目标 locale 的 `reviewed` translation，缺失时返回源内容和实际 locale。
- [x] Gin 使用严格 JSON 解码，不接受未知字段；公共错误保持 `code + params + traceId`，内部数据库/JWT/decoder 细节不进入响应。
- [x] 增加 JWT/UUID 单元测试、PostgreSQL application-service contract 和真实 Gin HTTP contract。

G3 暂不实现 `component-versions/:id/parts` 与 `/source`：前者依赖 G7 的结构投影，后者依赖 G4 的对象存储签名下载边界。

验证结果：

```text
go tool sqlc generate PASS
go tool sqlc vet      PASS
go test ./...          PASS
go test -race ./...    PASS
go vet ./...           PASS
isolated PostgreSQL    PASS（G2 migration + G3 service/HTTP contracts）
owner isolation        PASS（Component/Version/Group/Artifact references）
version lifecycle      PASS（draft -> published，current version 原子切换）
group invariants       PASS（root/depth/cycle/sibling uniqueness/concurrency/sort）
official translation   PASS（draft 不可见，reviewed 可选，source fallback 带实际 locale）
HTTP error contract    PASS（JWT、严格 JSON、code + params + traceId）
frontend i18n check    PASS（2 locales / 10 namespaces；复用既有 error codes）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS
Python backend pytest  PASS（294 tests；6 个既有 warning）
```

未连接、重置或修改现有开发数据库；所有 PostgreSQL application tests 使用自动清理的隔离临时 cluster。

## 7. G4 完成记录

日期：2026-08-08

完成内容：

- [x] 增加 Storage interface 与 Supabase Storage REST adapter；普通对象 URL 不支持 HEAD，因此使用对象信息端点完成 metadata-only 校验。
- [x] 增加 Storage 配置边界、disabled 开发模式、认证 header、请求 timeout、短期签名 URL、幂等删除和 provider 错误归一化。
- [x] 增加 `/api/v1/component-imports/upload-sessions` 创建和完成接口；严格 JSON DTO 不接受客户端 `objectPath`/完整 key。
- [x] object key 固定为 server-generated `{ownerId}/component-repo/uploads/{sessionId}/{role}/{artifactId}.{ext}`，与现有 Supabase Storage policy 的 `auth.uid()/component-repo` 前缀一致；原始文件名仅作为用户内容原文保存，不进入可信定位符。
- [x] 上传会话冻结规范化 locale、IANA timezone、owner、目标 Component/Base Version；目标引用必须属于 actor 且关系一致。
- [x] upload complete 在 Storage HEAD/size/MIME 校验后用 serializable transaction 原子创建 immutable source Artifact、关联 session file 并完成 session；幂等重试不重复 HEAD 或 Artifact。
- [x] complete 不读取对象正文；`VerifyOwnedArtifact` 以单次流式读取同时计算 SHA-256 和长度，成功/失败都持久化机器验证状态，已验证重试不重复读取。
- [x] 增加 owner-scoped Artifact 和 Component Version source 签名下载；只允许 verified Artifact，响应不暴露 provider key、原始错误或正文。
- [x] metadata 失败会幂等删除本会话对象，并在同一数据库事务中将 session/files 标记失败；对象回收失败时保留 pending 供重试，不制造半完成 Artifact。
- [x] 独立 Worker 周期清理过期 pending upload；只有全部对象删除成功后才将 session 标记 expired，部分失败会在下次周期重试。
- [x] 原始 Artifact 始终 `source_kind=source`、`immutable=true` 且使用唯一对象 key；G4 没有提供覆盖或以 derived 替换 source 的写路径。
- [x] G4 complete 只完成上传和 Artifact 元数据，不提前创建缺少 durable task 的 queued import；G6 再原子创建 import + parse task 并启用最终 `202` 契约。

验证结果：

```text
go tool sqlc generate PASS
go tool sqlc vet      PASS
go test ./...          PASS
go test -race ./...    PASS
go vet ./...           PASS
isolated PostgreSQL    PASS（Goose v1 + G3/G4 service/HTTP contracts + startup schema no-drift）
server key boundary    PASS（客户端 objectPath 被 strict JSON 拒绝；owner/session/artifact path）
upload completion      PASS（1 HEAD / 0 body reads；事务、幂等、immutable source）
hash verification      PASS（唯一 1 次 body open；已验证重试 0 次额外读取）
owner isolation        PASS（session complete、Artifact download 与 target/base ownership）
failure compensation   PASS（对象删除、session/files failed、0 个残留 Artifact）
expired cleanup        PASS（对象删除成功后才 expired；Worker 独立接线）
frontend i18n check    PASS（2 locales / 10 namespaces；仅复用既有 error codes）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（294 tests；6 个既有 warning；多进程用例在沙箱外验证）
```

未增加 i18n 资源或 UI 文案；locale/timezone、文件名原文和结构化 error code 的既有边界保持不变。未连接、重置或修改现有开发数据库；PostgreSQL 验证继续使用自动删除的隔离临时 cluster。

## 8. G3/G4 hardening 记录

日期：2026-08-09

完成内容：

- [x] `GET /api/v1/component-groups` 不再调用 `EnsureComponentRootGroup` 或开启写事务；空仓库返回空列表，首次创建分组时在 mutation transaction 内创建 root。
- [x] `artifacts.sql` 的业务查询和 mutation 返回值全部改为显式列名，重新生成 sqlc 代码且生成类型无契约漂移。
- [x] Supabase 上传路径从 `component-repo/owners/{ownerId}/...` 调整为 `{ownerId}/component-repo/...`，匹配 owner-scoped authenticated INSERT/SELECT policy 的目录约束。
- [x] `STORAGE_KEY_PREFIX` 默认值固定为 `component-repo`，避免启用 Supabase 时因省略配置生成不符合默认 policy 的路径。
- [x] 创建 ComponentVersion 的请求收紧为 `componentCandidateId + version/release metadata`；客户端提交 source/exchange Artifact、Snapshot、parser、part library 或签名/hash 字段会被严格 JSON DTO 拒绝。
- [x] 增加 Goose v2 来源完整性 migration：Candidate 显式保存 Worker 物化的 interface/structure/geometry hash，组合外键约束 Artifact/Import/Snapshot/Candidate owner 和来源关系，数据库 trigger 保护用户版本的完整来源链。
- [x] `CreateVersion` 在 serializable transaction 中沿 Candidate -> SceneSnapshot -> Import -> verified source Artifact 推导全部机器字段；Import 必须 `succeeded` 且目标 Component、parser version、可选 exchange/part library 与 Candidate 一致。
- [x] 保持异步边界：Gin 创建版本不读取对象正文、不解析 Studio/LDraw、不计算几何或接口签名；这些字段由 G6 Worker 在请求外物化到 Candidate。
- [x] 增加 Goose v3 source Artifact 不可变 migration：数据库 trigger 禁止修改来源、对象定位、hash/size/MIME、immutable 和删除字段，禁止 derived 升格为 source，并将 `verified`/`failed` 设为终态。
- [x] source Artifact 允许 Worker 在请求外执行 `pending -> verified/failed`，但验证完成后不能降级、替换或删除；上传失败与过期清理仍发生在 Artifact 建立之前。
- [x] 增加 Alembic `20260809_0022`，移除 Supabase `storage.objects` 的 authenticated DELETE policy；浏览器保留 owner-scoped 直传/读取，Go API/Worker 使用 server-only service-role credential 执行补偿和清理。
- [x] 明确 migration authority：Goose 只管理 `component_repo`，Alembic 暂管 provider-owned `storage` policy；本次两个 migration 没有交叉修改对象。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（含 go test、go vet、sqlc vet、格式检查）
go test -race ./...    PASS
isolated PostgreSQL    PASS（空库 Goose v1 -> v2 -> v3、v3 down/up、G3/G4 contracts、startup schema no-drift）
GET group contract     PASS（首次读取 0 rows；首次 mutation 后 root + custom group）
Storage path contract  PASS（{actorId}/component-repo/uploads/...）
explicit SQL columns   PASS（artifacts.sql 无 SELECT */alias.* / RETURNING *）
version source lineage PASS（跨 owner、pending Artifact、直接 SQL 拼接均拒绝）
async parse boundary   PASS（CreateVersion 仅执行 PostgreSQL 查询/事务，不读取 Storage 正文）
source immutability    PASS（结构字段修改、终态降级、source 删除均由 PostgreSQL 拒绝）
Storage delete policy PASS（Alembic head 0022；authenticated DELETE policy 移除 contract）
Python backend pytest  PASS（295 tests；6 个既有 warning；多进程用例在沙箱外验证）
```

本次没有修改 UI 文案、i18n 资源、locale/timezone、结构化错误或用户内容字段。

## 9. G5 完成记录

日期：2026-08-09

完成内容：

- [x] 增加 Goose v4 durable task migration：任务 JSON object、状态字段、取消审计、结果 Artifact owner、terminal immutable 与合法 transition/attempt trigger 均由 PostgreSQL 约束。
- [x] 幂等唯一键调整为 `(owner_id, task_type, idempotency_key)`；相同 key 只有在 payload、locale/timezone 和 max attempts 一致时复用，不同 owner 不互相冲突。
- [x] 增加显式 sqlc 任务查询：创建、owner 查询、`FOR UPDATE SKIP LOCKED` 领取、heartbeat、progress、完成、失败、退避重试、协作取消和 lease 过期恢复。
- [x] 每个任务状态变化在同一 PostgreSQL transaction 中创建 `task_events` 和 `component.task.events` outbox；outbox 具有独立 lease、attempts、退避重试和 publish acknowledgement。
- [x] 增加 `GET /api/v1/tasks/:taskId` 与 `POST /api/v1/tasks/:taskId/cancel`；跨 owner 返回统一 not found，公共响应不包含内部 payload、lease owner 或数据库错误。
- [x] 独立 Go Worker 支持 task type registry、可配置并发、短事务领取、计算期 lease heartbeat、丢失 lease 停止提交、有限重试、协作取消和优雅停止。
- [x] upload complete 事务原子创建 source Artifact、`component.artifact.verify` task、初始 event/outbox；Gin 仍不读取对象正文。
- [x] Artifact 校验接入 Go Worker；Worker 崩溃发生在 Artifact 已验证但 task 未完成时，lease 恢复后重领会复用 verified 终态，不再次打开对象正文或创建重复业务结果。
- [x] 增加语言无关 Go/Python Worker 协议文档，固定 JSON、状态机、locale/timezone、错误、lease、幂等、取消和 outbox 契约；Python parser adapter 按路线图在 G6 接入。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（go test、go vet、sqlc vet、格式检查）
go test -race ./...    PASS
isolated PostgreSQL    PASS（空库 Goose v1 -> v4、v4 down/up、startup schema no-drift）
task state constraints PASS（非法跳过 running、claim 不增 attempts、非 object payload 均拒绝）
concurrent claim       PASS（12 路并发 SKIP LOCKED，无重复领取）
lease/retry/cancel     PASS（崩溃重领、最大 attempts、heartbeat、协作取消）
task event/outbox      PASS（原子创建、outbox lease/retry/publish）
Artifact Worker        PASS（上传事务入队；崩溃恢复后正文仍只读取 1 次）
task HTTP ownership    PASS（owner GET/cancel；跨 owner not found；不返回 payload）
independent Worker     PASS（持久任务领取、handler、完成、停止）
frontend i18n check    PASS（2 locales / 10 namespaces；catalog 未变）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（295 tests；6 个既有 warning；多进程用例在沙箱外验证）
```

多语言影响面为异步任务契约：locale/timezone 在任务创建时冻结；状态、task type、JSON key、progress/error code 与 params 保持机器值；未新增最终任务句子、资源 key 或 catalog 版本。

未连接、重置或修改现有开发数据库；Goose 和集成测试继续使用自动删除的隔离临时 PostgreSQL cluster。

## 10. G6 完成记录

日期：2026-08-09

完成内容：

- [x] 新增 Goose v5 import pipeline migration：Import 显式关联 upload session 与 parse task；Task 支持同 owner 的持久化依赖；SceneSnapshot 每个 Import 唯一且数据库禁止 UPDATE/DELETE；Candidate 的三类签名/hash 必填。
- [x] upload complete 切换为最终 `202 Accepted {importId, taskId, status}`；在一个 serializable transaction 中创建 source Artifact、Artifact verification tasks、Import、Parse Task、依赖、初始 task event/outbox 和 upload terminal state。
- [x] Parse Task 只有在全部 Artifact verification Task 成功后才可 claim；前置 Task 失败/取消会原子传播到下游 Task，Import trigger 同步结构化终态，不消耗 Python parser attempts。
- [x] Import pipeline trigger 校验 upload owner/target/context、Parse Task type/payload/context，以及 source/exchange verification task 来源关系；parser version、snapshot schema、part-library version、locale/timezone 均在上传完成时冻结。
- [x] 增加独立 Python `component.import.parse` Worker adapter：直接遵循 PostgreSQL claim/lease/heartbeat/retry/cancel/event/outbox 协议，不提供公共 FastAPI 路由。
- [x] 复用既有确定性 LDraw/MPD parser，异步物化 document、BOM、结构化 parse issues、summary、interface signature、structure hash 和 geometry hash；Gin 请求不读取或解析对象正文。
- [x] Python Worker 在同一个 PostgreSQL transaction 中提交 SceneSnapshot、Candidate、用户 Component（无 target 时）、Draft ComponentVersion、Import succeeded、Task succeeded、task event 与 outbox，避免崩溃留下半个业务结果。
- [x] Stable derived IDs、唯一约束和 immutable Snapshot 保证同一 Import 重试不覆盖或重复创建历史快照；任务终态与业务结果原子提交。
- [x] Studio `.io` 在 Worker 中提取 `model.ldr`，使用稳定 key 写入 verified derived Artifact；`derived_from_artifact_id` 显式指向原始 Studio source，版本来源链允许且校验该边界。
- [x] 增加 `GET /api/v1/component-imports/:importId` 与 `GET /api/v1/component-candidates/:candidateId`；owner 过滤、Candidate/Snapshot/Draft 投影和跨 owner not found 通过 PostgreSQL contract。
- [x] parse issue、task/import failure 只保存稳定 `code + params`；测试确认不保存最终译文、原始异常、SQL、路径、堆栈或凭据。上传文件名保持用户原文，新建 Component 使用冻结 `contentLocale`。
- [x] 更新语言无关 Worker 协议、Go backend 运行说明和 Python parser Worker 启动方式。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（go test、go vet、sqlc vet、格式检查）
go test -race ./...    PASS
isolated PostgreSQL    PASS（空库 Goose v1 -> v5、v5 down/up、重复 up、startup schema no-drift）
upload atomicity       PASS（Artifact tasks + Import + Parse Task + dependency + event/outbox）
dependency routing     PASS（校验完成前不能 claim；终态失败传播不消耗 parser attempt）
Python Worker E2E      PASS（5 tests：LDraw、Studio derived lineage、结构化失败、原子结果、快照不可变）
owner isolation        PASS（Import/Candidate owner GET；跨 owner not found）
async parse boundary   PASS（upload complete 0 body reads；解析仅在独立 Python Worker）
snapshot idempotency   PASS（每 Import 1 个 immutable Snapshot；终态重跑不新增）
i18n task context      PASS（Import/Task/新用户 Component 保持冻结 zh-CN/Asia/Shanghai）
frontend i18n check    PASS（2 locales / 10 namespaces；catalog 未变）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（297 passed / 3 PostgreSQL-gated skipped；6 个既有 warning）
```

多语言影响面为异步任务、解析 issue、导入 API 和自动创建的用户 Component：机器字段与
错误/issue 均保持 code + params；locale/timezone 在任务创建时冻结；上传文件名和由其取得的
用户 Component 名称保留原文并记录 `contentLocale`。未增加资源 key、译文、catalog version
或 release notes。

未连接、重置或修改现有开发数据库；Goose/Python Worker 集成验收使用自动删除的隔离临时
PostgreSQL cluster 和内存 Storage fake。

## 11. G7 完成记录

日期：2026-08-09

完成内容：

- [x] 新增 Goose v6 workbench migration：Candidate/Relation/Interface/Connector/Validation 的 owner 来源链、relation endpoint 规范化列与无向唯一索引、connector occupancy slot、validation lineage、preview generation/task 和 Part/Reviewed Translation 投影均由 `component_repo` schema 管理。
- [x] `component.relations.detect` 由独立 Python Worker 消费；复用冻结的 part connector library 和既有兼容规则，原子物化 RelationCandidate、normalized ConnectorAnalysis、自动 external Interface、Candidate/Draft interface signature、Task event/outbox 与任务终态。
- [x] Relation detection 只读取 immutable SceneSnapshot；E2E 在检测前后比较完整 document，确认 Transform 未被修改。同一 Part instance 内的 connector 不互相生成装配关系。
- [x] 增加关系列表、异步检测、确认/拒绝、connector 与 interface 查询 API；所有路由带 actor/owner 边界，检测和长计算返回 `202 + taskId`。
- [x] 关系确认使用 serializable transaction；数据库 trigger 锁定 normalized connector row 并预留容量 slot。无向 endpoint pair 唯一、RelationCandidate 与 AssemblyRelation 来源一致、单容量 connector 冲突均由数据库拒绝。
- [x] 确认关系后原子移除已占用 connector 的 external Interface 投影，并同步更新 Candidate 与 Draft Version 的 interface signature、清除旧 validation report；已发布版本不能再进入关系审核写路径。
- [x] `component.validate` 接入 Go Worker，保存结构化 checks/issues；ValidationReport 通过 owner/task/Candidate/Version/validator version 与 interface/structure/geometry hash 绑定。
- [x] 发布数据库 trigger 要求对应 `component.validate` Task 已 `succeeded`、publish report 已通过且三类签名/hash 未过期；Go API 将失败稳定映射为 `component_repo.publish_validation_failed`。
- [x] `component.preview.materialize` 接入 Go Worker；使用 SceneSnapshot Transform 生成确定性的 version-addressed structural GLB，服务端 upsert verified derived Artifact，并返回独立的短期签名 URL。
- [x] `GET /component-versions/:versionId/preview` 完全只读；缺失 Storage 对象只有显式 materialize mutation 才增加 generation 并重建同一稳定 Artifact ID。
- [x] `GET /component-versions/:versionId/parts` 与 GLB 分离加载；BOM 机器编号/数量保持稳定，Part 名称只选择 `reviewed` 译文，缺失时返回 source fallback 和实际 `contentLocale`。
- [x] Supabase Storage adapter 增加 server-only derived object upsert；service-role header、MIME、长度和 owner-scoped derived key 通过单元测试。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（go test、go vet、sqlc vet、格式检查）
go test -race ./...    PASS
isolated PostgreSQL    PASS（空库 Goose v1 -> v6、v6 down/up、重复 up、startup schema no-drift）
relation invariants    PASS（Transform 不变、无向端点唯一、来源一致、capacity slot 冲突）
Python Relation E2E    PASS（2 connectors / 1 candidate relation / 2 external interfaces / 原子任务终态）
validation publish gate PASS（无报告阻止发布；succeeded + passing + fresh hashes 后允许）
preview contract       PASS（GET 0 写入；显式物化；缓存丢失重建同一 Artifact ID）
localized BOM          PASS（reviewed 译文、source fallback 与 machine part number 分离）
frontend i18n check    PASS（2 locales / 10 namespaces；复用既有 code，catalog 未变）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（297 passed / 4 PostgreSQL-gated skipped；6 个既有 warning）
```

多语言影响面为异步关系/验证/预览任务、验证 issue、预览失败和 locale-aware Part BOM。任务继续冻结 locale/timezone；任务类型、状态、connector、relation、artifact、版本、GLB 与 BOM 编号保持机器值；错误与 issue 复用既有 `code + params`，没有保存最终译文或原始异常。Part API 只选择 reviewed 官方译文并返回实际内容 locale。未修改前端资源、catalog version、content hash 或 release notes。

未连接、重置或修改现有开发数据库；全部 migration、并发、Go/Python Worker 和 Storage 验收继续使用自动删除的隔离 PostgreSQL cluster 与内存 Storage fake。

## 12. G5/G7 hardening 记录

日期：2026-08-10

完成内容：

- [x] G5 的 heartbeat、progress、complete、retry、fail 与 claimed cancellation SQL 全部增加 `claimed_attempt` 条件；同一 worker ID 被下一次 retry 复用时，旧 attempt 也不能续租或覆盖新 attempt。
- [x] Go Worker 传递完整 `ClaimedTask` 执行 heartbeat；Python Import/Relation Worker 的 heartbeat、lease lock 与全部终态 UPDATE 同样匹配 claim 时冻结的 attempts。
- [x] `Complete` 保持原子 UPDATE 为所有权判据；任务已经 `succeeded` 时重复结果提交成为无操作，不重复创建 succeeded task event/outbox，非当前 attempt 仍返回 lease 丢失。
- [x] G7 `parts_resolved` 改为校验递归展开后的真实 leaf Part 与 BOM 完全一致、数量为正、Version/Import Part Library 一致，并由 PostgreSQL 对冻结 Part Library 计算 unresolved part count。
- [x] SceneSnapshot 校验增加 root/model 完整性、重复 model、缺失 submodel、递归环/深度、reference kind、有限位置/矩阵、递归 world transform 与实际 bounding position 检查。
- [x] `relations_valid` 改为校验已确认 AssemblyRelation 的 endpoint Connector、两端 occupancy 与 capacity；没有 AssemblyRelation 本身仍是合法状态，不再以 connector 数量代替关系校验。
- [x] `interfaces_valid` 改为双向核对未拒绝 Interface 与未占用 `external` Connector、`external_interface_id`、world connector，并要求至少一个真实有效的 external interface。
- [x] ValidationReport 继续只保存稳定 `component_repo.validation.*` code、空 params 与机器 path；没有增加最终译文、资源 key 或 locale 分支。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（go test、go vet、sqlc vet、格式检查）
go test -race ./...    PASS
isolated PostgreSQL    PASS（Go integration + 7 个 Python Worker tests；临时 cluster 自动删除）
attempt fencing        PASS（相同 worker ID 的 attempt 1 不能 heartbeat/complete attempt 2）
terminal complete      PASS（重复 complete 只保留 1 条 succeeded event）
validation facts       PASS（frozen Part Library、Assembly occupancy、external Interface SQL 投影）
scene validation       PASS（递归 leaf/BOM、cycle、transform、bounding position 单元测试）
frontend i18n check    PASS（2 locales / 10 namespaces；catalog 未变）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（297 passed / 5 PostgreSQL-gated skipped；6 个既有 warning）
```

多语言影响面为异步任务状态提交与发布验证 issue：locale/timezone 仍在任务创建时冻结；
task/validation code、JSON key、ID、attempt 和状态保持机器值。未修改 UI、官方 Part 译文、
用户内容、资源 catalog、content hash 或 release notes。

未连接、重置或修改现有开发数据库；PostgreSQL 验收只使用自动删除的隔离临时 cluster。

## 13. G5/G7 通用逻辑任务模型记录

日期：2026-08-12

完成内容：

- [x] 新增 Goose v7 `task_jobs`，以 `(owner_id, task_type, logical_key, input_hash)` 表达 Logical Job；`tasks` 改为不可变 Execution，并增加 `task_job_id`、递增 `execution_number` 与 `retry_of_task_id`。
- [x] PostgreSQL trigger/约束原子校验 Job owner/type、最新 Execution、成功 Execution、执行编号和重提链；并发提交由唯一约束和 Job 行锁串行化，不依赖进程内锁。
- [x] 通用调度规则统一为：复用 queued/running；复用成功结果；failed/cancelled 后新增同一 Job 的下一次 Execution；只有服务确认派生缓存缺失时才允许显式新 Execution。
- [x] Attempt 继续只表达单个 Execution 的 lease 领取与恢复；不会复用 task ID 表示新的 Execution，也不会因进程重试增加 Job execution count。
- [x] 关系检测以 Candidate 为 logical key，并将 structure/geometry、Snapshot schema/parser、Part Library source hash、detector version 纳入 input hash；Python Worker 执行前复算并拒绝 stale input。
- [x] 发布校验以 Version 为 logical key，并将 interface/structure/geometry、Part Library source hash、validator version 纳入 input hash；Go Worker 执行前复算并拒绝 stale input。
- [x] 预览以 Version 为 logical key，并将 immutable SceneSnapshot ID、generator version 纳入 input hash；缓存存在时复用成功结果，缓存丢失时在同一 Job 下创建下一次 Execution 并重建稳定 Artifact ID。
- [x] Go/Python task event/outbox 统一携带 `taskJobId + executionNumber + attempt`；公共 Task DTO 返回 Job 与 Execution 编号，不返回内部 payload。
- [x] 删除原 `tasks.idempotency_key` 去重职责；旧 `Enqueue` 调用统一适配到通用 Schedule，未给 relation/validation/preview 增加领域专属任务状态机。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（go test、go vet、sqlc vet、格式检查）
go test -race ./...    PASS
isolated PostgreSQL    PASS（空库 Goose v1 -> v7、v7 down/up、重复 up、startup schema no-drift）
logical concurrency    PASS（8 个并发调度只创建 1 Job / 1 Execution）
execution reuse        PASS（active/succeeded 复用；failed 新建 Execution 2）
workbench scheduling   PASS（relation failed rerun、validation success reuse、preview cache rebuild）
Python Worker E2E      PASS（7 tests；relation input hash 与事件字段已接入）
frontend i18n check    PASS（2 locales / 10 namespaces；catalog 未变）
frontend test          PASS（12 files / 50 tests）
frontend build         PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（297 passed / 5 PostgreSQL-gated skipped；6 个既有 warning）
```

多语言影响面为异步任务状态与结构化事件：locale/timezone 仍在 Execution 创建时冻结；
Job ID、Execution number、Attempt、input hash、task/status/error code 与 JSON key 都是机器值。
未修改 UI、用户内容、官方翻译、资源 catalog、content hash 或 release notes。

未连接、重置或修改现有开发数据库；migration、并发和 Worker 验收只使用自动删除的隔离临时 PostgreSQL cluster。

## 14. G8.1 前端切换盘点记录

日期：2026-08-12

完成内容：

- [x] 扫描 `frontend/src/componentRepo/componentRepoApi.ts`、Component Repo 四个页面、`PartViewerPage`、统一 API client、Supabase token 与 task context；确认 Component Repo 请求仍全部使用旧 `/api` FastAPI 契约。
- [x] 逐项对照 Gin `/api/v1` 的 Component、Group、Artifact、Import、Candidate、Task 和 Workbench 路由、请求 DTO、响应 DTO、HTTP method、分页和异步边界。
- [x] 确认上传完成、关系检测、发布校验和预览物化已变为 `202 + taskId`；前端当前没有 Component Repo 通用 Task poller，仍按同步旧响应工作。
- [x] 确认可以在前端 adapter 解决的差异：page unwrap、`locale` query、Group member POST body、relation/connector/interface `{items}`、Import 的 candidate/draft IDs、签名下载、Version preview 显式物化和删除后刷新。
- [x] 确认必须先在 Go 收口的契约：显式 root bootstrap 与只读根视图、组件库搜索/统计、组件所属分组、Draft Version 元数据 PATCH、ValidationReport GET、Part preview 所有权、Component logical size 和 Group direct count 投影。
- [x] 明确不迁移旧同步 multipart fallback、first/library/candidate Component preview 同义接口、legacy connector-summary 和旧 rich DTO；不得通过兼容代理或双路请求补回。
- [x] 新增 [G8 前端切换清单](./go_g8_frontend_cutover_inventory.md)，记录旧接口到 Gin 的逐项分类、前端 adapter 规则、验收矩阵与 G8.2 -> G8.6 顺序。

验证结果：

```text
frontend call-site scan PASS（4 个 Component Repo 页面 + PartViewer + 单一 adapter）
Gin route inventory      PASS（component/artifact/ingestion/task/workbench 全量 Register 对照）
DTO/HTTP diff review     PASS（同步、异步、分页、下载、所有权和预览边界已分类）
error catalog audit      PASS（Gin 当前稳定 auth/request/component/task code 均已有资源）
git diff --check         PASS
```

本步骤的多语言影响面仅为 G8 后续错误与任务渲染决策：机器状态、ID、Task code 和 JSON key
保持不翻译；用户内容保留原文；官方内容继续只读 reviewed 翻译。没有修改 UI 文案、资源 key、
catalog version、content hash 或 release notes，因此未触发资源发布流程。

本步骤只修改迁移文档，没有切换运行时请求、删除 Python 路由、连接数据库或执行数据变更。

下一步：继续 G8.2，先实现清单中剩余的组件库查询/分组投影、Draft Version 元数据、ValidationReport 读取和 Part preview 合约，再切换剩余旧入口。

## 15. G8.2 可独立闭环能力切换记录

日期：2026-08-12

完成内容：

- [x] Vite 开发代理按最长前缀把 `/api/v1` 发送到独立 Gin 地址（默认 `127.0.0.1:8080`），旧 `/api` 暂时继续发送到 FastAPI（默认 `127.0.0.1:8000`）；没有增加业务网关、兼容代理或双请求。
- [x] Component detail 与 Version list/detail/delete 切换 Gin page/DTO/`204` 契约；owner 判断改用 `ownerId`，只有 Gin 可见的 owner draft 在客户端展示删除动作。
- [x] 上传只保留 Supabase 直传：创建 upload session、完成 upload、读取 Import、轮询持久 Task、使用 Import 的 `candidateId` 读取 Candidate；删除同步 multipart/XHR 回退和 import-candidate/candidate-preview 旧流程。
- [x] Candidate workbench 使用 Go Candidate 的 `componentId/draftVersionId`；关系检测和校验改为 `202 + taskId -> GET Task`，成功后重新读取 durable relation/connector/interface 结果。
- [x] Connector 与 Interface 分别读取 Gin `{items}` 并在前端 view model 合并；仅做数组坐标到场景坐标的表示转换，不恢复 legacy recognition summary 字段。
- [x] 发布前使用 Gin `PATCH Component` 保存名称/分类，再调用无 body 的 Gin publish；Version label/release note 在 Draft Version PATCH 合约完成前不再提供可编辑输入。
- [x] Version preview 使用只读 `GET -> POST materialize -> Task poll -> GET`；BOM 使用 Go `items/ldrawPartNum`，不伪造 availability、image URL 或 logical size。
- [x] Source 下载先从 Gin 获取短期签名 descriptor，再直接下载对象；签名 URL 不进入配置、日志或持久状态。
- [x] Storage 客户端失败统一映射到既有稳定错误 code，不展示 Supabase 原始 provider 消息。
- [x] 增加 Component Repo adapter 契约测试，覆盖异步关系检测、异步预览、版本删除、connector/interface 投影、异步校验及无 legacy body 发布。

验证结果：

```text
frontend i18n check      PASS（2 locales / 10 namespaces；catalog 未变）
frontend adapter tests   PASS（5 cases）
frontend full test       PASS（13 files / 55 tests）
frontend TypeScript/Vite PASS（既有 Vite deprecation/chunk-size warnings）
Python backend pytest    PASS（297 passed / 5 PostgreSQL-gated skipped；6 个既有 warning）
git diff --check         PASS
```

多语言影响面为已有 Task/ApiError 的结构化渲染和 locale/timezone 传递；没有增加文案、资源 key、
catalog version、content hash 或 release notes。Task code、状态、ID、文件 hash、part number 和 JSON
字段保持机器值；Component/Part 用户内容与官方翻译选择边界未改变。

本批没有修改 Go 后端、Python Worker、数据库 schema 或数据；没有连接、重置或修改开发数据库。

仍保留旧 FastAPI 的运行时能力：Component Repo 分组树、分组搜索/统计、分组成员管理与组件所属
分组，以及 `PartViewerPage` 的 Part/Library preview。由于这些能力仍被页面调用，G8 尚未完成，
不得删除 Python Component Repo router。

下一步：补齐剩余 Gin 合约后切换这些旧入口，并增加 ValidationReport 全文读取与 Draft Version
元数据保存；最后执行浏览器网络验收并删除旧 Python 公共 API。

## 16. G8.2/G8.3 剩余 Go 合约与前端切换记录

日期：2026-08-12

完成内容：

- [x] Component Group 的 GET 保持只读；新增显式幂等 `POST /api/v1/component-groups/bootstrap`，空仓库前端只在未读取到 root 时执行该 mutation。
- [x] root group 直接投影当前 actor 可见组件全集；custom group 使用 membership；列表补齐 direct count，不为 root 复制 membership。
- [x] 新增只读 Group component GET search，提供名称/ID 查询、多状态、稳定分页、总数和未过滤状态统计；官方内容仍只选择请求 locale 的 reviewed translation。
- [x] 新增 owner-scoped Component group IDs 投影；Group member 前端改用 Gin page、POST collection body 与 DELETE item 契约。
- [x] Component DTO 补齐 logical size；owner draft Version 新增 PATCH version/revision/release note/locale，发布接口继续无编辑 body。
- [x] 新增 owner-scoped ValidationReport GET；Task result 仍只携带 report ID/passed，前端读取持久 checks/issues 后再渲染稳定 code + params。
- [x] 前端 Component Repo group、search、membership、Draft Version 和 ValidationReport 配置全部切换到 `/api/v1`；没有双请求或旧 DTO 代理。
- [x] 明确 Part/Library preview 暂不强迁：`component_repo.parts` 只有 Part 编号和内容字段，几何/Artifact 仍属于未迁移 Part 域。旧 `/api/library-items/{itemType}/{itemId}/preview` 是当前唯一 Component Repo 相关旧入口。

验证结果：

```text
go tool sqlc generate PASS
make check             PASS（Go tests、vet、sqlc vet）
isolated PostgreSQL    PASS（Goose up/down/up、全部 Go integration、7 个 Python Worker tests）
startup schema drift   PASS（API/Worker 启动前后 component_repo schema 相同）
frontend i18n check    PASS（2 locales / 10 namespaces；catalog 未变）
frontend test          PASS（13 files / 57 tests）
frontend build         PASS（仅既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（297 passed / 5 PostgreSQL-gated skipped；6 个既有 warning）
```

多语言影响面包括自定义分组与 release note 用户原文、官方 Component reviewed translation、
ValidationReport 结构化 code + params。没有增加 UI 文案或资源 key，catalog、content hash 和 release
notes 未变；ID、状态、版本、revision、Part 编号、JSON key 与分页参数保持机器值。

未连接、重置或修改现有开发数据库；PostgreSQL 验收使用自动删除的隔离临时 cluster。

下一步：执行 G8.4 浏览器双语言和网络流量验收；同时把 Part preview 作为 Part 域迁移前置项，
未补齐真实 Part 几何/Artifact 所有权前不得删除旧 FastAPI Component Repo router。

## 17. G8.4 本地启动脚本切换记录

日期：2026-08-13

完成内容：

- [x] 仓库根目录 `scripts/start-backend.sh` 从 FastAPI 启动器改为 Gin API 启动器，不运行 migration、DDL、reset 或 reseed。
- [x] 启动器先加载共享 `backend/.env`，再加载可选 `backend-go/.env` 作为 Go 专属覆盖；调用者已导出的环境变量保持最高优先级。
- [x] 兼容映射旧 Storage 开发变量到 `STORAGE_PROVIDER` 与服务端 `SUPABASE_STORAGE_SERVICE_ROLE_KEY`，脚本不嵌入或输出密钥值。
- [x] `scripts/start-dev.sh` 默认后端端口切换到 `8080`，健康等待端点切换到 Gin 只读 `/health/live`。
- [x] 精确停止遗留的旧 `go run` API 父/子进程后，通过新脚本重新启动 Gin；前端 Vite 继续运行在 `127.0.0.1:5173`。

验证结果：

```text
bash -n scripts/start-backend.sh scripts/start-dev.sh PASS（兼容 macOS Bash 3.2）
git diff --check                                 PASS
GET /health/live                                200 status=ok
GET /health/ready                               200 database=ok
GET /api/v1/components（无 Bearer token）       401 auth.authentication_required
```

i18n 影响为无：本批只改变开发启动编排，没有修改 UI、API code、任务、用户内容、官方内容、
资源 catalog、content hash 或 release notes。未执行数据库 schema 或数据写入。

下一步：使用真实 Supabase 登录会话执行 G8.4 双语言浏览器与网络流量验收；Part Preview 仍是
唯一明确保留在旧 FastAPI `/api` 的 Component Repo 相关边界。

## 18. G8.4 Supabase ES256/JWKS 认证记录

日期：2026-08-13

完成内容：

- [x] 诊断真实 Supabase 登录 Token 返回 `auth.session_invalid`：issuer 与项目一致，项目公共 JWKS 当前只发布 `ES256 / EC P-256`，旧 Go verifier 仅接受 `HS256`。
- [x] Go verifier 增加 `ES256` 验签：按 JWT header `kid` 从 Supabase JWKS 选择 P-256 公钥，校验 JOSE 固定 64-byte `r || s` 签名。
- [x] JWKS 公钥在进程内缓存 10 分钟；未知/过期 key 触发受限刷新，支持 Supabase signing-key rotation，不把 Auth 服务放入每次请求热路径。
- [x] 保留可选 `AUTH_JWT_SECRET` 验证 legacy HS256 token；`AUTH_JWKS_URL` 未显式配置时从 `AUTH_JWT_ISSUER` 派生。
- [x] 非测试环境强制 JWKS 使用 HTTPS；继续验证 `exp`、`nbf`、`iss`、`aud` 和 UUID `sub`，外部失败统一返回稳定认证 code，不暴露 JWKS/provider 细节。
- [x] 通过更新后的启动脚本重启 Gin；数据库与健康检查保持正常。

验证结果：

```text
Supabase public JWKS       PASS（1 个 ES256 / EC key，kid 存在）
auth unit tests            PASS（HS256、ES256、tamper、unknown kid、cache）
make check                 PASS（Go tests、vet、sqlc vet）
GET /health/live           200 status=ok
GET /health/ready          200 database=ok
GET /api/v1/components     401 auth.authentication_required（无 Token 基线）
git diff --check           PASS
```

i18n 影响仅为既有稳定认证错误码 `auth.authentication_required`、`auth.session_invalid` 与
`auth.verification_not_configured` 的选择逻辑；没有增加或修改资源文案、catalog、content hash 或
release notes。JWT header/claims、kid、alg、UUID sub 和 JWKS 字段保持机器值。

下一步：刷新用户当前已登录的前端页面，以其现有 Supabase ES256 Access Token完成真实 actor 请求
验收；随后继续 G8.4 双语言和 `/api/v1` 网络流量检查。

## 19. 阻塞与风险

G1-G7 的代码与隔离测试阶段验收已完成，但 2026-08-14 Review 确认当前开发环境仍有运行和切换缺口；这些缺口不回退阶段代码状态，却会阻止 G8 完成：

- `scripts/start-dev.sh` 当前只启动 Go API 与前端，没有启动 Go/Python Worker；PowerShell 入口仍启动 FastAPI，平台行为不一致。
- 当前 Supabase Worker 所需 service-role 尚未配置，Review 时有 5 个 queued task 未被消费。
- active 非 draft Component 的 Go Preview 可见性与现有 Supabase Storage RLS 规则尚未完全对齐。
- 历史数据迁移建立的 29 个 task 没有对应 task event/outbox；outbox service 也尚无运行时 publisher。
- Part/Library preview 仍走旧 `/api`，FastAPI 仍挂载 Component Repo router，因此仓库中仍存在两套公共入口。
- G5-G8 大量实现仍处于未提交工作树，当前 Git HEAD 不能复现已验证能力。
- Nginx 只做反向代理/HTTPS/负载均衡；不新增业务网关。
- 删除旧 Python Component Repo 公共路由和仅为这些路由服务的 schema/service；保留 `component.import.parse` 与 `component.relations.detect` 两个明确 Worker 算法边界。
- G7 当前 GLB 是确定性的 structural preview；若后续要求 LDraw 精细表面 mesh，可在不改变 version-addressed Artifact/Task/API 契约的前提下升级 generator version。
- Auth verifier 已兼容 Supabase ES256/JWKS 和 legacy HS256；部署时需要保证 issuer/JWKS URL 指向同一个 Supabase 项目。

具体职责、证据、完成判据和推荐顺序见[当前跟进指南](./go_migration_followup_guide.md)。实际开发库若以后执行 reset/reseed，仍需先确认精确数据库目标。

## 20. G8.4 开发库结构初始化与历史数据迁移记录

日期：2026-08-13

完成内容：

- [x] 在用户确认的 Supabase `postgres` 开发数据库执行 Goose `00001`～`00007`，创建由
  Goose 独占管理的 `component_repo` schema；未修改 provider-owned `storage` schema。
- [x] 确认 legacy Component Repo 位于 Alembic 管理的 `public` schema；新增可审计的一次性事务
  数据迁移脚本，将 Component、Artifact、UploadSession、Import、SceneSnapshot、Candidate、Version、
  Group、Membership、Part Library、Connector Analysis 和 ValidationReport 复制到 Go schema。
- [x] 保留业务 UUID；对 legacy `partlib-v1`、历史 Task/Job 和缺失 UploadSession 使用确定性 UUID；
  将 `auth:<uuid>` actor 规范化为 UUID，并从关联 Import 恢复 system-owned Artifact 的真实 owner。
- [x] 迁移 6 Component、26 Artifact、10 Import、7 Snapshot/Candidate、6 Version、3 Group、3 Membership、
  1 Part Library、29,853 Connector Definition、3,859 Part、464 Connector/Interface 与 3 ValidationReport。
- [x] 为历史 Import、Artifact verification 和 Validation 建立 durable `task_jobs/tasks/dependencies` lineage，
  不关闭 G5～G7 trigger/约束硬写数据。
- [x] 旧 relational connector 数据已有 464 个稳定 `external_interface_id` 但没有 Interface 行；按一对一
  Connector 事实恢复 pending Interface，不生成用户译文。Candidate-only ValidationReport 根据唯一 Version
  以及 persisted review decision 的一致引用恢复 Version 关联。
- [x] legacy `public` 的 20 张 Component Repo 表及原始行全部保留，未删除、重命名或修改，供核验与回退；
  Go 运行时仍只访问 `component_repo`，没有兼容 view、双写或跨 schema fallback。

验证结果：

```text
Goose migration        PASS（成功迁移到 version 7）
transactional copy     PASS（任一中间错误均整体回滚；最终单事务 COMMIT）
core count parity      PASS（Component 6、Artifact 26、Import 10、Candidate 7、Version 6、Group 3）
large-table parity     PASS（Connector Definition 29,853、Connector Item 464、Path Node 480）
validation recovery    PASS（3/3，含 1 条唯一 Version 关联恢复）
orphan checks          PASS（Version/Component、Candidate/Import、Connector/Interface、Task/Job 均为 0）
published report gate  PASS（published Version 缺失或失败 Report 数为 0）
legacy preservation    PASS（public Component Repo tables=20，public.components=6）
GET /health/ready      200
GET /api/v1/component-groups 200（3 groups，1 root）
make check             PASS（Go tests、vet、sqlc vet）
frontend i18n check    PASS（2 locales / 10 namespaces；catalog 未变）
frontend test          PASS（13 files / 57 tests）
frontend build         PASS（仅既有 Vite deprecation/chunk-size warnings）
Python backend pytest  PASS（297 passed / 5 PostgreSQL-gated skipped；6 个既有 warning）
```

多语言影响面为领域内容与异步任务上下文的数据迁移：Component 名称、描述、标签和分组名称原样保存；
已有 `contentLocale` 原样保留；机器 ID、状态、hash、Part 编号和 JSON key 不翻译；历史任务使用冻结的
`zh-CN`/`Asia/Shanghai` 上下文与稳定 code，不保存最终译文。未修改 UI 资源、catalog version、content
hash 或 release notes。

下一步：继续 G8.4，使用真实 Supabase 登录会话完成 Component Repo 页面双语言与 `/api/v1` 网络流量
验收；确认历史组件、分组、版本、预览、连接器和 ValidationReport 的页面投影。

## 21. G8.4 请求 JWT 访问 Supabase Storage 修复记录

日期：2026-08-13

完成内容：

- [x] 对照旧 Python `CurrentUser.access_token`、`with_authorization_token` 与
  `component_repo_storage` 实现，恢复相同的用户请求权限模型：`apikey` 使用
  `SUPABASE_PUBLISHABLE_KEY`，Bearer 使用当前已经验签的 Supabase Access Token。
- [x] Go `Actor` 只在请求内保存非导出的 Access Token；Component upload complete、Artifact/source
  download、Preview read 和已存在 Preview 的 metadata check 都显式调用 user-scoped Storage 方法。
- [x] 用户 JWT 不写数据库、不进入 task payload/outbox，不作为结构化日志字段；外部失败继续只返回稳定
  `component_repo.storage_unavailable` code，不暴露对象 key、provider body 或 credential。
- [x] server-scoped `Open`、`Put`、`Delete`、Artifact verification、Preview generation 与 cleanup 仍仅使用
  `SUPABASE_STORAGE_SERVICE_ROLE_KEY`；不允许 publishable key 伪装成 service-role key。
- [x] API-only Supabase 配置允许只提供 URL + publishable key；Supabase 模式 Go Worker 缺少 service-role
  key 时在启动前 fail closed，避免异步任务运行到中途才以 Storage unavailable 失败。
- [x] 根启动脚本不再把 `SUPABASE_STORAGE_KEY` 回退映射为 service-role credential；文档和环境模板明确
  request JWT 与 Worker credential 的权限边界。
- [x] 通过 `scripts/start-backend.sh` 重新启动 Gin API；启动日志确认 Supabase provider 配置有效。

验证结果：

```text
make check                 PASS（Go tests、vet、sqlc vet）
storage auth tests        PASS（user JWT / publishable apikey；server service-role；API-only fail closed）
worker config tests       PASS（Supabase 缺 service-role 拒绝启动）
bash -n + diff check      PASS
frontend i18n check       PASS（2 locales / 10 namespaces；catalog 未变）
frontend test             PASS（13 files / 57 tests）
frontend build            PASS（仅既有 Vite deprecation/chunk-size warnings）
Python backend pytest     PASS（297 passed / 5 PostgreSQL-gated skipped；6 个既有 warning）
GET /health/live          PASS（API 已监听 127.0.0.1:8080）
```

i18n 影响仅为既有 `component_repo.storage_unavailable` 错误路径恢复为成功响应；没有增加或修改 UI 文案、
API code、任务消息、资源 key、catalog version、content hash 或 release notes。JWT、apikey、对象 key、
UUID 与 Storage provider 字段保持机器值。

当前自动化浏览器的新会话没有用户已登录的 localhost Supabase session，因此没有读取或导出浏览器
token；真实 `3991ebc5-0bab-4fd4-9e2d-baad162843e0` Preview 的最终 200 验收需在现有用户页面刷新后完成。

下一步：刷新已登录的 Component Repo 页面，确认 Preview GET 返回 ready + signed URL；随后继续 G8.4
双语言和仅 `/api/v1` 网络流量验收。

## 22. G8 当前职责与跟进基线记录

日期：2026-08-14

完成内容：

- [x] 新增 [Component Repo Go 迁移跟进指南](./go_migration_followup_guide.md)，明确区分代码能力完成、当前环境可运行和迁移切换完成。
- [x] 固化 Go API、Go Worker 与 Python Worker 的职责边界和五类任务路由，明确 API 不执行长计算、Worker 不提供公共 HTTP API。
- [x] 将 2026-08-14 客观 Review 的运行缺口、优先级、完成判据和推荐执行顺序整理为后续检查清单。
- [x] 修正顶部 G8 摘要和“无外部阻塞”的过时表述；G8 继续保持 `In progress`，未把文档整理当作阶段完成。

验证结果：

```text
mandatory Go migration docs read PASS（三份文档全文核对）
document link/heading audit       PASS
git diff --check                 PASS
```

i18n 影响为无：本次只整理内部迁移文档，没有修改 UI、API、任务、验证结果、持久化内容、配置标签、导出或资源 catalog。

下一步：按跟进指南先配置 Worker service-role、启动三个 Worker 并消费 queued task，再收口 Bash/PowerShell 开发启动拓扑。

## 23. G8 开发启动拓扑与 Worker 运行验收记录

日期：2026-08-14

完成内容：

- [x] 增加共享开发环境加载器；`backend/.env` 先加载，`backend-go/.env` 可覆盖，调用方已导出的变量优先，脚本不输出凭据值。
- [x] 增加独立 Bash/PowerShell launcher：Go API、legacy FastAPI、Go Worker、Python Import Worker 和 Python Relation Worker 均可单独启动和重启。
- [x] `start-dev` 默认表达 G8 混合拓扑并管理全部子进程；Go/legacy API 分别通过只读 health endpoint 就绪后才启动前端，任一启动失败会清理子进程。`START_LEGACY_API=0` 和 `START_COMPONENT_WORKERS=0` 仅用于明确缩减的本地拓扑。
- [x] Go/Python Worker 支持现代 `SUPABASE_SECRET_KEY`（`sb_secret_*`）和 legacy `SUPABASE_STORAGE_SERVICE_ROLE_KEY`；现代 secret 只放在 `apikey` header，不作为非 JWT Bearer token 发送。publishable key 继续不能充当服务端凭据。
- [x] Python Relation Worker 增加与 Import Worker 一致的 SIGINT/SIGTERM 协作停止入口。
- [x] 使用真实 Supabase 开发环境启动 Go API、Go Worker、Python Import Worker、Python Relation Worker 和前端；Go API live/ready 均为 `200`，进程边界与 task type 路由符合 G5～G7 设计。
- [x] 启动前 5 个 queued 历史任务被实际消费，证明 PostgreSQL claim/依赖传播链路恢复；没有残留 queued task。

运行验收同时发现两个未闭环项：

- legacy FastAPI 需要 Alembic `20260809_0022`，当前真实开发库仍为 `20260803_0021`，因此默认完整拓扑会 fail closed 并清理子进程。未在本次自动执行真实 `storage` policy migration。
- 一次性历史迁移创建的 runnable payload 含协议外 `legacyMigration` 字段；Artifact Verify 严格校验后 3 个任务以 `common.internal_error` 终止，依赖传播使 2 个 Parse Task 在 attempts=0 时失败。该结果不是 Storage credential 失败；终态任务不可原行重排，需要单独决定可审计修复/新 Execution 策略。

验证结果：

```text
bash -n startup scripts       PASS（共享 env、5 个独立进程 launcher、start-dev）
git diff --check              PASS
backend-go make check         PASS（GOCACHE 使用 sandbox 可写临时目录）
backend-go go test -race      PASS
Python Worker/Storage tests   PASS（11 passed / 5 PostgreSQL-gated skipped）
Python backend pytest         PASS（299 passed / 5 skipped；1 个既有多进程用例在沙箱外重跑 PASS）
frontend i18n check           PASS（2 locales / 10 namespaces；catalog 未变）
frontend test/build           PASS（13 files / 57 tests；仅既有 Vite/chunk warnings）
modern Supabase secret        PASS（只发送 secret apikey，不发送 Bearer）
Go API /health/live           200
Go API /health/ready          200 database=ok
process topology              PASS（Go API + Go Worker + 2 Python Worker + Vite）
queue consumption             PASS（5 queued -> 3 Artifact failed + 2 dependent Parse failed）
legacy API startup            BLOCKED（Alembic actual 0021 / expected 0022）
```

多语言影响为无：本次只修改开发进程编排、服务端凭据选择和内部 Worker 停止行为；没有修改 UI、API/任务 code、locale/timezone、领域内容、导出、资源 catalog 或最终译文。历史任务继续只保存稳定 `common.internal_error + {}`，未写入异常正文、SQL、路径或凭据。

下一步：先决定并执行历史 runnable Task 的可审计修复策略；如需恢复完整 G8 混合拓扑，再明确授权 Alembic `20260809_0022` 修改真实 Supabase `storage` policy。两项均不得通过放宽 Worker payload 校验绕过。

## 24. G8 Part preview 直接迁移记录

日期：2026-08-14
阶段：G8
状态：In progress

完成内容：

- [x] 删除通用 `/api/library-items/{itemType}/{itemId}/preview` FastAPI 路由、配置键、服务函数和前端调用；不保留 alias、兼容 DTO、同步物化或双路请求。
- [x] 新增不可变 Part preview 资源：`partLibraryVersionId + ldrawPartNum`；GET 只读，显式 materialize POST 返回 durable `taskId`。
- [x] 新增 Goose v8 `part_geometries` 与 `part_previews`，分别保存版本化源 hash/路径/尺寸和可重建 Artifact 状态；任务终态 trigger 只写稳定 `code + params`。
- [x] 新增 `component.part_preview.materialize` Go Worker：校验严格 payload、Part Library/source hash 和 generation，递归展开 LDraw type 1/3/4，生成真实 uncompressed GLB，上传对象存储并原子绑定 verified derived Artifact。
- [x] 修复 Component/Part Preview 在 retry attempt 时业务状态仍为 `running` 的恢复问题；同一 task 可在 `pending/running` 上重新进入 Worker，不放宽 payload 或 attempt fencing。
- [x] Part viewer 路由改为 `/parts/:partLibraryVersionId/:ldrawPartNum`；Part Search 通过 active Part Library discovery 构造版本化链接，Component Version BOM 直接返回冻结的 `partLibraryVersionId`。
- [x] 官方 Part 内容继续只选择请求 locale 的 `reviewed` translation；source fallback 返回实际 `contentLocale`，编号、hash、路径、状态和 JSON key 不翻译。
- [x] 新增显式、幂等 `20260814_public_parts_to_go.sql`，用于把 legacy `public.ldraw_parts/ldraw_part_geometry/part_translations` 交接到 `component_repo`；API/Worker startup 不执行该脚本。

验证结果：

```text
go tool sqlc generate          PASS
backend-go make check          PASS（Go tests、vet、sqlc vet）
isolated PostgreSQL            PASS（Goose 0->v8、v8 down/up、重复 up、全部 integration）
startup schema drift           PASS（API/Worker 启动前后 schema 一致）
LDraw mesh/GLB unit tests      PASS（reference transform、quad triangulation、recursion rejection、GLB header）
Python parser Worker contract  PASS（9 passed）
frontend i18n check            PASS（2 locales / 10 namespaces；catalog `frontend-2026.08.14.1`）
frontend test                  PASS（13 files / 58 tests）
frontend build                 PASS（仅既有 Vite deprecation/chunk-size warnings）
Python backend pytest          PASS（299 passed / 5 skipped；唯一 sandbox multiprocessing 用例在沙箱外重跑 PASS）
legacy library-items route     PASS（OpenAPI 不存在；请求返回 404）
```

i18n 影响包括官方 Part 名称选择、API error 和 Task failure；为三个精确的 Part error code 增加双语资源，catalog 升级为 `frontend-2026.08.14.1`，content hash 与 `I18N_RELEASE_NOTES.md` 已同步。机器字段保持稳定。

未修改真实 Supabase 开发库、`storage` policy 或终态历史任务。真实环境仍是 Goose v7；启用新 Part preview 前必须明确数据库目标并执行 Goose v8、Part 数据交接、行数/hash 核对，同时为 Go Worker 配置与该版本一致的只读 `LDRAW_ROOT`。G8 仍未完成，剩余工作是实际数据/Artifact smoke、浏览器双语言与网络验收，以及删除其余 Python Component Repo 公共 API。

## 25. 更新模板

每次完成迁移工作后追加：

```text
日期：YYYY-MM-DD
阶段：Gx
状态：In progress / Completed / Blocked
完成：代码与文档事实
验证：执行命令与结果
遗留：仍未完成的内容
下一步：下一项可执行工作
```

阶段只有满足路线图中的全部验收条件后才能标记为 `Completed`。
