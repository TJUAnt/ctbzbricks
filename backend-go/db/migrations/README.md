# Go migrations

Goose exclusively owns every object in the PostgreSQL `component_repo` schema. Alembic may temporarily continue to manage unmigrated legacy objects in `public`, but it must never touch this schema.

Migration files are also the schema input for sqlc. Do not maintain a second scaffold schema, edit generated sqlc files, or run migrations implicitly from API/Worker startup.

Current repository schema head is v25 (`part_library_search`; Watch preference history begins in v15,
publish events in v16, relationship lifecycle cleanup in v17, and Component catalog projection in v24). A successful isolated migration does not imply
that a real Supabase database has been upgraded; verify and record the target database Goose version separately.

`reset` and the Down section of the baseline drop the complete `component_repo` schema. Run them only after confirming the exact development or temporary database target.
