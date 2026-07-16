"""Apply the checked-in low-risk Supabase database size reduction."""

from sqlalchemy import create_engine, inspect, text

from src.config.db_config import get_db_url
from src.model.models import PartImage


def database_size(connection) -> int:
    return int(connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one())


def columns(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def slim() -> None:
    engine = create_engine(get_db_url(), pool_pre_ping=True, pool_recycle=1800)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("DATABASE_URL is not PostgreSQL")

    with engine.connect() as connection:
        before = database_size(connection)
    print(f"database_bytes_before={before}")

    PartImage.__table__.create(bind=engine, checkfirst=True)
    inventory_columns = columns(engine, "rb_inventory_parts")
    pixel_columns = columns(engine, "pixel_art_projects")

    with engine.begin() as connection:
        if "img_url" in inventory_columns:
            expected = int(
                connection.execute(
                    text(
                        "SELECT COUNT(DISTINCT part_num) FROM rb_inventory_parts "
                        "WHERE img_url IS NOT NULL AND img_url <> ''"
                    )
                ).scalar_one()
            )
            connection.execute(
                text(
                    "INSERT INTO rb_part_images (part_num, img_url) "
                    "SELECT DISTINCT ON (part_num) part_num, img_url "
                    "FROM rb_inventory_parts "
                    "WHERE img_url IS NOT NULL AND img_url <> '' "
                    "ORDER BY part_num, id "
                    "ON CONFLICT (part_num) DO NOTHING"
                )
            )
            actual = int(
                connection.execute(text("SELECT COUNT(*) FROM rb_part_images")).scalar_one()
            )
            invalid = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM rb_part_images i "
                        "WHERE NOT EXISTS ("
                        "SELECT 1 FROM rb_inventory_parts p "
                        "WHERE p.part_num=i.part_num AND p.img_url=i.img_url)"
                    )
                ).scalar_one()
            )
            if actual != expected or invalid:
                raise RuntimeError(
                    f"Part image validation failed: expected={expected}, "
                    f"actual={actual}, invalid={invalid}"
                )
            print(f"part_images_validated={actual}")

            connection.execute(text("ALTER TABLE rb_inventory_parts DROP COLUMN img_url"))
            print("dropped=rb_inventory_parts.img_url")

        if "source_image" in pixel_columns:
            connection.execute(text("ALTER TABLE pixel_art_projects DROP COLUMN source_image"))
            print("dropped=pixel_art_projects.source_image")

        connection.execute(text("DROP INDEX IF EXISTS idx_ldraw_ref_from"))
        connection.execute(text("DROP INDEX IF EXISTS idx_xref_rb"))
        connection.execute(text("ALTER TABLE rb_part_images ENABLE ROW LEVEL SECURITY"))
        connection.execute(
            text(
                "REVOKE ALL PRIVILEGES ON TABLE rb_part_images "
                "FROM anon, authenticated"
            )
        )
        print("dropped_redundant_indexes=2")

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for table_name in ("rb_inventory_parts", "pixel_art_projects"):
            print(f"vacuum_full={table_name}")
            connection.execute(text(f"VACUUM (FULL, ANALYZE) {table_name}"))

    with engine.connect() as connection:
        after = database_size(connection)
    engine.dispose()
    print(f"database_bytes_after={after}")
    print(f"database_bytes_saved={before - after}")


if __name__ == "__main__":
    slim()
