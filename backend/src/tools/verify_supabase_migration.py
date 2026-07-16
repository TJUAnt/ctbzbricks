"""Compare source MySQL and target Supabase PostgreSQL after migration."""

import os
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text

from src.config.db_config import normalize_database_url


@dataclass(frozen=True)
class TableResult:
    table: str
    source_count: int
    target_count: int
    source_pk_max: object | None = None
    target_pk_max: object | None = None

    @property
    def matches(self) -> bool:
        return (
            self.source_count == self.target_count
            and self.source_pk_max == self.target_pk_max
        )


def required_url(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return normalize_database_url(value)


def quoted_identifier(engine, identifier: str) -> str:
    return engine.dialect.identifier_preparer.quote(identifier)


def scalar(engine, statement: str):
    with engine.connect() as connection:
        return connection.execute(text(statement)).scalar_one()


def table_count(engine, table: str) -> int:
    table_name = quoted_identifier(engine, table)
    return int(scalar(engine, f"SELECT COUNT(*) FROM {table_name}"))


def single_primary_key(engine, table: str) -> str | None:
    columns = inspect(engine).get_pk_constraint(table).get("constrained_columns") or []
    return columns[0] if len(columns) == 1 else None


def primary_key_max(engine, table: str, primary_key: str | None):
    if primary_key is None:
        return None
    table_name = quoted_identifier(engine, table)
    column_name = quoted_identifier(engine, primary_key)
    return scalar(engine, f"SELECT MAX({column_name}) FROM {table_name}")


def compare_databases(source_url: str, target_url: str) -> tuple[list[TableResult], set[str], set[str]]:
    source = create_engine(source_url, pool_pre_ping=True)
    target = create_engine(target_url, pool_pre_ping=True)
    try:
        source_tables = set(inspect(source).get_table_names())
        target_tables = set(inspect(target).get_table_names())
        results = []
        for table in sorted(source_tables & target_tables):
            source_pk = single_primary_key(source, table)
            target_pk = single_primary_key(target, table)
            comparable_pk = source_pk if source_pk == target_pk else None
            results.append(
                TableResult(
                    table=table,
                    source_count=table_count(source, table),
                    target_count=table_count(target, table),
                    source_pk_max=primary_key_max(source, table, comparable_pk),
                    target_pk_max=primary_key_max(target, table, comparable_pk),
                )
            )
        return results, source_tables - target_tables, target_tables - source_tables
    finally:
        source.dispose()
        target.dispose()


def main() -> int:
    results, missing_from_target, target_only = compare_databases(
        required_url("SOURCE_DATABASE_URL"),
        required_url("TARGET_DATABASE_URL"),
    )

    print("status table source_rows target_rows source_pk_max target_pk_max")
    for result in results:
        status = "OK" if result.matches else "MISMATCH"
        print(
            status,
            result.table,
            result.source_count,
            result.target_count,
            result.source_pk_max,
            result.target_pk_max,
        )

    if missing_from_target:
        print("missing_from_target:", ", ".join(sorted(missing_from_target)))
    if target_only:
        print("target_only:", ", ".join(sorted(target_only)))

    has_mismatch = any(not result.matches for result in results)
    return 1 if has_mismatch or missing_from_target else 0


if __name__ == "__main__":
    sys.exit(main())
