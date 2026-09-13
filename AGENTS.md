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

## Mandatory detailed module design synchronization

- 以一个用户可见菜单或可独立访问的链接作为一个功能模块；已经批准的设计文档明确规定其他边界时，按已批准边界执行。
- 每次修改代码文件前，必须识别受影响的详细模块设计文档，并核对 `README.md` 的“详细功能设计”索引。
- 代码修改完成后、任务结束前，必须按实际实现同步更新所有受影响的详细模块设计文档，至少覆盖功能逻辑、前端调用、HTTP 接口、后端服务、持久化或任务边界、权限、i18n、关键代码索引和验证证据。
- 如果受影响功能没有对应的详细模块设计文档，必须在所属领域的文档目录中创建独立文档，并在 `README.md` 的“详细功能设计”中增加引用；不得只把新功能附加到无关模块文档中。
- 整理文档时发现的冗余、偏移、过期或不合理设计，应记录为带编号的清理项，说明代码证据、影响、依赖阶段和客观关闭条件。未经当前任务授权，不得顺手改变无关产品行为。
- 文档状态必须以代码、测试、迁移和部署证据为准；只有规划或脚手架时不得写成已实现、已部署或已验收。

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

## Mandatory SQL performance preflight and review

These rules apply whenever a change adds or materially modifies list, search, filter, pagination, count,
aggregate, translation, membership, or relationship SQL. SQL correctness and passing functional tests are not
sufficient evidence that the design is ready.

### Required design preflight

- Before implementation, record the expected cardinality and growth direction for the driving relation, the
  actor/tenant distribution, candidate-set source, filter selectivity, exact `ORDER BY`, pagination model, total
  count requirement, and whether list rows and totals must come from one consistent snapshot.
- Start actor- or tenant-scoped queries from the narrow authoritative relationship/ownership/membership index.
  Do not drive from the full business table with broad `OR`/`EXISTS` predicates when a scoped candidate relation
  can establish the result set first.
- Fix the page before running optional translations, per-row aggregates, current-version projections, preview
  metadata, or other expensive enrichments. Page-level aggregates should operate on the selected page IDs.
- An optional filter over a computed or normalized value is not indexable merely because its source columns are
  indexed. The design must choose either a demonstrably bounded candidate scan or an authoritative persisted
  projection with a predicate/order-specific index. Do not add a generic B-tree without plan evidence.
- Page-number `OFFSET` pagination is linear in the skipped row count. For actor- or tenant-scoped collections
  expected to reach 100,000 rows, use keyset/cursor pagination with the exact stable sort and a unique tiebreaker,
  or document an explicit hard result cap and a measured SLO that justifies retaining `OFFSET`.
- Treat exact `COUNT` as an independent potentially O(N) workload. Decide whether the product truly needs an
  exact total, and do not add a separate count round trip by default. If rows and totals must be mutually
  consistent, use one SQL statement or an explicit consistent read snapshot; separate statements under default
  `READ COMMITTED` do not guarantee the same snapshot.
- Leading-wildcard search does not become efficient through an ordinary B-tree. Exact machine identifiers need
  an exact-match path; fuzzy human text needs a suitable search projection/index or a bounded candidate set.
- A fixed UI/API fetch cap must never silently represent the complete collection. Any collection that can exceed
  the cap requires server-side pagination/search and visible continuation behavior.

### Required query-shape checks

- Do not assume optional-parameter `OR` predicates, JOIN conditions, or SQL textual order will short-circuit work.
  A gated `LATERAL` subquery must place the gate inside the subquery (or produce an equivalent one-time executor
  filter), and `EXPLAIN ANALYZE` must confirm that the inner node has zero loops when the feature/filter is absent.
- Translation and official-content probes must only execute when the requested projection or filter needs them.
  Confirm this with actual loop and buffer counts rather than relying on the join's `ON` condition.
- Review every plan for the real driving relation, stable ordering, row-estimate errors, nested per-row probes,
  heap fetches, sorts, spills/temp files, and hidden result caps. Verify that counts and list predicates express
  the same visibility rules.
- Every new index must correspond to the exact join, predicate, or ordering it serves. Record the supporting plan
  and consider write amplification and storage cost; an unused or speculative index is not an accepted fix.

### Required performance evidence

- Before completion, run `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` for the unfiltered case, a selective filter, the
  worst/high-match filter, the first page, and the deepest supported page or cursor path. Include materially
  different actor/tenant distributions and user/official translation mixes when those branches exist.
- Use at least 100,000 rows for a relationship expected to reach that scale. If the approved roadmap targets
  1,000,000 rows, the release gate must include a 1,000,000-row run. Record dataset shape, PostgreSQL version and
  relevant settings, warm/cold-cache caveats, plan evidence, and timings in the feature roadmap or migration
  progress document. Local timings prove query shape only and must not be presented as production SLOs.
- Functional integration tests must cover pagination stability and count/list semantics, but they do not replace
  plan review. Keep unresolved asymptotic risks as numbered review items with an owner phase and objective closure
  criteria; do not mark a phase complete while those criteria remain unmet.

### Lessons that must guide future designs

- SQL semantic correctness does not prove executor efficiency; executor loops, buffers, and scale behavior are
  part of the design contract.
- A feature can be functionally paginated and filtered while remaining asymptotically unsuitable because of deep
  `OFFSET`, exact counts, computed filters, or per-row enrichment.
- UI collection limits and backend pagination are one scalability contract; a hardcoded first-N client workflow
  is a data-loss defect once the collection can exceed N.
- Performance evidence is an implementation and release gate, not a post-implementation optimization task.

### Current product capacity and interaction decisions

- Current capacity planning uses at most 1,000 users, at most 1,000 Star relationships per actor, and at most
  1,000 active Watch relationships per actor. Closed Watch periods are append-only history and are assessed
  separately; the active-Watch estimate must not be misrepresented as a lifetime-history cap.
- These figures are the approved planning envelope, not an implicit API rejection threshold. Do not introduce a
  new hard limit or error contract unless the product explicitly approves that behavior. Reopen the scale review
  before the envelope is raised or observed data approaches it.
- Do not implement a performance remediation that materially changes an existing user interaction unless the
  user explicitly approves that product change. Record the item as deferred, validate the retained interaction
  against the approved capacity envelope, and keep an objective reopen condition.

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
```

The legacy `backend` Python test suite is temporarily excluded from this completion gate while functionality is
migrated to Go. When an i18n-affecting change also modifies `backend-go`, run the Go checks required by the
affected module and migration phase; Python regression tests are not a substitute for those checks.

Also update architecture, field classification, governance, or release documentation when a contract or boundary changes. In the final handoff, report the i18n impact and validation results.

If a requested change conflicts with these rules, stop and explain the conflict instead of introducing a parallel localization mechanism.
