# Go 后端迁移原则

> 状态：Approved target architecture（Component Repo Go-only）
> 生效日期：2026-08-06
> Component Repo Go-only 修订：2026-08-22
> Component 上传边界修订：2026-08-23
> 发布与验证边界修订：2026-08-24
> 首个迁移域：Component Repo
> 路线图：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 进度台账：[go_migration_progress.md](./go_migration_progress.md)

文档口径冲突时按以下顺序解释：本文的长期原则与已确认决策优先；阶段范围以迁移计划为准；
schema、任务和 Part Library 细节分别以专项 contract/roadmap 为准；当前完成事实以进度台账最后记录为准；
带日期的 inventory、Review 和执行记录只描述当时事实，不能覆盖后续目标决策。

## 1. 目标

BrickBuilder 后端逐步转为以下主体架构：

```text
Nginx / 云负载均衡
        ↓
多个无状态 Gin API 实例
        ↓
PostgreSQL + 对象存储
        ↓
PostgreSQL 持久化任务队列
        ↓
Go Worker
```

目标技术栈：

```text
Gin + PostgreSQL + sqlc + pgx/v5 + pgxpool + Goose
```

- Gin 负责 HTTP API、middleware、参数绑定和响应。
- sqlc 根据 PostgreSQL schema 与手写 SQL 生成类型安全的数据访问代码。
- pgx/pgxpool 负责 PostgreSQL 驱动、事务和连接池。
- Goose 负责版本化数据库 migration；sqlc 不承担 migration。
- PostgreSQL 保存业务数据、任务、任务状态和 outbox。
- 对象存储保存上传源文件和大型派生文件。
- Go 是系统主体。
- **Component Repo 的目标运行时是 Go-only**：公共 API、事务编排、持久任务消费、解析、
  关系检测、校验、预览和 Part Library 工具链最终都由 Go 承担，不以 Python 进程作为功能可用前提。
- 其他尚未迁移领域是否保留 Python，由各自路线图单独决定；不得据此声称整个 BrickBuilder
  后端已经 Go-only。

### 1.1 Component Repo Go-only 决策边界

- `component.relations.detect` 已迁移为 Go Worker handler；Component Repo 不再允许 Python task
  consumer。不得新增 Python task type、公共 API 或持久化模型。
- 新增 Component Repo 功能默认直接使用 Go。若现有 Python 算法阻碍功能开发，应先固定输入、输出、
  golden fixture 和 PostgreSQL 不变量，再迁移为 Go handler。
- 语言无关的任务协议用于保证迁移期间可替换和可验收，不表示执行语言可以永久漂移。
- Component Repo Go-only 完成的判据是：停止 Python 进程后，完整 Component Repo 业务链路仍可运行，
  且仓库不再保留 Component Repo Python 公共路由或任务执行入口。

## 2. 开发阶段策略

项目尚未生产，迁移不承担历史客户端、在线流量或旧开发数据兼容义务：

- 可以重新设计组件 API，并统一使用 `/api/v1`。
- 可以整理或重建开发数据库 schema；实际执行清库或重置前仍需明确确认目标。
- 不保留 MySQL fallback。
- 不做双写、影子流量、灰度兼容层或 Gin 到 FastAPI 的业务代理。
- 不逐函数翻译 Python；按目标领域模型和事务边界重新实现。
- 新 Go 能力完成验收后直接切换前端，并删除对应 Python 组件路由、Worker 入口与仅服务该实现的代码。

历史 ADR 仍用于解释组件领域不变量。若历史文档的技术实现与本文冲突，以本文的 Go 目标架构为准；领域数据完整性、对象所有权、国际化和安全不变量继续有效。

## 3. 架构边界

### 3.1 模块化单体优先

当前只构建一个 Gin API 和按能力部署的 Worker，不拆组件微服务，也不开发业务网关。

推荐调用结构：

```text
Gin Handler -> Application Service -> sqlc Queries -> PostgreSQL
```

- Handler 不包含业务规则和 SQL。
- Application Service 负责授权、事务、幂等和领域编排。
- SQL 保存在按领域拆分的 query 文件中。
- 只有对象存储、认证、任务执行器等确实存在替换需求的边界才定义 interface。
- sqlc 生成代码禁止手工修改。

