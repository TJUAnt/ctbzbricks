# Component Repo Go 迁移跟进指南

> 当前快照：2026-08-24
> 当前阶段：G8（前端切换与 Component Repo Python 删除）
> 目标决策：Component Repo Go-only；所有 Component Repo task type 已由 Go Worker 消费
> 当前工作主链：上传 Studio `.io` -> 准确 BOM -> ComponentVersion 整体 GLB，见第 7 节
> 事实台账：[go_migration_progress.md](./go_migration_progress.md)
> 阶段定义：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 长期原则：[go_backend_migration_principles.md](./go_backend_migration_principles.md)
> Studio Part Library 路线图：[go_part_library_studio_roadmap.md](./go_part_library_studio_roadmap.md)

本文用于日常跟进，不代替阶段验收记录。阅读状态时必须区分三个层次：

1. **代码能力完成**：实现和隔离测试已经通过。
2. **当前环境可运行**：所需 API、Worker、凭据、数据库和 Storage policy 已实际配置并启动。
3. **迁移切换完成**：前端不再依赖旧公共 API，Component Repo 的 Python 路由和任务执行入口已经删除。

G5～G7 与关系检测 Go 迁移的代码能力已经完成，但这不自动表示当前开发环境中的异步链路正在
运行；G8 只有同时满足运行验收和旧 Python 公共 API 删除门槛后才能完成。

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

在组件上传中，Go API 创建 owner-scoped upload session，生成并持久化精确 Storage key；浏览器使用
当前用户 JWT 向 API 返回的目标直传正文，不能自行指定 key。Storage INSERT RLS 只接受 actor 自己仍为
pending、未过期的会话 key。API 确认上传结果并在短事务中建立持久任务链。upload complete 返回 `202`
后，本次前端写交互结束；verify、解析/BOM 和整体 GLB 必须继续由 Worker 完成。

### 1.2 Go Worker（`cmd/worker`）

Go Worker 是独立进程，负责适合 Go 的异步执行：

| task type | 当前职责 |
|---|---|
| `component.artifact.verify` | 流式读取对象，校验大小与 SHA-256，推进 Artifact 验证状态 |
| `component.import.parse` | 解析 LDraw/Studio，物化 SceneSnapshot、BOM、Candidate 和 Draft Version |
| `component.relations.detect` | 从冻结且 relation-ready 的 Part Library 识别关系，原子物化 RelationCandidate、Connector 和 Interface 投影 |
| `component.validate` | 执行用户显式触发的可选版本质量验证，写入 ValidationReport；不阻塞发布 |
| `component.preview.materialize` | 使用 ComponentVersion 固定的 SceneSnapshot 与 Studio/LDraw Part Library 生成整体 GLB，写入派生 Artifact 与对象存储 |
| `component.part_preview.materialize` | 从版本固定的只读 LDraw library 生成真实 Part GLB，写入派生 Artifact 与对象存储 |

它还负责 PostgreSQL 队列的通用运行协议：`FOR UPDATE SKIP LOCKED` 领取、lease、heartbeat、attempt fencing、有限重试、协作取消、终态提交、task event/outbox，以及过期上传对象清理。

Go Worker 不提供 HTTP API。Supabase 模式下，它进行服务端对象读取、写入、验证和清理，因此必须使用
现代 `SUPABASE_SECRET_KEY` 或兼容的 `SUPABASE_STORAGE_SERVICE_ROLE_KEY`；缺少服务端凭据时应在
启动前 fail closed，任何 secret 都不得进入浏览器。

### 1.3 Python 边界

Component Repo 已无 Python task consumer。仓库仍保留的 legacy Python 公共 router 是 G8 最终
删除项，不得新增功能或作为 Go API fallback。

### 1.4 一次典型异步调用

```text
Frontend
  -> Go API：认证、短事务、创建 task
  <- 202 Accepted + taskId

Go Worker
  -> PostgreSQL：领取 task + lease
  -> Object Storage / 算法计算
  -> PostgreSQL：业务结果 + task 终态 + event/outbox

Frontend
  -> Go API：轮询 task
  -> Go API：读取 Import/Candidate/Validation/Preview 结果
```

