# Supabase database migration runbook

The application keeps FastAPI and SQLAlchemy. Supabase is used as the managed
PostgreSQL database; the frontend does not connect to Supabase directly during
the first migration phase.

## 1. Connection configuration

Copy `backend/.env.example` to `backend/.env` and set `DATABASE_URL` to the
connection string shown by Supabase's **Connect** dialog.

- Persistent backend with IPv6: direct connection on port 5432.
- Persistent backend on an IPv4-only network: session pooler on port 5432.
- Always require SSL.
- Do not put the database URL or a service-role key in frontend environment
  variables.

The legacy `MYSQL_*` settings remain available only as a rollback path when
`DATABASE_URL` is absent.

## 2. Pre-migration inventory

Before the first rehearsal, record the source database size, table list, row
counts, primary-key maxima, indexes, foreign keys, and unique constraints. Take
a transactionally consistent `mysqldump` and test that it can be restored.

## 3. Rehearsal migration

Use a disposable Supabase project for the first run. Migrate the complete MySQL
database with Supabase's MySQL migration notebook or pgloader. Do not point the
production application at the rehearsal project.

For this repository, the checked-in SQLAlchemy models can also perform a
resumable, table-at-a-time migration without pgloader:

```bash
PYTHONPATH=backend .venv/bin/python \
  -m src.tools.migrate_mysql_to_supabase --batch-size 2000
```

The command refuses unknown target tables and refuses to overwrite a partially
populated table. A completed table is skipped on rerun; a failed table-level
transaction remains empty and can be retried.

After importing data:

1. Compare every source and target table row count.
2. Check orphaned foreign keys and duplicate unique keys.
3. Reset every PostgreSQL identity/sequence to the corresponding maximum ID.
4. Exercise image/blob reads, JSON fields, search, project creation, updates,
   and deletes.
5. Run the complete backend test suite against PostgreSQL.

The first two checks can be automated without exposing either password in
command output:

```bash
cd backend
SOURCE_DATABASE_URL='mysql+pymysql://...' \
TARGET_DATABASE_URL='postgresql+psycopg://...?sslmode=require' \
python -m src.tools.verify_supabase_migration
```

The command exits non-zero when a source table is missing or a row count or
comparable primary-key maximum differs.

## 4. Supabase access policy

During phase one, all application access goes through FastAPI. Revoke direct
`anon` and `authenticated` access to application tables. Enable RLS for tables
in exposed schemas and create no browser-facing policies until direct frontend
access is intentionally designed.

Apply that policy to all application-owned tables with:

```bash
PYTHONPATH=backend .venv/bin/python -m src.tools.harden_supabase_schema
```

For production, create a least-privilege database role for FastAPI instead of
using the `postgres` administrator permanently. A later hardening change can
move internal tables into a non-exposed schema.

## 5. Production cutover

1. Announce and start a write freeze.
2. Take the final MySQL backup.
3. Apply the final data migration or delta.
4. Repeat row-count, constraint, sequence, and smoke-test checks.
5. Change only the backend `DATABASE_URL` and restart the backend.
6. Monitor database connections, API errors, latency, and write operations.
7. Keep MySQL read-only for the rollback window.

Rollback consists of stopping writes, restoring the old MySQL environment
configuration, restarting the backend, and reconciling any writes accepted by
PostgreSQL before the rollback decision.

## 6. Schema lifecycle

The accepted PostgreSQL schema is tracked by Alembic. Apply migrations as an
explicit deployment step before starting a new backend build:

```bash
scripts/migrate-backend.sh
scripts/start-backend.sh
```

On Windows:

```powershell
scripts\migrate-backend.ps1
scripts\start-backend.ps1
```

FastAPI startup only validates that `alembic_version` equals the revision
expected by the build. It never creates tables, alters columns, creates indexes,
or runs data backfills. A missing or mismatched revision stops the process.

The configured Supabase database was fully compared with the 50-table
SQLAlchemy contract before its one-time adoption at revision
`20260723_0013`; migration `20260725_0014` then aligned the remaining locale,
task-context, and structured-error columns. Future revisions must be applied
with the same migrate-before-start order.

Migration `20260725_0015` adds backend-only per-user Component groups,
group memberships, and Component subscriptions. These tables have RLS enabled
and grant no direct access to `anon` or `authenticated`; clients use the
authenticated Component Repo API.

`ensure_*` helpers remain available only for SQLite tests and explicit offline
development initialization. They are not a production migration mechanism and
must not stamp `alembic_version`.

## 7. Follow-up work

- Pixel-art source images were removed from PostgreSQL after export because the
  application only uses the compact preview and generated pixel data.
- Add scheduled logical exports in addition to provider-managed backups.
