"""Recreate the empty DEM slope pattern table with the current schema."""

from sqlalchemy import create_engine, func, select

from src.config.db_config import get_db_url
from src.config.dem_slope_candidate_config import DEM_SLOPE_CANDIDATE_CONFIG
from src.model.models import DemSlopeCandidatePattern


def recreate_pattern_table(engine) -> None:
    pattern_table = DemSlopeCandidatePattern.__table__
    with engine.connect() as connection:
        pattern_count = connection.scalar(select(func.count()).select_from(pattern_table))
    if pattern_count != 0:
        raise ValueError(
            DEM_SLOPE_CANDIDATE_CONFIG["pattern_generation"]["errors"][
                "pattern_table_not_empty"
            ]
        )
    pattern_table.drop(engine, checkfirst=True)
    pattern_table.create(engine)


def main() -> None:
    recreate_pattern_table(create_engine(get_db_url()))


if __name__ == "__main__":
    main()