判断某段逻辑归属时使用一个简单规则：能在短请求内确定完成的授权、查询和事务属于 Go API；可能受文件大小、算法复杂度或外部对象存储延迟影响的工作属于 Worker。

组件上传采用更严格的业务门禁：前端只有在 BOM 已落库且 ComponentVersion 整体 GLB 已生成并验证后
才可进入 `ready` 并挂载三维预览器；此前只读轮询并显示本地化 processing 状态。关系、connector、
interface、validation 和 publish 不属于默认上传完成条件。

## 2. 当前状态与剩余工作

截至 2026-08-23：G0～G7 已完成；Component Repo 的所有 task type 均由 Go Worker 消费；前端主要
流程只使用 `/api/v1`；上传、BOM、partial GLB 和缺件标注已通过用户真实页面验证。当前仍需完成：

1. 补齐 G8 授权、非 owner Preview RLS、`zh-CN/en-US` 与维护动作的完整浏览器矩阵；
2. 删除 FastAPI 中仍挂载但新前端已不依赖的 Component Repo 公共 router 及专用死代码；
3. 在 Go-only Worker 内按 generator version 继续改进颜色/BFC/normal/TEXMAP 与 GLB 压缩；
4. 精确 collider clearance/raycast 作为独立后续能力，不回到普通上传完成条件。

## 3. 已归档的 2026-08-15 Review

本节保留当时的环境与测试事实，不作为 2026-08-22 之后的当前状态来源；当前事实以
[进度台账](./go_migration_progress.md) 最后记录为准。

### 2.1 已验证的代码事实

- G0～G4 已完成。
- G5 的任务状态机、Logical Job / Execution / Attempt、lease/retry/cancel、语言无关 Worker 协议已实现。
- G6 的 `upload -> artifact verify -> parse -> Snapshot/Candidate/Draft` 异步链路已实现。
- G7 的关系检测、可选版本验证、BOM 与预览物化链路已实现。
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

### 2.2 Review 时未闭环项

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
| P1 | Component Repo task runtime Go-only | Resolved 2026-08-22：import parse 与 relation detect 均由 Go Worker 消费；Python relation worker/adapter/launcher 已删除；隔离 PostgreSQL relation E2E 通过 | 保持 Go-only，不新增 Component Repo Python task type；G8 仍需删除旧 Python 公共 router |
| P2 | G8 仍保留 Python 公共 router | 旧 `library-items` preview 已删除，但 FastAPI 仍挂载 Component Repo router 的其他公共能力 | 完成剩余公共 API 盘点和浏览器网络验收后删除 Python Component Repo router，不保留 Component Repo Python 公共入口 |
| P2 | PowerShell 运行验收 | PowerShell 已与 Bash 对齐为 Go API、legacy API 和三个独立 Worker launcher，但当前 macOS 环境没有 PowerShell runtime | 在 Windows 真实启动、停止并重启各进程，确认环境覆盖优先级和健康端口 |

## 4. 已废弃的 2026-08-15 执行顺序

下列旧顺序已被 2026-08-23 的 Go-only、Studio Part Library、上传 continuation 和 partial preview
实现取代，不再作为执行清单。保留它只为解释历史记录中的编号：

1. **修复历史 runnable Task**：为协议外 legacy payload 制定可审计修复和新 Execution 方案，同时补齐历史 event/outbox 决策；不得把终态行改回 queued。
2. **完成真实 legacy schema 前置**：确认目标后执行 Alembic `20260809_0022`，再验证默认完整启动拓扑；在 Windows 补做 PowerShell smoke。
3. **修正 Preview RLS**：先确定 active Component 的业务可见性，再让数据库查询和 Storage policy 使用同一规则；用真实 Supabase 用户身份验收。
4. **确定 outbox runtime 策略**：若当前不外发则记录禁用与积压策略；需要外发时实现 publisher 和指标。
5. **固化代码基线**：按阶段拆分并提交当前工作树，保证任意开发者能从提交重现测试结果。
6. **闭环 Studio Component preview signed URL**：整体 GLB 物化已通过真实 Go API/Worker + server-side Storage 验证，Storage preview helper 已通过 Alembic 修正并 SQL 验证；下一步用真实 Supabase 登录 access token 重跑 API GET preview。Part-level GLB 用 `3001.dat`、`3023.dat`、一个 printed textured part 和一个 ready `bl_` 样例作为补充 smoke。
7. **进入 S3 external IDs**：从 Studio `elementInfoList.json`、`ldraw_new.xml`、`designid.xml` 补充 BrickLink / LEGO design / LEGO element；Rebrickable 视需要从 legacy 或 CSV 重建。
8. **执行 G8 最终验收**：真实登录态、`zh-CN/en-US`、上传/解析/关系检测/审核/校验/发布/预览，
   网络请求只走预期入口，完整链路不启动 Python。
