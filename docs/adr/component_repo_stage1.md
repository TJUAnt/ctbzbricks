# ADR: Component Repo Stage 1 Foundations

Date: 2026-07-12

## Status

Accepted

Storage authentication, user-scoped paths, and derived preview artifacts are
refined by `component_repo_storage_and_preview_cache.md`.

## Context

The Component Repo module needs to preserve BrickLink Studio projects while also
parsing component structure into queryable and reviewable data. Stage 1 focuses
on reliable import, review, and immutable version publishing for 8-wide vehicle
components.

## Decisions

- Studio `.io` files are treated as immutable source artifacts.
- Users provide `.ldr` or `.mpd` as the Stage 1 exchange format for structure
  parsing.
- Geometry coordinates stay in the LDraw coordinate system and LDU units.
- Component IDs are UUIDs.
- Authenticated user flows write `auth:{user_id}` audit identities. `system`
  remains limited to tests, offline development, and explicit system jobs.
- Supabase Storage is the production artifact store. A local storage provider
  exists for tests and offline development.
- Connector data is frozen into `part_library_version` snapshots. Published
  components reference a fixed snapshot.
- Connection recognition uses two tolerance levels: wider candidate detection
  thresholds and stricter publication validation thresholds.
- The publication workflow is:

```text
ComponentImport -> ComponentCandidate -> Draft ComponentVersion -> Published ComponentVersion
```

- Only published ComponentVersions are visible to downstream search, fitting,
  and automated design.
- Revision updates may only modify metadata. Structure truth changes require a
  new ComponentVersion.

## Consequences

- The first implementation must prioritize artifact integrity, storage
  roundtrip checks, and migration safety.
- The parser should start with standard LDraw type `1` lines and MPD
  `0 FILE`/`0 NOFILE` sections. Studio-specific lines such as type `11` are
  recorded as parse issues until explicitly supported.
- Tables are introduced through Alembic migrations, while local tests can still
  use explicit table creation helpers during the transition.
