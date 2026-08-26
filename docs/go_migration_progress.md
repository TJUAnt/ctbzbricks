# Go 后端迁移进度

> 最后更新：2026-08-26（Part Search meshopt GLB 静态缩略图）
> 状态依据：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 跟进指南：[go_migration_followup_guide.md](./go_migration_followup_guide.md)
> Studio Part Library 路线图：[go_part_library_studio_roadmap.md](./go_part_library_studio_roadmap.md)
> 更新规则：只记录已经由代码、测试或文档证据证明的事实。

## 1. 当前摘要

| 阶段 | 状态 | 说明 |
|---|---|---|
| G0 原则、路线与工程决策 | Completed | 目标架构、迁移原则、阶段和完成定义已入库 |
| G1 Go 工程骨架 | Completed | API、Worker、migration、sqlc/pgxpool 与测试骨架已验收 |
| G2 PostgreSQL schema baseline | Completed | `component_repo` baseline、authority、sqlc 与 PostgreSQL contract 已验收 |
| G3 组件目录、版本和分组 | Completed | GET 只读与 Candidate 来源链约束已完成 hardening 并通过 PostgreSQL contract |
| G4 Artifact 与上传会话 | Completed | source Artifact 数据库不可变边界、直传 RLS 与服务端清理权限均已通过 contract |
| G5 持久化任务系统 | Completed | Logical Job / Execution / Attempt、PostgreSQL 状态机、attempt-fenced lease/retry/cancel、event/outbox 与语言无关 Worker 协议已验收 |
| G6 导入、解析与候选流程 | Completed | upload -> verify dependency -> Go parse -> Snapshot/Candidate/Draft 异步闭环已验收 |
| G7 关系、接口、校验和预览 | Completed | 关系检测/审核、可选版本验证、预览与 PostgreSQL 不变量均由 Go 承担 |
| G8 前端切换与 Component Repo Python 删除 | In progress | 主要前端能力与全部 Component Repo task consumer 已切换 Go；尚需真实浏览器/RLS 验收和旧 Python 公共 router 删除 |

当前 Go 后端已经覆盖 Component Repo 的目录、版本、分组、订阅、Artifact、上传、持久任务、导入、解析、Candidate、关系检测/审核、connector/interface、可选版本验证、直接发布、BOM 和预览闭环。发布与验证已解耦：owner 可直接发布 Draft，验证由用户在 Draft/Published 上显式异步触发，最近报告在详情页展示且不改变发布状态。`component.import.parse` 与 `component.relations.detect` 均由 Go Worker 执行，旧 Python import/relation worker adapter 与启动入口均已删除。上传弹窗以 complete `202` 为终点，Worker 持久执行 verify/parse/BOM/GLB；Candidate 默认只展示整体 GLB 与 BOM，Connector 按开关加载。BOM 已逐项返回 `geometryStatus`，缺少几何的 Part 保留并标注，整体 GLB 采用记录 omissions 的 partial preview。G8 已切换 Component Repo 的主要前端调用；Part preview 已切到 `/api/v1`，Studio LDraw snapshot 已成为 active Part Library。真实 Supabase 当前已执行 Goose v12 与 Studio connector 导入，active library 为 `preview_ready/relation_ready=true`；collider 采用 metadata-only。真实 Supabase 非 owner Preview RLS、完整双语言网络矩阵和旧 Python 公共 router 删除仍需完成。代码阶段状态与当前环境运行状态必须分开判断，详见[跟进指南](./go_migration_followup_guide.md)。

## 2. 已确认决策

- [x] Component Repo 目标运行时为 Go-only；其他 BrickBuilder 领域是否保留 Python 由各自路线图决定。
- [x] `component.relations.detect` 已迁移为 Go Worker；不得新增 Component Repo Python task type。
- [x] 技术栈采用 Gin、PostgreSQL、sqlc、pgx/v5、pgxpool。
- [x] 增加 Goose 作为 Go 目标 schema migration 工具。
- [x] 当前开发阶段不承担旧 API、在线流量、MySQL 或开发数据兼容义务。
- [x] 采用模块化单体 API，不开发 Go 业务网关。
- [x] 组件长任务通过 PostgreSQL 持久化队列异步执行。
- [x] Gin 不同步执行文件解析、复杂几何和长时间计算。
- [x] 新组件 API 使用 `/api/v1`，不要求复刻旧 FastAPI DTO。
- [x] migration authority 按 PostgreSQL schema/domain 分配：Goose 独占 `component_repo`；Alembic 暂时管理未迁移的 legacy `public` 域及 provider-owned Supabase `storage` policy，双方不得跨边界管理同一对象。
- [x] Go API 继承现有 i18n、领域内容和结构化错误不变量。
- [x] ComponentVersion 发布不要求 ValidationReport；验证是用户显式触发的可选异步质量报告，可作用于 Draft/Published，失败不阻止或撤销发布。

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
- 当时计划删除旧 Python Component Repo 公共路由、保留两个算法 Worker；该目标已被 2026-08-22
  Component Repo Go-only 决策取代，见第 41 节。
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

## 25. G8 Part preview 真实开发库迁移执行记录

日期：2026-08-15
阶段：G8
状态：In progress

完成内容：

- [x] 在已确认的 Supabase `postgres` 开发数据库执行 Goose `00008_part_preview.sql`，真实库从 version 7 升级到 version 8。
- [x] 真实库新增 Goose-owned `component_repo.part_geometries` 与 `component_repo.part_previews`；未修改 provider-owned `storage` schema 或 policy。
- [x] 执行显式 Part 数据交接脚本 `backend-go/db/data_migrations/20260814_public_parts_to_go.sql`；legacy `public.ldraw_parts`、`public.ldraw_part_geometry` 与 `public.part_translations` 未删除、未重命名。
- [x] 交接脚本成功提交事务，将 24,214 个 legacy Part 行写入/更新到 `component_repo.parts`；`component_repo.part_previews` 通过 trigger 与既有数据覆盖到 25,062 行。
- [x] 确认 legacy `public.part_translations` 为 0 行，因此本次 `component_repo.part_translations` 插入 0 行符合源数据状态。
- [x] 用户提供的 `LDCadShadowLibrary` 经检查为 LDCad shadow/connectivity 信息库，不是 Part preview 所需几何源；改用本机 Studio LDraw 根目录 `/Applications/Studio 2.0/ldraw` 生成 source hash staging。
- [x] 新增并执行显式补交接脚本 `backend-go/db/data_migrations/20260815_part_geometries_from_hash_stage.sql`，使用 `/tmp/ctbzbricks_studio_part_hashes.tsv` 写入可核对的 `source_relative_path + sha256`。

验证结果：

```text
Goose migrate up                    PASS（00008 applied；database version=8）
Part data handoff transaction        PASS（BEGIN -> COMMIT）
component_repo.parts                 25,062 rows
component_repo.part_previews         25,062 rows
component_repo.part_geometries       4,062 rows
component_repo.part_geometries ready 4,062 rows
public.ldraw_parts                   24,214 rows retained
public.ldraw_part_geometry           24,214 rows retained
public.part_translations             0 rows retained
legacy Part file_hash audit          24,214 empty file_hash values
legacy geometry numeric readiness    8,228 rows with required parsed geometry fields
LDCadShadowLibrary coverage          3,302 matching legacy paths（rejected as geometry source）
Studio LDraw coverage                11,785 matching legacy paths
geometry hash staging                11,785 rows
geometry completion transaction      PASS（COPY 11,785；INSERT/UPDATE 4,062；COMMIT）
sample geometry                      3001.dat -> parts/3001.dat -> 414 faces
```

i18n 影响为官方 Part 内容数据交接：机器 ID、Part 编号、hash、状态和 JSON key 保持不翻译；legacy 翻译源表为空，未新增或修改资源 key、catalog version、content hash 或 release notes。

遗留：真实库现在已有可用 Part preview geometry 子集，但仍有 21,000 个 `component_repo.parts` 缺少 `part_geometries`。原因是 legacy `public.ldraw_parts.file_hash` 全为空，且 Studio LDraw 与 legacy Part 清单只部分重叠；本次只对本地源文件存在、legacy geometry 字段完整且已解析的 Part 写入 `ready` geometry。下一步应为 Go Worker 配置只读 `LDRAW_ROOT=/Applications/Studio 2.0/ldraw`，用 `3001.dat` 等已具备 geometry 的样例执行真实 Part preview Artifact smoke；若要求覆盖更多 Part，需要补充与 legacy Part 清单一致的完整 LDraw library 或重新导入 Part/geometry 元数据。

## 26. G8 Part identity 与 logical size schema 决策固化

日期：2026-08-15
阶段：G8
状态：In progress

完成内容：

- [x] 固化 Part 核心身份继续使用 `(partLibraryVersionId, ldrawPartNum)`，不改为 LEGO design ID、BrickLink ID 或 Rebrickable ID；外部平台编号作为版本化多值映射。
- [x] 新增 Goose v9 `part_external_ids`，用于挂载 `ldraw/rebrickable/bricklink/lego_design/lego_element`，并记录 `relation_type/confidence/source/metadata`。
- [x] `part_geometries.logical_width_stud/logical_depth_stud/logical_height_plate` 从必填字段改为可空派生字段，新增稳定机器字段 `logical_size_derivation_status`。
- [x] Part preview API 的 `geometry` 仍代表可预览几何；logical size 可为 `null`，前端尺寸展示对 `null` 使用既有空值样式，不阻塞 GLB preview。
- [x] 新增显式、幂等 `20260815_part_external_ids_from_legacy.sql`，用于在 Goose v9 后把 legacy `public.xref_part_numbers` 交接到 `component_repo.part_external_ids`；脚本不删除或修改 legacy 表。

验证结果：

```text
go tool sqlc generate                         PASS
backend-go db/migrations tests                PASS
backend-go internal/workbench tests           PASS
frontend componentRepoApi focused test        PASS（含 i18n:check）
legacy external ID audit                      PASS（xref rows=25,384；distinct LDraw=5,504；当前仅 Rebrickable 有值）
Studio LDraw/connectivity audit               PASS（top-level distinct parts=24,426；connectivity files=8,998；collider files=10,386）
```

i18n 影响为 API 结构字段和机器状态扩展：`logicalSizeDerivationStatus`、`id_system`、`relation_type`、外部编号和 JSON key 都是机器值，不翻译；未新增 UI 文案、错误码、资源 key、catalog version、content hash 或 release notes。

真实开发库执行记录：2026-08-15 已在已确认的 Supabase `postgres` 开发数据库执行 Goose v9，`00009_part_geometry_derivation_and_external_ids.sql` 成功提交。核对结果为 `goose_version=9`、`component_repo.part_external_ids` 已存在且当前 0 行、`component_repo.part_geometries.logical_size_derivation_status` 已存在，既有 4,062 条 geometry 均为 `legacy_imported`。未修改 provider-owned `storage` schema 或 policy，未删除或修改 legacy `public` 表。

真实开发库 external ID 交接记录：2026-08-15 已执行 `20260815_part_external_ids_from_legacy.sql`。第一次运行因 legacy `xref_part_numbers` 存在重复映射而在事务内失败并回滚；脚本补充 `DISTINCT ON` 去重后重跑成功提交。结果为 `component_repo.part_external_ids=50,444`，其中 `ldraw=25,062`、`rebrickable=25,382`，非 LDraw external ID 覆盖 5,504 个 Part；`relation_type` 分布为 `exact=5,504`、`unknown=19,878`。真实源表当前没有 BrickLink、LEGO design 或 LEGO element 值，因此对应系统仍为 0。未修改 provider-owned `storage` schema 或 policy，未删除或修改 legacy `public` 表。

遗留：v9 schema 与 legacy Rebrickable external ID 已交接到真实库；BrickLink/LEGO design/element 仍需后续引入可信映射源。下一步应补一次真实 Part preview smoke，并决定是否接入 Studio `connectivity/*.conn` 与 `collider/*.col`。

## 27. G8 Studio Part Library 基准路线图记录

日期：2026-08-15
阶段：G8
状态：Roadmap recorded

完成内容：

- [x] 新增 [Studio Part Library 基准路线图与数据来源依据](./go_part_library_studio_roadmap.md)，固化后续 Part Library 不再以 legacy `public.ldraw_parts` 为权威基准，而以 Studio LDraw snapshot 为几何和 Part membership 基准。
- [x] 明确 legacy 数据边界：legacy 只作为名称、类别、历史 Rebrickable cross-reference 和迁移审计/enrichment 来源，不再决定新 Part Library 包含哪些 Part。
- [x] 明确外部编号策略：核心 Part ID 继续为 `(partLibraryVersionId, ldrawPartNum)`；BrickLink、LEGO design、LEGO element、Rebrickable 全部通过 `component_repo.part_external_ids` 多值挂载。
- [x] 明确 LEGO element 是颜色/材质相关编号，不能作为无颜色 Part 的唯一身份；后续导入必须携带 color metadata 或迁入颜色感知表。
- [x] 明确 logical size 从 Studio 几何派生，并使用 `logical_size_derivation_status` 记录 `derived_exact/derived_approximate/not_applicable/failed` 等状态；Part preview 不因 logical size 缺失失败。
- [x] 明确 Studio connectivity/collider 作为后续独立阶段，不混入本次 Part preview 几何基准。

数据来源依据：

```text
Studio root                                  /Applications/Studio 2.0
Studio LDraw all .dat/.ldr/.mpd              50,578 files
Studio distinct top-level parts              24,426
Studio top-level bl_ prefixed files           1,966
ldraw_new.xml                                Transformation=5,272 / Assembly=97 / Decoration=43 / Material=210
designid.xml                                 Part=443 / alternate design IDs=533
elementInfoList.json                         rows=84,317 / elementId=75,608 / blItemNo=45,006 / blColorCode=170
Studio connectivity                           8,998 .conn files
Studio collider                               10,397 .col files
example LEGO element cardinality              blItemNo=3001 -> 79 elementId rows
```

i18n 影响为无：本次仅新增开发 roadmap 与数据来源文档；没有修改 UI、API/任务 code、locale/timezone、官方 Part 翻译、资源 key、catalog version、content hash 或 release notes。机器编号、外部编号、状态和 JSON key 继续不翻译。

遗留：roadmap 尚未实现。下一步是 S1 Studio manifest 生成器：只读扫描 Studio snapshot，生成可审计 manifest、hash 和 coverage report；不写真实数据库。

## 28. G8 legacy public 容量清理执行记录

日期：2026-08-15
阶段：G8
状态：Completed

完成内容：

- [x] 在用户确认后，对已确认的 Supabase `postgres` 开发数据库执行显式清理脚本 `backend-go/db/data_migrations/20260815_cleanup_legacy_capacity.sql`。
- [x] 只清理两张 legacy/public 辅助导入表：`public.rb_inventory_parts` 与 `public.ldraw_file_references`。
- [x] 未修改 `component_repo` schema、`storage` schema、Supabase Storage policy、Goose migration 版本或其它 `public` 表。
- [x] 清理前执行外键 preflight：两张表只作为 child table 引用 `rb_inventories/rb_parts/ldraw_files`，没有其它表引用它们，因此执行无 `CASCADE` 的 `TRUNCATE`，不会连带删除父表或 Go schema 数据。

验证结果：