### 3.2 API、计算、存储分离

Gin 请求链路只执行有界的验证、查询、事务和任务创建。以下工作不得在 API 请求中同步长时间执行：

- Studio/LDraw 大文件解析；
- 网格和几何生成；
- 连接识别与大规模搜索；
- 动态规划、组合优化和复杂校验；
- GLB 等大型派生资产生成。

这些工作必须通过持久化任务交给 Worker。API 返回任务 ID，客户端查询状态和结果。

#### 3.2.1 Component 上传交互边界

Component Repo 的普通上传流程固定为以下边界：

- Go Backend API 拥有上传控制面：校验 actor/session/file metadata，生成并持久化不可由客户端指定的
  owner-scoped bucket/object key，再把该精确上传目标返回浏览器。
- 浏览器使用当前用户 JWT 直接把文件正文传到 Object Storage；Storage INSERT RLS 必须把写入限制到
  actor 自己仍为 pending、未过期的 upload session 精确 key。浏览器不得拼接任意 key，也不得删除已完成
  或已关联 Artifact 的对象。
- API 不中转或缓存整个文件，也不在上传请求中解析模型、计算 BOM 或生成 GLB。
- 浏览器调用 upload complete 后，API 做 Storage 完成确认、有界校验、短事务和持久任务编排，
  以 `202 Accepted` 结束本次写交互。返回 `202` 不表示解析或 GLB 已完成。
- `artifact verify -> component import parse/BOM -> component preview materialize` 必须由服务端持久任务链
  继续推进。关闭、刷新或离开页面不得中断任务，也不得依赖浏览器再发起一次 materialize 请求才能得到
  上传主结果。
- 上传主结果只有在 BOM 已落库且 ComponentVersion 整体 GLB 已生成并验证后才是 `ready`。在此之前，
  前端只能读取并展示 `processing` 状态，不得挂载三维预览器、请求预览 URL 或展示旧的、尚未验证的
  任务中间产物。
- Component GLB 允许受控 partial preview：冻结 Part Library 中 geometry 为 `failed/missing` 的 Part
  保留在 BOM，并以稳定机器状态明确标注；Worker 跳过这些实例后仍可生成 verified GLB。任务结果和
  Artifact metadata 必须记录 `omittedPartRefs` 与 `complete`。若 geometry 已声明 `ready`，但 Worker
  本地 source 缺失、哈希漂移或递归解析失败，仍属于环境/快照一致性错误，不能静默降级。
- relation detection、connector/interface、validation 和 publish 是后续工作台能力，不属于普通上传主链的
  默认完成条件。
- ComponentVersion 发布与验证相互独立：owner 可以直接发布 Draft；`component.validate` 是用户显式触发的
  可选异步质量报告，不是发布前置条件。Draft/Published 都可验证，详情页只在当前报告 `passed=true` 时
  展示已通过状态；验证失败不得撤销、阻止或隐式改变版本发布状态。

`processing/ready/failed` 等为稳定机器状态。界面文案必须通过 typed semantic i18n key 渲染；不得在
TS/TSX 中硬编码“解析中”或其他最终译文。失败继续使用稳定 `code + params`。

### 3.3 Worker 分工

Go Worker 默认负责：

- 文件校验、hash、归档读取和常规解析；
- 规则计算、网格、搜索、动态规划和拼搭校验；
- 对象存储读写和派生资产编排；
- 适合高并发或低延迟的确定性计算。

对于 Component Repo，上述列表不是“Go 适合做什么”的建议，而是最终执行边界。即使算法原先使用
NumPy、SciPy、OpenCV、OR-Tools 或 Python 3D 库，也必须通过可验证的 Go 实现、受控数据生成步骤
或已批准的外部基础设施消除 Python 运行时依赖；引入外部基础设施需要单独架构决策。

Component Repo 不允许 Python task consumer；原 `component.relations.detect` 过渡 Worker 已在
Go handler 通过 PostgreSQL E2E 后删除。任务协议仍必须与实现语言无关，以保证持久状态、恢复和
可验收性，而不是为另一个运行时保留入口。

任务协议必须与实现语言无关。任务结果写回 PostgreSQL 和对象存储，不能只存在于进程内内存。

