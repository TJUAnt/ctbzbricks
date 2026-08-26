# Component Repo Go schema baseline

> 状态：G2 completed；当前 schema 已演进至 Goose v12
> 生效日期：2026-08-06
> migration authority：Goose / `backend-go/db/migrations`

## 1. 所有权边界

G2 新建 PostgreSQL schema `component_repo`，作为 Go Component Repo 的完整数据边界。Goose 独占该 schema 内的表、索引、约束、函数、trigger 和 RLS；Alembic 只能继续管理尚未迁移的 legacy `public` 域。

新 Go 代码不读取或写入 legacy `public.component_*` 表。由于项目尚未生产，本阶段不做数据复制、兼容 view、双写或在线切换。实际清空或重建任何开发数据库前，必须再次确认精确的 `DATABASE_URL`。

## 2. Legacy 模型清点与已执行处置

迁移启动时 legacy Python/public Component Repo 有 22 张领域表。该数字只用于解释 G2 取舍，
不表示当前 Go runtime 仍读取这些表。已执行的处置如下：

| Python/public 概念 | Go `component_repo` 处置 | 决策 |
|---|---|---|
| `components` | `components` | 保留并补充 `owner_id`、明确 content/status 约束 |
| `component_translations` | `component_translations` | 保留；官方内容专用，状态限定为 `draft/reviewed/rejected` |
| `component_versions` | `component_versions` | 保留；发布后由 trigger 保护结构字段不可变 |
| `component_groups` | `component_groups` | 保留；根节点、同级命名和 owner 关系显式约束 |
| `component_group_memberships` | `component_group_memberships` | 保留并冗余 `owner_id`，便于授权查询和 RLS |
| `component_subscriptions` | `component_subscriptions` | 保留并统一 `owner_id` 命名 |
| `component_artifacts` | `artifacts` | 重命名为域内通用资产；显式 source/derived、owner、hash、对象定位 |
| `component_upload_sessions` | `upload_sessions` + `upload_session_files` | 拆分；不再用单个 JSON 保存预期文件关系 |
| `component_imports` | `imports` | 域内简名；增加冻结 locale/timezone 与结构化失败 |
| `component_scene_snapshots` | `scene_snapshots` | 域内简名；继续保存权威解析快照 |
| `component_candidates` | `candidates` | 域内简名；review 数据仍为算法快照 JSONB |
| `component_relation_candidates` | `relation_candidates` | 域内简名；保留可审核检测结果 |
| `component_assembly_relations` | `assembly_relations` | 域内简名；保留人工确认关系 |
| `component_interfaces` | `interfaces` | 域内简名；保留确认后的外部接口 |
| `component_validation_reports` | `validation_reports` | 域内简名；issue 只允许结构化 `code + params` 数据 |
| `part_library_versions` | `part_library_versions` | 保留冻结的算法输入版本 |
| `part_connector_definitions` | `part_connector_definitions` | 保留结构化 connector 数据 |
| Studio collider definitions | `part_collider_definitions` / library metadata | Goose v10 新增可选逐行表；小容量环境默认只保存已验证 count/hash/parser/storage mode，精确求解所需的大型 collider bundle 应进入对象存储 |
| `component_connector_analyses` | `connector_analyses` | 保留，供 G7 Worker 结果物化 |
| `component_connector_analysis_items` | `connector_analysis_items` | 保留结构化坐标、方向、状态和 eligibility |
| analysis path/blocker/relation 三表 | 同名域内简化表 | 保留，避免把可查询关系退回 JSONB |

新增共享基础表：

- `tasks`：持久化任务事实来源，冻结 locale/timezone，支持 lease、重试、幂等和结构化进度/错误。
- `task_events`：任务状态历史，只保存机器 code 与 params。
- `outbox_events`：业务事务与异步发布的原子边界。

## 3. 数据类型和不变量

