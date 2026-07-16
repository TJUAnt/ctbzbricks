"""Tests for replacing persisted DEM slope pattern capabilities."""

import unittest

from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from src.model.models import Base, DemSlopeCandidate, DemSlopeCandidatePattern
from src.tools.calculate_dem_slope_patterns import synchronize_patterns


@compiles(BigInteger, "sqlite")
def compile_big_integer_for_sqlite(_type, _compiler, **_kwargs) -> str:
    return "INTEGER"


class CalculateDemSlopePatternsTest(unittest.TestCase):
    def test_synchronize_replaces_patterns_with_global_candidate_ranks(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=(DemSlopeCandidate.__table__, DemSlopeCandidatePattern.__table__),
        )
        with Session(engine) as session:
            session.add(
                DemSlopeCandidate(
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
            )
            session.commit()
            count = synchronize_patterns(
                session,
                {
                    1: (
                        {
                            "patternKey": "pattern-a",
                            "heightmapPattern": {"validRotations": [0, 90, 180, 270]},
                            "matchMetrics": {},
                        },
                        {
                            "patternKey": "pattern-b",
                            "heightmapPattern": {"validRotations": [0, 90, 180, 270]},
                            "matchMetrics": {},
                        },
                    )
                },
            )
            rows = session.scalars(
                select(DemSlopeCandidatePattern).order_by(
                    DemSlopeCandidatePattern.pattern_rank
                )
            ).all()

        self.assertEqual(count, 2)
        self.assertEqual([row.pattern_rank for row in rows], [1, 2])
        self.assertEqual([row.pattern_key for row in rows], ["pattern-a", "pattern-b"])


if __name__ == "__main__":
    unittest.main()