9. **删除 Python 公共 Component Repo API**：删除 FastAPI router 和只服务旧公共接口的代码。
10. **再进入部署收口**：Nginx、指标、告警、最小数据库权限和正式进程编排。

## 5. 每次继续迁移时的检查表

开始前：

- [ ] 先看 [go_migration_progress.md](./go_migration_progress.md) 的最新记录，不从 Completed 标签推断进程已启动。
- [ ] 明确本次修改属于 G8 的哪个验收缺口，以及是否影响 i18n、API、任务或 Storage policy。
- [ ] 确认数据库 migration authority：`component_repo` 归 Goose，Supabase `storage` policy 暂归 Alembic。
- [ ] 若操作真实数据库或 Storage，确认目标项目和凭据权限；任何 reset/reseed 仍需再次明确确认。

完成后：

- [ ] 运行与风险相称的 Go、PostgreSQL 和前端验证；Component Repo task 不再要求 Python Worker 验证。
- [ ] 对异步功能同时验证 API 创建任务和 Worker 实际消费，不能只检查 `202`。
- [ ] 检查任务是否产生预期 event/outbox，队列是否残留 queued/running/stale lease。
- [ ] 用真实 Supabase RLS 验证 owner 与非 owner 场景，不能只依赖 fake Storage。
- [ ] 更新 [go_migration_progress.md](./go_migration_progress.md)，记录事实、命令、遗留和下一步。
- [ ] 只有旧 Python 公共路由和 Component Repo Python 公共启动入口全部删除，且 G8
  Go-only 验收通过后，才能把 G8 标记为 Completed。

## 6. 状态更新规则

本文件以当前决策为主，不继续累积会误导实施的旧建议。后续处理完某项后：

1. 在 [go_migration_progress.md](./go_migration_progress.md) 追加带日期的证据记录；
2. 更新本文件的当前剩余工作和主链问题状态；
3. 历史证据保留在进度台账；本指南中已失效的步骤可以直接删除或压缩为归档说明；
4. 不以单元测试替代真实 Worker、真实 Supabase RLS 或浏览器切换验收。

## 7. 2026-08-23 上传、BOM 与整体 GLB 主链问题清单

状态：核心主链已完成并通过真实页面验收；仅渲染精度与压缩优化继续开放。

当前产品目标收敛为：用户在组件管理中上传一个 Studio `.io` 后，系统能够在不依赖 Python、
不依赖浏览器页面持续打开的情况下，持久化得到该组件实际使用的零件清单和对应的
ComponentVersion 整体 GLB。关系检测、connector/interface 审核、可选版本验证与发布仍可保留，
但不进入这条上传主链的默认完成条件。

交互和运行边界已经明确：API 管理上传会话与精确 Storage key，浏览器只向该目标直传；upload
complete 返回 `202` 后前端不再发起解析或首次 GLB 物化 mutation。服务端持久任务链负责
`verify -> parse/BOM -> GLB`。聚合
状态在 BOM 与 verified GLB 同时可用前保持 `processing`，页面不挂载 Viewer、不请求预览 URL，只用
typed semantic key 渲染处理提示。

上传弹窗的生命周期到 complete `202` 为止，不能在弹窗内等待上述 Worker 链。前端收到 `importId`
后立即关闭弹窗，进入只读 Import 状态页展示“解析中”；状态页轮询只用于观察并支持刷新恢复。

### 7.1 已确认问题