```text
target database                         postgres
target user                             postgres
public.rb_inventory_parts before        1,497,951 rows / 128 MB
public.ldraw_file_references before       431,347 rows / 122 MB
TRUNCATE transaction                    PASS（BEGIN -> TRUNCATE -> COMMIT）
ANALYZE truncated tables                PASS
public.rb_inventory_parts after         0 rows / 16 kB
public.ldraw_file_references after      0 rows / 48 kB
database total before cleanup           466 MB
database total after cleanup            216 MB
released database space                 about 250 MB
remaining public legacy candidates      about 116 MB
largest remaining public legacy table   fitting_candidate_profiles / 16 MB
```

i18n 影响为无：本次是开发数据库 legacy 辅助数据清理；没有修改 UI、API/任务 code、locale/timezone、官方 Part 翻译、资源 key、catalog version、content hash 或 release notes。机器编号、外部编号、状态和 JSON key 继续不翻译。

遗留：`public` 中仍保留约 116 MB legacy 候选数据，用于迁移审计和后续 Studio-based Part Library 对照；如容量继续紧张，可再单独评估 `fitting_candidate_profiles`、legacy connector/shadow 和 Rebrickable catalog 表。不得在未确认前清理 `component_repo`、`storage` 或旧 Component Repo 公共 API 仍可能读取的小体积 `public.component_*` 表。

## 29. G8 Studio Part Library S1 manifest 生成器执行记录

日期：2026-08-15
阶段：G8 / Studio Part Library S1
状态：Completed for manifest generation

完成内容：

- [x] 新增 Go 离线工具 `backend-go/cmd/studio-manifest` 与内部包 `backend-go/internal/partlibrary`，用于只读扫描 BrickLink Studio install root 或其 `ldraw` 子目录。
- [x] 新增 `backend-go Makefile` 入口 `studio-manifest`，通过 `STUDIO_ROOT`、`OUT_DIR` 和可选 `LEGACY_PARTS_FILE` 运行。
- [x] 工具输出 `studio_manifest.json` 与 `studio_manifest_summary.json`；每个源文件记录 `relative_path/file_kind/sha256/size_bytes`，并生成 canonical top-level Part 清单。
- [x] 工具识别 top-level official/unofficial `.dat` Part、LEGO `.dat`、subpart、primitive、texture、connectivity `.conn`、collider `.col` 和其它 LDraw 文件。
- [x] 固化 duplicate policy：同一 `ldrawPartNum` 同时存在 official 与 unofficial 来源时，canonical membership 优先 official，所有 candidate path 仍保留在 manifest 中。
- [x] 工具解析 Studio metadata source 摘要：`ldraw_new.xml`、`designid.xml`、`elementInfoList.json`。
- [x] coverage report 能力已实现：只有显式提供 `LEGACY_PARTS_FILE` 时才生成 `studio_manifest_coverage.json`；工具本身不连接或读取真实数据库。
- [x] 单元测试覆盖 manifest 分类、duplicate policy、metadata parsing、coverage 计算和 manifest hash 确定性。

真实 Studio snapshot 运行结果：

```text
command install root              go run ./cmd/studio-manifest --studio-root '/Applications/Studio 2.0' --out-dir /tmp/ctbzbricks_studio_manifest_s1_v3
command ldraw root                go run ./cmd/studio-manifest --studio-root '/Applications/Studio 2.0/ldraw' --out-dir /tmp/ctbzbricks_studio_manifest_s1_v3_repeat
manifest path                     /tmp/ctbzbricks_studio_manifest_s1_v3/studio_manifest.json
summary path                      /tmp/ctbzbricks_studio_manifest_s1_v3/studio_manifest_summary.json
manifest sha256                   524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
hash determinism                  PASS（install root 与 ldraw root 输入 hash 一致）
total manifest files              69,968
LDraw .dat/.ldr/.mpd files         50,578
canonical top-level parts          24,426
official top-level .dat            12,132
unofficial top-level .dat          23,216
duplicate part nums                10,922
top-level bl_ prefixed files        1,966
connectivity .conn files            8,998
collider .col files                10,386
textures                               6
ldraw_new.xml transformations       5,272
ldraw_new.xml assemblies               97
ldraw_new.xml decorations              43
designid.xml parts                    443
designid.xml alternate IDs            533
elementInfoList.json rows          84,317
distinct elementId                 75,608
distinct blItemNo                  45,005
distinct blColorCode                  170
blItemNo=3001 element rows             79
```

验证结果：

```text
go test ./internal/partlibrary ./cmd/studio-manifest PASS
GOCACHE=/tmp/ctbzbricks-go-cache make check          PASS
Makefile studio-manifest target                      PASS（hash 524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b）
git diff --check                                    PASS
```

i18n 影响为无：本次新增离线开发工具、Makefile 入口和开发文档记录；没有修改 UI、API/任务 code、locale/timezone、官方 Part 翻译、资源 key、catalog version、content hash 或 release notes。机器编号、外部编号、状态和 JSON key 继续不翻译。

遗留：真实 coverage report 未生成，因为 S1 工具按设计不读取真实数据库，且本次没有提供显式导出的 `LEGACY_PARTS_FILE`。下一步 S2 前应决定是否从备份或显式只读导出生成 legacy part list，用于 coverage 审计；随后实现 Studio-based Part Library Version importer，但仍不得在 API/Worker startup 中执行导入或回填。

## 30. G8 Studio Part Library S2 importer 与真实库激活记录

日期：2026-08-15
阶段：G8 / Studio Part Library S2
状态：Completed for Studio-based Part Library metadata import

完成内容：

- [x] 新增 Go 离线工具 `backend-go/cmd/studio-import`，从 S1 `studio_manifest.json` 创建或更新 Studio-based Part Library Version。
- [x] 新增 `backend-go Makefile` 入口 `studio-import`；默认 `STATUS=building`，不会自动激活 runtime library。
- [x] importer 默认使用 manifest hash 确定性生成 Library UUID，避免重复导入同一 snapshot 产生多个版本。
- [x] importer 使用临时 staging table + `CopyFrom` 批量写入 `component_repo.part_library_versions`、`parts`、`part_geometries`；`part_previews` 由 Goose v8 trigger 自动创建。
- [x] importer 不读取 legacy `public.ldraw_parts`、不连接 Storage、不修改 `storage` schema/policy、不在 API/Worker startup 执行。
- [x] LDraw 解析器修复 Windows 风格 backslash reference 归一化；同一修复同步到 Part preview Worker 的 `normalizeLDrawPath`。
- [x] importer 递归解析 LDraw type 1/3/4，写入 bbox、source hash、vertex/face count；logical size 当前为 geometry-derived approximate；解析失败写入 `geometry_status=failed` 和稳定 `component_repo.geometry_not_materialized`。
- [x] 在真实 Supabase `postgres` 开发库导入 Studio-based Part Library Version，初始 `status=building`。
- [x] 样例核对通过后，将 Studio-based library 标为 `active`，并将旧 legacy-based active library 标为 `retired`；未删除旧数据，冻结引用仍可查。

真实开发库结果：

```text
partLibraryVersionId                 c8176a73-eccb-4db3-ba72-30edf5f9fd23
source_name                          bricklink_studio_ldraw
source_hash                          524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
previous active library              a834780c-6c1b-a698-70a5-2513d4c94c15 / connector_instances
previous active status after switch   retired
Studio library status after switch    active
parts                                24,426
part_previews                        24,426
geometry ready                       22,569
geometry failed                       1,857
external_ids                              0（S3 范围）
```

代表样例：

```text
3001.dat             ready / face_count=700 / logical≈4 x 2 x 3.5
3002.dat             ready / face_count=508 / logical≈3 x 2 x 3.5
3003.dat             ready / face_count=316 / logical≈2 x 2 x 3.5
3020.dat             ready / face_count=700 / logical≈4 x 2 x 1.5
3023.dat             ready / face_count=172 / logical≈2 x 1 x 1.5
3062b.dat            ready / face_count=448 / logical≈1 x 1 x 3.5
3710.dat             ready / face_count=364 / logical≈4 x 1 x 1.5
bl_10202pb016.dat    ready / face_count=2444
```

验证结果：

```text
go test ./internal/partlibrary ./internal/workbench ./cmd/studio-import ./cmd/studio-manifest PASS
isolated PostgreSQL make test-postgres                                               PASS
GOCACHE=/tmp/ctbzbricks-go-cache make check                                          PASS
real Supabase Studio import status=building                                          PASS
real Supabase Studio activation                                                      PASS
git diff --check                                                                     PASS
```

i18n 影响为无：本次新增离线导入工具、机器状态和开发文档记录；没有修改 UI、API/任务 code、locale/timezone、官方 Part 翻译、资源 key、catalog version、content hash 或 release notes。Part 编号、hash、status、error code/params 和 JSON key 继续不翻译。

遗留：本次完成 DB-level Part/geometry/preview metadata 导入与 active library 切换；尚未执行真实 GLB Artifact materialize smoke。`part_external_ids` 对新 Studio library 仍为 0，BrickLink/LEGO design/LEGO element/Rebrickable external ID 补充属于 S3。后续 parser hardening 已显式写入真实库，见下一节。

## 31. G8 Studio LDraw geometry parser hardening 记录

日期：2026-08-15
阶段：G8 / Studio Part Library S2 hardening
状态：Completed

完成内容：

- [x] 诊断真实库 1,857 个 `geometry_status=failed`：原始失败主要由 `invalid LDraw face`、`missing LDraw reference`、`bufio.Scanner: token too long` 和少量 no-face 组成。
- [x] 明确处理原则写入 [Studio Part Library 基准路线图](./go_part_library_studio_roadmap.md)：当前 Part preview 以 mesh/bbox 为目标，忽略 printed texture 的 UV/metadata，但不对真正缺失的 subpart/primitive 猜测几何。
- [x] `backend-go/internal/partlibrary` 的 LDraw parser 改为 line reader，避免超长 `PE_TEX_INFO` 触发 scanner token limit。
- [x] LDraw type 3/4 face 接受 Studio trailing UV/texture fields，只解析标准几何坐标。
- [x] LDraw reference resolver 增加 Studio primitive fallback：`8/<name>.dat` / `48/<name>.dat` 在原路径缺失时可解析到 plain `p/<name>.dat`。
- [x] missing reference 错误保留稳定 reason，同时在 importer 失败参数和 dry-run sample 中记录 `fromPath`、`reference` 和 `candidates`，便于后续判断是真缺源文件还是 resolver 缺口。
- [x] 同步修复 Part preview Worker 的 LDraw parser，避免 importer ready 与 GLB materialize 语义分叉。
- [x] 增加 importer 与 Worker 回归测试：Studio textured face、超长 texture metadata、`8/`/`48/` primitive fallback、missing reference 诊断。
- [x] 用户确认后，显式重跑 `studio-import` 写回已确认的真实 Supabase `postgres` 开发库；同一 deterministic Studio library 保持 `active`。

验证结果：

```text
go test ./internal/partlibrary ./internal/workbench ./cmd/studio-import ./cmd/studio-manifest PASS
studio-import dry-run before hardening baseline                                    24,426 parts / 22,569 ready / 1,857 failed（写库前真实库基线）
studio-import dry-run after texture face + long metadata hardening                 24,426 parts / 24,322 ready /   104 failed
studio-import dry-run after 8/48 primitive fallback                                24,426 parts / 24,373 ready /    53 failed
real Supabase studio-import write                                                  PASS（DryRun=false；status=active）
real Supabase DB count check                                                       PASS（parts=24,426；previews=24,426；ready=24,373；failed=53；active libraries=1）
real Supabase sample check                                                         PASS（10202pb021.dat/115551.dat/14769pb079.dat ready；13195.dat missing reference）
remaining failure sample source check                                              PASS（抽样 reference 在本机 Studio snapshot 中未找到）
```

i18n 影响为无：本次只修改离线 importer、Worker 内部几何解析、机器诊断字段和开发文档；没有修改 UI 文案、公共 API 文案、locale/timezone、官方 Part 翻译、资源 key、catalog version、content hash 或 release notes。LDraw path、reference、状态、error code/params 和 JSON key 继续作为机器值不翻译。

真实开发库核对结果：

```text
partLibraryVersionId                 c8176a73-eccb-4db3-ba72-30edf5f9fd23
source_hash                          524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
status                               active
active libraries                     1
parts                                24,426
part_previews                        24,426
geometry ready                       24,373
geometry failed                          53
```

遗留：真实 Supabase active Studio library 已更新到 parser hardening 结果；尚未执行真实 GLB Artifact materialize smoke。下一步使用 `3001.dat`、`3023.dat`、printed textured 样例和 ready `bl_` 样例，通过 Go API/Worker + Storage 物化 GLB Artifact。

## 32. G8 ComponentVersion Studio mesh preview 迁移记录

日期：2026-08-15
阶段：G8 / Component Repo Part preview & Component preview
状态：In progress

完成内容：

- [x] Go `component.preview.materialize` 生成器从 structural cube 升级为 Studio/LDraw mesh-based
  ComponentVersion 整体 GLB。
- [x] Preview Worker 只使用 ComponentVersion 固定的 `part_library_version_id`，并从
  `component_repo.part_geometries.source_relative_path` 找到对应 Studio/LDraw source file；
  不读取当前 active Part Library 来重解释旧版本。
- [x] Component preview input hash 改为绑定冻结输入：
  `componentVersionId + sceneSnapshotId + structureHash + geometryHash + partLibraryVersionId +
  partLibrarySourceHash + generatorVersion`。
- [x] generator version 升级为 `component-preview-studio-ldraw-glb-v1`；旧 generator 的
  ready/failed preview 会通过 API 暴露为 `stale` 并触发重新物化。
- [x] Worker 不再提供 structural fallback；缺少 `LDRAW_ROOT` 时不注册 Component/Part preview
  materialize handler，避免悄悄生成假几何。
- [x] GLB artifact metadata 记录 `partLibraryVersionId` 与 `partLibrarySourceHash`，方便审计来源。
- [x] 记录策略：Component list / detail 的主要 preview artifact 是整体 Component GLB；
  批量 materialize 每个 Part 的 GLB 作为后续缓存/性能 TODO，不混入本次链路。
- [x] 同步更新任务协议、Studio Part Library roadmap 和跟进指南。

验证结果：

```text
GOCACHE=/tmp/ctbzbricks-go-cache go tool sqlc generate       PASS
GOCACHE=/tmp/ctbzbricks-go-cache go test ./internal/workbench ./cmd/worker PASS
GOCACHE=/tmp/ctbzbricks-go-cache go test ./...               PASS
real Supabase smoke fixture                                   PASS（versionId=b48a8fc1-b6c6-45b7-877d-a30f39e7a96f；partLibraryVersionId=c8176a73-eccb-4db3-ba72-30edf5f9fd23；part=3001.dat）
Go API POST /api/v1/component-versions/:id/preview/materialize PASS（202；taskId=27515e65-a043-4e83-a8bf-dca92d18d540）
Go Worker component.preview.materialize                        PASS（task succeeded；attempts=1；artifactId=2ea5a928-3f0d-5e86-9785-a951b4615352）
real Supabase Storage server-side GLB read                     PASS（34,500 bytes；MIME=model/gltf-binary；magic=glTF；sha256 matches DB）
real GLB JSON chunk                                            PASS（generator=component-preview-studio-ldraw-glb-v1；meshCount=1；nodeCount=2；materialCount=1；bufferByteLength=33,600）
Go API GET /api/v1/component-versions/:id/preview signed URL   BLOCKED（503 component_repo.storage_unavailable with local HS256 smoke JWT）
Alembic storage policy upgrade                                 PASS（20260803_0021 -> 20260809_0022 -> 20260816_0023）
real Supabase storage policy check                             PASS（authenticated DELETE policy removed；component preview managed select retained）
real Supabase preview helper check                             PASS（can_read_component_preview_artifact(smoke artifact storage_key)=true for owner UUID）
```

