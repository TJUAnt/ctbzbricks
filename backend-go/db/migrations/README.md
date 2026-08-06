# Go migrations

Goose exclusively owns every object in the PostgreSQL `component_repo` schema. Alembic may temporarily continue to manage unmigrated legacy objects in `public`, but it must never touch this schema.

Migration files are also the schema input for sqlc. Do not maintain a second scaffold schema, edit generated sqlc files, or run migrations implicitly from API/Worker startup.

`reset` and the Down section of the baseline drop the complete `component_repo` schema. Run them only after confirming the exact development or temporary database target.