| ID | 优先级 | 代码审查事实 | 当前影响 | 完成判据 |
|---|---|---|---|---|
| `UPLOAD-GLB-01` | P0 / Resolved 2026-08-23 | Go importer 原 `ldrawBOM()` 和 `partInstanceCount` 基于所有模型定义计数，已改为使用共享 Go scene expansion 的真实实例结果。 | parser v2 新导入的 BOM/summary、Validation、Relation 和 GLB 使用同一实例集合；重复 root/子模型按实例倍增，未使用定义排除。parser v1 的 immutable Snapshot 不原地改写。 | `internal/scene` 单测覆盖多 root、重复/嵌套子模型、未使用定义、cycle、transform 和 legacy `rootModelId`；Go 全量与隔离 PostgreSQL 验收通过。 |
| `UPLOAD-GLB-02` | P0 / Resolved 2026-08-23 | Parse Worker 已在写 SceneSnapshot/BOM/Candidate/Draft 的同一事务中创建首个 Preview Logical Job/Execution、设置 Version preview task，并建立 `Preview -> Parse` dependency；前端不再 POST 首次 materialize。 | 关闭页面不再使 GLB 永久 pending；Preview 仅在 Parse task succeeded 后可领取。 | 事务原子性、Logical Job 唯一性、dependency 与关闭浏览器后的 Worker 延续需要纳入集成/真实环境验收。 |
| `UPLOAD-GLB-03` | P1 / Resolved 2026-08-23 | Candidate ready 页已默认并发读取 Version Preview 与 BOM，并分别维护成功/失败状态；初次进入不再读取 relations/connectors/interfaces。 | 默认页面只呈现整体 GLB、零件清单和连接信息开关；连接审核工作台不再产生无关首屏请求。 | 用户开启开关后才并发读取 relation/connector/interface；关闭只隐藏高级工作台，不触发检测 mutation。前端 i18n check/test/build 已通过；真实浏览器网络记录仍并入 G8 总体验收。 |
| `UPLOAD-GLB-04` | P1 / Resolved 2026-08-23 | Preview Worker 允许 partial preview：冻结 Part Library 中 `geometry_status` 非 ready 或缺少 geometry 的 Part 实例从 GLB 省略，BOM 保留完整条目并返回 `geometryStatus=ready/failed/missing`；任务结果和 Artifact metadata 记录 `omittedPartRefs`、`complete`。 | 用户可在候选页和详情页准确看到哪些 Part 缺少预览几何；单个缺件不再阻断整体 GLB。ready source 的本地路径缺失、哈希漂移或递归解析失败继续作为环境/快照错误失败。 | 集成测试覆盖 BOM 状态与 partial GLB 成功；generator 升级为 `component-preview-studio-ldraw-glb-v3`，旧结果通过 generator stale 机制重建。 |
| `UPLOAD-GLB-05` | P1 / Resolved 2026-08-23 | importer、Validation、Relation 和 Preview 原有的重复 SceneSnapshot 展开已收口到 `backend-go/internal/scene`。 | root、递归、transform、cycle/depth、Part 规范化和实例路径只有一套实现。 | 调用方只保留领域投影；共享包聚焦测试、`make check` 与隔离 PostgreSQL 均通过。 |
| `UPLOAD-GLB-06` | P2 | 当前 Go GLB 只递归 type 1/3/4，忽略 BFC/TEXMAP，GLB 没有 NORMAL，Part 内部颜色继承/多材质未建模；颜色表只硬编码基础 code，未知颜色回落灰色。 | 普通砖块可形成真实表面 mesh，但印刷、多色、特殊材质和部分 Studio 零件与 Studio 视觉不完全一致。 | 以新 generator version 逐步接入版本化 `LDConfig.ldr` 颜色、16/24 继承、BFC/normal、多材质；TEXMAP/特殊件单列 fixture 和支持边界，不静默声称完全一致。 |
| `UPLOAD-GLB-07` | P2 | 当前 Go Component GLB 为 uncompressed；旧 Python 预热路径曾执行 meshopt。 | 整体 GLB 占用更多 Supabase Storage 和网络带宽，组件多版本时会放大容量压力。 | 在 Go-only Worker 边界内选择可部署的压缩方案，升级 generator version，以代表组件对比压缩前后字节数、加载兼容性和生成耗时；继续只默认保存整体 Component GLB，不把批量 Part GLB 设为前置条件。 |
| `UPLOAD-GLB-08` | P0 / Resolved 2026-08-23 | SceneSnapshot schema v2 已在 document 中增加有序 `rootInstances[]`；数据库 `root_model_id` 仅保留单主模型投影，不再是展开器的唯一输入。 | 多个显式 root 分别展开并合并，不做实例去重；普通 Studio/MPD 仍生成一个 identity root；未引用定义不会被猜成 root。 | 多 root 与同模型多入口测试通过；parser/snapshot 默认版本升级到 v2，旧 v1 快照通过 `rootModelId` 只读适配但不原地改写 BOM。 |
| `UPLOAD-GLB-09` | P0 / Resolved 2026-08-23 | Import API 已聚合 Import、Snapshot/BOM、Draft Version、Preview Task 和 verified Preview Artifact 为 `processing/ready/failed`；上传前端轮询该投影，ready 前不进入候选页，Preview loader 不再主动 materialize。 | parse succeeded 不再被误判为可预览。 | 真实浏览器仍需验证处理中无 Preview URL/Viewer 请求；ready 结果页已由 `UPLOAD-GLB-03` 收口为 GLB/BOM 默认展示。 |
| `UPLOAD-GLB-10` | P0 / Resolved by decision and policy 2026-08-23 | 保留 API 控制的浏览器直传：API 生成并持久化 bucket/objectPath，浏览器使用用户 JWT 直传精确目标；Alembic `20260823_0024` 将 INSERT RLS 收紧为 pending file/session、owner、expiry 与精确 key。 | API 掌握可信 key 和数据库事实，Worker 从 Artifact/Import 元数据感知对象；正文不占用 API 内存/带宽。 | 真实 Supabase 执行迁移后验证合法上传成功、任意 owner prefix key/过期 session key 被拒绝，authenticated DELETE 仍不可用。 |