- 对外实体 ID 与 actor/owner ID 统一为 UUID，由 Go 在写入前生成，不依赖数据库扩展。
- 时间统一为 `timestamptz`；schema 默认值使用 `now()`，应用边界使用 UTC。
- 机器状态、类型、错误 code、JSON property name、对象 key 和算法版本不翻译。
- 用户 Component 与 Group 保存规范化 `content_locale`，正文原样保存。
- 官方 Component 使用 translation 表；G3 查询只能选择 `translation_status = 'reviewed'`。
- JSONB 仅用于算法快照、扩展 metadata 和结构化 `params`，所有权、状态、关系、lease 与幂等字段必须为列。
- Part Library 的 `status` 只表达生命周期；Goose v10 的 `preview_ready/relation_ready` 分别表达
  preview/关系能力。connector/collider count、source hash 和 parser version 为显式审计列。
- source artifact 必须不可变；对象定位 `(storage_provider, storage_bucket, storage_key)` 唯一。
- `component_versions` 一旦进入 `published/deprecated/archived`，结构、hash、源资产和算法版本字段不可更新；生命周期状态和派生 preview 字段仍可按业务流程更新。
- Goose v13 将整体预览 AABB、stud/plate 逻辑尺寸和 `preview_bounds_complete` 放在
  `component_versions`。这些字段描述特定不可变 SceneSnapshot 与生成器的派生结果；Component 目录只投影
  当前发布 Version（无发布版本时为最新 Draft），避免较晚完成的旧草稿任务覆盖当前尺寸。Box 使用 LDraw
  世界坐标；部分几何预览的完整性为 false，全部无可渲染几何时整组字段保持 NULL。
- `component_versions.validation_report_id` 是 Draft/Published 最近一次可选质量报告的引用；报告通过与否不构成发布门禁，也不改变已发布结构的不可变边界。
- 所有 Component Repo 表启用 RLS。baseline 不授予 `PUBLIC` schema/table 权限；G3 仍必须在所有 sqlc 业务 SQL 中显式包含 owner/actor 条件，不能把 RLS 当成唯一授权层。

## 4. sqlc 与 migration 单一来源

`sqlc.yaml` 直接读取 `db/migrations`。Goose 的 Up migration 是 schema 的唯一 SQL 来源，不再维护一份手写 scaffold schema。生成文件只由 `go tool sqlc generate` 更新。

API 与 Worker 启动路径不导入 Goose migration 包，也不执行 DDL。migration 只能由 `cmd/migrate` 或显式部署步骤运行。

## 5. 开发 reset/reseed runbook

本 runbook 只是操作约束，不授权自动清库：

1. 明确展示并人工确认目标 `DATABASE_URL`、数据库名和主机；禁止对未确认目标运行 `reset`。
2. 备份仍需保留的开发数据或对象 metadata。
3. 对全新/隔离数据库执行 `go run ./cmd/migrate up`。
4. 使用 `go run ./cmd/migrate status` 与 PostgreSQL contract tests 验证 head。
5. 仅在已明确确认的临时或开发数据库执行 `go run ./cmd/migrate reset`；该命令会删除整个 `component_repo` schema。
6. reseed 必须调用版本化 seed 命令或导入任务；不得把环境专属用户内容写进 baseline migration。

G2 验收使用本机创建的隔离临时 PostgreSQL cluster，不连接现有开发数据库。

## 6. S5 schema extension（Goose v10）

`00010_part_library_connectivity.sql` 在 baseline 上增加：

- `part_library_versions.preview_ready/relation_ready`；
- connector/collider count、source SHA-256 和 parser version；
- `part_collider_definitions`，唯一键为
  `(part_library_version_id, source_collider_id)`，并保存 part、kind、position、orientation、
  normalized half-extents 与原始结构化参数；
- count、hash、readiness 的 check constraint 与 collider RLS。

Goose 仍是这些对象的唯一 authority。API/Worker startup 不会执行 v10；真实环境必须在确认
目标数据库后显式迁移，再运行 Studio importer v2。

Goose v11 删除 Go relation query path 未使用的 connector type/gender 全局索引。按冻结 library +
part number 的索引继续保留。Studio collider 默认使用 `metadata-only`：`collider_count/source_hash/
parser_version` 表示完整输入已解析验证，不表示对应数量的 PostgreSQL 行已经物化。
