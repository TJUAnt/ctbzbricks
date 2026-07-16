"""Prevent direct Data API access to backend-owned application tables."""

from sqlalchemy import create_engine, text

from src.config.db_config import get_db_url
from src.model.models import Base


def harden() -> None:
    engine = create_engine(get_db_url(), pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("DATABASE_URL is not PostgreSQL")

    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            table_name = preparer.quote(table.name)
            connection.execute(
                text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            )
            connection.execute(
                text(
                    f"REVOKE ALL PRIVILEGES ON TABLE {table_name} "
                    "FROM anon, authenticated"
                )
            )
            print(f"RLS {table.name}: enabled")

        connection.execute(
            text(
                "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
                "FROM anon, authenticated"
            )
        )
    engine.dispose()


if __name__ == "__main__":
    harden()
