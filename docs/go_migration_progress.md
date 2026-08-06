# Go 后端迁移进度

> 最后更新：2026-08-06（G2）
> 状态依据：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 更新规则：只记录已经由代码、测试或文档证据证明的事实。

## 1. 当前摘要

| 阶段 | 状态 | 说明 |
|---|---|---|
| G0 原则、路线与工程决策 | Completed | 目标架构、迁移原则、阶段和完成定义已入库 |
| G1 Go 工程骨架 | Completed | API、Worker、migration、sqlc/pgxpool 与测试骨架已验收 |
| G2 PostgreSQL schema baseline | Completed | `component_repo` baseline、authority、sqlc 与 PostgreSQL contract 已验收 |
| G3 组件目录、版本和分组 | Not started | 下一实施阶段 |
| G4 Artifact 与上传会话 | Not started | 等待 G3 核心实体稳定 |
| G5 持久化任务系统 | Not started | 等待 G2，可与 G4 局部并行设计 |
| G6 导入、解析与候选流程 | Not started | 等待 G4/G5 |
| G7 关系、接口、校验和预览 | Not started | 等待 G6 |
| G8 前端切换与 Python API 删除 | Not started | 等待 Go 组件闭环 |

当前已有可运行的 Go 工程骨架、Goose 管理的 `component_repo` schema baseline 和 sqlc 生成类型，但还没有 Component Repo 业务 API 或已切换的前端接口。不得把 schema 完成等同于组件业务迁移完成。

## 2. 已确认决策

- [x] Go 作为后端系统主体，Python 作为算法插件。
- [x] 技术栈采用 Gin、PostgreSQL、sqlc、pgx/v5、pgxpool。
- [x] 增加 Goose 作为 Go 目标 schema migration 工具。
- [x] 当前开发阶段不承担旧 API、在线流量、MySQL 或开发数据兼容义务。
- [x] 采用模块化单体 API，不开发 Go 业务网关。
- [x] 组件长任务通过 PostgreSQL 持久化队列异步执行。
- [x] Gin 不同步执行文件解析、复杂几何和长时间计算。
- [x] 新组件 API 使用 `/api/v1`，不要求复刻旧 FastAPI DTO。
- [x] migration authority 按 PostgreSQL schema/domain 分配：Goose 独占 `component_repo`，Alembic 暂时只管理未迁移的 legacy `public` 域。
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

## 6. 阻塞与风险

当前无外部阻塞。

进入 G3 的已知实现重点：

- 所有 sqlc 业务查询仍必须显式包含 owner/actor 条件，不能因为 RLS 已 enable 就省略应用授权。
- ComponentGroup 的循环检测、最大深度和移动排序需要在显式 pgx transaction 中实现。
- 官方 translation 查询只能选择 `reviewed`；用户内容必须保留 `content_locale` 和原文。
- G2 只建立 task schema，任务领取、lease、重试和 outbox 发布逻辑属于 G5。

实际开发库是否 reset/reseed 尚未决定；若以后执行，仍需先确认精确数据库目标。

## 7. 更新模板

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
