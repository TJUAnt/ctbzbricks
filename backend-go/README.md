# BrickBuilder Go backend

This module is the target BrickBuilder system backend. The current migration phase is tracked in [`../docs/go_migration_progress.md`](../docs/go_migration_progress.md), and every registered Component Repo endpoint is documented in [`../docs/api.md`](../docs/api.md).

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

After updating a local BrickLink Studio installation, rebuild and atomically activate the Part Library with:

```bash
cd backend-go
./scripts/update-studio-part-library.sh
```

The script loads the Go development environment, prints the resolved database target, requires an exact
confirmation, generates a fresh manifest, runs a full dry-run, applies pending Goose migrations, imports the
snapshot, and atomically retires the previous active library. For non-interactive automation, set
`CONFIRM_DATABASE_TARGET` to the exact value printed by the script. `STUDIO_ROOT` and
`STUDIO_MANIFEST_OUT_DIR` may be overridden; `SKIP_STUDIO_DRY_RUN=1` is intended only for an already-validated
snapshot. An already active and relation-ready manifest is a no-op; `FORCE_STUDIO_REIMPORT=1` is required for a
deliberate rebuild. Collider rows default to `metadata-only` because expanding the 145 MB Studio collider source
into roughly 1.88 million PostgreSQL rows exceeds the intended metadata boundary and small Supabase quotas.

From the repository root, `scripts/start-backend.sh` starts the Go API for
local development. The independent `start-go-worker` and
`start-legacy-backend` launchers start the remaining G8 topology.
They load shared connection values from `backend/.env`, then optional Go-only
overrides from `backend-go/.env`; already-exported shell variables take
precedence. Secrets remain in environment files and are not embedded in the
scripts. `scripts/start-dev.sh` starts the Go API, necessary legacy API, one Go
Worker, and Vite, and waits for both HTTP processes before declaring readiness.
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
/auth/session
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

`GET /api/v1/auth/session` is the full-page refresh boundary. The middleware first applies the same local JWT/JWKS checks, then the handler uses `SUPABASE_PUBLISHABLE_KEY` and the request JWT to confirm the minimal user identity through Supabase Auth. A provider `401/403` becomes `auth.session_invalid`; timeouts, rate limits, and provider `5xx` become `auth.session_verification_unavailable`, so the frontend only removes local credentials after an explicit invalid-session decision. Ordinary business requests do not perform this remote confirmation.

User-authored Component and Group content is returned verbatim with normalized `contentLocale`. Official Components select only a `reviewed` translation for the requested `locale`; otherwise they return source content and its actual `contentLocale`.

G4 direct uploads use `STORAGE_PROVIDER=supabase`. The client submits filenames, sizes, hashes, locale/timezone, and optional domain targets; it cannot submit the trusted object key. The API returns an owner-scoped, server-generated `bucket + objectPath` for the Supabase client upload. Completion performs metadata-only validation and atomically creates immutable, pending-verification source Artifact records. Hash verification streams the object once; download endpoints require a verified Artifact and return only a short-lived signed URL. Provider errors and storage keys are not exposed by download responses. As in the previous Python backend, request-scoped Storage calls send `SUPABASE_PUBLISHABLE_KEY` as `apikey` and the already-verified user JWT as Bearer authorization, so Supabase RLS remains authoritative. Independent Workers use either modern `SUPABASE_SECRET_KEY` (`sb_secret_*`, sent only as `apikey`) or legacy `SUPABASE_STORAGE_SERVICE_ROLE_KEY` for server-side object reads, writes, verification, and cleanup; a Supabase-configured Worker fails startup when neither credential is present.

The independent Go Worker retries expired-upload object cleanup when Storage is enabled. Upload completion now returns `202 Accepted` and atomically creates the Import, its `component.import.parse` task, Artifact verification tasks, task dependencies, events, and outbox rows. The parse task cannot be claimed until every source Artifact verification task succeeds; a terminal verification failure is propagated to the parse task and Import without spending parser attempts.

G5 uses PostgreSQL as the authoritative task queue. Upload completion atomically enqueues owner-scoped `component.artifact.verify` tasks; the Go Worker claims only registered types with `FOR UPDATE SKIP LOCKED`, renews leases, cooperatively handles cancellation, and persists retry/terminal events plus outbox records. Clients can read and cancel owned tasks through `GET /api/v1/tasks/:taskId` and `POST .../cancel`. The language-neutral persistent-task contract is documented in [`docs/go_task_protocol.md`](../docs/go_task_protocol.md); Component Repo's target runtime remains Go-only.

G6 now runs the deterministic LDraw/Studio import parser inside the Go Worker while Go owns the public API and durable workflow. Run it independently from the Go backend directory:

```bash
cd backend-go
go run ./cmd/worker
```

