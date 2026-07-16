"""Stream all application tables from legacy MySQL to Supabase PostgreSQL."""

import argparse
from urllib.parse import quote_plus

from sqlalchemy import (
    BigInteger,
    Integer,
    bindparam,
    create_engine,
    func,
    inspect,
    select,
    text,
)

from src.config.db_config import LEGACY_ENV_FILE_PATH, get_db_url, load_mysql_config
from src.model.models import Base, PartImage


def migration_tables():
    """Tables copied one-for-one from the legacy MySQL schema."""
    return [
        table
        for table in Base.metadata.sorted_tables
        if table.name != PartImage.__tablename__
    ]


def legacy_mysql_url() -> str:
    config = load_mysql_config(LEGACY_ENV_FILE_PATH)
    password = quote_plus(str(config["MYSQL_PASSWORD"]))
    return (
        f"mysql+pymysql://{config['MYSQL_USER']}:{password}"
        f"@{config['MYSQL_HOST']}:{config['MYSQL_PORT']}/{config['MYSQL_DATABASE']}"
        f"?charset={config['MYSQL_CHARSET']}"
    )


def row_count(connection, table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def validate_table_sets(source_engine, target_engine) -> None:
    model_tables = set(Base.metadata.tables)
    source_model_tables = {table.name for table in migration_tables()}
    source_tables = set(inspect(source_engine).get_table_names())
    missing_source = source_model_tables - source_tables
    if missing_source:
        raise RuntimeError(
            "Model tables missing from source MySQL: " + ", ".join(sorted(missing_source))
        )

    target_tables = set(inspect(target_engine).get_table_names(schema="public"))
    unknown_target = target_tables - model_tables
    if unknown_target:
        raise RuntimeError(
            "Unexpected existing tables in target public schema: "
            + ", ".join(sorted(unknown_target))
        )


def copy_table(source_engine, target_engine, table, batch_size: int) -> int:
    primary_keys = list(table.primary_key.columns)
    self_fk_columns = [
        foreign_key.parent
        for foreign_key in table.foreign_keys
        if foreign_key.column.table is table
    ]
    with source_engine.connect() as source_connection:
        source_total = row_count(source_connection, table)
    with target_engine.connect() as target_connection:
        target_total = row_count(target_connection, table)

    if target_total == source_total:
        print(f"SKIP {table.name}: {source_total} rows already present", flush=True)
        return source_total
    if source_total == 0:
        print(f"OK {table.name}: empty", flush=True)
        return 0

    statement = select(table)
    copied = 0
    if target_total:
        if self_fk_columns or len(primary_keys) != 1:
            raise RuntimeError(
                f"Target table {table.name} is partially populated "
                f"({target_total}/{source_total}) and cannot be resumed safely"
            )
        primary_key = primary_keys[0]
        with target_engine.connect() as target_connection:
            target_max = target_connection.execute(
                select(func.max(primary_key))
            ).scalar_one()
        with source_engine.connect() as source_connection:
            source_prefix_count = int(
                source_connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(primary_key <= target_max)
                ).scalar_one()
            )
        if source_prefix_count != target_total:
            raise RuntimeError(
                f"Target table {table.name} is not a contiguous primary-key prefix"
            )
        statement = statement.where(primary_key > target_max)
        copied = target_total
        print(
            f"RESUME {table.name}: {copied}/{source_total} after {target_max}",
            flush=True,
        )

    if primary_keys:
        statement = statement.order_by(*primary_keys)

    if self_fk_columns and len(primary_keys) != 1:
        raise RuntimeError(
            f"Self-referencing table {table.name} requires a single primary key"
        )
    with source_engine.connect().execution_options(stream_results=True) as source_connection:
        result = source_connection.execute(statement)
        if self_fk_columns:
            deferred_self_updates = []
            with target_engine.begin() as target_connection:
                while True:
                    rows = result.fetchmany(batch_size)
                    if not rows:
                        break
                    payload = [dict(row._mapping) for row in rows]
                    primary_key = primary_keys[0]
                    for record in payload:
                        deferred_self_updates.append(
                            {
                                "_self_pk": record[primary_key.name],
                                **{
                                    f"_self_{column.name}": record[column.name]
                                    for column in self_fk_columns
                                },
                            }
                        )
                        for column in self_fk_columns:
                            record[column.name] = None
                    target_connection.execute(table.insert(), payload)
                    copied += len(rows)

                update_statement = (
                    table.update()
                    .where(primary_key == bindparam("_self_pk"))
                    .values(
                        {
                            column.name: bindparam(f"_self_{column.name}")
                            for column in self_fk_columns
                        }
                    )
                )
                target_connection.execute(update_statement, deferred_self_updates)
                print(
                    f"SELF-FK {table.name}: {len(deferred_self_updates)} rows updated",
                    flush=True,
                )
        else:
            while True:
                rows = result.fetchmany(batch_size)
                if not rows:
                    break
                payload = [dict(row._mapping) for row in rows]
                with target_engine.begin() as target_connection:
                    target_connection.execute(table.insert(), payload)
                copied += len(rows)
                if copied == source_total or copied % 50000 < batch_size:
                    print(
                        f"COPY {table.name}: {copied}/{source_total}",
                        flush=True,
                    )

    if copied != source_total:
        raise RuntimeError(f"Incomplete copy for {table.name}: {copied}/{source_total}")
    return copied


