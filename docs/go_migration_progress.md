# Go 后端迁移进度

> 最后更新：2026-08-06（G1）
> 状态依据：[go_component_migration_plan.md](./go_component_migration_plan.md)
> 更新规则：只记录已经由代码、测试或文档证据证明的事实。

## 1. 当前摘要

| 阶段 | 状态 | 说明 |
|---|---|---|
| G0 原则、路线与工程决策 | Completed | 目标架构、迁移原则、阶段和完成定义已入库 |
| G1 Go 工程骨架 | Completed | API、Worker、migration、sqlc/pgxpool 与测试骨架已验收 |
| G2 PostgreSQL schema baseline | Not started | 下一实施阶段 |
| G3 组件目录、版本和分组 | Not started | 等待 G2 |
| G4 Artifact 与上传会话 | Not started | 等待 G3 核心实体稳定 |
| G5 持久化任务系统 | Not started | 等待 G2，可与 G4 局部并行设计 |
| G6 导入、解析与候选流程 | Not started | 等待 G4/G5 |
| G7 关系、接口、校验和预览 | Not started | 等待 G6 |
| G8 前端切换与 Python API 删除 | Not started | 等待 Go 组件闭环 |

当前已有可运行的 Go 工程骨架和 sqlc 生成代码，但还没有 Component Repo 业务 API、Go schema baseline 或已切换的前端接口。不得把工程骨架完成等同于组件迁移完成。

## 2. 已确认决策

- [x] Go 作为后端系统主体，Python 作为算法插件。
- [x] 技术栈采用 Gin、PostgreSQL、sqlc、pgx/v5、pgxpool。
- [x] 增加 Goose 作为 Go 目标 schema migration 工具。
- [x] 当前开发阶段不承担旧 API、在线流量、MySQL 或开发数据兼容义务。
- [x] 采用模块化单体 API，不开发 Go 业务网关。
- [x] 组件长任务通过 PostgreSQL 持久化队列异步执行。
- [x] Gin 不同步执行文件解析、复杂几何和长时间计算。
- [x] 新组件 API 使用 `/api/v1`，不要求复刻旧 FastAPI DTO。
- [x] 迁移期间禁止 Alembic 与 Goose 并行拥有 schema；在 G2 完成一次性交接。
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

## 5. 阻塞与风险

当前无外部阻塞。

进入 G2 前需要做出的数据库决策：

- 哪些现有 Component Repo 表直接保留；
- 是否合并 `component_artifacts` 为通用 `artifacts`；
- 现有开发数据是否 reset/reseed；
- RLS 继续由 PostgreSQL policy 承担的范围；
- Alembic head 与 Goose baseline 的一次性交接方式。

这些是 G2 的首批决策项。

## 6. 更新模板

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
