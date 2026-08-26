# Repository instructions for coding agents

These instructions apply to the entire repository.

## Mandatory Go migration preflight

BrickBuilder is migrating from a Python/FastAPI backend to a Go system backend, beginning with Component Repo. Before changing Go backend code, Component Repo APIs, Component Repo persistence, artifact storage, or the shared task system, read:

1. `docs/go_backend_migration_principles.md` — approved target architecture and non-negotiable migration rules.
2. `docs/go_component_migration_plan.md` — phase boundaries, dependencies, API direction, and acceptance gates.
3. `docs/api.md` — current Component Repo Go endpoints, ownership boundaries, and execution logic.
4. `docs/go_migration_progress.md` — completed facts, current phase, and next work.

At the beginning of implementation, identify the migration phase being changed. At completion, update
`docs/go_migration_progress.md` with evidence and validation results, and update `docs/api.md` whenever a
Component Repo route, request/response contract, authorization boundary, or execution flow changes. Do not mark
a phase complete because scaffolding or planning exists.

### Non-negotiable Go migration rules

- Go is the system backend. Component Repo's target runtime is Go-only: its public API and persistent task
  consumers must run in Go. `component.relations.detect` is a temporary migration exception, not a permanent
  Python boundary; do not add new Component Repo Python task types or expand that exception. Other domains may
  retain explicit Python algorithm workers only when their own approved roadmap says so.
- Build a modular monolith first: Gin API plus independently runnable Workers. Do not introduce a business gateway or Component Repo microservice without a new approved decision.
- New Go persistence is PostgreSQL-only and uses `sqlc` with `pgx/v5`/`pgxpool`. Do not add MySQL compatibility or an ORM alongside sqlc.
- `sqlc` generates data-access code but does not own migrations. Migration authority is assigned by PostgreSQL schema/domain: Goose exclusively owns `component_repo`; Alembic temporarily owns unmigrated legacy objects in `public` and the already-established Supabase policies in the provider-owned `storage` schema. Goose must not manage `storage`, Alembic must not manage `component_repo`, and no object may have two authorities.
- API and Worker startup must not run DDL, schema repair, or data backfills.
- Gin handlers perform bounded HTTP work. File parsing, geometry, search, dynamic programming, validation, and derived-asset generation run as persistent tasks when they can be long-running.
- Task state is durable in PostgreSQL. In-memory goroutines, process-local queues, and request background callbacks are not authoritative task systems.
- PostgreSQL stores business and task metadata; object storage stores uploaded source files and large derived artifacts. Preserve source/derived and owner boundaries.
- New Component Repo APIs use `/api/v1` and may replace the development FastAPI contract directly. Do not add dual-write, compatibility proxy, or shadow-traffic infrastructure unless the user explicitly changes the migration strategy.
- Destructive development database reset/reseed is allowed by the target plan but still requires explicit confirmation of the exact database before execution.
- Generated sqlc files are never manually edited. Business SQL lives in versioned query files and multi-step writes use explicit pgx transactions.
- Preserve the approved i18n, content, API-error, ownership, immutable-version, and storage-security invariants during the rewrite.

## Mandatory i18n preflight

BrickBuilder uses an approved end-to-end multilingual architecture. Before changing any UI, API, background task, validation result, persisted content, configuration label, or export, read:

1. `I18N_CHANGE_GUARDRAILS.md` — mandatory task-level rules and decision table.
2. `I18N_ARCHITECTURE.md` — system architecture and invariants.
3. `I18N_FIELD_CLASSIFICATION.md` — machine, user-authored, official, and system-content boundaries.
4. `I18N_GOVERNANCE.md` — ownership, review, version, and release rules when resources change.

At the beginning of the task, tell the user which i18n surfaces are affected. If none are affected, explicitly state that the task has no user-visible or locale-sensitive impact. Do not begin implementation until this classification is made.

## Non-negotiable architecture rules

- UI text uses typed semantic keys. Never add user-visible hardcoded Chinese or English to TS/TSX or display configuration.
- Machine values, IDs, enum values, database keys, API codes, and JSON property names are never translated.
- Public API errors and task messages use stable `code + params`; never expose `str(error)`, stack traces, paths, SQL, or final translated text.
- User-authored content is preserved verbatim with `contentLocale`; never machine-translate it or treat it as a resource key.
- Official Component/Part content uses translation tables, and only `reviewed` translations may be selected.
- Locale-sensitive requests and tasks carry normalized locale/timezone context. Async work must not read the browser's later language state.
- Server-generated exports use frozen `ExportContext` and versioned server resources. Keep machine fields stable and localize only human-facing metadata.
- Adding a production language is catalog/resource work, not a business-code branch. Never add `if (locale === ...)` behavior to feature code.
- Missing resources fail CI. Do not add `defaultValue`, source-text fallbacks, compatibility shims, or silent missing-key behavior.
- Resource changes require catalog version, content hash, and `I18N_RELEASE_NOTES.md` updates.

## Mandatory Chinese code comments

- 新增或实质修改的代码接口、公开入口和主要执行入口必须添加清晰的中文注释，包括但不限于：
  导出函数与类型、HTTP Handler、应用服务方法、Worker/Task Handler、存储边界、数据迁移或维护命令，
  以及不易直接理解的 SQL 查询和迁移逻辑。
- 接口注释应按实际需要说明职责、重要输入与输出、授权或所有权边界、事务或异步边界，以及关键副作用；
  不得只重复函数名、类型名或代码字面含义。
- 主要业务逻辑必须在关键决策点添加中文注释，重点解释“为什么这样处理”以及必须维持的不变量，尤其是
  幂等、重试、任务依赖、事务一致性、不可变版本、源文件与派生资产边界、对象存储补偿，以及
  Scene/BOM/几何算法等逻辑。避免逐行翻译代码或为显而易见的语句添加噪声注释。
- 修改既有接口或主要逻辑时，必须同步检查并更新附近的中文注释；与代码行为不一致的过期注释视为缺陷。
- 中文代码注释只用于开发者文档，不得作为用户可见文案、API 最终错误消息或持久化翻译内容；稳定机器值、
  标识符、JSON 字段、API/Task/Error Code 和 SQL 标识符仍遵守现有 i18n 与接口规则。
- 生成文件（包括 sqlc 生成代码）以及 vendored/第三方代码不适用本规则，且不得为了补充注释而手工修改；
  相关说明应写在手写源码、SQL 查询文件或迁移文件中。
- 代码注释是对 `docs/api.md`、迁移文档和测试的补充，不能替代这些文档及验证要求。

## Required completion checks

For any i18n-affecting change, run:

```bash
cd frontend
npm run i18n:check
npm test
npm run build

cd ../backend
python -m pytest
```

Also update architecture, field classification, governance, or release documentation when a contract or boundary changes. In the final handoff, report the i18n impact and validation results.

If a requested change conflicts with these rules, stop and explain the conflict instead of introducing a parallel localization mechanism.
