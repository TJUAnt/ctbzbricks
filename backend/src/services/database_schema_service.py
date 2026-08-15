"""Database revision validation for API startup."""

from __future__ import annotations

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


EXPECTED_DATABASE_REVISION = "20260809_0022"


class DatabaseSchemaError(RuntimeError):
    """Raised when the configured database is not ready for this build."""


def validate_database_revision(engine: Engine) -> None:
    """Fail fast unless the database is at this build's single Alembic head."""
    try:
        with engine.connect() as connection:
            revisions = {
                str(row[0])
                for row in connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            }
    except SQLAlchemyError as error:
        raise DatabaseSchemaError(
            "database.schema_revision_unavailable "
            f"expected={EXPECTED_DATABASE_REVISION}"
        ) from error

    if revisions != {EXPECTED_DATABASE_REVISION}:
        actual = ",".join(sorted(revisions)) or "none"
        raise DatabaseSchemaError(
            "database.schema_revision_mismatch "
            f"expected={EXPECTED_DATABASE_REVISION} actual={actual}"
        )
