"""Cross-dialect SQLAlchemy upsert helpers used by import tools."""

from collections.abc import Iterable
from typing import Any

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session


def upsert_statement(
    session: Session,
    model: Any,
    records: list[dict],
    *,
    conflict_columns: Iterable[str],
    update_columns: Iterable[str],
):
    """Build an INSERT ... UPDATE statement for MySQL or PostgreSQL."""
    bind = session.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        statement = postgresql_insert(model).values(records)
        return statement.on_conflict_do_update(
            index_elements=list(conflict_columns),
            set_={
                column: getattr(statement.excluded, column)
                for column in update_columns
            },
        )

    if dialect_name == "mysql":
        statement = mysql_insert(model).values(records)
        return statement.on_duplicate_key_update(
            **{
                column: getattr(statement.inserted, column)
                for column in update_columns
            }
        )

    raise RuntimeError(f"Upsert is not supported for database dialect: {dialect_name}")
