"""Unit tests for fitting candidate recall."""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.schemas.fitting_candidate_recall import (
    FittingCandidateRecallBBoxRequest,
    FittingCandidateRecallConnectorRequest,
    FittingCandidateRecallRequest,
)
from src.config.app_settings import load_json_config
from src.config.fitting_candidate_recall_config import (
    REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
)
from src.config.part_shape_profile_config import REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS
from src.model.models import (
    FittingCandidateProfile,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
)
from src.services.fitting_candidate_recall_service import recall_fitting_candidates
from src.services.part_shape_profile_service import (
    ensure_part_shape_profile_table,
    save_failed_part_shape_profile,
)


class FittingCandidateRecallServiceTest(unittest.TestCase):
    def test_recall_filters_ready_candidate_by_bbox_connector_and_category(self) -> None:
        config = recall_config()
        engine = test_engine()
        seed_ready_part_candidate(engine, config)

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=[config["defaults"]["candidate_types"][0]],
                bbox=FittingCandidateRecallBBoxRequest(
                    widthLdu=20,
                    heightLdu=8,
                    depthLdu=20,
                    toleranceLdu=0,
                ),
                connectors=[
                    FittingCandidateRecallConnectorRequest(
                        connectorType="stud",
                        connectorGender="male",
                        minCount=1,
                    )
                ],
                categories=["Plate"],
            ),
        )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.candidates[0].candidateId, "3024.dat")
        self.assertEqual(response.candidates[0].profileStatus, config["defaults"]["profile_statuses"][0])
        self.assertIn(config["response"]["connector_filter_reason"], response.candidates[0].scoreReasons)

    def test_recall_filters_submodel_by_part_summary_category_and_color(self) -> None:
        config = recall_config()
        engine = test_engine()
        seed_ready_submodel_candidate(engine, config)

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=[config["defaults"]["candidate_types"][1]],
                categories=["Brick"],
                colorCodes=["4"],
            ),
        )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.candidates[0].candidateType, config["defaults"]["candidate_types"][1])
        self.assertEqual(response.candidates[0].candidateId, "door-module")
        self.assertIn(config["response"]["category_filter_reason"], response.candidates[0].scoreReasons)
        self.assertIn(config["response"]["color_filter_reason"], response.candidates[0].scoreReasons)

    def test_recall_includes_irregular_failed_shape_profile_when_requested(self) -> None:
        config = recall_config()
        shape_config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_irregular_part(engine)
        save_failed_part_shape_profile(
            engine,
            shape_config,
            "60801.dat",
            "irregular-hash",
            "LDraw part 60801.dat depth is not aligned to the stud grid",
        )

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=[config["irregular"]["candidate_type"]],
                includeIrregular=True,
                bbox=FittingCandidateRecallBBoxRequest(
                    widthLdu=21,
                    depthLdu=20,
                    toleranceLdu=0,
                ),
                categories=["Plate"],
            ),
        )

        self.assertEqual(response.total, 1)
        candidate = response.candidates[0]
        self.assertEqual(candidate.candidateId, "60801.dat")
        self.assertEqual(candidate.profileStatus, config["irregular"]["degraded_profile_status"])
        self.assertEqual(candidate.profileErrorType, config["irregular"]["allowed_error_types"][0])
        self.assertIn(config["response"]["irregular_reason"], candidate.scoreReasons)

    def test_recall_excludes_irregular_failed_shape_profile_by_default(self) -> None:
        config = recall_config()
        shape_config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_irregular_part(engine)
        save_failed_part_shape_profile(
            engine,
            shape_config,
            "60801.dat",
            "irregular-hash",
            "LDraw part 60801.dat depth is not aligned to the stud grid",
        )

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=[config["irregular"]["candidate_type"]],
                categories=["Plate"],
            ),
        )

        self.assertEqual(response.total, 0)


def recall_config() -> dict:
    return load_json_config(
        "fitting_candidate_recall.json",
        REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
    )


def test_engine():
    engine = create_engine("sqlite:///:memory:")
    LDrawFile.__table__.create(bind=engine)
    LDrawPart.__table__.create(bind=engine)
    LDrawPartGeometry.__table__.create(bind=engine)
    ensure_part_shape_profile_table(engine)
    ensure_fitting_candidate_profile_table(engine)
    return engine


def seed_ready_part_candidate(engine, config: dict) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            FittingCandidateProfile(
                candidate_type=config["defaults"]["candidate_types"][0],
                candidate_id="3024.dat",
                profile_key="candidate-v1",
                profile_status=config["defaults"]["profile_statuses"][0],
                source_hash="source-hash",
                shape_signature="part:3024.dat",
                bbox_json={
                    "bbox": {
                        "widthLdu": 20,
                        "heightLdu": 8,
                        "depthLdu": 20,
                    }
                },
                logical_size_json={
                    "logicalSize": {
                        "widthStud": 1,
                        "depthStud": 1,
                        "heightPlate": 1,
                    }
                },
                shape_profile_json={},
                appearance_tags_json={
                    "category": "Plate",
                    "name": "Plate 1 x 1",
                },
                color_summary_json=None,
                connector_summary_json={
                    "totalCount": 1,
                    "byTypeGender": [
                        {
                            "connectorType": "stud",
                            "connectorGender": "male",
                            "count": 1,
                        }
                    ],
                },
                source_metadata_json={},
            )
        )
        session.commit()


def seed_ready_submodel_candidate(engine, config: dict) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            FittingCandidateProfile(
                candidate_type=config["defaults"]["candidate_types"][1],
                candidate_id="door-module",
                profile_key="candidate-v1",
                profile_status=config["defaults"]["profile_statuses"][0],
                source_hash="submodel-hash",
                shape_signature="submodel:door-module",
                bbox_json={
                    "bbox": {
                        "widthLdu": 40,
                        "heightLdu": 24,
                        "depthLdu": 20,
                    }
                },
                logical_size_json={
                    "logicalSize": {
                        "widthStud": 2,
                        "depthStud": 1,
                        "heightPlate": 3,
                    }
                },
                shape_profile_json={},
                appearance_tags_json={
                    "name": "door module",
                    "remarks": "Reusable hinged detail",
                },
                color_summary_json=[
                    {
                        "colorCode": "4",
                        "percentage": 40,
                    }
                ],
                connector_summary_json={
                    "totalCount": 0,
                    "byTypeGender": [],
                },
                source_metadata_json={
                    "partSummary": {
                        "totalCount": 2,
                        "byCategory": [
                            {
                                "category": "Brick",
                                "count": 1,
                            }
                        ],
                    }
                },
            )
        )
        session.commit()


def seed_irregular_part(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawFile(
                id=1,
                relative_path="parts/60801.dat",
                file_name="60801.dat",
                library_section="parts",
                file_role="part",
            )
        )
        session.add(
            LDrawPart(
                id=1,
                ldraw_part_num="60801.dat",
                file_id=1,
                name="Irregular Plate",
                category="Plate",
                relative_path="parts/60801.dat",
                file_hash="irregular-hash",
            )
        )
        session.add(
            LDrawPartGeometry(
                id=1,
                ldraw_part_id=1,
                bbox_min_x=0,
                bbox_min_y=0,
                bbox_min_z=0,
                bbox_max_x=21,
                bbox_max_y=8,
                bbox_max_z=20,
                width_ldu=21,
                height_ldu=8,
                depth_ldu=20,
                logical_width_stud=None,
                logical_depth_stud=None,
                logical_height_plate=None,
                geometry_status="parsed",
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
