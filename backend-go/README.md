# BrickBuilder Go backend

This module is the target BrickBuilder system backend. The current migration phase is tracked in [`../docs/go_migration_progress.md`](../docs/go_migration_progress.md).

## Commands

```bash
cp .env.example .env
make generate
make check
make test-postgres
make run-api
make run-worker
make migrate-help
```

Environment files are not loaded implicitly. Export the variables through the shell, a development runner, or the deployment environment.

The API exposes:

```text
GET /health/live
GET /health/ready
```

The migration command supports `status`, `version`, `up`, `up-by-one`, `down`, `redo`, and `reset`. Goose exclusively owns the `component_repo` schema; Alembic may only manage unmigrated legacy objects outside it. Do not run destructive migration commands without confirming the exact database.

`make test-postgres` creates an isolated temporary local PostgreSQL cluster, migrates it from zero to head, runs schema contract tests, verifies a second `up` is a no-op, and confirms that API/Worker startup does not change the schema. It never uses `DATABASE_URL` from your environment.

`make generate` and `make check` use the project-level sqlc tool version pinned in `go.mod`. Generated files under `db/generated` must not be edited manually.
