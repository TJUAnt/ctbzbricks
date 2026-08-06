# Repository instructions for coding agents

These instructions apply to the entire repository.

## Mandatory Go migration preflight

BrickBuilder is migrating from a Python/FastAPI backend to a Go system backend, beginning with Component Repo. Before changing Go backend code, Component Repo APIs, Component Repo persistence, artifact storage, or the shared task system, read:

1. `docs/go_backend_migration_principles.md` — approved target architecture and non-negotiable migration rules.
2. `docs/go_component_migration_plan.md` — phase boundaries, dependencies, API direction, and acceptance gates.
3. `docs/go_migration_progress.md` — completed facts, current phase, and next work.

At the beginning of implementation, identify the migration phase being changed. At completion, update `docs/go_migration_progress.md` with evidence and validation results. Do not mark a phase complete because scaffolding or planning exists.

### Non-negotiable Go migration rules

- Go is the system backend; Python remains only for explicit algorithm-worker responsibilities after a domain migrates.
- Build a modular monolith first: Gin API plus independently runnable Workers. Do not introduce a business gateway or Component Repo microservice without a new approved decision.
- New Go persistence is PostgreSQL-only and uses `sqlc` with `pgx/v5`/`pgxpool`. Do not add MySQL compatibility or an ORM alongside sqlc.
- `sqlc` generates data-access code but does not own migrations. Migration authority is assigned by PostgreSQL schema/domain: Goose exclusively owns `component_repo`; Alembic temporarily owns unmigrated legacy objects in `public`. Never let both tools evolve the same schema object, table, sequence, function, or policy.
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