### 7.2 主链保留与延后边界

上传主链必须保留：

- owner-scoped Upload Session、API 生成/持久化精确 key 与浏览器 JWT 直传 Storage；
- 原始 `.io` 不可变保存、大小/SHA-256 校验和派生 `.ldr` 来源链；
- PostgreSQL durable task、SceneSnapshot、冻结 Part Library Version、Component/Draft Version；
- Version-addressed BOM 与可重建 GLB Artifact。
- upload complete 后由服务端持久串联的 `verify -> parse/BOM -> GLB` continuation，以及可恢复的聚合处理状态。

默认上传完成条件不包含：

- relation detection、connector/interface 审核；
- 可选版本验证与发布（两者相互独立）；
- clearance/raycast 精确碰撞求解；
- 批量物化每个 Part 的独立 GLB。

Candidate/Relation/Validation schema 暂不为本目标删除。它们仍承载当前来源链和可选质量报告；先从
默认页面和任务编排中解除耦合，等上传主链验收后再单独评估数据模型简化。

### 7.3 推荐解决顺序

1. [x] `UPLOAD-GLB-01` + `UPLOAD-GLB-05` + `UPLOAD-GLB-08`：已固定显式 root instance 集合并统一 world-part 展开，parser v2 BOM 已修正。
2. [x] `UPLOAD-GLB-10`：确认 API 控制的浏览器直传，并用精确 upload-session RLS 封闭任意 key 写入。
3. [x] `UPLOAD-GLB-02`：把现有 Preview durable task 自动串到 Parse 成功之后，消除浏览器依赖。
4. [x] `UPLOAD-GLB-09` + `UPLOAD-GLB-03`：增加聚合 ready 门禁；处理中只显示本地化状态；ready 后默认
   展示 Version BOM 与整体 GLB，连接审核工作台通过开关按需加载。
5. [x] `UPLOAD-GLB-04`：BOM 已返回逐 Part geometry 状态，partial GLB 跳过缺件并记录 omissions；
   用户真实页面验收通过。
6. `UPLOAD-GLB-06`、`UPLOAD-GLB-07`：以 generator version 管理渲染精度和压缩升级。
