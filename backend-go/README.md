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

G3 also exposes the authenticated Component Repo catalog under `/api/v1`:

```text
/components
/components/:componentId/versions
/component-versions/:versionId
/component-groups
/component-groups/:groupId/components
/components/:componentId/subscription
```

Component Repo routes require an HS256 Bearer JWT. `AUTH_JWT_SECRET` verifies the signature; optional `AUTH_JWT_ISSUER` and `AUTH_JWT_AUDIENCE` restrict claims. The verified UUID `sub` is the actor identity. Missing auth configuration fails closed for these routes while health endpoints remain available.

User-authored Component and Group content is returned verbatim with normalized `contentLocale`. Official Components select only a `reviewed` translation for the requested `locale`; otherwise they return source content and its actual `contentLocale`.

The migration command supports `status`, `version`, `up`, `up-by-one`, `down`, `redo`, and `reset`. Goose exclusively owns the `component_repo` schema; Alembic may only manage unmigrated legacy objects outside it. Do not run destructive migration commands without confirming the exact database.

`make test-postgres` creates an isolated temporary local PostgreSQL cluster, migrates it from zero to head, runs schema contract tests, verifies a second `up` is a no-op, and confirms that API/Worker startup does not change the schema. It never uses `DATABASE_URL` from your environment.

`make generate` and `make check` use the project-level sqlc tool version pinned in `go.mod`. Generated files under `db/generated` must not be edited manually.
