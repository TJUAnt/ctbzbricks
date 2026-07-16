"""Create the persisted DEM slope candidate tables."""

from sqlalchemy import create_engine

from src.config.db_config import get_db_url
from src.model.models import Base, DemSlopeCandidate, DemSlopeCandidatePattern


DEM_SLOPE_CANDIDATE_TABLES = (
    DemSlopeCandidate.__table__,
    DemSlopeCandidatePattern.__table__,
)


def create_dem_slope_candidate_tables(engine) -> None:
    Base.metadata.create_all(engine, tables=DEM_SLOPE_CANDIDATE_TABLES)


def main() -> None:
    create_dem_slope_candidate_tables(create_engine(get_db_url()))


if __name__ == "__main__":
    main()