The Go Worker claims `component.import.parse` after its Artifact verification dependencies have succeeded, reads verified source objects with the server-only Storage credential, and commits SceneSnapshot, BOM, structured parse issues, Candidate, and draft ComponentVersion before the shared task runner marks the task succeeded. Snapshot schema `component-repo-v2` stores explicit ordered `rootInstances`; the shared Go scene expander computes BOM, summary, validation, relations, and Component GLB from actual root/submodel instances rather than model definitions. Studio `.io` imports materialize a verified derived LDraw Artifact with explicit `derived_from_artifact_id` lineage. Parser version, snapshot schema, part-library version, locale, and timezone are frozen when upload completion creates the Import. The Worker stores stable codes/params only; it does not store translated messages, raw exception text, SQL, stack traces, or service credentials in public task/import fields.

`WORKER_TASK_TYPES` can restrict a maintenance Worker to a comma-separated capability list. A restricted Worker only claims those durable task types and does not run generic upload maintenance; this is used by the Part prebuild script/runtime so queued Import tasks remain untouched. The provided prebuild launcher also uses one PostgreSQL session and a five-minute lease because small Supabase session pools and remote batch preparation must not cause lease churn.

Relation detection runs in the independent Go Worker together with validation and preview materialization. It reads connector definitions from the Candidate's frozen Part Library version, verifies the connector source hash and parser version included in the task input hash, and atomically materializes relation candidates, connector analysis, and external interfaces.

`POST .../relations/detect`, `POST .../validate`, and `POST .../preview/materialize` only create durable tasks and return `202`. Relation detection never updates SceneSnapshot transforms. Relation confirmation reserves normalized connector slots through PostgreSQL constraints/triggers, removes occupied connectors from the external-interface projection, updates the Candidate and draft-version interface signature together, and invalidates stale validation. Owners may publish a Draft directly; validation is an optional asynchronous quality report for Draft/Published versions and never gates or revokes publication.

`GET .../preview` is read-only: it returns state and a short-lived URL only for a ready derived Artifact. The Go Worker builds a deterministic version-addressed GLB from the frozen SceneSnapshot and Studio/LDraw Part Library; if its Storage object is missing, a new materialization generation recreates the same stable derived Artifact. `GET .../parts?locale=...` loads BOM display data separately and selects only reviewed Part translations, leaving the GLB and machine part numbers locale-independent.

Part preview is a separate immutable resource keyed by `partLibraryVersionId + ldrawPartNum`; there is no generic `library-items` alias. Goose owns Part content, geometry metadata, preview state, and Artifact links. The Go Worker registers `component.part_preview.materialize` and `component.part_preview.prebuild` when `LDRAW_ROOT` points to the read-only, version-pinned LDraw library and `PART_PREVIEW_GLTFPACK_PATH` resolves to the pinned gltfpack 1.2 executable (native preferred). It recursively expands real type 1/3/4 geometry, validates the root Part file hash, converts LDraw coordinates to the project Y-up/stud coordinate system, generates indexed creased normals, and writes an `EXT_meshopt_compression` GLB. Final bytes are SHA-256 content-addressed under `component-repo/part-library-assets/glb`; the global immutable Artifact has no owner and `part_previews` owns the Part binding. The API never reads LDraw files or generates geometry in an HTTP request. Use `scripts/install-gltfpack.sh` to install the pinned native tool and `scripts/prebuild-part-previews.sh` to inspect or explicitly schedule a resumable full-library build. Run `db/data_migrations/20260814_public_parts_to_go.sql` explicitly after Goose v8 to hand legacy Part content and geometry to `component_repo`; API/Worker startup never performs this backfill.

`scripts/cleanup-migrated-public-part-source-data.sh` is the guarded capacity-maintenance command for three migrated, dependency-free legacy sources: `public.connector_instances`, `public.ldraw_part_geometry`, and `public.xref_part_numbers`. It defaults to dry-run, requires the exact database confirmation to execute, verifies the active Go Part Library, creates row-counted and SHA-256-checked CSV recovery shards, rejects unexpected foreign-key dependents, and truncates without `CASCADE`. The other legacy Part parent tables are intentionally outside this command because DEM, shape-profile, shadow-include, or historical connector-analysis rows still reference them. This maintenance changes data only; ownership of `public` schema objects remains with Alembic.

The migration command supports `status`, `version`, `up`, `up-by-one`, `down`, `redo`, and `reset`. Goose exclusively owns the `component_repo` schema. Alembic temporarily owns unmigrated legacy `public` objects and the existing Supabase policies in the provider-owned `storage` schema; it must never modify `component_repo`. Do not run destructive migration commands without confirming the exact database.

`make test-postgres` creates an isolated temporary local PostgreSQL cluster, migrates it from zero to head, runs Go schema/API/task/ingestion/relation contracts, verifies a second `up` is a no-op, and confirms that API/Worker startup does not change the schema. It never uses `DATABASE_URL` from your environment.

`make generate` and `make check` use the project-level sqlc tool version pinned in `go.mod`. Generated files under `db/generated` must not be edited manually.