i18n 影响为无：本次只修改内部任务机器字段、generator version、GLB artifact 生成逻辑、sqlc
查询和开发文档；没有新增 UI 文案、翻译资源、官方 Part 翻译、locale/timezone 选择逻辑或
resource catalog/release notes。

遗留：

- 真实 Supabase ComponentVersion 整体 GLB 物化链路已经通过：Go API 创建任务、Go Worker 使用
  Studio/LDraw mesh 写入 Supabase Storage、server-side 读取 artifact 与 hash/GLB 结构校验均成功。
- 用户侧 signed URL 仍未闭环：本次使用 Go API 本地 HS256 smoke JWT 可以通过 API auth，但
  Supabase Storage RLS 对该 token 返回不可用，API 映射为 `component_repo.storage_unavailable`。
- Alembic-owned Storage policy 已修正：`20260816_0023` 保留 legacy `public` preview 读取语义，
  并让 `public.can_read_component_preview_artifact(text)` 同时识别 Go `component_repo` 的
  derived/verified preview artifact。SQL 层 helper 已验证 smoke owner 可读。
- 剩余未闭环点是 token 来源：本地 HS256 smoke JWT 不是 Supabase Auth token，直接调用
  Supabase Storage sign endpoint 返回 `signature verification failed`。后续需要使用真实
  Supabase 登录 access token 重跑 API GET。
- Part GLB 全库预生成已在本文件第 61 节闭环；单 Part preview API 继续承担显式补建，维护脚本承担
  Part Library 更新后的可恢复批量回填。
- 颜色表目前为基础 LDraw color code 映射；如需 Studio/BrickLink/LEGO 颜色精确一致，后续应接入
  版本化颜色表。

下一步：

- 使用真实 Supabase 登录 access token 重跑 `GET /api/v1/component-versions/:id/preview`，
  验证 API 返回 signed URL 并可由浏览器下载 GLB。若真实 token 仍失败，再继续查 Storage
  policy 或 JWT audience/issuer 配置。
- 之后进入 external IDs S3，补充 BrickLink / LEGO design / LEGO element 映射。

## 33. G8 Component 列表 version 可见性 hardening

日期：2026-08-17
阶段：G8 / Component Repo 前端切换与 Go API 行为收敛
状态：Completed for list visibility hardening

完成内容：

- [x] `GET /api/v1/components` 的 Go 查询不再返回没有任何未删除 `component_versions` 的空壳
  Component。
- [x] 可见 version 判定与现有 version API 权限一致：owner 可看到自己未删除版本；非 owner 只通过
  `active` Component 下的非 `draft` 版本获得列表可见性。
- [x] Component group 的 root/custom 成员列表、搜索结果和状态计数同步采用同一 version-exists
  条件，避免列表项、分组计数和筛选统计不一致。
- [x] 更新 sqlc 生成代码，并补充 PostgreSQL integration contract：刚创建但没有 version 的
  Component 不出现在 owner 的列表中；分页 fixture 改为显式包含 published version。

验证结果：

```text
GOCACHE=/private/tmp/ctbzbricks-go-cache go tool sqlc generate PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./internal/component ./internal/httpapi ./internal/workbench PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache ./scripts/test-postgres.sh PASS（沙箱外；隔离 PostgreSQL Goose v1->v9、startup contract、integration tests）
git diff --check PASS
```

i18n 影响为无资源变更：本次改变 Component 列表返回集合，不新增 UI 文案、错误 code、任务消息、
翻译资源、locale/timezone 逻辑、catalog version、content hash 或 release notes。Component
status、version ID 和 JSON 字段继续作为机器值不翻译。

遗留：真实 Supabase 中已有空壳 Component 不会再出现在 Go 列表接口，但本次不删除或回填真实数据；
如需释放容量，应另行执行经确认的数据清理脚本。

## 34. G8 Component 整体删除语义与前端入口

日期：2026-08-17
阶段：G8 / Component Repo 前端切换与生命周期语义
状态：Completed for component delete affordance

完成内容：

- [x] 明确 Component 整体删除采用 GitHub repository 类似语义：owner 可以删除已发布后的
  user Component；该操作是整个 Component 软删除，不等同于删除某个 published/current
  ComponentVersion。
- [x] 保持后端 `DELETE /api/v1/components/:componentId` 的 owner-only、`content_kind='user'`
  和 `deleted_at` 软删除边界；删除后 Component 详情、列表、分组入口和非 owner 公开读取均不可见。
- [x] 保持 `DELETE /api/v1/component-versions/:versionId` 的草稿版本删除语义，current/published
  version 不通过版本删除入口单独删除。
- [x] 前端 Component 详情页新增 owner 可见的“删除组件”入口、确认弹窗和删除后回组件仓库列表流程；
  API adapter 新增 `deleteComponent()`，调用整体 Component resource endpoint。
- [x] 补充前端 adapter 测试，确认整体删除调用 `/api/v1/components/:componentId`，避免与
  ComponentVersion 删除 endpoint 混淆。
- [x] 补充 PostgreSQL integration contract，确认 owner 可删除 published Component，删除后 owner
  与非 owner 读取均返回 `component_repo.component_not_found`。

验证结果：

```text
frontend npm run i18n:check                                  PASS（2 locales / 10 namespaces；catalog frontend-2026.08.17.1）
frontend componentRepoApi focused test                       PASS（9 tests）
frontend npm test                                            PASS（13 files / 59 tests）
frontend npm run build                                       PASS（仅既有 Vite deprecation/chunk-size warnings）
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./internal/component ./internal/httpapi PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache ./scripts/test-postgres.sh PASS（沙箱外；隔离 PostgreSQL Goose v1->v9、startup contract、integration tests）
git diff --check                                             PASS
python -m pytest                                             NOT RUN（当前 shell 无 python 命令）
python3 -m pytest                                            NOT RUN（系统 Python 缺少 pytest 模块）
bundled python3 -m pytest                                    NOT RUN（Codex bundled Python 缺少 pytest 模块）
```

i18n 影响：新增 Component 详情页整体删除按钮、确认标题、确认说明、保留 artifact 警告和删除中状态文案；
生产语言 `zh-CN`、`en-US` 已同步，`catalogVersion` 升级为 `frontend-2026.08.17.1`，
`contentHash=93479d839918ae1af7dc517030383981ad8ff5a7d50312f60f2a338761fae8b9`，并更新
`I18N_RELEASE_NOTES.md`。Component ID、Version ID、删除审计字段、Storage key 和用户组件名称仍为
机器数据或用户内容，不翻译。

遗留：本次不做物理删除 Storage artifact、不清理历史 deleted Component 关联行；如需释放对象存储容量，
需要单独设计可审计的 retention/GC 策略。

## 35. G8 Component 删除简化与强删除 TODO

日期：2026-08-21
阶段：G8 / Component Repo 生命周期与数据清理
状态：Completed for simplification；真实库无需执行 v10

完成内容：

- [x] 经设计复盘，确认当前直接目标是“owner 删除 Component 后普通列表、详情、分组、公开访问不可见”，
  不要求“所有信息立即清除”。
- [x] 保留既有 `DELETE /api/v1/components/:componentId` soft delete 语义：
  `components.status='archived'`、`deleted_at/deleted_by` 写入审计字段；不删除版本、导入、快照、候选、
  artifact、task 或 Storage object。
- [x] 移除未执行到真实库的 Goose v10 `00010_component_purge.sql`、`component_repo.redact_owned_component`
  函数、`component_purge.sql`、sqlc generated purge query、Go `component.purge` Worker handler、
  task type、API 路由和 Service 方法；Goose head 回到真实开发库当前 v9。
- [x] 前端移除独立“永久删除”入口、确认弹窗、purge adapter、`componentPurge` 配置和相关测试；
  Component 详情页只保留“删除组件”soft delete 入口。
- [x] 从任务协议删除 `component.purge`，避免后续开发者误以为当前系统支持强删除任务。
- [x] 将 [Component 删除、脱敏与 GC TODO](./component_deletion_retention_gc.md) 降级为 future TODO，
  明确当前实现不得引入 `component.purge` API/Worker/Goose migration；强删除、脱敏、Storage 清理和
  FK-safe GC 后续按宽度优先单独评估。

验证结果：

```text
backend-go:
- gofmt -w internal/component/service.go internal/component/handler.go internal/component/service_integration_test.go internal/component/types.go internal/task/types.go cmd/worker/main.go
- GOCACHE=/private/tmp/ctbzbricks-go-cache go tool sqlc generate
- GOCACHE=/private/tmp/ctbzbricks-go-cache go tool sqlc vet
- GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./db/migrations ./internal/component ./cmd/worker
- GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./...
- GOCACHE=/private/tmp/ctbzbricks-go-cache ./scripts/test-postgres.sh
  - Goose migrated only 00001..00009 and reported version 9
  - isolated PostgreSQL migration and startup contract: PASS

frontend:
- npm run i18n:check
- npm test
- npm run build

repo:
- git diff --check
- runtime grep confirmed no remaining component.purge / purgeComponent / component_purge references
  outside docs and historical release notes.

legacy Python backend:
- python -m pytest NOT RUN（当前 shell 无 python 命令）
- python3 -m pytest NOT RUN（系统 Python 缺少 pytest 模块）
- .venv/bin/python -m pytest NOT RUN（仓库 .venv 缺少 pytest 模块）
```

i18n 影响：移除未采用的永久删除 UI 文案和 purge 错误资源；普通“删除组件”文案继续保留。
资源版本更新为 `frontend-2026.08.21.1`，
`contentHash=93479d839918ae1af7dc517030383981ad8ff5a7d50312f60f2a338761fae8b9`。
Component 名称继续作为用户内容原样展示/插值；Component ID、删除审计字段、Storage key、状态和
JSON key 仍为机器数据，不翻译。

遗留：

- 当前删除不释放数据库行空间或对象存储容量，也不脱敏历史 task/import/artifact metadata。
- 如果后续确实需要强删除/隐私擦除/容量回收，再从 TODO 文档中按独立切片实现 redaction、Storage cleanup
  或 admin-only GC；不要把这些能力混入当前 soft delete 主线。

## 36. G8 upload complete 422 诊断日志

日期：2026-08-22
阶段：G8 / 真实浏览器与 Supabase Storage 验收
状态：In progress；诊断增强已完成

背景：

- 真实浏览器上传 Component 时，`POST /api/v1/component-imports/upload-sessions/:sessionId/complete`
  返回 `422 component_repo.upload_session_complete_failed`。
- 真实 `storage.objects` policy 已确认包含 owner-scoped authenticated INSERT/SELECT，以及 preview
  managed SELECT；缺少 upload SELECT policy 已被排除。
- 失败 session 对应的 Storage object 事后查不到，但 Go complete 失败路径会执行
  `failAndCompensate` 并尝试删除 object，因此事后对象缺失不能区分“前端未上传”和“complete 校验失败后被补偿删除”。

完成内容：

- [x] 在 `artifact.Service.CompleteUploadSession` 的 preflight 分支加入内部 warning 日志：
  - `no_files`
  - `storage_provider_bucket_mismatch`
  - `storage_object_not_found`
  - `storage_head_unavailable`
  - `storage_metadata_mismatch`
- [x] 日志只包含机器诊断字段：`uploadSessionId`、`ordinal`、`artifactId`、`artifactType`、
  provider/bucket、expected/actual size、expected/actual content type 和错误对象；不改变公共 API
  响应，不向前端暴露 Storage key、SQL、路径或 provider 原始响应正文。
- [x] API router 将同一个结构化 logger 注入 artifact service，便于与请求日志按时间和 session 关联。

验证结果：

```text
gofmt -w internal/artifact/service.go internal/httpapi/router.go
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./internal/artifact ./internal/httpapi ./cmd/api PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./... PASS
```

i18n 影响：无。仅新增内部日志，不新增/修改用户可见文案、API error code、任务进度或资源 catalog。

下一步：

- 重启 Go API 后重新上传一次 Component。
- 在后端日志中查找 `Component upload completion failed preflight`，用 `reason` 判断下一步：
  - `storage_object_not_found`：浏览器 upload 没有留下对象，或 Go 使用的 JWT/路径读不到对象；
  - `storage_head_unavailable`：Supabase Storage info 请求或凭据配置异常；
  - `storage_metadata_mismatch`：查看 size / MIME 差异，决定是前端 upload content type 还是 Go 校验规则需要调整。

## 37. G8 Studio .io MIME mismatch 修复

日期：2026-08-22
阶段：G8 / 真实浏览器与 Supabase Storage 验收
状态：Completed for MIME fix；需重启 Go API 后重试真实上传

背景：

- 诊断日志确认真实上传失败根因为 `storage_metadata_mismatch`：
  - `artifactType=studio_io`
  - `expectedSize=275136`
  - `actualSize=275136`
  - `expectedContentType=application/octet-stream`
  - `actualContentType=application/x-studioformat`
- 因 size 一致且 Storage policy 已确认存在 owner-scoped authenticated INSERT/SELECT，本次不是 RLS 缺失或对象丢失问题，而是 Go 对 Studio `.io` 的 MIME 校验过窄。

完成内容：

- [x] 将 `studio_io` 的首选 MIME 从 `application/octet-stream` 调整为
  `application/x-studioformat`；前端 upload session 返回的 `.io` `contentType` 也随之使用该值。
- [x] `studio_io` 校验同时接受 `application/x-studioformat` 与 `application/octet-stream`，避免不同浏览器或 Supabase 元数据行为导致同类误拒。
- [x] `ldraw_ldr` / `ldraw_mpd` 继续保持 `text/plain`，不放宽为任意 binary。
- [x] mismatch 诊断日志从单个 `expectedContentType` 改为 `expectedContentTypes`，便于后续排查 MIME 别名。
- [x] 新增单元测试覆盖 Studio MIME 首选值、Supabase Studio MIME、octet-stream 兼容、参数化 MIME，以及 LDraw MIME 边界。

验证结果：

```text
gofmt -w internal/artifact/service.go internal/artifact/service_test.go
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./internal/artifact ./internal/httpapi ./cmd/api PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./... PASS
```

i18n 影响：无。只调整内部 MIME 校验和 upload session 机器字段；不新增/修改用户可见文案、API error code、任务进度或资源 catalog。

下一步：

- 重启 Go API。
- 重新上传 Studio `.io` Component；不要复用已 failed 的 upload session。
- 若 complete 通过但后续任务停住，再查看 `component.artifact.verify` / `component.import.parse` task 状态与 Worker 日志。

## 38. 更新模板

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

## 39. G6/G8 `component.import.parse` 迁移到 Go Worker

日期：2026-08-22
阶段：G6 import parse 执行者迁移 / G8 真实上传 smoke 前置修复
状态：Completed for import parse migration；`component.relations.detect` 仍保留为 Python 算法 Worker

背景：

- 真实浏览器上传 `.io` 后，Go API 已能完成 upload session 并创建 durable tasks，但前端继续轮询
  `/api/v1/tasks/:taskId`，根因是 `component.import.parse` 仍需要单独启动 Python Worker。
- 目标是只保留一个常驻 Go Worker 处理上传后的验证、解析、validation、preview 等 Go 已迁移任务；
  不在本次迁移关系检测算法。

