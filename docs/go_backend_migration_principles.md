# Go 后端迁移原则

> 状态：Approved target architecture
> 生效日期：2026-08-06
> 首个迁移域：Component Repo
> 路线图：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 进度台账：[go_migration_progress.md](./go_migration_progress.md)

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
Go Worker / Python Worker
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
- Go 是系统主体；Python 只作为科学计算、复杂算法和迁移期算法插件。

## 2. 开发阶段策略

项目尚未生产，迁移不承担历史客户端、在线流量或旧开发数据兼容义务：

- 可以重新设计组件 API，并统一使用 `/api/v1`。
- 可以整理或重建开发数据库 schema；实际执行清库或重置前仍需明确确认目标。
- 不保留 MySQL fallback。
- 不做双写、影子流量、灰度兼容层或 Gin 到 FastAPI 的业务代理。
- 不逐函数翻译 Python；按目标领域模型和事务边界重新实现。
- 新 Go 能力完成验收后直接切换前端，并删除对应 Python 组件路由与服务。

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

### 3.3 Worker 分工

Go Worker 默认负责：

- 文件校验、hash、归档读取和常规解析；
- 规则计算、网格、搜索、动态规划和拼搭校验；
- 对象存储读写和派生资产编排；
- 适合高并发或低延迟的确定性计算。

Python Worker 负责：

- NumPy、SciPy、OpenCV、OR-Tools 和机器学习；
- 复杂 3D、拟合或已有 Python 算法插件；
- 尚未迁移到 Go 的组件算法，但不得继续承载公共 HTTP API。

任务协议必须与实现语言无关。任务结果写回 PostgreSQL 和对象存储，不能只存在于进程内内存。

## 4. 数据库原则

### 4.1 PostgreSQL-only

新 Go 后端只支持 PostgreSQL。不得为 MySQL、SQLite 或 ORM 方言兼容降低 SQL 设计质量。SQLite 可以用于与生产语义无关的纯函数测试，但不能替代 PostgreSQL 集成测试。

### 4.2 单一 schema authority

任何时刻只能有一个生产 schema migration authority：

1. 在 Go schema baseline 被验收前，现有 Alembic 仍是当前数据库 authority。
2. 迁移计划的数据库基线阶段完成一次性交接。
3. 交接后，`backend-go/db/migrations` 与 Goose 成为唯一 authority，Alembic 冻结并不再新增 revision。
4. 禁止 Alembic 与 Goose 并行修改同一数据库。

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

任务至少包含：

```text
id
task_type
status
payload_json
result_json / result_artifact_id
locale
timezone
created_by
idempotency_key
attempts / max_attempts
available_at
lease_owner / lease_expires_at
progress_code / progress_params_json / progress_percent
error_code / error_params_json
created_at / started_at / finished_at
```

执行规则：

- Worker 使用 `FOR UPDATE SKIP LOCKED` 短事务领取任务。
- 领取后写 lease，计算期间不持有领取事务。
- 任务必须支持超时重领、有限重试和幂等执行。
- 业务状态与任务/outbox 创建需要原子一致时，必须放在同一事务。
- `LISTEN/NOTIFY` 只能作为唤醒优化，任务表才是事实来源。
- 不保存最终展示句子、原始异常正文、SQL、路径或堆栈。

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

- 目标功能由 Go API 或明确的 Worker 边界承担。
- schema migration、sqlc queries 和生成代码一致。
- PostgreSQL 集成测试覆盖成功、失败、授权和并发路径。
- API 错误、多语言内容边界和任务上下文符合现有架构。
- 计算未进入 Gin 长请求链路。
- 对象存储部分失败和任务重试具有幂等或补偿策略。
- 文档和 `go_migration_progress.md` 已更新。
- 被替代的 Python 公共路由和死代码已删除，除非路线图明确保留为算法插件。
