"""Unit tests for fitting candidate recall."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.api.schemas.fitting_candidate_recall import (
    FittingCandidateRecallBBoxRequest,
    FittingCandidateRecallConnectorRequest,
    FittingCandidateRecallLogicalSizeRequest,
    FittingCandidateRecallRequest,
)
from src.config.app_settings import load_json_config
from src.config.fitting_candidate_recall_config import (
    REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
)
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.config.part_shape_profile_config import REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS
from src.model.models import (
    Component,
    ComponentSceneSnapshot,
    ComponentTranslation,
    ComponentVersion,
    FittingCandidateProfile,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
    PartTranslation,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
)
from src.services.fitting_candidate_recall_service import recall_fitting_candidates
from src.services import fitting_candidate_recall_service as recall_service
from src.services.part_shape_profile_service import (
    ensure_part_shape_profile_table,
    save_failed_part_shape_profile,
)


class FittingCandidateRecallServiceTest(unittest.TestCase):
    def test_recall_excludes_part_with_sticker(self) -> None:
        config = recall_config()
        engine = test_engine()
        seed_sticker_part_candidate(engine, config)

        with patch(
            "src.services.fitting_candidate_recall_service.ready_candidate_response",
            wraps=recall_service.ready_candidate_response,
        ) as candidate_builder:
            response = recall_fitting_candidates(
                engine,
                config,
                FittingCandidateRecallRequest(
                    candidateTypes=["part"],
                    logicalSize=FittingCandidateRecallLogicalSizeRequest(
                        widthStud=2,
                        depthStud=2,
                        heightPlate=1,
                        tolerance=0,
                    ),
                    typeQuery="plate",
                ),
            )

        self.assertEqual(response.total, 0)
        self.assertEqual(candidate_builder.call_count, 0)

    def test_recall_mixes_published_component_with_part_profiles(self) -> None:
        config = recall_config()
        component_config = load_json_config(
            "component_repo.json",
            REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_ready_part_candidate(engine, config)
        seed_published_component(engine, component_config)

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=["component", "part"],
                logicalSize=FittingCandidateRecallLogicalSizeRequest(
                    widthStud=1,
                    depthStud=1,
                    heightPlate=1,
                    tolerance=0,
                ),
                typeQuery="plate",
            ),
            component_config,
        )

        self.assertEqual(response.total, 2)
        self.assertEqual(
            {candidate.candidateType for candidate in response.candidates},
            {"component", "part"},
        )

    def test_recall_fuzzy_matches_type_query(self) -> None:
        config = recall_config()
        engine = test_engine()
        seed_ready_part_candidate(engine, config)

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=["part"],
                logicalSize=FittingCandidateRecallLogicalSizeRequest(
                    widthStud=1,
                    depthStud=1,
                    heightPlate=1,
                    tolerance=0,
                ),
                typeQuery="plte",
            ),
        )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.candidates[0].matchedType, "Plate")
        self.assertGreater(response.candidates[0].typeScore, 0.8)

    def test_recall_allows_planar_dimension_rotation(self) -> None:
        config = recall_config()
        engine = test_engine()
        seed_ready_part_candidate(engine, config)
        Session = sessionmaker(bind=engine)
        with Session() as session:
            profile = session.scalar(select(FittingCandidateProfile))
            profile.logical_size_json = {
                "logicalSize": {"widthStud": 2, "depthStud": 4, "heightPlate": 1}
            }
            profile.width_stud = 2
            profile.depth_stud = 4
            session.commit()

        response = recall_fitting_candidates(
            engine,
            config,
            FittingCandidateRecallRequest(
                candidateTypes=["part"],
                logicalSize=FittingCandidateRecallLogicalSizeRequest(
                    widthStud=4,
                    depthStud=2,
                    heightPlate=1,
                    tolerance=0,
                ),
                typeQuery="plate",
                allowPlanarRotation=True,
            ),
        )

        self.assertEqual(response.total, 1)

    def test_recall_prefilters_persisted_dimensions_before_building_candidates(self) -> None:
        config = recall_config()
        engine = test_engine()
        seed_ready_part_candidate(engine, config)
        seed_ready_part_candidate(
            engine,
            config,
            candidate_id="oversized-plate.dat",
            width_stud=8,
            depth_stud=8,
        )

        with patch(
            "src.services.fitting_candidate_recall_service.ready_candidate_response",
            wraps=recall_service.ready_candidate_response,
        ) as candidate_builder:
            response = recall_fitting_candidates(
                engine,
                config,
                FittingCandidateRecallRequest(
                    candidateTypes=["part"],
                    logicalSize=FittingCandidateRecallLogicalSizeRequest(
                        widthStud=1,
                        depthStud=1,
                        heightPlate=1,
                        tolerance=0,
                    ),
                    typeQuery="plate",
                ),
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(candidate_builder.call_count, 1)

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


def seed_ready_part_candidate(
    engine,
    config: dict,
    candidate_id: str = "3024.dat",
    width_stud: float = 1,
    depth_stud: float = 1,
) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            FittingCandidateProfile(
                candidate_type=config["defaults"]["candidate_types"][0],
                candidate_id=candidate_id,
                profile_key="candidate-v1",
                profile_status=config["defaults"]["profile_statuses"][0],
                source_hash="source-hash",
                shape_signature=f"part:{candidate_id}",
                bbox_json={
                    "bbox": {
                        "widthLdu": 20,
                        "heightLdu": 8,
                        "depthLdu": 20,
                    }
                },
                logical_size_json={
                    "logicalSize": {
                        "widthStud": width_stud,
                        "depthStud": depth_stud,
                        "heightPlate": 1,
                    }
                },
                width_stud=width_stud,
                depth_stud=depth_stud,
                height_plate=1,
                is_sticker=False,
                normalized_type="plate",
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
                width_stud=2,
                depth_stud=1,
                height_plate=3,
                is_sticker=False,
                normalized_type=None,
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


def seed_sticker_part_candidate(engine, config: dict) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            FittingCandidateProfile(
                candidate_type="part",
                candidate_id="stickered-plate.dat",
                profile_key="candidate-v1",
                profile_status=config["defaults"]["profile_statuses"][0],
                source_hash="sticker-hash",
                shape_signature="part:stickered-plate.dat",
                bbox_json={
                    "bbox": {"widthLdu": 40, "heightLdu": 8, "depthLdu": 40}
                },
                logical_size_json={
                    "logicalSize": {"widthStud": 2, "depthStud": 2, "heightPlate": 1}
                },
                width_stud=2,
                depth_stud=2,
                height_plate=1,
                is_sticker=True,
                normalized_type="plate",
                shape_profile_json={},
                appearance_tags_json={
                    "category": "Plate",
                    "name": "Plate 2 x 2 with Sticker",
                },
                color_summary_json=None,
                connector_summary_json={"totalCount": 0, "byTypeGender": []},
                source_metadata_json={},
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


def seed_published_component(engine, config: dict) -> None:
    ComponentSceneSnapshot.__table__.create(bind=engine)
    Component.__table__.create(bind=engine)
    ComponentTranslation.__table__.create(bind=engine)
    PartTranslation.__table__.create(bind=engine)
    ComponentVersion.__table__.create(bind=engine)
    now = datetime.now(timezone.utc)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawFile(
                id=10,
                relative_path="parts/3024.dat",
                file_name="3024.dat",
                library_section="parts",
            )
        )
        session.add(
            LDrawPart(
                id=10,
                ldraw_part_num="3024.dat",
                file_id=10,
                name="Plate 1 x 1",
                content_locale="en-US",
                category="Plate",
                relative_path="parts/3024.dat",
            )
        )
        session.add(
            LDrawPartGeometry(
                id=10,
                ldraw_part_id=10,
                bbox_min_x=0,
                bbox_min_y=0,
                bbox_min_z=0,
                bbox_max_x=20,
                bbox_max_y=8,
                bbox_max_z=20,
                width_ldu=20,
                height_ldu=8,
                depth_ldu=20,
                logical_width_stud=1,
                logical_depth_stud=1,
                logical_height_plate=1,
            )
        )
        session.add(
            ComponentSceneSnapshot(
                id="snapshot-1",
                import_id="import-1",
                schema="component-scene-v1",
                parser_version="test",
                root_model_id="root",
                document_json={
                    "rootModelId": "root",
                    "models": [
                        {
                            "modelId": "root",
                            "references": [
                                {
                                    "instanceId": "part-1",
                                    "referenceKind": "part",
                                    "referenceName": "3024.dat",
                                    "transform": {
                                        "position": {"x": 0, "y": 0, "z": 0},
                                        "matrix": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                                    },
                                }
                            ],
                        }
                    ],
                },
                bom_json={},
                parse_issues_json=[],
                created_at=now,
            )
        )
        session.add(
            Component(
                id="component-1",
                name="Small plate module",
                content_kind="user",
                content_locale="en-US",
                category="Plate module",
                status=config["components"]["status"]["active"],
                current_version_id="version-1",
                logical_width_stud=1,
                logical_depth_stud=1,
                logical_height_plate=1,
                description=None,
                tags_json=["plate"],
                metadata_json={},
                created_by="tester",
                created_at=now,
            )
        )
        session.add(
            ComponentVersion(
                id="version-1",
                component_id="component-1",
                component_candidate_id="candidate-1",
                version="1.0.0",
                revision=1,
                status=config["versions"]["status"]["published"],
                source_artifact_id="artifact-1",
                exchange_artifact_id=None,
                scene_snapshot_id="snapshot-1",
                parser_version="test",
                part_library_version_id=None,
                validation_report_id=None,
                interface_signature="signature",
                structure_hash="structure",
                geometry_hash="geometry",
                metadata_json={},
                created_by="tester",
                created_at=now,
                published_at=now,
            )
        )
        session.add(
            FittingCandidateProfile(
                candidate_type="component",
                candidate_id="component-1",
                profile_key="candidate-v1",
                profile_status="ready",
                source_hash="component-source-hash",
                shape_signature="component:component-1:basic",
                bbox_json={
                    "bbox": {"widthLdu": 20, "heightLdu": 8, "depthLdu": 20}
                },
                logical_size_json={
                    "logicalSize": {
                        "widthStud": 1,
                        "depthStud": 1,
                        "heightPlate": 1,
                    }
                },
                width_stud=1,
                depth_stud=1,
                height_plate=1,
                is_sticker=False,
                normalized_type="plate",
                shape_profile_json={},
                appearance_tags_json={
                    "category": "Plate module",
                    "name": "Small plate module",
                    "tags": ["plate"],
                },
                color_summary_json=None,
                connector_summary_json={"totalCount": 0, "byTypeGender": []},
                source_metadata_json={"componentVersionId": "version-1"},
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