完成内容：

- [x] 新增 Go LDraw/Studio import parser：
  - 支持 Studio `.io` zip 中的 `model.ldr` 抽取；
  - 支持 `.ldr` / `.mpd` type 1 reference、`0 FILE` / `0 NOFILE` / `0 Name:`；
  - 产出 SceneSnapshot document、BOM、parse issues、summary、interface/structure/geometry hash；
  - 对 invalid payload、unsupported artifact、缺失 `model.ldr`、invalid UTF-8 等返回稳定 parse failure。
- [x] 新增 deterministic UUIDv5 helper，沿用 Python Go-owned worker 的 namespace，使
  snapshot/candidate/component/draft-version/studio-exchange ID 对同一 import 可重试、幂等。
- [x] 新增 `component.import.parse` Go handler：
  - 读取 verified immutable artifact；
  - 校验 object sha256；
  - Studio `.io` 派生 verified `ldraw_ldr` artifact，并设置 `derived_from_artifact_id`；
  - 在同一 PostgreSQL transaction 中写入 Import succeeded、SceneSnapshot、Candidate、
    Draft ComponentVersion；
  - handler 成功返回后，由共享 Go task runner 完成 task succeeded，满足
    `sync_import_parse_task_state` trigger 对 import/task 顺序的约束。
- [x] `cmd/worker` 注册 `component.import.parse`，因此开发期上传链路不再要求启动
  `python -m src.tools.run_component_import_worker`。
- [x] 更新 `backend-go/README.md`、`docs/go_task_protocol.md`、
  `docs/go_component_migration_plan.md`，将 parse 执行者从 Python Worker 改为 Go Worker。

验证结果：

```text
GOCACHE=/private/tmp/ctbzbricks-go-cache go tool sqlc generate PASS
gofmt -w internal/uuidutil/uuid5.go internal/ingestion/import_parser.go \
  internal/ingestion/import_parser_test.go internal/ingestion/parse_task.go \
  internal/artifact/service_integration_test.go cmd/worker/main.go PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./internal/ingestion ./internal/artifact ./cmd/worker PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./... PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go tool sqlc vet PASS
./scripts/test-postgres.sh PASS
  - Goose migrated component_repo to version 9
  - Go integration packages PASS
  - backend/tests/test_go_component_import_worker.py: 9 passed
  - isolated PostgreSQL migration and startup contract: PASS
```

i18n 影响：无。只迁移后台 worker 执行者与机器数据写入；不新增/修改用户可见文案、API error code、
任务进度文案或资源 catalog。任务 payload/result、error code、JSON key、artifact type 和 hash
继续作为机器字段，不翻译。

遗留：

- `component.relations.detect` 仍为 Python 算法 Worker；本记录当时尚未决定是否迁移，后续
  2026-08-22 Go-only 决策已将其纳入 G8 必须迁移项。
- 旧 Python import worker 源码暂未删除，可作为短期对照与回退参考；不要在开发流程中继续要求它常驻。
- `scripts/start-dev.sh` 仍只启动 Go API + frontend；真实上传 smoke 需要另开一个
  `cd backend-go && go run ./cmd/worker`。

下一步：

- 重启 Go API 与 Go Worker 后，重新上传一个 Studio `.io` Component；
- 观察 `component.artifact.verify` 与 `component.import.parse` task 应依次进入 `succeeded`，
  前端不应继续卡在“组件处理中”。

## 40. G6/G8 Python import Worker 清理

日期：2026-08-22
阶段：G6 import parse 收尾 / G8 mixed topology 清理
状态：Completed

背景：

- `component.import.parse` 已迁移到 Go Worker 后，继续保留 Python import worker adapter、
  import worker launcher 和专项 pytest 会制造两套执行路径，容易让开发环境再次启动错误 worker。
- `component.relations.detect` 仍是 Python 算法 Worker，因此不能直接删除所有 Python task
  adapter 代码；需要先把关系 Worker 复用的通用 claim/lease/event helper 从 import worker 中拆出。

完成内容：

- [x] 新增 Python 共享 `GoTaskWorker` 基类，仅服务尚未迁移的 Python 算法 Worker。
- [x] `go_relation_worker.py` 改为继承共享 `GoTaskWorker`，不再依赖 import worker。
- [x] 删除旧 Python import worker adapter 与启动入口：
  - `backend/src/component_repo/go_import_worker.py`
  - `backend/src/component_repo/go_import_parser.py`
  - `backend/src/tools/run_component_import_worker.py`
  - `backend/tests/test_go_component_import_worker.py`
  - `scripts/start-component-import-worker.sh`
  - `scripts/start-component-import-worker.ps1`
- [x] `scripts/start-dev.sh` / `scripts/start-dev.ps1` 不再启动 Python Import Worker；
  Go Worker 负责 `component.import.parse`。
- [x] 开发拓扑默认只启动一个 Go Worker；Python Relation Worker 改为显式 opt-in，
  仅在设置 `START_PYTHON_RELATION_WORKER=1` 时启动 `component.relations.detect`。
- [x] `backend-go/scripts/test-postgres.sh` 不再运行已删除的 Python import worker pytest；
  Go ingestion/artifact integration tests 覆盖 import parse path。
- [x] `backend-go/README.md` 和当前进度摘要同步为 Go import parse / Python relation-only topology。

验证结果：

```text
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./internal/ingestion ./internal/artifact ./cmd/worker PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go test ./... PASS
GOCACHE=/private/tmp/ctbzbricks-go-cache go tool sqlc vet PASS
./scripts/test-postgres.sh PASS
  - Goose migrated component_repo to version 9
  - Go integration packages PASS
  - isolated PostgreSQL migration and startup contract: PASS
```

i18n 影响：无。清理对象是后台 worker 源码、开发启动脚本和工程文档；不新增/修改 UI 文案、
API error code、任务进度文案、资源 catalog 或用户内容处理规则。

遗留：

- Python 代码中仍保留 `component.relations.detect` 算法 Worker，但默认开发拓扑不启动；
  当时是否继续迁移仍待决策；2026-08-22 已确定必须迁移到 Go，见下一节。
- 旧 FastAPI Component Repo 公共 router 删除仍属于 G8 后续切片；本次只清理 import worker。

下一步：

- 使用 `scripts/start-dev.sh` 或单独 `cd backend-go && go run ./cmd/worker` 重新做真实上传 smoke；
  默认不应再出现任何 Python Worker 进程。

## 41. Component Repo Go-only 目标固化

日期：2026-08-22
阶段：G8 / 架构治理与 Python 退出边界
状态：Decision completed；运行时迁移仍 In progress

已确认决策：

- [x] Go-only 先约束 Component Repo，不宣称整个 BrickBuilder 后端已经 Go-only。
- [x] Component Repo 的公共 API、事务编排、持久任务、解析、关系检测、校验、预览和
  Part Library 工具链目标执行者均为 Go。
- [x] `component.relations.detect` 是唯一已知 Python 过渡实现，不是长期例外；不得新增
  Component Repo Python task type、公共 API、持久化模型或扩大过渡 payload/result。
- [x] G8 完成门槛增加关系检测 Go handler、Python relation worker/adapter/launcher 删除，
  并要求不启动 Python 也能完成上传到发布/预览的完整业务链路。
- [x] 语言无关任务协议继续保留，用于持久化契约、迁移对照和可替换性，不作为 Python
  长期运行时授权。

文档同步：

- [x] 仓库级 `AGENTS.md`、`backend-go/README.md`、长期原则、阶段计划、任务协议、G8
  切换清单和跟进指南统一为 Component Repo Go-only。
- [x] Studio Part Library 后续 importer/worker 新能力默认使用 Go。
- [x] schema baseline 未修改：其数据库 authority 与语言无关边界没有发生变化。

验证结果：

```text
documentation consistency grep  PASS
git diff --check                PASS
runtime tests                   NOT RUN（仅文档治理变更）
```

i18n 影响：无。仅修改工程与迁移文档；不修改 UI 文案、API error code、任务 code、locale/timezone、
资源 catalog、用户内容或官方翻译选择规则。

下一步：

- 为 `component.relations.detect` 固定 Python 现状的 golden fixtures、input hash 和 PostgreSQL
  写入不变量，恢复被清理掉的 relation worker PostgreSQL E2E 覆盖；
- 实现 Go relation handler 并做等价/差异验收，通过后删除 Python relation worker、共享 adapter
  和启动入口；
- 完成真实浏览器/RLS 验收并删除 FastAPI Component Repo 公共 router，G8 才可标记 Completed。

## 42. Component Repo Go API 契约文档

日期：2026-08-22
阶段：G8 / API 文档收口
状态：Completed for current route inventory

完成内容：

- [x] 新增 [Component Repo Go API](./api.md)，覆盖当前 2 条健康检查和 48 条认证
  `/api/v1` 路由。
- [x] 对每条接口记录职责、主要输入/输出、owner/可见性边界，以及 HTTP 内短事务或 durable task
  的执行逻辑。
- [x] 记录上传 `verify -> parse` dependency、关系检测、发布校验、Component/Part Preview
  materialize、任务取消和短期 Storage URL 流程。
- [x] 明确旧 FastAPI、同步 multipart、Candidate Preview、GET 隐式 materialize、hard purge 和
  `library-items` alias 不属于 Go API。
- [x] API 文档已随 S5 更新：`component.relations.detect` 当前由 Go Worker 执行，不存在长期或
  过渡 Python task 边界。
- [x] 将 `docs/api.md` 加入仓库级 Go migration preflight；后续路由、DTO、授权或执行流程变化必须
  同步更新 API 文档。
- [x] 为仓库 `docs/*` ignore 规则增加精确的 `!docs/api.md` 例外，确保该契约可进入版本控制。

验证结果：

```text
registered route coverage check  PASS（50/50）
git diff --check                 PASS
runtime tests                    NOT RUN（仅文档变更）
```

i18n 影响：无。新增的是工程 API 文档，不修改 UI 文案、公共 error/task code、资源 catalog、
locale/timezone 处理、用户内容或官方翻译规则。

## 43. G8 / Studio Part Library S5 connectivity 与 Go relation Worker

日期：2026-08-22
阶段：G8 / Studio Part Library S5
状态：Completed for code and isolated validation；真实数据库迁移/导入未执行

完成内容：

- [x] 新增 Goose v10 `00010_part_library_connectivity.sql`：
  - `part_library_versions.preview_ready/relation_ready`；
  - connector/collider count、source hash、parser version；
  - 版本化、RLS-enabled 的 `part_collider_definitions`。
- [x] 新增 Go Studio connectivity/collider parser：
  - `.conn` 支持已观测的 Axle、Ball、Hole、Stud、Fixed、Hinge、Rail、Slider record；
  - Stud/Hole matrix 展开为可检测 connector definitions；
  - `.col` 支持 type `9/8192` box，signed half-extents 规范化并保留原值；
  - parser 与 importer 不依赖 Studio DLL；本机 DLL 只用于只读格式对照。
- [x] `studio-import` 升级为 v2：校验 sidecar hash/size，确定性生成 source ID/hash，使用
  staging + `CopyFrom` + pgx transaction 写 connector/collider，并显式计算两类 readiness。
- [x] `component.relations.detect` 迁移到 Go Worker：
  - 只接受 Candidate 冻结且 `relation_ready=true` 的 Part Library；
  - input hash 覆盖 Part Library ID/source hash 与 connector source hash/parser version；
  - 从版本化 connector definitions 识别既有三类兼容关系；
  - 原子物化 RelationCandidate、ConnectorAnalysis、external Interface 与 Candidate/Draft
    interface signature；不修改 SceneSnapshot transform。
- [x] 删除旧 Python relation worker、共享 adapter、命令入口与 Bash/PowerShell launcher；开发拓扑
  只由 Go Worker 消费 Component Repo task。
- [x] 更新 schema baseline、迁移原则/计划、task protocol、API 契约、G8 inventory、跟进指南、
  Studio roadmap 与 Go README。

完整 Studio dry-run（未连接数据库）：

```text
manifest sha256          524fee2594a1e8023965e718b398b90d7bc8a10adc864dbbd84e64c77bc50e2b
parts                    24,426
geometry ready           24,373
geometry failed              53（缺失 LDraw reference）
connector files           8,881
connector definitions   190,419
connector failures            0
connector source hash   0aab7080e5d1ba2f365037e22f09ee26518f507f7e4b70be394765221d2be7ac
collider files            10,295
collider definitions   1,876,415
collider failures             0
collider source hash    1266cefe0db7cd1db7cca8b94e480bba106bb1e4e03845724a1fa070f821e5b6
preview_ready              true
relation_ready             true
```

验证结果：

```text
GOCACHE=/private/tmp/ctbz-go-cache go test ./...  PASS
backend-go/scripts/test-postgres.sh                PASS
  - Goose up/down/up through v10                   PASS
  - schema/API/task/worker/ingestion/workbench     PASS
  - Go relation E2E: 3 connectors / 1 relation /
    3 external interfaces + task terminal state    PASS
full Studio importer --dry-run                     PASS（约 35 s）
bash -n scripts/start-dev.sh scripts/dev-env.sh    PASS
```

i18n 影响：无。改动只涉及机器 ID、hash、parser/detector version、数据库能力字段和内部 task
执行者；未新增用户可见文案、公共错误/进度 code、locale-sensitive 数据、资源 catalog 或翻译。

已知边界与下一步：

- 本次没有连接或修改真实数据库。真实执行前必须确认准确 `DATABASE_URL`，显式执行 Goose v10，
  再用同一 manifest 运行 Studio importer v2；API/Worker startup 不代做迁移或回填。
- S5 完成 collider 数据接入和 availability 标记，不包含精确 clearance/raycast 求解；不能把
  `eligibility_clearance_data_available=true` 解释为已做精确碰撞验证。
- G8 仍为 In progress：剩余门槛是真实 Supabase/browser/RLS 验收和旧 FastAPI Component Repo
  公共 router 删除，不再包含 Python task Worker 迁移。

## 44. S5 真实 Supabase 导入与 connector 容量压缩

日期：2026-08-22
阶段：G8 / Studio Part Library S5 真实环境收口
状态：Completed

执行事实：

- [x] 在已确认的 Supabase EU West `postgres` 数据库执行 Goose v10/v11。
- [x] 第一次逐行 collider 导入在事务内因 WAL 磁盘空间不足失败；PostgreSQL 自动回滚完整 importer
  事务，核对确认没有半量 connector/collider 数据，数据库恢复后继续服务。
- [x] 根据既定“PostgreSQL metadata / object storage large artifacts”边界，将 collider 默认改为
  `metadata-only`：解析验证 10,295 个文件、1,876,415 条定义并保存 count/hash/parser/storage mode，
  不在小容量 Supabase 展开 187 万数据库行。
- [x] connector 正式导入 8,881 个文件、190,419 条定义，parse failure 为 0；active library 恢复
  `preview_ready=true/relation_ready=true`。
- [x] Goose v11 删除 Go relation query 未使用的 type/gender 全局索引。
- [x] 经用户明确授权执行 connector 压缩维护：确认 active definitions 无 ConnectorAnalysis 引用，
  临时关闭 relation readiness，删除可重建 active definitions，`VACUUM FULL`，再以去除重复 library
  path/hash/parser JSON 的格式重导。retired library 29,853 条定义及其 464 条历史分析引用保留。
