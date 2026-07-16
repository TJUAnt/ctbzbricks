"""Tests for persisted DEM slope candidate schema constraints."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config.dem_slope_candidate_config import (
    DEM_SLOPE_CANDIDATE_DATABASE_CONFIG,
)
from src.model.models import Base, DemSlopeCandidate, DemSlopeCandidatePattern
from src.tools.create_dem_slope_candidate_tables import (
    create_dem_slope_candidate_tables,
)


class DemSlopeCandidateModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        create_dem_slope_candidate_tables(self.engine)

    def candidate(self) -> DemSlopeCandidate:
        return DemSlopeCandidate(
            id=1,
            ldraw_part_id=1,
            candidate_enabled=True,
            catalog_status="profiled",
            current_candidate=False,
            capability_eligible=True,
            family="straight",
            group_id="slope-test",
            flags_json={},
            database_geometry_json={},
            capability_json={},
            catalog_payload_json={},
            source_hash="source-hash",
        )

    def pattern(self, rank: int) -> DemSlopeCandidatePattern:
        return DemSlopeCandidatePattern(
            id=rank,
            candidate_id=1,
            pattern_rank=rank,
            pattern_key=f"pattern-{rank}",
            heightmap_pattern_json={},
            match_metrics_json={},
        )

    def test_schema_uses_configured_table_names(self) -> None:
        self.assertEqual(
            DemSlopeCandidate.__tablename__,
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["candidate_table"],
        )
        self.assertEqual(
            DemSlopeCandidatePattern.__tablename__,
            DEM_SLOPE_CANDIDATE_DATABASE_CONFIG["pattern_table"],
        )

    def test_each_candidate_has_three_rank_slots(self) -> None:
        maximum_rank = DEM_SLOPE_CANDIDATE_DATABASE_CONFIG[
            "maximum_patterns_per_candidate"
        ]
        with Session(self.engine) as session:
            session.add(self.candidate())
            session.add_all(
                self.pattern(rank)
                for rank in range(1, maximum_rank + 1)
            )
            session.commit()

            session.add(self.pattern(maximum_rank + 1))
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_pattern_rank_is_unique_per_candidate(self) -> None:
        with Session(self.engine) as session:
            session.add(self.candidate())
            session.add(self.pattern(1))
            session.commit()

            duplicate_rank = self.pattern(1)
            duplicate_rank.id = 2
            duplicate_rank.pattern_key = "another-pattern"
            session.add(duplicate_rank)
            with self.assertRaises(IntegrityError):
                session.commit()


if __name__ == "__main__":
    unittest.main()
