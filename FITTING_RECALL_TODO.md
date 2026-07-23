# Fitting Recall TODO

## Approved layering

- Basic recall is the first-stage candidate index.
- Precise recall always starts from the bounded result set produced by basic recall.
- `fitting_candidate_profiles` stores the queryable basic index for official LDraw Parts,
  published Component Repo Components, and existing Submodels.
- Basic Part eligibility depends on `ldraw_part_geometry`, not
  `ldraw_part_shape_profiles`.
- `ldraw_part_shape_profiles` is optional enrichment for precise surface,
  collision, contact, and connector-fit calculations.

## Interface TODO

- [ ] Add a dedicated basic recall endpoint. It must push dimensions, sticker
  exclusion, candidate status, and normalized type filtering into SQL.
- [ ] Add a dedicated precise recall endpoint. It must accept or reproduce a
  basic recall query, cap the basic candidate set, and score only those
  candidates with `ldraw_part_shape_profiles` data.
- [ ] Define precise-recall behavior for candidates without a ready shape
  profile: exclude with a machine reason code or return a structured degraded
  result. Do not silently treat basic geometry as a precise match.
- [ ] Add separate latency, candidate-count, and coverage metrics for the two
  stages.
- [ ] Keep the current `/api/fitting/candidates/recall` route as the basic
  compatibility route until clients move to the dedicated endpoint.

## Basic index invariants

- Every LDraw Part with complete logical dimensions in `ldraw_part_geometry`
  has one current basic candidate profile.
- Every active Component Repo Component with a published current version has
  one current basic candidate profile.
- Publishing a Component and upserting its basic candidate profile occur in
  the same database transaction.
- Removing the current published Component version removes its basic candidate
  profile in the same database transaction.
- User-authored Component content remains verbatim with its `contentLocale`;
  official content continues to use reviewed translations.