- [x] 保留 `backend-go/scripts/update-studio-part-library.sh`；脚本要求精确数据库确认、默认完整
  dry-run、默认 metadata-only collider，并对相同 active/ready manifest 默认 no-op。

真实库最终证据：

```text
Goose version                         11
database size before cleanup          546 MB
after unused index removal            528 MB
after active delete + VACUUM FULL     291 MB
after compressed connector rebuild    408 MB
connector table before                276 MB（初始）/ 258 MB（drop index 后）
connector table after                 138 MB（heap 110 MB / indexes 28 MB）
active connector rows                 190,419
retired connector rows                 29,853
active raw_params average                 180 bytes（原 404）
connector source hash                 0aab7080e5d1ba2f365037e22f09ee26518f507f7e4b70be394765221d2be7ac
collider source count                 1,876,415（metadata-only；stored rows 0）
collider source hash                  1266cefe0db7cd1db7cca8b94e480bba106bb1e4e03845724a1fa070f821e5b6
preview_ready / relation_ready        true / true
```

验证：

```text
isolated PostgreSQL migration/startup contracts through v10 PASS
Go partlibrary/parser unit tests                         PASS
real DB FK/reference guards                              PASS
real DB post-import count/hash/readiness/size audit       PASS
git diff --check                                         PASS
```

i18n 影响：无。此次只修改数据库机器数据、索引、hash/count/parser/storage mode 与开发运维脚本；
没有修改用户可见文案、公共错误/任务 code、locale/timezone、资源 catalog 或翻译。

后续边界：

- 新 Studio snapshot 会产生新的不可变 library；保留旧 snapshot connector 会增加数据库容量。下一次
  大版本更新前应评估 Supabase 容量，或把 connector/collider snapshot 进一步改为对象存储 bundle +
  按 Part 加载，不能依赖反复 `VACUUM FULL` 作为长期数据模型。
- 精确 clearance/raycast 需要可按 Part 读取的 collider bundle 与空间查询算法；本次 metadata-only
  只证明输入可解析，不提供精确碰撞结论。

## 45. 上传、BOM 与 Component GLB 主链问题盘点

日期：2026-08-23
阶段：G8 / 上传后核心产物收敛
状态：主链 continuation、ready 门禁和默认结果页已完成；GLB 质量问题继续开放

本次确认的产品目标：组件管理上传一个 Studio `.io` 后，Go-only 后台应持续完成真实零件清单
和 ComponentVersion 整体 GLB；relation/connector/interface、发布校验、发布及精确碰撞不属于
默认上传完成条件。

代码审查事实：

- [x] `UPLOAD-GLB-01`（P0，Resolved 2026-08-23）：parser v2 的 BOM 与 summary 已改为按
  Scene 顶层入口实例递归展开；重复/嵌套模型按实例倍增，未使用定义不计入。
- [x] `UPLOAD-GLB-02`（P0，Resolved 2026-08-23）：Parse Worker 在业务事务中创建首个 Preview
  Logical Job/Execution、写入 Version preview task，并建立 `Preview -> Parse` dependency；前端不再
  触发首次 `POST .../preview/materialize`。
- [x] `UPLOAD-GLB-03`（P1，Resolved 2026-08-23）：Candidate ready 页默认读取并独立展示 Version
  BOM 与整体 GLB；relation/connector/interface 只有用户开启连接信息开关后才读取。
- [x] `UPLOAD-GLB-04`（P1，Resolved 2026-08-23）：冻结 Part Library 缺少 ready geometry 时允许
  partial GLB；BOM 对每个 Part 返回 `ready/failed/missing`，Worker 结果和 Artifact metadata 记录
  `omittedPartRefs` 与 `complete`。ready source 的路径/哈希/解析故障仍严格失败。
- [x] `UPLOAD-GLB-05`（P1，Resolved 2026-08-23）：importer、validation、relation 和 preview
  已统一使用 `backend-go/internal/scene` 的纯 Go world-part expansion。
- [ ] `UPLOAD-GLB-06`（P2）：当前 GLB 的颜色、BFC/normal、多材质和 TEXMAP 支持有限，不能把
  普通 mesh 可见等同于 Studio 视觉完全一致。
- [ ] `UPLOAD-GLB-07`（P2）：当前整体 Component GLB 未压缩；旧 Python meshopt 仅作为行为/效果
  参考，后续压缩仍必须留在 Go-only Worker 边界，不恢复 Python runtime 依赖。
- [x] `UPLOAD-GLB-08`（P0，Resolved 2026-08-23）：SceneSnapshot document v2 已使用显式、有序
  `rootInstances[]`；多个入口分别展开并合并，普通 Studio/MPD 生成一个 identity root，未引用定义不
  自动推断为 root。数据库 `root_model_id` 保留为单主模型投影，展开权威输入为 document。

已确认不应为本目标移除的边界：Upload Session、原始 Artifact 不可变、SHA-256、SceneSnapshot、
冻结 Part Library、durable task、Component/Draft Version 和 version-addressed derived GLB。
Candidate/Relation/Validation 数据模型暂不删除，只从默认上传主链解除关系/发布步骤耦合。