## 4. 数据库原则

### 4.1 PostgreSQL-only

新 Go 后端只支持 PostgreSQL。不得为 MySQL、SQLite 或 ORM 方言兼容降低 SQL 设计质量。SQLite 可以用于与生产语义无关的纯函数测试，但不能替代 PostgreSQL 集成测试。

### 4.2 按 schema/domain 分配 migration authority

渐进迁移期间，migration authority 以 PostgreSQL schema/domain 为所有权单元；任一数据库对象在任一时刻只能有一个 authority：

1. G2 前，Alembic 拥有现有 `public` 中的 Python/legacy 对象。
2. G2 建立独立 `component_repo` schema；此 schema 内的表、索引、约束、函数、trigger 和 RLS 只由 `backend-go/db/migrations` 与 Goose 管理。
3. Alembic 可以暂时继续管理尚未迁移的 `public` 域，以及既有 Supabase 集成在 provider-owned `storage` schema 中的 policy；不得创建、修改或删除 `component_repo` 内的任何对象。
4. Goose 不管理 Supabase `storage` schema；`component_repo` 与 `storage` 的对象和 policy 不得跨工具重复定义。
5. 后续领域迁移必须记录一次明确的所有权交接；交接后冻结该领域对应的 Alembic revision，不做双写或双 authority。
6. 当最后一个 legacy 域及 provider-owned policy 完成独立迁移或冻结后，Alembic 才整体冻结，Goose 成为应用自有 schema 的唯一 authority。

schema 隔离不是运行时兼容层。新 Go 组件代码只访问 `component_repo`，不会代理或同步 legacy `public` 组件表。

迁移在部署或显式开发命令中运行；API 和 Worker 启动不得创建表、补列、建索引或回填数据。

### 4.3 SQL 与事务

- SQL 使用 PostgreSQL 原生能力，明确列名，避免业务查询中的 `SELECT *`。
- 多步写操作必须在 Application Service 中使用显式 pgx transaction。
- 事务中使用 sqlc 生成的 `WithTx` queries。
- 计算、网络请求和对象正文上传下载不得占用长事务。
- 并发状态变更使用约束、条件更新或行锁保证，不依赖进程内 mutex。
- `jsonb` 只保存扩展字段和算法快照；高频查询、关系、状态和一致性字段必须结构化。

### 4.4 ID、时间与删除

- 对外实体使用 UUID。
- 时间使用 `timestamptz`，服务端统一写 UTC。
- 状态和类型使用稳定机器值。
- 发布版本不可变；结构变化创建新版本。
- 是否软删除由领域审计和引用需求决定，不使用全局默认策略。

## 5. 任务队列原则

初期使用 PostgreSQL 持久化任务队列，不额外引入 Redis、Kafka 或 RabbitMQ。

任务系统必须区分三个层次：

- Logical Job：同一 owner、task type、业务对象和确定性输入的逻辑计算；
- Execution：Logical Job 的一次实际执行，失败/取消后重提会创建下一次 Execution；
- Attempt：单个 Execution 因 lease 超时或可重试错误产生的领取尝试。

Logical Job 至少包含：

```text
id
owner_id / task_type
logical_key / input_hash
execution_count
latest_task_id / successful_task_id
```

Execution 至少包含：

```text
id
task_type
status
payload_json
result_json / result_artifact_id
locale
timezone
created_by
task_job_id / execution_number / retry_of_task_id
attempts / max_attempts
available_at
lease_owner / lease_expires_at
progress_code / progress_params_json / progress_percent
error_code / error_params_json
created_at / started_at / finished_at
```

执行规则：