def copy_part_images(source_engine, target_engine, batch_size: int) -> None:
    with source_engine.connect() as source_connection:
        source_total = int(
            source_connection.execute(
                text(
                    "SELECT COUNT(DISTINCT part_num) FROM rb_inventory_parts "
                    "WHERE img_url IS NOT NULL AND img_url <> ''"
                )
            ).scalar_one()
        )
    with target_engine.connect() as target_connection:
        target_total = row_count(target_connection, PartImage.__table__)
    if target_total == source_total:
        print(f"SKIP rb_part_images: {source_total} rows already present", flush=True)
        return
    if target_total:
        raise RuntimeError(
            f"Target rb_part_images is partially populated ({target_total}/{source_total})"
        )

    query = text(
        "SELECT p.part_num, p.img_url FROM rb_inventory_parts p "
        "JOIN (SELECT part_num, MIN(id) AS id FROM rb_inventory_parts "
        "WHERE img_url IS NOT NULL AND img_url <> '' GROUP BY part_num) first_image "
        "ON first_image.id=p.id ORDER BY p.part_num"
    )
    copied = 0
    with source_engine.connect().execution_options(stream_results=True) as source_connection:
        result = source_connection.execute(query)
        while True:
            rows = result.fetchmany(batch_size)
            if not rows:
                break
            with target_engine.begin() as target_connection:
                target_connection.execute(
                    PartImage.__table__.insert(),
                    [dict(row._mapping) for row in rows],
                )
            copied += len(rows)
    if copied != source_total:
        raise RuntimeError(f"Incomplete rb_part_images copy: {copied}/{source_total}")
    print(f"COPY rb_part_images: {copied}/{source_total}", flush=True)


def reset_postgresql_sequences(target_engine) -> None:
    preparer = target_engine.dialect.identifier_preparer
    with target_engine.begin() as connection:
        for table in migration_tables():
            primary_keys = list(table.primary_key.columns)
            if len(primary_keys) != 1:
                continue
            primary_key = primary_keys[0]
            if not isinstance(primary_key.type, (Integer, BigInteger)):
                continue

            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": primary_key.name},
            ).scalar_one_or_none()
            if not sequence:
                continue

            table_name = preparer.quote(table.name)
            column_name = preparer.quote(primary_key.name)
            connection.execute(
                text(
                    "SELECT setval(CAST(:sequence AS regclass), "
                    f"GREATEST(COALESCE(MAX({column_name}), 0), 1), "
                    f"COUNT(*) > 0) FROM {table_name}"
                ),
                {"sequence": sequence},
            )
            print(f"SEQUENCE {table.name}.{primary_key.name}: reset", flush=True)


def verify_counts(source_engine, target_engine) -> None:
    mismatches = []
    with source_engine.connect() as source, target_engine.connect() as target:
        for table in migration_tables():
            source_total = row_count(source, table)
            target_total = row_count(target, table)
            status = "OK" if source_total == target_total else "MISMATCH"
            print(
                f"VERIFY {status} {table.name}: {source_total}/{target_total}",
                flush=True,
            )
            if source_total != target_total:
                mismatches.append(table.name)
    if mismatches:
        raise RuntimeError("Row-count mismatches: " + ", ".join(mismatches))


def migrate(batch_size: int) -> None:
    source_engine = create_engine(legacy_mysql_url(), pool_pre_ping=True)
    target_engine = create_engine(
        get_db_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    try:
        if target_engine.dialect.name != "postgresql":
            raise RuntimeError("Target DATABASE_URL is not PostgreSQL")
        validate_table_sets(source_engine, target_engine)
        Base.metadata.create_all(target_engine)
        for table in migration_tables():
            copy_table(source_engine, target_engine, table, batch_size)
        copy_part_images(source_engine, target_engine, batch_size)
        reset_postgresql_sequences(target_engine)
        verify_counts(source_engine, target_engine)
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    migrate(args.batch_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