详细影响、验收条件和解决顺序见[当前跟进指南第 7 节](./go_migration_followup_guide.md#7-2026-08-23-上传bom-与整体-glb-主链问题清单)。

验证：

```text
mandatory migration preflight PASS（principles / plan / api / progress 全文核对）
code path audit               PASS（frontend upload/preview/BOM；Go ingestion/workbench；legacy Python prewarm 仅作行为基线）
runtime tests                 NOT RUN（本次只记录问题，不修改运行时代码）
database/storage mutation     NOT RUN
```

i18n 影响：无。本次只增加内部工程问题记录，不修改 UI 文案、公共 API/task/error code、
locale/timezone、用户内容、官方 Part 翻译、资源 catalog、content hash 或 release notes。

后续更新：`UPLOAD-GLB-02/09/10` 已在第 47 节实现并收口，`UPLOAD-GLB-03` 已在第 48 节实现并
收口。缺件诊断与 partial preview 已在第 50 节完成（`UPLOAD-GLB-04`）。

## 46. BOM 与多 root Scene expansion 修复

日期：2026-08-23
阶段：G8 / 上传后核心产物收敛
状态：Completed for parser v2 and BOM contract

完成内容：

- [x] 新增共享纯 Go `internal/scene` 展开器，输入为 SceneSnapshot 的有序 `rootInstances[]` 和
  model definitions，输出带完整实例路径、规范化 Part 编号、颜色和 world transform 的叶子 Part。
- [x] 展开按实例计数，不使用全局 model visited 去重；cycle 只按当前递归路径检测，并限制深度及
  最大展开实例数量。
- [x] Go importer 的 BOM、`partInstanceCount`、`submodelInstanceCount` 与 geometry hash 投影改为
  使用共享展开结果；未被 root 使用的 model definition 不进入 BOM。
- [x] Validation、Go relation detection 和 Component GLB 删除各自递归实现，统一消费共享展开器。
- [x] parser 默认版本升级为 `component-repo-ldraw-parser-v2`，Snapshot schema 升级为
  `component-repo-v2`；普通 Studio/MPD 生成一个 identity root instance，显式多 root 文档分别展开。
- [x] Relation detector 与 Component Preview generator 因实例路径/展开算法变化分别升级为 v3/v2，
  避免旧 Logical Job 或派生缓存被错误复用。
- [x] `GET /api/v1/component-versions/:versionId/parts` DTO 不变，仍只读取冻结 BOM 并选择 reviewed
  Part translation；API 文档补充 `partCount`、`quantity` 和多 root 计数语义。

验证结果：

```text
focused scene/ingestion/workbench/config/artifact tests PASS
backend-go make check                                  PASS（go test ./... / go vet / sqlc vet）
isolated PostgreSQL                                    PASS（Goose v1 -> v11、integration、startup contract）
multi-root fixture                                     PASS（同模型两个 root = 两组 Part 实例）
nested multiplier fixture                              PASS（重复 child x nested = 4 个叶子实例）
unused model fixture                                   PASS（未使用定义不进入 BOM）
tracked Studio test.io                                 PASS（声明 210 bricks，BOM/summary 均为 210）
legacy rootModelId adapter                             PASS（只读展开兼容）
git diff --check                                       PASS
```

i18n 影响：无资源变更。BOM 编号、数量、实例 ID、root/model ID、parser/schema/generator version 和
JSON key 都是机器数据；官方 Part 名称仍由 BOM API 按请求 locale 只选择 reviewed translation，
缺失时返回 source fallback/missing。未修改资源 key、catalog version、content hash 或 release notes。

历史边界：SceneSnapshot 不可变，因此 parser v1 / snapshot v1 已有记录不会被本次代码静默更新；
旧开发版本若需要新 BOM 语义，应从原始 Artifact 重新导入生成 v2 Snapshot。本次没有连接、修改或
回填真实 Supabase 数据库。

## 47. 上传流程 API / Worker / Frontend 边界决策

日期：2026-08-23
阶段：G8 / 上传后核心产物收敛
状态：Implemented；保留 API 控制的浏览器直传与 Worker 持久异步链

已确认目标边界：

- 浏览器调用 Go API 创建 owner-scoped upload session；API 生成并持久化可信 bucket/objectPath，
  浏览器使用当前用户 JWT 只向该精确目标直传 Storage。客户端不能指定 key；Storage INSERT RLS
  复核 pending file/session、owner、expiry 和精确 key。
- upload complete 由 API 执行 Storage 完成确认、有界校验、短事务和持久任务编排；返回 `202`
  后本次前端写交互结束。`202` 不表示解析或预览已完成。
- Go Worker 持久推进 `artifact verify -> import parse/SceneSnapshot/BOM/Draft -> component preview
  materialize/verified GLB`。关闭、刷新或离开页面不得中断主链，也不得要求浏览器再发起首次 Preview
  materialize mutation。
- 面向页面的聚合机器状态为 `processing | ready | failed`。只有 BOM 已落库且 ComponentVersion
  整体 GLB 已生成、验证并可读取时才是 `ready`；parse task 单独 succeeded 仍不可预览。
- `processing` 时前端不挂载 Viewer、不请求签名 Preview URL、不展示旧或尚未验证的中间模型，只通过 typed
  semantic key 渲染处理状态。失败通过稳定 `code + params` 展示。
- relation detection、connector/interface、validation 和 publish 仍是可保留的后续工作台能力，
  但不属于普通上传主链的默认完成条件。

当前实现状态：

- [x] `UPLOAD-GLB-10`：确认保留 API 控制的浏览器直传；Alembic `20260823_0024` 将 INSERT policy
  收紧到 API 已登记的 pending、未过期、owner-scoped 精确 key。authenticated DELETE 仍由既有
  `20260809_0022` 禁止，补偿/清理由 Worker 服务端凭据执行。
- [x] `UPLOAD-GLB-02`：Parse Worker 在 SceneSnapshot/BOM/Candidate/Draft 同一事务中创建 Preview
  Logical Job/Execution 和 `Preview -> Parse` dependency；关闭浏览器不影响后继任务。
- [x] `UPLOAD-GLB-09`：Import API 返回 `processingStatus` 与 `previewTaskId`，ready 要求 BOM/Draft 和
  verified Preview Artifact；前端只读轮询聚合状态，ready 前不进入预览页，Preview loader 不再主动写入。
- [x] `UPLOAD-GLB-03`（Resolved 2026-08-23）：ready 后默认并发读取并独立展示 Version BOM 与整体
  GLB；relation/connector/interface 初始不请求，只有用户开启连接信息开关后才加载。

本次修订文档：

- `go_backend_migration_principles.md`：增加 Component 上传交互的不可变边界。
- `go_component_migration_plan.md`：修正 G6/G7/G8 的服务端 continuation 与前端 ready 验收。
- `api.md`：记录已实现上传主链与精确 Storage RLS，明确 Preview materialize 的重建/恢复定位。
- `go_task_protocol.md`：补充 parse -> Preview 的幂等、可恢复后继任务契约。
- `go_g8_frontend_cutover_inventory.md`：修正正常上传的前端状态门禁和网络请求验收。
- `go_migration_followup_guide.md`：登记 `UPLOAD-GLB-09/10` 并调整解决顺序。
- `I18N_FIELD_CLASSIFICATION.md`：明确处理状态为机器值，展示由 typed semantic key 完成。
- `component_repo_storage_and_preview_cache.md`：用后续修订替换浏览器直传的早期 ADR 数据流。

`go_component_schema_baseline.md` 与 `go_part_library_studio_roadmap.md` 本次不修改：聚合状态由现有
Import、Task、BOM、Version Preview 和 Artifact 状态投影，没有新增持久化列；Part Library 的冻结
版本、source hash 和几何输入边界也未改变。

验证：

```text
backend-go make check                    PASS（go test ./... / go vet / sqlc vet）
isolated PostgreSQL                     PASS（Goose v1 -> v11；Preview dependency/claim gate/Import projection）
frontend i18n check/test/build          PASS（13 files / 60 tests / production build）
Python backend pytest                   PASS（298 passed；含 Alembic head 与 Storage policy contract）
Storage policy migration unit test      PASS（pending owner/expiry/exact-key）
real Supabase Alembic                   PASS（0023 -> 0024）
real Storage policy introspection       PASS（helper 存在；INSERT policy 调用 exact-session helper）
```

i18n 影响：上传处理状态页面继续使用既有 typed semantic key；API/数据库状态保持机器值，任务/失败
保持 `code + params`。本次未新增生产文案或资源 key，因此 catalog version、content hash 和 release
notes 无需因本次实现再次变化。

## 48. Candidate 默认 GLB/BOM 与 Connector 按需加载

日期：2026-08-23
阶段：G8 / 上传 ready 结果页收口
状态：Implemented；`UPLOAD-GLB-03` Resolved

实现结果：

- [x] Candidate 页面初次加载时并发读取 Draft Version 的只读 Preview 与冻结 BOM，默认结果区直接
  展示整体 GLB 和零件清单。
- [x] Preview 与 BOM 分别维护 loading/ready/error 状态；任一读取失败不会隐藏另一项已经成功的结果。
- [x] 删除 Candidate 页进入时对 relation、connector 和 interface 的 eager GET；默认网络请求不再
  包含这些连接审核投影。
- [x] 新增“加载连接信息”开关。只有开启后才并发读取 Candidate relation、connector 和 interface；
  开关不调用 relation detect mutation，关闭仅隐藏已加载的高级工作台。
- [x] 组件或 Candidate 路由变化时关闭开关并清空旧连接数据，避免跨版本展示陈旧投影。
- [x] `docs/api.md`、G8 inventory 与 follow-up guide 已同步默认读取集合和按需加载边界。

验证：

```text
frontend npm run i18n:check  PASS（2 locales / 10 namespaces / catalog frontend-2026.08.23.1）
frontend npm test            PASS（13 files / 60 tests）
frontend npm run build       PASS（TypeScript + Vite production build）
backend Python pytest        PASS（298 passed；首次沙箱运行因系统 semaphore 权限失败，非沙箱重跑通过）
```

i18n 影响：新增 `componentRepo:loadConnectorData`、
`componentRepo:loadConnectorDataDescription` 和 `componentRepo:partsUnavailable` 三个 typed semantic
key，生产语言 `zh-CN/en-US` 同步；catalog 升级为 `frontend-2026.08.23.1`，content hash 为
`a1df75fe1221177d4efd58e7818fb311468895007441a96056d65a7633e42b81`，并已更新
`I18N_RELEASE_NOTES.md`。Part 编号、数量、connector/relation/interface 状态和 API 字段保持机器数据，
不翻译。

未修改 Go API、Worker、数据库 schema 或 Storage 数据；本次没有连接或写入真实 Supabase。
真实浏览器网络验收仍属于 G8 总体验收：需记录开关关闭时无 relation/connector/interface 请求，开启后
才出现对应只读 GET。

## 49. 上传弹窗终点与 Import 处理状态页修正

日期：2026-08-23
阶段：G8 / API、Worker 与前端交互边界修正
状态：Implemented and runtime verified

问题事实：

- 后端 upload complete 已正确返回 `202` 并创建 durable verify/parse/preview 链，但前端
  `createComponentImportWithProgress()` 随后仍在上传弹窗内调用 `waitForComponentImportReady()`；因此
  弹窗会持续轮询到 GLB ready，与“API 上传交互到 complete 为止”的已批准边界不一致。
- 2026-08-23 15:40 只读进程检查确认当时只有 Go API，没有 Go Worker。第一次启动 Worker 又因
  `LDRAW_ROOT` 未配置而 fail closed，因此已排队 Import 没有消费者推进。

修正结果：

- [x] 上传 helper 在 complete `202` 后立即返回 `{importId,taskId,status}`，不再等待 Candidate、BOM
  或 Preview ready。
- [x] 所有上传入口收到 complete 后立即关闭弹窗，并导航到可刷新恢复的
  `/component-repo/imports/:importId`。
- [x] 新增 Import 状态页：只读轮询 `GET /api/v1/component-imports/:importId`；processing 时只显示
  typed semantic key 对应的“解析中”，不加载 Viewer/Preview；ready 后才替换导航到 Candidate 页面。
- [x] 状态页轮询不调用 parse、Preview materialize 或其他 mutation；Worker continuation 仍完全由
  PostgreSQL durable task 驱动。
- [x] 上传弹窗文案收敛为只等待文件上传完成，不再把 Worker 处理描述为弹窗 loading 生命周期。
- [x] 本地 `backend-go/.env` 已配置只读
  `LDRAW_ROOT='/Applications/Studio 2.0/ldraw'`，并成功启动独立 Go Worker。

真实运行证据：

```text
Go Worker startup                         PASS（Storage=supabase；Part preview capability enabled）
latest Import 30c0dc6b-...                succeeded
component.artifact.verify 9afe35f1-...    succeeded
component.import.parse b55a167a-...       succeeded
component.preview.materialize 065775a4... succeeded
```

上述 Worker 对当前真实数据库和 Supabase Storage 执行了用户已发起上传的正常任务链；启动时也领取了
历史 queued Preview backlog，其中缺少可用几何输入的旧任务按既有规则终态为
`component_repo.preview_unavailable`。没有执行 migration、reset、reseed、purge 或额外数据清理。
Worker 进程在本次开发会话中保持运行。

验证：

```text
frontend npm run i18n:check  PASS（2 locales / 10 namespaces / catalog frontend-2026.08.23.2）
frontend npm test            PASS（13 files / 60 tests）
frontend npm run build       PASS（TypeScript + Vite production build）
backend Python pytest        PASS（298 passed）
git diff --check             PASS
```

i18n 影响：没有新增 key，但修正四组上传弹窗中英文文案，使“上传”和“Worker 处理”不再混为同一
loading 生命周期。catalog 升级为 `frontend-2026.08.23.2`，content hash 为
`645fa27f5f45b7c2e112a194a50e6b24246346c2937c07cdeb9d66b4f89e9b04`，并已更新
`I18N_RELEASE_NOTES.md`。Import/task/status/ID 和路由参数继续作为机器数据，不翻译。

## 50. BOM 几何状态与 Component partial preview

日期：2026-08-23
阶段：G7/G8 / `UPLOAD-GLB-04`
状态：Completed；用户真实页面验收通过

实现结果：

- [x] `GET /api/v1/component-versions/:versionId/parts` 在冻结 BOM 上 LEFT JOIN 同一 Part Library 的
  geometry，逐项返回稳定机器枚举 `geometryStatus=ready/failed/missing`；缺少 Part 主记录或 geometry
  记录统一为 `missing`。
- [x] Component Preview Worker 不再用 ready geometry 行数等于 BOM 种类数作为整件门禁；非 ready
  Part 的实例从 GLB scene 省略，其他实例继续生成真实 mesh，完整 BOM 不删减。
- [x] 任务结果和 derived Artifact metadata 写入稳定排序的 `omittedPartRefs` 与 `complete`，不暴露
  本地文件路径、原始解析异常或 SQL 信息。
- [x] 已声明 ready 的 source 若在 Worker 本地缺失、读取失败、SHA-256 漂移或递归解析失败，仍按
  `component_repo.preview_unavailable` 失败；partial preview 只表达冻结 Part Library 的几何覆盖率，
  不掩盖运行环境与快照一致性错误。
- [x] generator 升级为 `component-preview-studio-ldraw-glb-v3`，旧 v2 状态通过现有 stale 机制重建。
- [x] Candidate 默认结果页和 Component 详情页均对非 ready Part 显示 typed semantic key
  `componentRepo:previewGeometryMissing`，同时保留名称、Part 编号与数量。

验证：

```text
backend-go make check            PASS
isolated PostgreSQL contracts   PASS（含 BOM ready/failed/missing 与 partial GLB）
frontend i18n check             PASS（2 locales / 10 namespaces / frontend-2026.08.23.3）
frontend tests                  PASS（13 files / 61 tests）
frontend production build       PASS
Python backend pytest           PASS（298 passed；仅因沙箱 semaphore 权限曾失败，沙箱外通过）
Go API / Worker health          PASS（新版进程连接当前 Supabase）
真实页面功能                     PASS（用户确认缺件标注与其余 GLB 渲染正常）
```

i18n 影响：新增一个用户可见 typed semantic key，`zh-CN/en-US` 同步；catalog 升级为
`frontend-2026.08.23.3`，content hash 为
`f79746ec4a2c52ec9061622ed0f43ff454eacdaaa761684a195ff1a3924bd726`。Part 编号、数量以及
`ready/failed/missing` 状态为稳定机器数据，不翻译。

## 51. 发布与可选版本验证解耦

日期：2026-08-24
阶段：G7/G8 / 版本生命周期与详情页
状态：Implemented and migrated

已确认的当前产品规则：

- [x] owner 发布 Draft 不要求先生成或通过 ValidationReport。
- [x] `component.validate` 保持用户显式触发的持久异步任务；API 不同步执行验证。
- [x] Candidate 当前关联的 Draft 或 Published Version 都可触发验证；验证失败不会阻止发布、撤销发布
  或隐式改变版本生命周期。
- [x] Version 关联最近一次通过或失败报告；Component 详情页允许 owner 触发验证，并在报告
  `passed=true` 时展示“已通过验证”状态。
- [x] 既有 `validationLevel=publish` 暂作为稳定机器值保留，其含义已修订为版本级质量验证，不能再解释
  为发布数据库门禁。

实现内容：

- 新增 Goose v12，删除 `component_versions_require_valid_publish_report` trigger 及对应函数；Down 可恢复
  旧门禁，API/Worker startup 仍不执行 migration。
- `PublishVersion` 删除旧 trigger 错误映射，继续在 serializable transaction 中完成旧 published 版本
  deprecate、目标发布与 Component current version 更新。
- Validation service 接受 Draft/Published；Worker 无论通过或失败都把最新报告关联到 Version，且继续用
  interface/structure/geometry、Part Library source hash 和 validator version 约束确定性输入。validator
  升级为 `component-repo-validator-v2`，避免复用旧版只关联通过报告的成功 Logical Job。
- Component 详情页读取已有报告、提供 owner-only 显式验证按钮并展示完整结构化 checks；发布按钮与验证按钮
  相互独立。Draft 报告只对 owner 可见，active Component 的非 Draft 报告沿用 Version 公开读取边界，
  因而其他可见用户也能看到“已通过”状态。
- 新增稳定错误 `component_repo.validation_unavailable`，旧 `component_repo.publish_validation_failed` 资源仅
  保留给历史持久任务的显示兼容，不再由当前发布路径产生。

验证结果：

```text
go tool sqlc generate / sqlc vet       PASS
Go focused/full tests + go vet         PASS
isolated PostgreSQL                     PASS（Goose 0 -> v12、v12 down/up、重复 up）
publication contract                    PASS（无 ValidationReport 直接发布）
published validation contract           PASS（Published Version 异步验证并关联最新报告）
frontend i18n check/test/build           PASS（2 locales / 10 namespaces / 61 tests）
Python backend pytest                    PASS（298 tests；multiprocessing 用例在沙箱外运行）
real Supabase Goose                      PASS（postgres v11 -> v12）
real publish-gate trigger count          0
```

i18n 影响：详情页复用既有“验证 / 已通过 / 验证结果”typed semantic key；新增稳定错误
`component_repo.validation_unavailable` 的中英文资源。catalog 升级为 `frontend-2026.08.24.1`，
content hash 为 `27e0a34eea2255209feb1f11d163c3c2ff1027a0f7ef0e94740f507321241d4c`。
Version/Candidate/Report/Task ID、`passed`、validator version 和 error code 继续作为机器数据，不翻译。

真实环境：已确认目标为 Supabase EU West `postgres` 开发数据库，Goose 从 v11 升级到 v12；升级后
`component_versions_require_valid_publish_report` 非内部 trigger 数为 0。没有执行 reset、reseed、数据删除
或 `storage` policy 修改。

## 52. Component 状态收敛与 Import 历史

日期：2026-08-24
阶段：G8 / Component Repo 前端切换后续
状态：Completed

当前产品边界：

- [x] Component 列表只展示“全部 / 草稿 / 已发布”，公开筛选机器值只允许 `draft/active`；
  `archived` 继续作为 soft delete 内部状态，不在正常列表出现。
- [x] Import 的 `processing/ready/failed` 只属于上传后的异步解析/BOM/GLB 聚合状态，不再映射成
  Component 状态；Task、Preview 和 Upload Session 的失败状态没有被全局删除。
- [x] 新增全局 `/component-repo/imports` 导入记录页，并在 Component 详情原版本历史位置增加
  “版本记录 / 导入记录”Tab。

实现内容：

- 新增 owner-scoped `GET /api/v1/component-imports`，支持 `page/pageSize/processingStatus/query/componentId`；
  返回文件原名、大小、类型、关联 Component/Candidate/Draft、聚合状态、结构化 failure 与时间字段，
  不返回 Storage key、provider/bucket 或 Worker payload。
- Component 关联筛选同时覆盖更新导入的 `target_component_id` 和新建导入的
  `Import -> Candidate -> Draft Version -> component_id`，因此同一 Component 的初次导入和后续更新均可回溯。
- Import 审计关联优先选择未删除 Version；Version 后续软删除时回退最近历史 Version，因此版本列表删除不会让
  该次导入从 Component 详情历史中消失。
- 列表聚合 Import、SceneSnapshot、Draft、Preview Task 与 verified Preview Artifact；状态筛选和计数使用
  相同 SQL 判定。缺少部分 Part geometry 但整体 partial GLB 已 verified 时仍为 ready。
- 全局记录页提供搜索、状态筛选、分页、手动刷新和结果入口；只有当前页含 processing 且页面可见时每 5 秒刷新，
  不为每条记录单独轮询。
- 未新增 PostgreSQL 表或 migration；复用既有 `imports_owner_created_idx`，数据访问继续由 sqlc/pgx 完成。

验证：

```text
backend-go make check          PASS（Go 全量测试、gofmt、go vet、sqlc vet）
backend-go make test-postgres  PASS（Goose 0 -> v12；Import history owner/component/filter contract）
frontend npm run i18n:check    PASS（2 locales / 10 namespaces / frontend-2026.08.24.2）
frontend npm test              PASS（13 files / 62 tests）
frontend npm run build         PASS（TypeScript + Vite production build）
backend Python pytest          PASS（298 tests；multiprocessing 用例沙箱外重跑）
local browser DOM/visual       PASS（组件列表仅三项；全局入口、筛选与响应式布局可见；运行中的旧 Go API 需重启加载新路由）
```

i18n 影响：新增 Import 历史页面和 Tab 的 `zh-CN/en-US` typed semantic keys；catalog 升级为
`frontend-2026.08.24.2`，content hash 为
`51167620152381700db4ca56a0fafef3a90d629847bd28053cd7ab952a234929`。Import/Component 状态、ID、
文件大小和时间继续作为机器数据；上传文件名按用户原文显示，failure 继续由 `code + params` 本地化。

## 53. Component Version Preview Box 与列表占用尺寸

日期：2026-08-24
阶段：G7/G8 / Preview 派生数据完善
状态：Implemented；隔离 PostgreSQL 已验证，真实 Supabase 待部署新 Worker 后受控回填

问题与边界：

- 旧 Preview Worker 只生成 GLB Artifact，没有计算或回填任何整体 Box；Component 列表一直读取
  `components.logical_*`，因此现有 10 个非删除 Component 均显示空尺寸，其中 5 个已有 ready Preview。
- 尺寸属于 ComponentVersion 及其冻结 SceneSnapshot，不属于可被任意异步任务直接更新的 Component。
  当前发布版本必须稳定优先；尚未发布的组件才显示最新 Draft 的派生尺寸。
- 多 Root、递归子模型和任意旋转统一按实际 GLB 实例的 world matrix 求解，不能只统计 BOM 数量，也不能只
  变换 Part 局部 AABB 的 min/max 两个角点。

实现内容：

- [x] 新增 Goose v13：`component_versions.preview_bbox_min/max`、三项逻辑尺寸和
  `preview_bounds_complete`，并增加三维数组、min/max、非负尺寸和整组 NULL/非 NULL 一致性约束。
- [x] Preview generator 升级为 `component-preview-studio-ldraw-glb-v4`。Go Worker 对 scene 包递归展开的
  全部 Root 与实例逐三角形顶点应用 world matrix，合并整体 LDraw 世界坐标 AABB；尺寸换算为
  X/20 stud、Z/20 stud、Y/8 plate，并按数据库精度保留四位小数。
- [x] Artifact upsert、Version ready、AABB、逻辑尺寸与完整性在同一 pgx transaction 内提交；generation/task
  条件继续阻止过期执行回填当前版本状态。
- [x] 缺少 geometry 的实例继续只从 GLB 省略，Box 描述实际渲染 GLB 且
  `preview_bounds_complete=false`；BOM 保持完整。全部实例均缺少几何时允许空场景 GLB ready，Box 保持 NULL。
- [x] Component 详情、普通列表、Group member 与 Group search 统一投影当前发布 Version；
  `current_version_id` 为空时选择最新 Draft。旧 `components.logical_*` 只作历史兼容回退，前端 DTO 与展示无需修改。
- [x] 新增 Go-only `cmd/preview-bounds-backfill` 与
  `backend-go/scripts/backfill-component-preview-bounds.sh`。维护进程只计数/调度 durable task；脚本要求输入精确
  数据库目标并先执行 Goose，几何计算和数据库回填仍由更新后的 Go Worker 异步完成，可重复执行。

验证：

```text
backend-go make generate       PASS
backend-go make check          PASS（Go 全量测试、gofmt、go vet、sqlc vet）
backend-go make test-postgres  PASS（Goose 0 -> v13、v13 down/up、重复 up）
Preview AABB unit contract     PASS（多 Root + 旋转；partial geometry；空场景）
PostgreSQL workbench contract  PASS（Box 事务回填、发布版本/最新 Draft logicalSize 投影、dry-run/force backfill 调度）
frontend i18n check/test/build PASS（2 locales / 10 namespaces / 62 tests；既有 DTO 与展示契约不变）
```

i18n 影响：无。AABB、stud/plate 数值、完整性、generator version 和 task 状态均为机器字段；未新增或修改
用户可见文案、typed semantic key、资源文件、catalog version、content hash 或 release notes。本阶段为
Component Repo Go-only 实现，未运行也不要求 Python 回归。

真实环境只读核对：目标 Supabase `postgres` 当前仍为 Goose v12；存在 5 个未删除 ready Preview，生成器
分布为 v1=1、v3=4，均属于 v4 历史回填范围。v13 migration、v4 API/Worker 和历史任务调度必须按此顺序
部署。当前本机仍有连接该库的旧 Worker，不识别 v4 payload，因此本次没有提前迁移或调度真实任务。部署并
确认新版 Worker 后再对已确认的 Supabase 目标执行脚本，并以版本 Box 非空数量和 pending/failed task 数
完成验收。

## 54. G8 Go 页面刷新会话确认与前端登录态收敛

日期：2026-08-25
阶段：G8 / Go 系统后端认证边界与前端刷新流程
状态：Implemented and locally verified

问题事实与决策：

- 前端 Header 原先直接读取 Supabase SDK 的本地 `session.user`；Go API 已拒绝过期或无效 JWT 时，
  API error 不会通知 `AuthContext`，因此右上角可能继续显示旧邮箱。
- `getSession()` 只负责恢复浏览器缓存和刷新临近过期的 token，不能单独作为 Go 系统后端已接受当前
  actor 的证据。
- 大量用户场景不应让每个业务 API 都远程访问 Supabase Auth；远程确认固定在页面完整刷新和认证 token
  变化边界，同一页面对相同 access token 去重。普通业务请求继续只执行本地 JWT/JWKS 校验。

实现内容：

- [x] Go 新增 `GET /api/v1/auth/session`。认证 middleware 先校验 JWT 签名、时间、issuer、audience 和
  UUID subject；handler 再用公开 project key 和当前用户 JWT 请求 Supabase Auth user endpoint。
- [x] Provider user ID 必须与 JWT actor ID 一致；成功只返回最小 `{authenticated,user:{id,email?}}`
  投影，不透传 provider payload，不记录 token，也不访问 PostgreSQL。
- [x] Provider `401/403` 映射为 `401 auth.session_invalid`；timeout、rate limit 和 `5xx` 映射为
  `503 auth.session_verification_unavailable`；其他非成功状态保持结构化
  `auth.session_verification_failed + status`。只有明确 session invalid 才允许前端清理本地会话。
- [x] `AuthProvider` 在 Go 确认完成前不向 Header 暴露本地缓存用户；成功后才显示用户信息。网络或
  provider 暂不可用时隐藏未经确认的信息但保留 Supabase 本地 session，下一次刷新可重试。
- [x] 通用 API client 只对 `401 auth.session_invalid` 发送进程内认证失效通知，并携带该请求 token
  供 `AuthProvider` 与当前 token 比对；旧 token 的延迟 `401` 不会清理刚刷新的新 token。页面运行期间的
  Go API 明确拒绝仍会同步清空 Header；普通 `401`、网络错误和 `5xx` 不触发误退出。
- [x] 更新 Go env 示例、README 和 API 契约。未新增数据库 schema、migration、任务类型或 Python
  认证入口。
- [x] 修正既有 ES256 tamper 测试：由修改 Base64 未使用尾位改为实际翻转签名字节，确保测试确实覆盖
  无效签名而不改变 verifier 生产逻辑。

验证：

```text
backend-go make check          PASS（Go 全量测试、gofmt、go vet、sqlc vet）
Go session focused contracts  PASS（用户匹配、JWT、provider invalid/outage、路由响应）
frontend npm run i18n:check    PASS（2 locales / 10 namespaces / frontend-2026.08.24.2）
frontend npm test              PASS（14 files / 65 tests）
frontend npm run build         PASS（TypeScript + Vite production build；既有 chunk-size warning）
backend Python pytest          PASS（298 tests / 6 个既有 warning；multiprocessing 用例沙箱外运行）
```

i18n 影响：页面登录状态和既有认证错误展示发生变化，但没有新增/修改用户可见文案或资源 key；复用
`auth.session_invalid`、`auth.session_verification_unavailable`、`auth.session_verification_failed`、
`auth.user_payload_invalid` 与 `auth.verification_not_configured`。catalog version、content hash 和 release
notes 不变。用户 ID、email、JWT claims、HTTP status 和进程内通知标识均为机器数据或用户身份原文，不翻译。

未连接、迁移或修改真实数据库和 Supabase Storage；真实浏览器仍需在部署新版 Go API 后，用已登录会话
确认刷新时仅出现一次 `/api/v1/auth/session`，并分别验收有效、明确失效和 provider 暂不可用三条路径。

## 55. 历史 Preview 降级与 Component owner 操作恢复

日期：2026-08-25
阶段：G8 / Component 详情页容错与授权投影
状态：Implemented and locally verified

问题结论：

- 页面显示 `component_repo.preview_unavailable` 不是因为历史数据只缺少“尺寸”字段。真实库中的历史 GLB
  使用 v1/v3 generator；当前代码要求 v4，因此 Preview GET 返回 stale/无 URL，前端 adapter 将其转换为
  preview unavailable。v13 与 v4 历史回填完成前，三维预览保持不可用是预期的派生数据状态。
- 详情页此前把 Preview 加载与 Component 主体放在同一个失败边界。Preview stale 会让页面进入全局错误态，
  即使 Component、Version 和 owner 数据已经成功返回。
- 删除按钮又依赖 `AuthContext.user.id === component.ownerId`。页面刷新会话确认期间，业务 API 可以已经使用
  有效 token 返回 Component，但 Header 用户投影仍可能暂时为空，从而错误隐藏发布和未发布 Component 的
  owner 操作。

实现内容：

- [x] Component 可见查询新增稳定机器字段 `ownedByActor`，由 Go API 使用已鉴权 actor 与数据库 owner 比较；
  Component 详情、列表、Group member/search 使用同一投影。真正的 DELETE 仍由 Go service owner 条件强制授权。
- [x] 详情页发布、验证和“删除整个组件”改用服务端 `ownedByActor`；旧开发 API 缺少该字段时才回退原
  `ownerId` 比较。服务端字段已返回时不再等待浏览器 Auth user 投影。
- [x] Component、Version、Group 和历史记录属于详情页主数据；Version Preview 是独立可重建派生数据。
  Preview stale/failed 现在只在三维区域显示错误，不再设置整页错误，也不阻断 owner 操作和版本/导入记录。
- [x] 发布状态不参与整个 Component 的删除按钮判断。当前发布 Version 仍不能单独删除；owner 可以使用
  页面顶部“删除组件”执行既有 soft delete，未发布 Component 同样适用。

验证：

```text
backend-go make check                 PASS（Go 全量测试、gofmt、go vet、sqlc vet）
backend-go make test-postgres         PASS（owner/non-owner ownedByActor、删除授权与 Goose v13）
frontend i18n check                  PASS（资源未变化）
frontend tests                       PASS（14 files / 65 tests）
frontend production build            PASS
Chrome 已登录运行态                    PASS（历史 Preview 错误仅留在预览区；Published 显示 Delete Component/Validate；Draft 显示 Delete Component/Validate/Publish）
```

运行新版 API 前，本机 `127.0.0.1:8080` 仍由 09:21 启动的旧二进制监听，因此响应缺少
`ownedByActor`，按钮不会仅靠前端热更新恢复。本次只重启 Go API、未停止 Worker；新版 API 启动后完成上述
浏览器验收。这也说明部署时 API 与前端必须同时更新，不能只发布前端。

i18n 影响：无新增或修改文案。复用既有 `component_repo.preview_unavailable`、删除组件、发布和验证语义 key；
`ownedByActor`、Preview status、generator version、owner ID 与 Component status 都是机器字段，不翻译。

## 56. G8 Component Repo Box 尺寸搜索迁移收口

日期：2026-08-25
阶段：G8 / Component 目录查询
状态：Implemented and locally verified

问题结论：

- [x] 组件仓库搜索已迁移到 Go：前端请求
  `GET /api/v1/component-groups/:groupId/components/search`，由 Gin Handler、Go Component Service 和 sqlc
  查询执行，Python 不在调用链中。
- [x] 当前运行 API 日志中的该路由请求均为 `200`，未复现用户看到的历史 `500`；旧实现仅做名称/UUID
  模糊查询，尺寸输入不会产生正确的尺寸结果。本次同时补齐尺寸语义并使用 PostgreSQL 集成测试覆盖 SQL。

实现内容：

- [x] `query` 完整匹配 `a x b` 或 `a x b x c` 时进入尺寸模式，兼容 `x/X/×`、空格和小数；其他输入继续
  作为名称/UUID 搜索，避免组件名称中的局部数字被误判。
- [x] 输入和 Version Box 三维都按升序归一化。三值逐维匹配；两值枚举 `ab/ac/bc`；每一维严格使用
  `> target-1 AND < target+1`，恰好相差 1 的边界不命中。
- [x] 尺寸来源与列表展示一致：当前发布 Version 优先，无发布版本时取最新 Draft，旧 Component 尺寸只作
  历史回退。任一尺寸为空时不参与尺寸搜索。
- [x] 结果查询和状态统计复用相同尺寸过滤条件，保证 `items/total/totalPages/statusCounts` 一致。移除前端
  adapter 中从未传输的旧 `allowPlanarRotation/sizeTolerance` 占位参数；容差固定为当前批准的开区间规则。

验证：

```text
backend-go make generate       PASS
backend-go make check          PASS（Go tests、go vet、sqlc vet；httptest 需沙箱外本机端口）
backend-go make test-postgres  PASS（Goose 0 -> v13；三值、两值 ab/ac/bc、开区间边界）
frontend i18n check/test/build PASS（2 locales / 10 namespaces / 65 tests；既有 chunk-size warning）
Chrome 已登录运行态           PASS（名称 `red`、三值 `11x12x20`/`1.1x5x6`、两值 `5x6` 均命中预期单条记录；开区间边界无结果；Go 路由均为 200）
```

i18n 影响：无。尺寸数值、解析维数、查询条件和分页/状态统计均为机器数据；没有新增或修改用户可见文案、
typed semantic key、资源文件、catalog version、content hash 或 release notes。Component Repo 保持 Go-only，
未运行也不要求 Python 回归。

## 57. G8 Component 搜索条件确认与标签交互

日期：2026-08-25
阶段：G8 / Component Repo 前端查询交互
状态：Implemented and locally verified

- [x] 搜索输入改为 draft/applied 两层状态；键入内容不会立即请求，按 Enter 后才固化并调用既有 Go 搜索接口。
- [x] 已应用条件以保留用户原文的标签显示在搜索框右侧；每次 Enter 追加条件，大小写相同的重复条件不重复
  添加。每个标签的 `×` 只移除自身并重置分页，其他标签继续生效。
- [x] 多个标签通过重复 `query` 参数传给 Go API，并按 AND 组合；普通文字、UUID 与二维/三维尺寸条件可复合。
  空输入不会意外清除已应用条件。状态筛选和 Group 切换继续与全部已应用条件组合，不读取未确认的输入草稿。
- [x] 新增 `componentRepo:activeSearchCondition` 与 `componentRepo:clearSearchCondition` 无障碍语义 key；资源版本
  升级为 `frontend-2026.08.25.1`，content hash 为
  `0d75a5beb557077fd3cb96260c051118b400c6231e0dfdadea4ded01e28055f1`。

验证：

```text
frontend i18n check/test/build PASS（2 locales / 10 namespaces / 65 tests；既有 chunk-size warning）
Chrome 已登录运行态           PASS（输入 5x6 未回车不请求/不出现标签；Enter 后命中单条并显示标签；× 后恢复三条且标签消失）
```

i18n 分类：标签值是用户查询原文，不翻译；标签容器与清除按钮是系统 UI 文案，使用 typed semantic key。
Go API 的响应结构、数据库 schema 与尺寸容差未改变；请求契约将 `query` 明确为最多重复 8 次的 AND 条件。

## 58. G8 Component 复合搜索条件追加修复

日期：2026-08-25
阶段：G8 / Component Repo 查询契约与前端标签状态
状态：Implemented and locally verified

- [x] 修复第二次 Enter 覆盖首个标签的问题：前端 applied state 从单字符串调整为条件数组，单个 `×` 只删除
  对应条件。
- [x] 前端 adapter 使用重复 `query` 参数；Gin Handler 使用 `QueryArray`，Go Service 对条件裁剪、大小写去重，
  并把文字条件与尺寸条件分流。
- [x] PostgreSQL 使用 `NOT EXISTS` 反例查询实现所有条件的 AND 语义；多个尺寸条件通过内部 JSON recordset
  参数化执行，不动态拼接 SQL。结果列表和状态统计继续使用同一条件，缺少 Box 不会因 SQL NULL 误通过。
- [x] 最大条件数为 8，每项最多 200 字符；超过边界返回既有结构化 request validation error。

验证：

```text
backend-go make check          PASS（Go tests、go vet、sqlc vet）
backend-go make test-postgres  PASS（文字 + 多尺寸 AND、复合不匹配、状态统计一致）
frontend i18n check/test/build PASS（2 locales / 10 namespaces / 65 tests；既有 chunk-size warning）
Chrome 已登录运行态           PASS（先加 5x6，再加 door，两个标签同时保留并命中同一组件；删除 door 后 5x6 继续生效；全部删除后恢复三条）
```

i18n 影响：交互行为变化但资源不变，继续复用 `activeSearchCondition` 与 `clearSearchCondition`；标签内容保持
用户查询原文。catalog 仍为 `frontend-2026.08.25.1`。

## 59. G8 Part Search Go API 切换

日期：2026-08-25
阶段：G8 / Part Library 查询与前端 legacy API 退出
状态：Implemented and locally verified；真实 active library 的源名称待受控重导

原接口功能盘点：

- 旧 `POST /api/fitting/candidates/recall` 是 Python fitting 域通用画像召回，包含
  `part/submodel/component`、profile status/irregular、bbox/logical size、connector/category/color、
  fuzzy key、score、分页与 legacy 图片补全。
- `/part-search` 页面实际只传 `candidateTypes=['part']`、搜索框 `query`、
  `includeIrregular=false` 和页码；未使用显式 bbox、connector、category、color、component/submodel 或
  `key` 契约。因此本次不把未使用的 fitting 算法字段复制进 Component Repo Go API。

实现内容：

- [x] 新增认证 `POST /api/v1/parts/search`，只读取 active Studio Part Library 的 `parts +
  part_geometries`，不访问 legacy `public.fitting_candidate_profiles/rb_part_images`。
- [x] 搜索框继续支持空格/中英文逗号分段、二维/三维精确尺寸、二维平面旋转、名称关键词至少一个命中、
  尺寸候选至少一个命中；名称集合与尺寸集合按 AND 组合。
- [x] 只返回 geometry ready 的 Part，排除 sticker/decal；使用 PostgreSQL count、命中关键词数和
  `source_name/ldraw_part_num` 稳定分页，`pageSize` 最大 200。
- [x] 响应返回实际 `partLibraryVersionId`，前端 Part 详情链接使用同一不可变快照；前端不再并行读取
  active library 或调用 `/api/fitting/candidates/recall`，因此关闭 legacy API 后页面搜索仍走 Go。
- [x] Go Studio importer 升级为 v3：离线读取顶层 LDraw 文件头描述并固化到 `parts.source_name`；
  API 请求不读取 `LDRAW_ROOT`。维护脚本将 importer version 纳入 no-op 判定，相同 manifest 的 v2
  snapshot 也会在明确执行脚本时受控重导。
- [x] 图片不从 legacy 表跨 schema 读取；Go 响应明确 `imageUrl=null`，前端继续显示已有占位图。
- [x] `docs/api.md` 已记录旧功能点、当前迁移覆盖与未迁移的 fitting 算法边界；字段分类同步改为 Go
  Part Search 源内容投影。

验证：

```text
backend-go make check          PASS（Go 全量 tests、gofmt、go vet、sqlc vet）
backend-go make test-postgres  PASS（Goose 0 -> v13；关键词+编号+二维尺寸、failed geometry 排除、importer source_name）
frontend i18n check            PASS（2 locales / 10 namespaces / frontend-2026.08.25.1）
frontend tests                 PASS（14 files / 65 tests）
frontend production build     PASS（仅既有 Vite/chunk-size warning）
```

i18n 影响：Part Search 名称从 legacy 画像源快照切换为 Studio importer 固化的 LDraw 源描述，仍属于
源内容，不选择 reviewed translation；用户 query 不保存、不翻译；Part 编号、尺寸、library ID、状态和
JSON key 保持机器值。没有新增或修改用户可见文案、typed semantic key 或资源，因此 catalog version、
content hash 和 release notes 不变。

遗留：本次没有连接或修改真实 Supabase。真实 active library 当前若仍由 importer v2 产生，名称可能仍等于
Part 编号；需要用户确认精确数据库目标后运行 `backend-go/scripts/update-studio-part-library.sh`，由 v3 importer
受控重建 `source_name`。旧 Python recall service 仍供 Component Repo 之外的 fitting 算法内部调用；
`/part-search` 已不再依赖它，不应为了本页面删除其他域仍使用的 Python service。

## 60. Part Search 前端认证注入修复

日期：2026-08-25
阶段：G8 / Part Search Go API 前端切换收口
状态：Implemented

- [x] 定位 `/api/v1/parts/search` 返回 `401` 的原因：页面直接调用无认证的通用 `requestJson`，请求没有
  `Authorization` header，因此在进入 Go Part Search Handler 前即被认证中间件拒绝；不是搜索 SQL、
  active Part Library 或 Go JWT/JWKS 校验逻辑故障。
- [x] 新增共享 `authenticatedRequestJson` 边界，统一读取当前 Supabase session access token、保留业务
  headers 并注入 Bearer token；Part Search 页面切换到该入口。
- [x] 增加回归测试，固定 Bearer token 和 `Content-Type` 同时存在的不变量。
- [x] `docs/api.md` 补充前端认证调用约束和 Part Search 的认证执行流。

验证：

```text
frontend npm run i18n:check PASS（2 locales / 10 namespaces / frontend-2026.08.25.1）
frontend npm test           PASS（15 files / 66 tests）
frontend npm run build      PASS（仅既有 Vite deprecation/chunk-size warning）
```

i18n 影响：无用户可见或 locale-sensitive 变化；没有新增文案、semantic key、资源或持久化内容，catalog
version、content hash 与 release notes 不变。

## 61. Part Preview meshopt GLB v2 与全库预生成

日期：2026-08-25
阶段：G8 / Part Preview 派生资产与真实 Storage 回填
状态：Completed and verified；真实全库回填完成

实现内容：

- [x] Part generator 提升为 `part-preview-ldraw-meshopt-glb-v2`：Worker 将 LDraw Y-down/LDU 坐标烘焙为
  项目 Y-up/stud 坐标，反转反射后的三角形 winding，生成可复用索引和 60° 折角法线；前端只为没有
  NORMAL 的历史 GLB 运行 `toCreasedNormals`，避免每次打开复制并重算法线。
- [x] 原生/CLI 压缩边界固定为 gltfpack 1.2，输出必须声明 `EXT_meshopt_compression`，否则任务稳定失败；
  前端既有 `GLTFLoader.setMeshoptDecoder` 直接解码。压缩器升级必须同步提升 generator version。
  本机 GitHub Release 原生包下载遇到 CDN framing/stall，初期批次使用同版本官方 npm WASM CLI；随后从
  meshoptimizer v1.2 官方源码构建原生 `gltfpack`，最终批次使用原生可执行文件完成。`install-gltfpack.sh`
  保留原生优先和固定版本校验，资产扩展和内容寻址语义不变。
- [x] 最终 GLB 按字节 SHA-256 写入当前 `component-artifacts` bucket 的
  `component-repo/part-library-assets/glb/{generator}/{shaPrefix}/{sha}.glb`。Artifact 是无 owner、不可变、
  内容寻址的全局派生资源；`part_previews.artifact_id` 保存 Part 绑定，通用 Task 的 owner-scoped
  `result_artifact_id` 保持为空，结构化 result 仍返回 artifact ID。
- [x] GET 只暴露当前 generator 的 ready Artifact；v1/未知 generator 投影为 pending。单 Part materialize 在
  generator 过期或 Storage 丢失时递增 generation，不让迟到的旧 Worker 覆盖 v2。
- [x] 新增 `component.part_preview.prebuild` durable task 和默认 dry-run 的
  `backend-go/scripts/prebuild-part-previews.sh`。脚本打印精确数据库/bucket/prefix，只有
  `CONFIRM_DATABASE_TARGET + PART_PREVIEW_PREBUILD_EXECUTE=1` 才写任务；Worker 一次批量冻结候选，按
  face count 从轻到重、8 路受控生成，每个成功 Part 只执行一次内容寻址 Storage PUT 和一次原子
  Artifact upsert + preview ready SQL。单 Part retryable 压缩/Storage 故障最多短重试三次，永久源缺陷
  记录稳定 `code + stage params` 并继续。
- [x] `WORKER_TASK_TYPES` 支持专用能力进程；`start-part-preview-prebuild-worker.sh` 只 claim prebuild，且关闭
  通用上传维护。本次真实库另有 queued Artifact verify/Import parse，专用 Worker 没有推进这些任务。
- [x] 保留 `install-gltfpack.sh` 与 prebuild/start 脚本，Studio/LDraw 零件更新并激活新 Part Library 后可重复
  dry-run、确认目标、调度；ready 当前 generator 自动跳过。

真实执行证据：

```text
database target  postgres@2a05:d018:8eb:2f01:8a32:92ac:c6f3:52f/128:5432
storage target   supabase/component-artifacts/component-repo/part-library-assets
library          c8176a73-eccb-4db3-ba72-30edf5f9fd23
matched initial  24,373
final task       b71acb19-2b22-4551-8280-5bff8643335f (execution 5, succeeded)
final result     matched=6,095 / ready=6,095 / failed=0
library total    24,373 ready / 0 pending / 0 failed
artifacts        19,885 distinct content-addressed objects / 291 MB stored / 345 MB logical references
integrity        0 missing objects / 0 size mismatch / 0 wrong key, owner, bucket or artifact contract
maintenance      post-completion dry-run matched=0
sample object    component-repo/part-library-assets/glb/part-preview-ldraw-meshopt-glb-v2/
                 5a/5a3b64570b87555e52715ab2f30170d684d3aac48dc5d3e775073b51d4264014.glb
sample metadata  owner_id IS NULL; SHA equals filename; 44,336 bytes; EXT_meshopt_compression
Storage info     HTTP 200
download/decode  SHA-256 PASS；EXT_meshopt_compression + KHR_mesh_quantization；Three MeshoptDecoder PASS
```

早期 execution 1-4 用于真实链路和吞吐诊断：确认 source hash 一致后，发现 Supabase object info 对不存在对象
返回不稳定，改为内容寻址幂等 PUT；随后把逐 Part 多次远程 SQL 合并为 500 条一批的候选准备和单条原子 finalize。
Supabase Session Pool 达到 15 连接上限后，专用 Worker 收缩为一个数据库会话、外层一个任务并把租约延长为 5 分钟；
Part 内部仍保持 8 路几何/Storage 并发。已 ready 的 v2 Artifact 在重试间保持有效，execution 5 只处理剩余
6,095 条并一次成功。另有 queued Artifact verify/Import parse 在整个专用回填期间均未被消费。

验证：

```text
gltfpack 1.2 real smoke      PASS（输出 EXT_meshopt_compression）
backend-go make check        PASS
backend-go make test-postgres PASS（Goose 0 -> v13；全量 API/task/workbench contract）
frontend npm run i18n:check  PASS（2 locales / 10 namespaces / frontend-2026.08.25.1）
frontend npm test            PASS（15 files / 66 tests）
frontend npm run build       PASS（仅既有 Vite/chunk-size warning）
real Supabase Artifact       PASS（global owner、content key、SHA、metadata 与 Storage info）
```

i18n 影响：无用户可见或 locale-sensitive 变化；generator version、SHA、Storage key、task type 和 failure stage
均为稳定机器值。没有新增文案、semantic key、资源或持久化内容，catalog version、content hash 与 release notes
不变。

## 62. Supabase 数据库容量审计与 migrated public Part source 清理

日期：2026-08-25
阶段：G8 / Go-only 数据边界与开发数据库容量维护
状态：Completed and verified（精确安全子集；范围外依赖数据保留）

审计结论：

- 清理前 `pg_database_size=500,337,811 bytes`（PostgreSQL 显示 477 MiB），已经超过 Supabase Free
  500 MB database size 阈值；项目当时 `default_transaction_read_only=off`，当前连接 20/60，因此根因是容量，
  不是连接数。
- schema 主要占用为 `component_repo=303 MB`、`public=123 MB`、`storage=37 MB`。19,885 个去重 Part GLB
  在 `component_repo.artifacts` 与 provider-owned `storage.objects` 各有一条元数据，二者合计约 62 MB；
  291 MB GLB 对象正文位于 Storage，不计入 PostgreSQL database size。
- 原计划中的 8 张 migrated `public` Part/Connector source 表约 68 MB，但其中 5 张仍被 1,956 条
  DEM、shape profile、shadow include 或历史 connector analysis 记录通过 `NO ACTION` 外键引用。没有使用
  `CASCADE`，也没有扩展清理到其他业务域。

真实执行：

- [x] 新增默认 dry-run 的 `backend-go/scripts/cleanup-migrated-public-part-source-data.sh`。执行要求精确
  `CONFIRM_DATABASE_TARGET`，先验证 active Go Part Library 的 Parts/geometry/connector 不变量，再检查未来是否
  新增外键子表。
- [x] 仅清空无外键子项、已进入 Go 权威库的
  `public.connector_instances`（29,853）、`public.ldraw_part_geometry`（24,214）和
  `public.xref_part_numbers`（25,384）；使用单事务 `TRUNCATE`，不重置 sequence，不使用 `CASCADE`。
- [x] 清理前通过 2,000 行短连接分片保存 41 个 CSV 数据文件；manifest 固化三表行数和分片数，所有文件
  SHA-256 校验通过。真实恢复目录为
  `/private/tmp/ctbz-public-part-source-20260825T222000Z`，总大小约 15 MB。
- [x] 清理后 `pg_database_size=468,757,651 bytes`（447 MiB），实际回收 31,580,160 bytes；三张目标表均为
  0 行，数据库仍可写。
- [x] active Part Library `c8176a73-eccb-4db3-ba72-30edf5f9fd23` 保持 24,426 Parts、24,426 geometries、
  190,419 connector definitions；当前 meshopt v2 preview 保持 24,373 ready。
- [x] `public.part_connector_definitions`、`ldraw_files`、`ldraw_parts`、`ldraw_shadow_meta_raw`、
  `ldraw_shadow_files` 及其范围外子表全部保留。retired Part Library 仍被 6 个 ComponentVersion、7 个 Import 和
  7 个 ConnectorAnalysis 引用，也未清理。

验证：

```text
bash -n maintenance script       PASS
shellcheck maintenance script    PASS
dry-run / exact DB confirmation  PASS
41 CSV shards + MANIFEST SHA-256 PASS
post-cleanup table counts        0 / 0 / 0
post-cleanup Go Part invariants  PASS
database size                    500,337,811 -> 468,757,651 bytes
```

本次没有 API route、request/response、授权或执行流变化，因此 `docs/api.md` 不变。i18n 影响为：当前 Go UI/API
无用户可见或 locale-sensitive 变化；清理对象是已迁移 legacy source 的机器/源数据，未修改当前官方 Part
translation、用户内容、semantic key、catalog version、content hash 或 release notes。旧 Python
Part/Connector 数据读取会得到空表，这是 Component Repo Go-only 清理的明确副作用。

## 63. Part Search meshopt GLB 静态缩略图

日期：2026-08-26
阶段：G8 / Part Search 预览投影
状态：Implemented

实现内容：

- [x] `POST /api/v1/parts/search` 在既有 Part/geometry 查询中可选关联当前
  `part-preview-ldraw-meshopt-glb-v2` ready preview 与 verified Artifact；不读取对象正文、不创建 Task，且不暴露
  Storage key。
- [x] Go Storage 边界增加同 bucket 批量签名，Supabase 使用一次 `POST /storage/v1/object/sign/{bucket}` 签名
  当前页去重后的 key。单 path 失败只省略对应 URL；批次请求失败时 Search 保留完整文本结果并令
  `previewModel=null`，不会把 Storage 短暂故障放大为搜索 500。
- [x] Search item 增加可选
  `previewModel={artifactId,format,compression,url,sha256,byteLength}`；`imageUrl` 继续为 null 兼容字段。真实
  Storage 中已有的全库 GLB 是唯一远程正文，本次不新增数据库表、Artifact 或缩略图 Storage 对象。
- [x] `/part-search` 使用 `IntersectionObserver` 提前 400px 按需加载；GLB 下载并发限制为 4，meshopt 解码后的
  GPU 渲染串行复用一个离屏 WebGL context，不为 20 张卡片创建常驻 canvas、OrbitControls 或 RAF。
- [x] 缩略图使用与 Part 详情页相同的 Y-up 模型和初始相机方向，输出静态 256px WebP；卡片继续使用普通
  `<img>`。结果以内存 128 条和 IndexedDB 100 MB/2,000 条两级缓存保存，cache key 包含 renderer version、
  Artifact ID 与 SHA；翻页或搜索切换会中止尚未完成的下载/排队渲染，失败仅回退既有占位图。
- [x] `docs/api.md` 同步当前 Search response、批量签名降级和前端执行边界。

验证：

```text
go tool sqlc generate                         PASS
backend-go make check                        PASS（全量 tests、gofmt、go vet、sqlc vet）
backend-go make test-postgres                PASS（Goose 0 -> v13；Search preview JOIN/批量签名集成契约）
frontend npm run i18n:check                  PASS（2 locales / 10 namespaces / frontend-2026.08.25.1）
frontend npm test                            PASS（15 files / 66 tests）
frontend npm run build                       PASS（仅既有 Vite deprecation/chunk-size warning）
```

i18n 影响：无用户可见或 locale-sensitive 变化；没有新增文案、semantic key、资源、API error code 或持久化
内容。`previewModel` 字段名、format/compression、Artifact ID/SHA 均为稳定机器值，catalog version、content hash
与 release notes 不变。
