# ctbzbricks

A data platform for LEGO bricks.

## Mandatory architecture constraints

- Coding agents must follow [AGENTS.md](./AGENTS.md).
- Every user-visible, API, task, domain-content, or export change must start with the multilingual impact check in [I18N_CHANGE_GUARDRAILS.md](./I18N_CHANGE_GUARDRAILS.md).
- The approved system design is documented in [I18N_ARCHITECTURE.md](./I18N_ARCHITECTURE.md).
- Go backend migration work must follow the [migration principles](./docs/go_backend_migration_principles.md), [Component Repo migration plan](./docs/go_component_migration_plan.md), [Component Repo API contract](./docs/api.md), and [migration progress log](./docs/go_migration_progress.md).
- The runnable Go API/Worker scaffold is documented in [backend-go/README.md](./backend-go/README.md).
