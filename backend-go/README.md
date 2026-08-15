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

From the repository root, `scripts/start-backend.sh` starts the Go API for
local development. The independent `start-go-worker`,
`start-component-import-worker`, `start-component-relation-worker`, and
`start-legacy-backend` launchers start the remaining G8 mixed topology.
They load shared connection values from `backend/.env`, then optional Go-only
overrides from `backend-go/.env`; already-exported shell variables take
precedence. Secrets remain in environment files and are not embedded in the
scripts. `scripts/start-dev.sh` starts the Go API, necessary legacy API, three
Workers, and Vite, and waits for both HTTP processes before declaring readiness.
Set `START_LEGACY_API=0` or `START_COMPONENT_WORKERS=0` only for a deliberately
reduced local topology. Corresponding PowerShell launchers provide the same
process boundaries on Windows.

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
/component-imports/:importId
/component-candidates/:candidateId
/component-candidates/:candidateId/relations
/component-candidates/:candidateId/relations/detect
/component-candidates/:candidateId/connectors
/component-candidates/:candidateId/interfaces
/component-candidates/:candidateId/validate
/artifacts/:artifactId/download
/component-versions/:versionId/source
/component-versions/:versionId/parts
/component-versions/:versionId/preview
/component-versions/:versionId/preview/materialize
/part-library-versions/active
/part-library-versions/:partLibraryVersionId/parts/:ldrawPartNum/preview
/part-library-versions/:partLibraryVersionId/parts/:ldrawPartNum/preview/materialize
/tasks/:taskId
```

Component Repo routes require a Bearer JWT. Supabase `ES256` tokens are verified against `AUTH_JWKS_URL`, which defaults to `<AUTH_JWT_ISSUER>/.well-known/jwks.json`; public keys are selected by `kid` and cached for ten minutes. `AUTH_JWT_SECRET` remains optional for legacy `HS256` tokens during migration. `AUTH_JWT_ISSUER` and `AUTH_JWT_AUDIENCE` restrict claims, and the verified UUID `sub` is the actor identity. Missing auth configuration fails closed for these routes while health endpoints remain available.

User-authored Component and Group content is returned verbatim with normalized `contentLocale`. Official Components select only a `reviewed` translation for the requested `locale`; otherwise they return source content and its actual `contentLocale`.

G4 direct uploads use `STORAGE_PROVIDER=supabase`. The client submits filenames, sizes, hashes, locale/timezone, and optional domain targets; it cannot submit the trusted object key. The API returns an owner-scoped, server-generated `bucket + objectPath` for the Supabase client upload. Completion performs metadata-only validation and atomically creates immutable, pending-verification source Artifact records. Hash verification streams the object once; download endpoints require a verified Artifact and return only a short-lived signed URL. Provider errors and storage keys are not exposed by download responses. As in the previous Python backend, request-scoped Storage calls send `SUPABASE_PUBLISHABLE_KEY` as `apikey` and the already-verified user JWT as Bearer authorization, so Supabase RLS remains authoritative. Independent Workers use either modern `SUPABASE_SECRET_KEY` (`sb_secret_*`, sent only as `apikey`) or legacy `SUPABASE_STORAGE_SERVICE_ROLE_KEY` for server-side object reads, writes, verification, and cleanup; a Supabase-configured Worker fails startup when neither credential is present.

The independent Go Worker retries expired-upload object cleanup when Storage is enabled. Upload completion now returns `202 Accepted` and atomically creates the Import, its `component.import.parse` task, Artifact verification tasks, task dependencies, events, and outbox rows. The parse task cannot be claimed until every source Artifact verification task succeeds; a terminal verification failure is propagated to the parse task and Import without spending parser attempts.

G5 uses PostgreSQL as the authoritative task queue. Upload completion atomically enqueues owner-scoped `component.artifact.verify` tasks; the Go Worker claims only registered types with `FOR UPDATE SKIP LOCKED`, renews leases, cooperatively handles cancellation, and persists retry/terminal events plus outbox records. Clients can read and cancel owned tasks through `GET /api/v1/tasks/:taskId` and `POST /api/v1/tasks/:taskId/cancel`. The language-neutral Go/Python contract is documented in [`docs/go_task_protocol.md`](../docs/go_task_protocol.md).

G6 keeps the existing deterministic LDraw/Studio parsing algorithm behind a Python Worker adapter while Go owns the public API and durable workflow. Run it independently from the repository root:

```bash
cd backend
../.venv-app/bin/python -m src.tools.run_component_import_worker
```

The Python Worker claims only `component.import.parse`, heartbeats the PostgreSQL lease, reads verified source objects with the server-only Storage credential, and commits SceneSnapshot, BOM, structured parse issues, Candidate, draft ComponentVersion, task result, task event, and outbox event atomically. Studio `.io` imports materialize a verified derived LDraw Artifact with explicit `derived_from_artifact_id` lineage. Parser version, snapshot schema, part-library version, locale, and timezone are frozen when upload completion creates the Import. Neither Worker stores translated messages, raw exception text, SQL, stack traces, or service credentials in public task/import fields.

G7 keeps relation detection in a second independent Python algorithm Worker while Go owns review transactions, validation, preview materialization, Storage writes, signed preview reads, and localized BOM projection:

```bash
cd backend
../.venv-app/bin/python -m src.tools.run_component_relation_worker
```

`POST .../relations/detect`, `POST .../validate`, and `POST .../preview/materialize` only create durable tasks and return `202`. Relation detection never updates SceneSnapshot transforms. Relation confirmation reserves normalized connector slots through PostgreSQL constraints/triggers, removes occupied connectors from the external-interface projection, updates the Candidate and draft-version interface signature together, and invalidates stale validation. Publishing requires a succeeded, passing `publish` validation task whose structure/interface/geometry hashes still match the draft.

`GET .../preview` is read-only: it returns state and a short-lived URL only for a ready derived Artifact. The Go Worker writes a deterministic version-addressed structural GLB; if its Storage object is missing, a new materialization generation recreates the same stable derived Artifact. `GET .../parts?locale=...` loads BOM display data separately and selects only reviewed Part translations, leaving the GLB and machine part numbers locale-independent.

Part preview is a separate immutable resource keyed by `partLibraryVersionId + ldrawPartNum`; there is no generic `library-items` alias. Goose owns Part content, geometry metadata, preview state, and Artifact links. The Go Worker registers `component.part_preview.materialize` when `LDRAW_ROOT` points to the read-only, version-pinned LDraw library, recursively expands real type 1/3/4 geometry, validates the root Part file hash, and stores an uncompressed GLB as a derived Artifact. The API never reads LDraw files or generates geometry in an HTTP request. Run `db/data_migrations/20260814_public_parts_to_go.sql` explicitly after Goose v8 to hand legacy Part content and geometry to `component_repo`; API/Worker startup never performs this backfill.

The migration command supports `status`, `version`, `up`, `up-by-one`, `down`, `redo`, and `reset`. Goose exclusively owns the `component_repo` schema. Alembic temporarily owns unmigrated legacy `public` objects and the existing Supabase policies in the provider-owned `storage` schema; it must never modify `component_repo`. Do not run destructive migration commands without confirming the exact database.

`make test-postgres` creates an isolated temporary local PostgreSQL cluster, migrates it from zero to head, runs Go schema/API/task contracts and the real Python parser adapter, verifies a second `up` is a no-op, and confirms that API/Worker startup does not change the schema. It never uses `DATABASE_URL` from your environment.

`make generate` and `make check` use the project-level sqlc tool version pinned in `go.mod`. Generated files under `db/generated` must not be edited manually.
