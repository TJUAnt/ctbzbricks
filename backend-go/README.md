# BrickBuilder Go backend

This module is the target BrickBuilder system backend. The current migration phase is tracked in [`../docs/go_migration_progress.md`](../docs/go_migration_progress.md).

## Commands

```bash
cp .env.example .env
make generate
make check
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

The migration command supports `status`, `version`, `up`, `up-by-one`, `down`, `redo`, and `reset`. G1 contains no schema migration; G2 will add the PostgreSQL baseline and complete the Alembic-to-Goose authority handoff. Do not run destructive migration commands without confirming the exact database.

`make generate` and `make check` use the project-level sqlc tool version pinned in `go.mod`. Generated files under `db/generated` must not be edited manually.
