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

The authenticated Component Repo API under `/api/v1` currently exposes:

```text
/components
/components/:componentId/versions
/component-versions/:versionId
/component-groups
/component-groups/:groupId/components
/components/:componentId/subscription
/component-imports/upload-sessions
/component-imports/upload-sessions/:sessionId/complete
/artifacts/:artifactId/download
/component-versions/:versionId/source
```

Component Repo routes require an HS256 Bearer JWT. `AUTH_JWT_SECRET` verifies the signature; optional `AUTH_JWT_ISSUER` and `AUTH_JWT_AUDIENCE` restrict claims. The verified UUID `sub` is the actor identity. Missing auth configuration fails closed for these routes while health endpoints remain available.

User-authored Component and Group content is returned verbatim with normalized `contentLocale`. Official Components select only a `reviewed` translation for the requested `locale`; otherwise they return source content and its actual `contentLocale`.

G4 direct uploads use `STORAGE_PROVIDER=supabase`. The client submits filenames, sizes, hashes, locale/timezone, and optional domain targets; it cannot submit the trusted object key. The API returns an owner-scoped, server-generated `bucket + objectPath` for the Supabase client upload. Completion performs metadata-only validation and atomically creates immutable, pending-verification source Artifact records. Hash verification streams the object once; download endpoints require a verified Artifact and return only a short-lived signed URL. Provider errors and storage keys are not exposed by download responses.

The independent Worker retries expired-upload object cleanup when Storage is enabled. G5 will add durable task claiming; G6 will atomically create the import and parse task, at which point upload completion will adopt the final `202 Accepted` task contract.

The migration command supports `status`, `version`, `up`, `up-by-one`, `down`, `redo`, and `reset`. Goose exclusively owns the `component_repo` schema; Alembic may only manage unmigrated legacy objects outside it. Do not run destructive migration commands without confirming the exact database.

`make test-postgres` creates an isolated temporary local PostgreSQL cluster, migrates it from zero to head, runs schema contract tests, verifies a second `up` is a no-op, and confirms that API/Worker startup does not change the schema. It never uses `DATABASE_URL` from your environment.

`make generate` and `make check` use the project-level sqlc tool version pinned in `go.mod`. Generated files under `db/generated` must not be edited manually.