- `(owner_id, task_type, logical_key, input_hash)` 唯一标识 Logical Job；`input_hash` 必须覆盖会改变结果的权威输入和算法/配置版本。
- 同一 Logical Job 已有 queued/running Execution 时复用该 Execution；已有可复用成功结果时直接返回；只有没有可复用结果或显式重建派生缓存时才创建下一次 Execution。
- failed/cancelled 是 Execution 终态，不得把原行改回 queued；重新提交创建同一 Job 下递增编号的新 Execution，并记录 `retry_of_task_id`。
- lease 恢复和有限重试只增加同一 Execution 的 Attempt，不创建新 Execution。
- Worker 使用 `FOR UPDATE SKIP LOCKED` 短事务领取任务。
- 领取后写 lease，计算期间不持有领取事务。
- 任务必须支持超时重领、有限重试和幂等执行。
- 业务状态与任务/outbox 创建需要原子一致时，必须放在同一事务。
- `LISTEN/NOTIFY` 只能作为唤醒优化，任务表才是事实来源。
- 不保存最终展示句子、原始异常正文、SQL、路径或堆栈。
- task event/outbox 必须携带 `taskJobId + executionNumber + attempt`，以便区分逻辑任务、执行和领取尝试。

## 6. 对象存储原则

- PostgreSQL 保存 artifact 元数据；对象正文进入对象存储。
- 原始上传是权威源数据，发布后不可覆盖。
- GLB、预览图和计算缓存是可重建派生数据。
- 每个对象保存 owner、类型、bucket、key、SHA-256、字节数和 MIME type。
- 对象路径由服务端根据已验证身份和服务端 ID 构造，客户端不能提交可信完整路径。
- 数据库提交与对象存储写入不能伪装成分布式事务；使用状态机、幂等 key 和补偿清理处理部分失败。
- 不向公共 API 暴露 provider 原始错误、内部路径或存储响应正文。

## 7. API 原则

- 新 API 使用 `/api/v1` 前缀和一致的资源命名。
- 请求和响应 DTO 与 sqlc 数据库类型分离。
- 所有分页必须有明确排序和稳定游标或页码语义。
- 状态改变不能隐藏在 GET 中。
- 创建异步工作返回 `202 Accepted`、任务 ID 和机器状态。
- mutation 应根据业务风险支持 idempotency key。
- 请求 context 必须贯穿 Handler、Service、pgx、Storage 和 Worker 调用。
- 设置请求超时、正文大小限制和优雅关闭。

公共错误统一为：

```json
{
  "error": {
    "code": "component_repo.component_not_found",
    "params": {"componentId": "..."},
    "traceId": "req_..."
  }
}
```

未知异常只记录内部日志，对外返回 `common.internal_error`。

## 8. 多语言与内容边界

Go 迁移不得建立第二套本地化机制，必须遵守仓库 i18n 文档：

- ID、状态、类型、错误 code、JSON key、Storage 定位符和算法版本永不翻译。
- 用户创建的组件、分组、标签和描述原样保存，并记录规范化 `contentLocale`。
- 官方 Component/Part 使用专属翻译表，只选择 `reviewed` 记录。
- 普通 JSON API 返回结构化错误，不返回最终译文。
- 任务创建时冻结规范化 locale 和 IANA timezone；Worker 不读取浏览器后续语言状态。
- 验证 issue、任务进度和任务错误只保存 `code + params`。
- 导出使用冻结 `ExportContext` 和版本化服务端资源。

## 9. 安全与可观测性

- 所有资源查询和写入必须显式带 owner/actor 边界，不能只依赖前端过滤。
- JWT 身份验证与业务授权分离。
- 日志使用结构化字段，至少包含 trace ID、route、status、duration 和 error code。
- API、数据库、对象存储和 Worker 使用同一 trace/correlation 语义。
- 暴露 pgxpool 使用量、等待时间、任务延迟、任务失败率和 Storage 延迟指标。
- 健康检查区分进程存活与依赖就绪。
- 凭据只来自环境或秘密管理系统，不进入仓库、日志、错误 params 或任务 payload。

## 10. 完成定义

一个 Go 迁移阶段只有在以下条件全部满足后才能标记完成：

- Component Repo 目标功能由 Go API 或 Go Worker 承担；临时 Python Worker 不能计入 Go-only 完成。
- schema migration、sqlc queries 和生成代码一致。
- PostgreSQL 集成测试覆盖成功、失败、授权和并发路径。
- API 错误、多语言内容边界和任务上下文符合现有架构。
- 计算未进入 Gin 长请求链路。
- 对象存储部分失败和任务重试具有幂等或补偿策略。
- 文档和 `go_migration_progress.md` 已更新。
- 被替代的 Component Repo Python 公共路由、Worker 入口和仅服务该实现的死代码已删除。
