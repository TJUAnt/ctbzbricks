"""Unit tests for unified fitting candidate profiles."""

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.fitting_candidate_profile_config import (
    REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
)
from src.config.part_shape_profile_config import REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS
from src.ldraw.surface_profile import PartSurfaceProfile
from src.model.models import (
    ConnectorInstance,
    FittingCandidateProfile,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
    LDrawSubmodel,
    LDrawSubmodelConnector,
    LDrawSubmodelPart,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
    save_part_fitting_candidate_profile,
    save_submodel_fitting_candidate_profile,
)
from src.services.part_shape_profile_service import (
    ensure_part_shape_profile_table,
    save_failed_part_shape_profile,
    save_part_surface_profile,
)
from src.tools.build_fitting_candidate_profiles import (
    load_candidate_parts,
    load_candidate_submodels,
)


class FittingCandidateProfileServiceTest(unittest.TestCase):
    def test_part_candidate_profile_uses_ready_shape_profile_and_connector_summary(self) -> None:
        fitting_config = load_json_config(
            "fitting_candidate_profile.json",
            REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
        )
        part_shape_config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        seed_connector(engine)
        save_part_surface_profile(
            engine,
            part_shape_config,
            "3024.dat",
            sample_profile(),
            "source-hash",
        )

        candidate = save_part_fitting_candidate_profile(
            engine,
            fitting_config,
            "3024.dat",
        )

        self.assertEqual(candidate["candidateType"], fitting_config["profile"]["candidate_types"]["part"])
        self.assertEqual(candidate["candidateId"], "3024.dat")
        self.assertEqual(candidate["profileStatus"], fitting_config["profile"]["ready_status"])
        self.assertEqual(candidate["appearanceTags"]["category"], "Plate")
        self.assertEqual(candidate["connectorSummary"]["totalCount"], 1)
        self.assertEqual(
            candidate["connectorSummary"]["byTypeGender"][0]["connectorType"],
            "stud",
        )

    def test_ready_only_candidate_loader_excludes_failed_shape_profiles(self) -> None:
        fitting_config = load_json_config(
            "fitting_candidate_profile.json",
            REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
        )
        part_shape_config = load_json_config(
            "part_shape_profile.json",
            REQUIRED_PART_SHAPE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        seed_brick_part(engine)
        save_part_surface_profile(
            engine,
            part_shape_config,
            "3024.dat",
            sample_profile(),
            "source-hash",
        )
        save_failed_part_shape_profile(
            engine,
            part_shape_config,
            "3005.dat",
            "brick-hash",
            "LDraw part 3005.dat depth is not aligned to the stud grid",
        )
        Session = sessionmaker(bind=engine)
        with Session() as session:
            parts = load_candidate_parts(session, fitting_config, None, None, True, None, None)

        self.assertEqual(parts, ["3024.dat"])

    def test_submodel_candidate_profile_summarizes_parts_colors_and_connectors(self) -> None:
        fitting_config = load_json_config(
            "fitting_candidate_profile.json",
            REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        seed_brick_part(engine)
        seed_submodel(engine)

        candidate = save_submodel_fitting_candidate_profile(
            engine,
            fitting_config,
            "door-module",
        )

        self.assertEqual(candidate["candidateType"], fitting_config["profile"]["candidate_types"]["submodel"])
        self.assertEqual(candidate["candidateId"], "door-module")
        self.assertEqual(candidate["bbox"]["bbox"]["widthLdu"], 40)
        self.assertEqual(candidate["logicalSize"]["logicalSize"]["widthStud"], 2)
        self.assertEqual(candidate["colorSummary"][0]["colorCode"], "16")
        self.assertEqual(candidate["appearanceTags"]["remarks"], "Reusable hinged detail")
        self.assertEqual(candidate["connectorSummary"]["totalCount"], 1)
        self.assertEqual(candidate["sourceMetadata"]["partCount"], 2)
        self.assertEqual(candidate["sourceMetadata"]["partSummary"]["totalCount"], 2)
        self.assertEqual(
            candidate["sourceMetadata"]["partSummary"]["byCategory"],
            [
                {"category": "Brick", "count": 1},
                {"category": "Plate", "count": 1},
            ],
        )

    def test_submodel_candidate_profile_persists_missing_geometry_failure(self) -> None:
        fitting_config = load_json_config(
            "fitting_candidate_profile.json",
            REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        seed_submodel(engine)

        candidate = save_submodel_fitting_candidate_profile(
            engine,
            fitting_config,
            "door-module",
        )

        self.assertEqual(candidate["candidateType"], fitting_config["profile"]["candidate_types"]["submodel"])
        self.assertEqual(candidate["profileStatus"], fitting_config["profile"]["failed_status"])
        self.assertEqual(
            candidate["profileError"],
            fitting_config["errors"]["submodel_part_geometry_not_found"].format(
                ldraw_part_num="3005.dat",
            ),
        )
        self.assertEqual(candidate["sourceMetadata"]["partCount"], 2)
        self.assertEqual(len(candidate["shapeProfile"]["parts"]), 2)

    def test_submodel_candidate_loader_skips_existing_profiles(self) -> None:
        fitting_config = load_json_config(
            "fitting_candidate_profile.json",
            REQUIRED_FITTING_CANDIDATE_PROFILE_CONFIG_KEYS,
        )
        engine = test_engine()
        seed_part(engine)
        seed_brick_part(engine)
        seed_submodel(engine)
        save_submodel_fitting_candidate_profile(engine, fitting_config, "door-module")
        Session = sessionmaker(bind=engine)
        with Session() as session:
            missing_submodels = load_candidate_submodels(session, fitting_config, None, True, None, None)
            included_submodels = load_candidate_submodels(session, fitting_config, None, False, None, None)

        self.assertEqual(missing_submodels, [])
        self.assertEqual(included_submodels, ["door-module"])


def test_engine():
    engine = create_engine("sqlite:///:memory:")
    LDrawFile.__table__.create(bind=engine)
    LDrawPart.__table__.create(bind=engine)
    LDrawPartGeometry.__table__.create(bind=engine)
    ConnectorInstance.__table__.create(bind=engine)
    LDrawSubmodel.__table__.create(bind=engine)
    LDrawSubmodelPart.__table__.create(bind=engine)
    LDrawSubmodelConnector.__table__.create(bind=engine)
    ensure_part_shape_profile_table(engine)
    ensure_fitting_candidate_profile_table(engine)
    return engine


def seed_part(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawFile(
                id=1,
                relative_path="parts/3024.dat",
                file_name="3024.dat",
                library_section="parts",
                file_role="part",
            )
        )
        session.add(
            LDrawPart(
                id=1,
                ldraw_part_num="3024.dat",
                file_id=1,
                name="Plate 1 x 1",
                category="Plate",
                relative_path="parts/3024.dat",
                file_hash="source-hash",
            )
        )
        session.add(
            LDrawPartGeometry(
                id=1,
                ldraw_part_id=1,
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
                geometry_status="parsed",
            )
        )
        session.commit()


def seed_brick_part(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawFile(
                id=2,
                relative_path="parts/3005.dat",
                file_name="3005.dat",
                library_section="parts",
                file_role="part",
            )
        )
        session.add(
            LDrawPart(
                id=2,
                ldraw_part_num="3005.dat",
                file_id=2,
                name="Brick 1 x 1",
                category="Brick",
                relative_path="parts/3005.dat",
                file_hash="brick-hash",
            )
        )
        session.add(
            LDrawPartGeometry(
                id=2,
                ldraw_part_id=2,
                bbox_min_x=0,
                bbox_min_y=0,
                bbox_min_z=0,
                bbox_max_x=20,
                bbox_max_y=24,
                bbox_max_z=20,
                width_ldu=20,
                height_ldu=24,
                depth_ldu=20,
                logical_width_stud=1,
                logical_depth_stud=1,
                logical_height_plate=3,
                geometry_status="parsed",
            )
        )
        session.commit()


def seed_connector(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            ConnectorInstance(
                id=1,
                ldraw_part_num="3024.dat",
                source_type="test",
                connector_kind="cyl",
                normalized_connector_type="stud",
                connector_gender="male",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
                confidence=1,
            )
        )
        session.commit()


def seed_submodel(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            LDrawSubmodel(
                id="door-module",
                name="door module",
                ldraw_content="\n".join(
                    [
                        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3024.dat",
                        "1 4 20 0 0 1 0 0 0 1 0 0 0 1 3005.dat",
                    ]
                ),
                color_percentages_json=[
                    {"colorCode": "16", "percentage": 60},
                    {"colorCode": "4", "percentage": 40},
                ],
                remarks="Reusable hinged detail",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            LDrawSubmodelPart(
                submodel_id="door-module",
                line_no=1,
                color_code="16",
                ldraw_part_num="3024.dat",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
            )
        )
        session.add(
            LDrawSubmodelPart(
                submodel_id="door-module",
                line_no=2,
                color_code="4",
                ldraw_part_num="3005.dat",
                pos_x=20,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
            )
        )
        session.add(
            LDrawSubmodelConnector(
                submodel_id="door-module",
                part_line_no=1,
                connector_label="top-stud",
                connector_kind="snap",
                normalized_connector_type="stud",
                connector_gender="male",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
                metadata_json={"usage": "attach roof"},
            )
        )
        session.commit()


def sample_profile() -> PartSurfaceProfile:
    return PartSurfaceProfile(
        part_id="3024.dat",
        ldraw_origin_to_base_ldu=8,
        ldraw_center_x_ldu=10,
        ldraw_center_z_ldu=10,
        width_stud=1,
        depth_stud=1,
        samples_per_stud_axis=1,
        surface_height_plate=((1.0,),),
        collision_intervals_plate=((((0.0, 1.0),),),),
        bottom_contact=((True,),),
        top_connection_mask=((True,),),
    )


if __name__ == "__main__":
    unittest.main()
